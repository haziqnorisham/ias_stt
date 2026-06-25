"""API key authentication.

A single shared API key (``API_KEY`` in the environment) protects the ``/api/*``
endpoints. Clients authenticate with an ``Authorization: Bearer <key>`` header.

If ``API_KEY`` is not configured the decorator passes requests through (auth is
effectively disabled) and a warning is logged at startup, so an administrator can
set the key later without the app refusing to start.
"""
import hmac
from functools import wraps

from flask import current_app, jsonify, request

UNAUTHORIZED = ({"error": "Invalid or missing API key"}, 401)


def _extract_bearer_token():
    header = request.headers.get("Authorization", "")
    parts = header.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def is_valid_key(provided):
    """Constant-time comparison against the configured API key."""
    configured = current_app.config.get("API_KEY")
    if not configured or not provided:
        return False
    return hmac.compare_digest(str(provided), str(configured))


def require_api_key(view):
    """Decorator: require a valid Bearer API key, unless no key is configured."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        # Pass-through when no key is configured (auth disabled).
        if not current_app.config.get("API_KEY"):
            return view(*args, **kwargs)
        token = _extract_bearer_token()
        if not is_valid_key(token):
            return jsonify(UNAUTHORIZED[0]), UNAUTHORIZED[1]
        return view(*args, **kwargs)

    return wrapper


def init_auth(app):
    """Log a startup warning when authentication is not configured."""
    if not app.config.get("API_KEY"):
        app.logger.warning(
            "API_KEY not set; API authentication is DISABLED. "
            "Set API_KEY in the environment to secure /api/* endpoints."
        )
    else:
        app.logger.info("API key authentication enabled for /api/* endpoints")
