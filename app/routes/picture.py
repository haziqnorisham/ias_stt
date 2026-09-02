"""CRUD API for Picture (/api/picture)."""
import os
import uuid
from flask import Blueprint, current_app, jsonify, request
from app.auth import require_api_key
from app.models.database import db
from app.models.deployment import Deployment

picture_bp = Blueprint("picture", __name__, url_prefix="/api")

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif"}
UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "static", "uploads",
)

def _error(message, code):
    return jsonify({"error": message}), code

def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@picture_bp.route("/deployments/<int:dep_id>/picture", methods=["POST"])
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
