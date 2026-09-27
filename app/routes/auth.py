"""Credential authentication and application JWT endpoints."""
from datetime import datetime, timezone

from flask import Blueprint, current_app, g, jsonify, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_jwt,
)
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.auth import (
    VALID_ROLES,
    auth_error,
    permissions_for_role,
    require_jwt,
    require_refresh_jwt,
)
from app.models.database import db
from app.models.user import User
from app.services.ldap_directory import (
    DirectoryAmbiguousIdentity,
    DirectoryIdentityNotFound,
    DirectoryInvalidCredentials,
    DirectoryUnavailable,
    get_ldap_directory,
)


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _claims_for_user(user):
    return {
        "username": user.username,
        "role": user.role,
        "display_name": user.display_name,
        "email": user.email,
        "auth_provider": user.auth_provider,
        "token_version": user.token_version,
    }


def _seconds(value):
    return int(value.total_seconds()) if hasattr(value, "total_seconds") else int(value)


def _iso_timestamp(timestamp):
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _user_response(user):
    return user.to_public_dict(permissions_for_role(user.role))


def _invalid_credentials():
    return auth_error(
        "INVALID_CREDENTIALS",
        "Invalid username or password.",
        401,
    )


def _provider_unavailable():
    return auth_error(
        "AUTH_PROVIDER_UNAVAILABLE",
        "The authentication service is temporarily unavailable.",
        503,
    )


def _https_required():
    return auth_error(
        "HTTPS_REQUIRED",
        "Credentials must be submitted over HTTPS.",
        400,
    )


def _local_user_by_username(username):
    matches = (
        User.query.filter(func.lower(User.username) == username.strip().lower())
        .limit(2)
        .all()
    )
    if len(matches) > 1:
        return None, True
    return (matches[0] if matches else None), False


def _ldap_user_for_login(username, password, known_local_user=None):
    if not current_app.config.get("LDAP_ENABLED"):
        if known_local_user is not None:
            raise DirectoryUnavailable("LDAP authentication is not enabled")
        return None

    directory = get_ldap_directory()
    if known_local_user is not None:
        if known_local_user.directory_key != directory.directory_key:
            raise DirectoryUnavailable("Provisioned directory is not configured")
        identity = directory.find_by_subject(known_local_user.directory_subject)
        user = known_local_user
    else:
        identity = directory.find_by_login(username)
        if identity is None:
            return None
        user = User.query.filter_by(
            auth_provider="LDAP",
            directory_key=identity.directory_key,
            directory_subject=identity.subject,
        ).first()
        if user is None:
            return None

    if not user.is_active:
        return None
    if identity is None:
        return None
    if (
        known_local_user is not None
        and identity.username.casefold() != username.casefold()
    ):
        # Do not keep accepting an old directory username after rename/reuse.
        # The next attempt with the new directory login resolves by stable ID.
        return None
    if (
        identity.directory_key != user.directory_key
        or identity.subject != user.directory_subject
    ):
        return None
    if identity.is_enabled is False:
        return None

    # A discovered directory identity must correspond to this already
    # provisioned LDAP account. Never authenticate it through LOCAL.
    directory.authenticate(identity, password)

    collision = User.query.filter(
        func.lower(User.username) == identity.username.strip().lower(),
        User.id != user.id,
    ).first()
    if collision is not None:
        return None

    user.username = identity.username
    user.display_name = identity.display_name
    user.email = identity.email
    user.ldap_dn = identity.dn
    user.ldap_synced_at = datetime.now(timezone.utc)
    db.session.commit()
    return user


def _issue_tokens(user, include_refresh=True):
    claims = _claims_for_user(user)
    subject = str(user.id)
    access_token = create_access_token(
        identity=subject,
        additional_claims=claims,
    )
    response = {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": _seconds(current_app.config["JWT_ACCESS_TOKEN_EXPIRES"]),
    }
    if include_refresh:
        response["refresh_token"] = create_refresh_token(
            identity=subject,
            additional_claims=claims,
        )
        response["refresh_expires_in"] = _seconds(
            current_app.config["JWT_REFRESH_TOKEN_EXPIRES"]
        )

    now = datetime.now(timezone.utc).timestamp()
    response["expires_at"] = _iso_timestamp(now + response["expires_in"])
    if include_refresh:
        response["refresh_expires_at"] = _iso_timestamp(
            now + response["refresh_expires_in"]
        )
    return response


