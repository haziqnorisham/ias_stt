"""API routes: public Hello World plus the auth verification endpoint."""
from flask import Blueprint, current_app, jsonify

from app.auth import require_api_key

api_bp = Blueprint("api", __name__)


@api_bp.route("/", methods=["GET"])
def hello_world():
    current_app.logger.info("Hello World endpoint hit")
    return "Hello World"


@api_bp.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@api_bp.route("/api/auth/verify", methods=["GET"])
@require_api_key
def verify():
    """Return 200 when a valid API key is supplied; used by the login page."""
    return jsonify({"ok": True}), 200
