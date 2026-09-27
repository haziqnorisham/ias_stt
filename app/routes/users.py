"""Administrator-only local account and LDAP provisioning API."""
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from app.auth import VALID_ROLES, auth_error, current_actor, require_user_permission
from app.models.database import db
from app.models.user import User
from app.services.ldap_directory import (
    DirectoryAmbiguousIdentity,
    DirectoryIdentityNotFound,
    DirectoryUnavailable,
    get_ldap_directory,
)


users_bp = Blueprint("users", __name__, url_prefix="/api/users")
ldap_users_bp = Blueprint("ldap_users", __name__, url_prefix="/api/ldap")

MAX_PASSWORD_LENGTH = 255
MIN_PASSWORD_LENGTH = 8
USER_FIELDS = {"display_name", "email", "role", "password", "is_active"}


def _not_found():
    return auth_error("NOT_FOUND", "User not found.", 404)


def _validation_error(message):
    return auth_error("VALIDATION_ERROR", message, 422)


def _directory_unavailable():
    return auth_error(
        "AUTH_PROVIDER_UNAVAILABLE",
        "The authentication service is temporarily unavailable.",
        503,
    )


def _username_matches(username):
    return User.query.filter(func.lower(User.username) == username.strip().lower())


def _username_conflict(username, except_user_id=None):
    query = _username_matches(username)
    if except_user_id is not None:
        query = query.filter(User.id != except_user_id)
    return query.first() is not None


def _validate_user_data(data, creating=False):
    if not isinstance(data, dict):
        return "Request body must be a JSON object"

    allowed = set(USER_FIELDS) | {"username"}
    if creating:
        allowed |= {"auth_provider", "directory_subject"}
    unknown = set(data) - allowed
    if unknown:
        return f"Unknown field(s): {', '.join(sorted(unknown))}"

    if creating:
        provider = data.get("auth_provider")
        if provider not in {"LOCAL", "LDAP"}:
            return "Field 'auth_provider' is required and must be LOCAL or LDAP"
        if data.get("role") not in VALID_ROLES:
            return f"Field 'role' must be one of: {', '.join(VALID_ROLES)}"

        if provider == "LOCAL":
            username = data.get("username")
            if not isinstance(username, str) or not username.strip():
                return "Field 'username' is required for LOCAL users"
            if len(username.strip()) > 150:
                return "Field 'username' exceeds max length of 150"
            password = data.get("password")
            if not isinstance(password, str) or not password:
                return "Field 'password' is required for LOCAL users"
            if len(password) < MIN_PASSWORD_LENGTH:
                return f"Field 'password' must be at least {MIN_PASSWORD_LENGTH} characters"
            if len(password) > MAX_PASSWORD_LENGTH:
                return f"Field 'password' exceeds max length of {MAX_PASSWORD_LENGTH}"
            if "directory_subject" in data:
                return "Field 'directory_subject' is only valid for LDAP users"
        else:
            subject = data.get("directory_subject")
            if not isinstance(subject, str) or not subject.strip():
                return "Field 'directory_subject' is required for LDAP users"
            if len(subject.strip()) > 255:
                return "Field 'directory_subject' exceeds max length of 255"
            forbidden = {"username", "password", "display_name", "email"} & set(data)
            if forbidden:
                return (
                    "LDAP profile fields are managed by the directory; do not supply: "
                    + ", ".join(sorted(forbidden))
                )

    if "password" in data and data["password"] is not None:
        password = data["password"]
        if not isinstance(password, str):
            return "Field 'password' must be a string"
        if len(password) < MIN_PASSWORD_LENGTH:
            return f"Field 'password' must be at least {MIN_PASSWORD_LENGTH} characters"
        if len(password) > MAX_PASSWORD_LENGTH:
            return f"Field 'password' exceeds max length of {MAX_PASSWORD_LENGTH}"

    for field, max_length in (("display_name", 255), ("email", 255)):
        value = data.get(field)
        if value is not None and (
            not isinstance(value, str) or len(value) > max_length
        ):
            return f"Field '{field}' must be a string of at most {max_length} characters"

    if "role" in data and data["role"] not in VALID_ROLES:
        return f"Field 'role' must be one of: {', '.join(VALID_ROLES)}"
    if "is_active" in data and not isinstance(data["is_active"], bool):
        return "Field 'is_active' must be a boolean"
    return None


def _active_local_admin_count(exclude_user_id=None):
    query = User.query.filter_by(
        auth_provider="LOCAL",
        role="administrator",
        is_active=True,
    )
    if exclude_user_id is not None:
        query = query.filter(User.id != exclude_user_id)
    return query.count()