@auth_bp.route("/login", methods=["POST"])
def login():
    if not request.is_json:
        return auth_error("INVALID_REQUEST", "Request body must be JSON.", 400)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return auth_error("INVALID_REQUEST", "Request body must be a JSON object.", 400)

    username = data.get("username")
    password = data.get("password")
    if not isinstance(username, str) or not username.strip():
        return _invalid_credentials()
    if not isinstance(password, str) or not password:
        return _invalid_credentials()
    username = username.strip()

    user, ambiguous = _local_user_by_username(username)
    if ambiguous:
        return _invalid_credentials()
    if not request.is_secure and not current_app.config.get("TESTING"):
        return _https_required()
    if user is not None:
        if not user.is_active:
            return _invalid_credentials()
        if user.auth_provider == "LOCAL":
            if not user.check_password(password):
                return _invalid_credentials()
        elif user.auth_provider == "LDAP":
            if not user.directory_subject:
                return _invalid_credentials()
            try:
                user = _ldap_user_for_login(
                    username,
                    password,
                    known_local_user=user,
                )
            except DirectoryInvalidCredentials:
                return _invalid_credentials()
            except DirectoryIdentityNotFound:
                return _invalid_credentials()
            except DirectoryUnavailable:
                current_app.logger.warning("LDAP provider unavailable during login")
                return _provider_unavailable()
            except DirectoryAmbiguousIdentity:
                return _invalid_credentials()
            except IntegrityError:
                db.session.rollback()
                return _invalid_credentials()
            except Exception:
                db.session.rollback()
                current_app.logger.warning(
                    "LDAP login/profile synchronization failed"
                )
                return _provider_unavailable()
            if user is None:
                return _invalid_credentials()
        else:
            return _invalid_credentials()
    else:
        try:
            user = _ldap_user_for_login(username, password)
        except DirectoryInvalidCredentials:
            return _invalid_credentials()
        except DirectoryIdentityNotFound:
            return _invalid_credentials()
        except DirectoryUnavailable:
            current_app.logger.warning("LDAP provider unavailable during login")
            return _provider_unavailable()
        except DirectoryAmbiguousIdentity:
            return _invalid_credentials()
        except IntegrityError:
            db.session.rollback()
            return _invalid_credentials()
        except Exception:
            db.session.rollback()
            current_app.logger.warning("LDAP login/profile synchronization failed")
            return _provider_unavailable()
        if user is None:
            return _invalid_credentials()

    if user.role not in VALID_ROLES:
        return auth_error(
            "APPLICATION_ACCESS_DENIED",
            "This account is not authorized to use the application.",
            403,
        )

    tokens = _issue_tokens(user)
    return jsonify(
        {
            "authenticated": True,
            "user": _user_response(user),
            **tokens,
        }
    ), 200


@auth_bp.route("/me", methods=["GET"])
@require_jwt
def me():
    user = g.auth_principal["user"]
    claims = get_jwt()
    return jsonify(
        {
            "authenticated": True,
            "user": _user_response(user),
            "expires_at": _iso_timestamp(claims["exp"]),
        }
    ), 200


@auth_bp.route("/refresh", methods=["POST"])
@require_refresh_jwt
def refresh():
    user = g.auth_principal["user"]
    if user.auth_provider == "LDAP":
        if not user.directory_subject:
            return auth_error(
                "AUTHENTICATION_REQUIRED", "Authentication is required.", 401
            )
        directory = get_ldap_directory()
        if user.directory_key != directory.directory_key:
            return _provider_unavailable()
        try:
            identity = directory.find_by_subject(user.directory_subject)
        except DirectoryUnavailable:
            current_app.logger.warning("LDAP provider unavailable during refresh")
            return _provider_unavailable()
        except (DirectoryIdentityNotFound, DirectoryAmbiguousIdentity):
            return auth_error(
                "AUTHENTICATION_REQUIRED", "Authentication is required.", 401
            )

        if (
            identity is None
            or identity.directory_key != user.directory_key
            or identity.subject != user.directory_subject
            or identity.is_enabled is False
        ):
            return auth_error(
                "AUTHENTICATION_REQUIRED", "Authentication is required.", 401
            )
        collision = User.query.filter(
            func.lower(User.username) == identity.username.strip().lower(),
            User.id != user.id,
        ).first()
        if collision is not None:
            return auth_error(
                "AUTHENTICATION_REQUIRED", "Authentication is required.", 401
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
            return auth_error(
                "AUTHENTICATION_REQUIRED", "Authentication is required.", 401
            )

    if user.role not in VALID_ROLES:
        return auth_error(
            "AUTHENTICATION_REQUIRED", "Authentication is required.", 401
        )
    return jsonify(_issue_tokens(user, include_refresh=False)), 200


@auth_bp.route("/logout", methods=["POST"])
def logout():
    # JWTs remain stateless and client-discarded; LDAP support does not change
    # the existing logout/revocation semantics.
    return "", 204
