"""Deployment and location-history API endpoints (/api/...)."""
import os
import uuid

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import IntegrityError

from app.auth import require_api_key
from app.models.database import db
from app.models.trap import Trap
from app.models.deployment import Deployment
from app.models.deployment_location import DeploymentLocation
from app.services import deployment_service

deployments_bp = Blueprint("deployments", __name__, url_prefix="/api")

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif"}
UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "static", "uploads",
)


def _error(message, code):
    return jsonify({"error": message}), code


# ---------------------------------------------------------------------------
# Deployment CRUD
# ---------------------------------------------------------------------------
@deployments_bp.route("/deployments", methods=["GET"])
@require_api_key
def list_deployments():
    try:
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        return _error("'limit' and 'offset' must be integers", 400)
    if limit < 0 or offset < 0:
        return _error("'limit' and 'offset' must be non-negative", 400)

    query = Deployment.query
    trap_id = request.args.get("trap_id")
    if trap_id:
        query = query.filter(Deployment.trap_id == trap_id)
    status = request.args.get("status")
    if status:
        query = query.filter(Deployment.status == status)

    deps = query.order_by(Deployment.start_date.desc()).limit(limit).offset(offset).all()
    return jsonify([d.to_dict() for d in deps]), 200


@deployments_bp.route("/deployments/<int:dep_id>", methods=["GET"])
@require_api_key
def get_deployment(dep_id):
    dep = db.session.get(Deployment, dep_id)
    if dep is None:
        return _error("Deployment not found", 404)
    return jsonify(dep.to_dict()), 200


@deployments_bp.route("/deployments", methods=["POST"])
@require_api_key
def create_deployment_manual():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Request body must be a JSON object", 400)

    trap_id = data.get("trap_id")
    if not trap_id:
        return _error("Field 'trap_id' is required", 400)

    trap = db.session.get(Trap, trap_id)
    if trap is None:
        return _error("Trap not found", 404)

    try:
        dep = deployment_service.create_deployment(
            trap,
            location=data.get("location"),
            notes=data.get("notes"),
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to manually create deployment")
        return _error("Internal Server Error", 500)

    return jsonify(dep.to_dict()), 201


@deployments_bp.route("/deployments/<int:dep_id>", methods=["PUT"])
@require_api_key
def update_deployment(dep_id):
    dep = db.session.get(Deployment, dep_id)
    if dep is None:
        return _error("Deployment not found", 404)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Request body must be a JSON object", 400)

    if "animal_capture" in data:
        dep.animal_capture = data["animal_capture"]
    if "notes" in data:
        dep.notes = data["notes"]

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to update deployment %s", dep_id)
        return _error("Internal Server Error", 500)

    return jsonify(dep.to_dict()), 200


@deployments_bp.route("/deployments/<int:dep_id>", methods=["DELETE"])
@require_api_key
def delete_deployment(dep_id):
    dep = db.session.get(Deployment, dep_id)
    if dep is None:
        return _error("Deployment not found", 404)
    try:
        db.session.delete(dep)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to delete deployment %s", dep_id)
        return _error("Internal Server Error", 500)
    return jsonify({"message": f"Deployment {dep_id} deleted"}), 200


# ---------------------------------------------------------------------------
# Photo upload
# ---------------------------------------------------------------------------
def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@deployments_bp.route("/deployments/<int:dep_id>/photo", methods=["POST"])
@require_api_key
def upload_photo(dep_id):
    dep = db.session.get(Deployment, dep_id)
    if dep is None:
        return _error("Deployment not found", 404)

    if "file" not in request.files:
        return _error("No file provided", 400)

    file = request.files["file"]
    if file.filename == "":
        return _error("No file selected", 400)

    if not _allowed_file(file.filename):
        return _error("File type not allowed (jpg, jpeg, png, gif)", 400)

    os.makedirs(UPLOAD_DIR, exist_ok=True)

    ext = file.filename.rsplit(".", 1)[1].lower()
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    file_path = os.path.join(UPLOAD_DIR, stored_name)
    file.save(file_path)

    dep.photo_filename = file.filename
    dep.photo_url = f"/static/uploads/{stored_name}"

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to save photo for deployment %s", dep_id)
        return _error("Internal Server Error", 500)

    return jsonify(dep.to_dict()), 200


# ---------------------------------------------------------------------------
# Trap-scoped nested endpoints
# ---------------------------------------------------------------------------
@deployments_bp.route("/traps/<int:trap_id>/deployments", methods=["GET"])
@require_api_key
def trap_deployments(trap_id):
    trap = db.session.get(Trap, trap_id)
    if trap is None:
        return _error("Trap not found", 404)

    deps = (
        trap.deployments
        .order_by(Deployment.start_date.desc())
        .all()
    )
    return jsonify([d.to_dict() for d in deps]), 200


@deployments_bp.route("/traps/<int:trap_id>/deployments/active", methods=["GET"])
@require_api_key
def trap_active_deployment(trap_id):
    trap = db.session.get(Trap, trap_id)
    if trap is None:
        return _error("Trap not found", 404)

    active = trap.get_active_deployment()
    if active is None:
        return _error("No active deployment", 404)

    return jsonify(active.to_dict()), 200


# ---------------------------------------------------------------------------
# Location history
# ---------------------------------------------------------------------------
@deployments_bp.route("/deployments/<int:dep_id>/locations", methods=["GET"])
@require_api_key
def deployment_locations(dep_id):
    dep = db.session.get(Deployment, dep_id)
    if dep is None:
        return _error("Deployment not found", 404)

    locs = (
        dep.locations
        .order_by(DeploymentLocation.recorded_at.desc())
        .all()
    )
    return jsonify([l.to_dict() for l in locs]), 200


@deployments_bp.route("/deployments/<int:dep_id>/locations/latest", methods=["GET"])
@require_api_key
def deployment_latest_location(dep_id):
    dep = db.session.get(Deployment, dep_id)
    if dep is None:
        return _error("Deployment not found", 404)

    loc = (
        dep.locations
        .order_by(DeploymentLocation.recorded_at.desc())
        .first()
    )
    if loc is None:
        return _error("No location recorded", 404)

    return jsonify(loc.to_dict()), 200


@deployments_bp.route("/traps/<int:trap_id>/locations", methods=["GET"])
@require_api_key
def trap_locations(trap_id):
    trap = db.session.get(Trap, trap_id)
    if trap is None:
        return _error("Trap not found", 404)

    locs = deployment_service.get_location_history(trap)
    return jsonify([l.to_dict() for l in locs]), 200