def _protect_local_admin_lockout(target, data):
    actor = current_actor()
    is_self = target.username == actor
    becoming_inactive = data.get("is_active") is False
    losing_admin_role = (
        data.get("role") is not None and data.get("role") != "administrator"
    )
    if is_self and (becoming_inactive or losing_admin_role):
        return auth_error(
            "CONFLICT",
            "You cannot deactivate or demote your own administrator account.",
            409,
        )

    target_is_protected_admin = (
        target.auth_provider == "LOCAL"
        and target.role == "administrator"
        and target.is_active
    )
    target_will_lose_admin = target_is_protected_admin and (
        becoming_inactive or losing_admin_role
    )
    if target_will_lose_admin and _active_local_admin_count(target.id) == 0:
        return auth_error(
            "CONFLICT",
            "At least one enabled LOCAL administrator must remain.",
            409,
        )
    return None


def _directory_identity_or_response(subject):
    directory = get_ldap_directory()
    try:
        identity = directory.find_by_subject(subject)
    except DirectoryAmbiguousIdentity:
        return None, auth_error(
            "CONFLICT",
            "The directory identity is ambiguous; provisioning was not completed.",
            409,
        )
    except DirectoryIdentityNotFound:
        return None, auth_error(
            "NOT_FOUND",
            "The selected directory user no longer exists.",
            404,
        )
    except DirectoryUnavailable:
        current_app.logger.warning("LDAP directory unavailable during provisioning")
        return None, _directory_unavailable()

    if identity is None:
        return None, auth_error(
            "NOT_FOUND",
            "The selected directory user no longer exists.",
            404,
        )
    directory = get_ldap_directory()
    if (
        identity.directory_key != directory.directory_key
        or identity.subject != subject
    ):
        return None, _directory_unavailable()
    if identity.is_enabled is False:
        return None, auth_error(
            "CONFLICT",
            "Disabled directory users cannot be provisioned.",
            409,
        )
    return identity, None


@users_bp.route("", methods=["GET"])
@require_user_permission("settings:admin")
def list_users():
    try:
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        return _validation_error("'limit' and 'offset' must be integers")
    if limit < 0 or offset < 0:
        return _validation_error("'limit' and 'offset' must be non-negative")

    query = User.query
    search = request.args.get("search", "").strip()
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                User.username.ilike(pattern),
                User.display_name.ilike(pattern),
                User.email.ilike(pattern),
            )
        )

    users = query.order_by(User.id).limit(limit).offset(offset).all()
    return jsonify([user.to_dict() for user in users]), 200


