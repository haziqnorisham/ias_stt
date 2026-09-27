"""JWT authentication, legacy service-key compatibility, and permissions."""
import hmac
import secrets
from functools import wraps

from flask import current_app, g, jsonify, request
from flask_jwt_extended import (
    JWTManager,
    get_jwt,
    get_jwt_identity,
    verify_jwt_in_request,
)
from flask_jwt_extended.exceptions import JWTExtendedException

from app.models.database import db
from app.models.user import User


ROLE_PERMISSIONS = {
    "administrator": {
        "traps:read",
        "trap_details:read",
        "traps:create",
        "traps:update",
        "traps:delete",
        "trackers:read",
        "trackers:unassigned:read",
        "trackers:manage",
        "deployments:read",
        "deployments:create",
        "deployments:update",
        "deployments:delete",
        "uplinks:read",
        "settings:admin",
        "notifications:read",
        "notifications:state:update",
    },
    "field_operator": {
        "traps:read",
        "trackers:unassigned:read",
        "deployments:read",
        "traps:update",
        "deployments:update",
        "notifications:read",
        "notifications:state:update",
    },
    "read_only": {
        "traps:read",
        "trap_details:read",
        "trackers:read",
        "trackers:unassigned:read",
        "deployments:read",
        "uplinks:read",
        "notifications:read",
        "notifications:state:update",
    },
}

VALID_ROLES = tuple(ROLE_PERMISSIONS)


def auth_error(code, message, status):
    return jsonify({"error": {"code": code, "message": message}}), status


def permissions_for_role(role):
    return sorted(ROLE_PERMISSIONS.get(role, set()))


def _extract_bearer_token():
    header = request.headers.get("Authorization", "")
    parts = header.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def _service_principal(token):
    configured = current_app.config.get("API_KEY")
    if not configured or not token:
        return None
    if not hmac.compare_digest(str(token), str(configured)):
        return None
    permissions = current_app.config.get("API_KEY_PERMISSIONS", ["*"])
    return {
        "type": "service",
        "username": "service-api",
        "role": None,
        "permissions": permissions,
    }


def _verify_jwt(refresh=False):
    try:
        verify_jwt_in_request(refresh=refresh)
    except JWTExtendedException:
        return None, auth_error(
            "INVALID_TOKEN",
            "The authentication token is invalid or expired.",
            401,
        )
    except Exception:
        current_app.logger.exception("JWT validation failed")
        return None, auth_error(
            "INVALID_TOKEN",
            "The authentication token is invalid or expired.",
            401,
        )

    claims = get_jwt()
    identity = get_jwt_identity()
    try:
        user_id = int(identity)
    except (TypeError, ValueError):
        return None, auth_error(
            "INVALID_TOKEN",
            "The authentication token is invalid or expired.",
            401,
        )

    user = db.session.get(User, user_id)
    if user is None or not user.is_active:
        return None, auth_error(
            "AUTHENTICATION_REQUIRED",
            "Authentication is required.",
            401,
        )
    if user.role not in ROLE_PERMISSIONS:
        return None, auth_error(
            "AUTHENTICATION_REQUIRED",
            "Authentication is required.",
            401,
        )
    try:
        token_version = int(claims.get("token_version", -1))
    except (TypeError, ValueError):
        token_version = -1
    if token_version != user.token_version:
        return None, auth_error(
            "AUTHENTICATION_REQUIRED",
            "Authentication is required.",
            401,
        )
    if claims.get("auth_provider") != user.auth_provider:
        return None, auth_error(
            "INVALID_TOKEN",
            "The authentication token is invalid or expired.",
            401,
        )

    return {
        "type": "user",
        "user_id": user.id,
        "user": user,
        "username": user.username,
        "role": user.role,
        "permissions": permissions_for_role(user.role),
        "display_name": user.display_name,
        "email": user.email,
        "auth_provider": user.auth_provider,
        "claims": claims,
    }, None


def _authenticate_request(allow_service=True):
    token = _extract_bearer_token()
    if allow_service:
        service = _service_principal(token)
        if service is not None:
            g.auth_principal = service
            return service, None

    if not token:
        if request.headers.get("Authorization"):
            return None, auth_error(
                "INVALID_TOKEN",
                "The authentication token is invalid or expired.",
                401,
            )
        return None, auth_error(
            "AUTHENTICATION_REQUIRED",
            "Authentication is required.",
            401,
        )

    principal, error = _verify_jwt()
    if error is not None:
        return None, error
    g.auth_principal = principal
    return principal, None


def require_auth(view):
    """Require a JWT user or an explicitly configured legacy service key."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        _, error = _authenticate_request()
        if error is not None:
            return error
        return view(*args, **kwargs)

    return wrapper


def require_jwt(view):
    """Require a user JWT, excluding the legacy service-key path."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        _, error = _authenticate_request(allow_service=False)
        if error is not None:
            return error
        return view(*args, **kwargs)

    return wrapper


def require_refresh_jwt(view):
    """Require a valid refresh JWT."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not _extract_bearer_token():
            return auth_error(
                "AUTHENTICATION_REQUIRED",
                "Authentication is required.",
                401,
            )
        principal, error = _verify_jwt(refresh=True)
        if error is not None:
            return error
        g.auth_principal = principal
        return view(*args, **kwargs)

    return wrapper


def require_permission(permission):
    """Require a user permission, or a legacy service key with that scope."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            principal, error = _authenticate_request()
            if error is not None:
                return error
            allowed = principal["permissions"]
            if "*" not in allowed and permission not in allowed:
                return auth_error(
                    "FORBIDDEN",
                    "You do not have permission to perform this action.",
                    403,
                )
            return view(*args, **kwargs)

        return wrapper

    return decorator


def require_user_permission(permission):
    """Require a permission from an authenticated user, not a service key."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            principal, error = _authenticate_request(allow_service=False)
            if error is not None:
                return error
            if permission not in principal["permissions"]:
                return auth_error(
                    "FORBIDDEN",
                    "You do not have permission to perform this action.",
                    403,
                )
            return view(*args, **kwargs)

        return wrapper

    return decorator


def require_api_key(view):
    """Require the legacy API key for service-only endpoints."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        principal = _service_principal(_extract_bearer_token())
        if principal is None:
            return auth_error(
                "AUTHENTICATION_REQUIRED",
                "A valid service API key is required.",
                401,
            )
        g.auth_principal = principal
        return view(*args, **kwargs)

    return wrapper


def current_actor():
    principal = getattr(g, "auth_principal", None)
    if not principal:
        return "system"
    return principal.get("username") or "system"


def init_auth(app):
    """Configure Flask-JWT-Extended and require a stable signing secret."""
    if not app.config.get("JWT_SECRET_KEY"):
        if app.config.get("TESTING") or app.config.get("DEBUG"):
            app.config["JWT_SECRET_KEY"] = secrets.token_urlsafe(32)
            app.logger.warning(
                "JWT_SECRET_KEY is not configured; using an ephemeral development key"
            )
        else:
            raise RuntimeError("JWT_SECRET_KEY must be configured in production")

    JWTManager(app)

    if app.config.get("API_KEY"):
        app.logger.info("Legacy service API-key authentication enabled")