@users_bp.route("/<int:user_id>", methods=["GET"])
@require_user_permission("settings:admin")
def get_user(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        return _not_found()
    return jsonify(user.to_dict()), 200


@users_bp.route("", methods=["POST"])
@require_user_permission("settings:admin")
def create_user():
    data = request.get_json(silent=True)
    error = _validate_user_data(data, creating=True)
    if error:
        return _validation_error(error)

    provider = data["auth_provider"]
    if provider == "LOCAL":
        username = data["username"].strip()
        if _username_conflict(username):
            return auth_error("CONFLICT", f"Username '{username}' already exists.", 409)
        user = User(
            username=username,
            auth_provider="LOCAL",
            display_name=data.get("display_name"),
            email=data.get("email"),
            role=data["role"],
            is_active=data.get("is_active", True),
        )
        user.set_password(data["password"])
    else:
        subject = data["directory_subject"].strip()
        directory = get_ldap_directory()
        if User.query.filter_by(
            auth_provider="LDAP",
            directory_key=directory.directory_key,
            directory_subject=subject,
        ).first() is not None:
            return auth_error(
                "CONFLICT",
                "This directory identity is already provisioned.",
                409,
            )

        identity, response = _directory_identity_or_response(subject)
        if response is not None:
            return response
        if _username_conflict(identity.username):
            return auth_error(
                "CONFLICT",
                f"Username '{identity.username}' is already assigned to an application user.",
                409,
            )

        user = User(
            username=identity.username,
            auth_provider="LDAP",
            directory_key=identity.directory_key,
            directory_subject=identity.subject,
            ldap_dn=identity.dn,
            ldap_synced_at=datetime.now(timezone.utc),
            display_name=identity.display_name,
            email=identity.email,
            role=data["role"],
            is_active=data.get("is_active", True),
            password_hash=None,
        )

    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return auth_error(
            "CONFLICT",
            "The username or directory identity is already provisioned.",
            409,
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Unable to provision application user")
        return auth_error("INTERNAL_ERROR", "Unable to create user.", 500)

    return jsonify(user.to_dict()), 201


@users_bp.route("/<int:user_id>", methods=["PUT"])
@require_user_permission("settings:admin")
def update_user(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        return _not_found()

    data = request.get_json(silent=True)
    error = _validate_user_data(data)
    if error:
        return _validation_error(error)
    if user.auth_provider == "LDAP":
        forbidden = {"display_name", "email", "password"} & set(data)
        if forbidden:
            return _validation_error(
                "LDAP profile and credentials are managed by the directory"
            )

    lockout_error = _protect_local_admin_lockout(user, data)
    if lockout_error is not None:
        return lockout_error

    security_change = False
    for field in ("display_name", "email", "role", "is_active"):
        if field in data:
            value = data[field]
            if getattr(user, field) != value:
                setattr(user, field, value)
                if field in {"role", "is_active"}:
                    security_change = True
    if "password" in data and data["password"] is not None:
        if user.auth_provider != "LOCAL":
            return _validation_error("Only LOCAL users can have a local password")
        user.set_password(data["password"])
        security_change = True
    if security_change:
        user.token_version += 1

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Unable to update user %s", user_id)
        return auth_error("INTERNAL_ERROR", "Unable to update user.", 500)

    return jsonify(user.to_dict()), 200


@users_bp.route("/<int:user_id>/sync-profile", methods=["POST"])
@require_user_permission("settings:admin")
def sync_ldap_profile(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        return _not_found()
    if user.auth_provider != "LDAP":
        return _validation_error("Only LDAP users have directory profiles")

    directory = get_ldap_directory()
    if user.directory_key != directory.directory_key:
        return _directory_unavailable()
    try:
        identity = directory.find_by_subject(user.directory_subject)
    except DirectoryUnavailable:
        current_app.logger.warning("LDAP directory unavailable during profile sync")
        return _directory_unavailable()
    except DirectoryAmbiguousIdentity:
        return auth_error("CONFLICT", "Directory identity is ambiguous.", 409)

    if identity is None:
        return auth_error("NOT_FOUND", "Directory user was not found.", 404)
    if (
        identity.directory_key != user.directory_key
        or identity.subject != user.directory_subject
    ):
        return _directory_unavailable()
    if _username_conflict(identity.username, except_user_id=user.id):
        return auth_error(
            "CONFLICT",
            "The directory username is already assigned to another application user.",
            409,
        )

    user.username = identity.username
    user.display_name = identity.display_name
    user.email = identity.email
    user.ldap_dn = identity.dn
    user.ldap_synced_at = datetime.now(timezone.utc)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return auth_error("CONFLICT", "The directory username is already in use.", 409)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Unable to sync LDAP profile for user %s", user_id)
        return auth_error("INTERNAL_ERROR", "Unable to synchronize user profile.", 500)
    return jsonify(user.to_dict()), 200


@users_bp.route("/<int:user_id>", methods=["DELETE"])
@require_user_permission("settings:admin")
def delete_user(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        return _not_found()
    if user.username == current_actor():
        return auth_error("CONFLICT", "You cannot delete your own account.", 409)
    if (
        user.auth_provider == "LOCAL"
        and user.role == "administrator"
        and user.is_active
        and _active_local_admin_count(user.id) == 0
    ):
        return auth_error(
            "CONFLICT",
            "At least one enabled LOCAL administrator must remain.",
            409,
        )

    try:
        db.session.delete(user)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Unable to delete user %s", user_id)
        return auth_error("INTERNAL_ERROR", "Unable to delete user.", 500)

    return jsonify({"message": f"User {user_id} deleted"}), 200


@ldap_users_bp.route("/users", methods=["GET"])
@require_user_permission("settings:admin")
def search_directory_users():
    search = request.args.get("search", "").strip()
    if len(search) < 2:
        return _validation_error("'search' must contain at least 2 characters")
    try:
        limit = int(request.args.get("limit", 25))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        return _validation_error("'limit' and 'offset' must be integers")
    if limit < 1 or limit > 50 or offset < 0:
        return _validation_error("'limit' must be between 1 and 50; offset must be non-negative")

    try:
        identities = get_ldap_directory().search_users(search)
    except DirectoryUnavailable:
        current_app.logger.warning("LDAP directory unavailable during user search")
        return _directory_unavailable()
    except (DirectoryAmbiguousIdentity, DirectoryIdentityNotFound):
        return auth_error("CONFLICT", "Directory search returned ambiguous identities.", 409)

    results = [identity.to_public_dict() for identity in identities]
    return jsonify(results[offset:offset + limit]), 200
