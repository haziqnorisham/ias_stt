"""Deployment action and action-type API endpoints."""
import mimetypes
import os
import re
import uuid

from flask import Blueprint, current_app, g, jsonify, request, send_file
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from app.auth import (
    auth_error,
    current_actor,
    require_permission,
    require_user_permission,
)
from app.models.database import db
from app.models.deployment import Deployment
from app.models.deployment_action import DeploymentAction
from app.models.deployment_action_type import DeploymentActionType
from app.services.deployment_action_service import (
    allowed_file,
    stored_file_path,
    upload_dir,
)


deployment_actions_bp = Blueprint(
    "deployment_actions",
    __name__,
    url_prefix="/api",
)

ACTION_TYPE_CODE_PATTERN = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


def _error(message, code):
    return jsonify({"error": message}), code


def _is_administrator():
    principal = getattr(g, "auth_principal", None) or {}
    return principal.get("type") == "user" and principal.get("role") == "administrator"


def _validate_action_type_data(data, creating=False):
    if not isinstance(data, dict):
        return "Request body must be a JSON object"

    allowed_fields = {"label", "description", "is_active"}
    if creating:
        allowed_fields.add("code")
    unknown = set(data) - allowed_fields
    if unknown:
        return f"Unknown field(s): {', '.join(sorted(unknown))}"

    if creating:
        code = data.get("code")
        if not isinstance(code, str) or not code.strip():
            return "Field 'code' is required and must be a non-empty string"
        code = code.strip()
        if len(code) > 50:
            return "Field 'code' exceeds max length of 50"
        if not ACTION_TYPE_CODE_PATTERN.fullmatch(code):
            return (
                "Field 'code' must contain lowercase letters, numbers, and underscores"
            )

        label = data.get("label")
        if not isinstance(label, str) or not label.strip():
            return "Field 'label' is required and must be a non-empty string"
    elif "label" in data and (
        not isinstance(data["label"], str) or not data["label"].strip()
    ):
        return "Field 'label' must be a non-empty string"

    if "label" in data and len(data["label"].strip()) > 100:
        return "Field 'label' exceeds max length of 100"

    if "description" in data and data["description"] is not None:
        if not isinstance(data["description"], str):
            return "Field 'description' must be a string or null"
        if len(data["description"]) > 500:
            return "Field 'description' exceeds max length of 500"

    if "is_active" in data and not isinstance(data["is_active"], bool):
        return "Field 'is_active' must be a boolean"

    return None


def _get_action_type_for_read(action_type_id):
    action_type = db.session.get(DeploymentActionType, action_type_id)
    if action_type is None:
        return None, _error("Action type not found", 404)
    if not action_type.is_active and not _is_administrator():
        return None, _error("Action type not found", 404)
    return action_type, None


# ---------------------------------------------------------------------------
# Action type administration
# ---------------------------------------------------------------------------
@deployment_actions_bp.route("/deployment-action-types", methods=["GET"])
@require_permission("deployments:read")
def list_action_types():
    include_inactive = request.args.get("include_inactive", "false").lower() == "true"
    if include_inactive and not _is_administrator():
        return auth_error(
            "FORBIDDEN",
            "Only administrators may include inactive action types.",
            403,
        )

    query = DeploymentActionType.query
    if not include_inactive:
        query = query.filter_by(is_active=True)
    action_types = query.order_by(DeploymentActionType.id).all()
    return jsonify([action_type.to_dict() for action_type in action_types]), 200


@deployment_actions_bp.route("/deployment-action-types/<int:action_type_id>", methods=["GET"])
@require_permission("deployments:read")
def get_action_type(action_type_id):
    action_type, error = _get_action_type_for_read(action_type_id)
    if error is not None:
        return error
    return jsonify(action_type.to_dict()), 200


@deployment_actions_bp.route("/deployment-action-types", methods=["POST"])
@require_user_permission("settings:admin")
def create_action_type():
    data = request.get_json(silent=True)
    error = _validate_action_type_data(data, creating=True)
    if error:
        return _error(error, 400)

    code = data["code"].strip()
    if DeploymentActionType.query.filter_by(code=code).first() is not None:
        return _error(f"Action type code '{code}' already exists", 409)

    action_type = DeploymentActionType(
        code=code,
        label=data["label"].strip(),
        description=data.get("description"),
        is_active=data.get("is_active", True),
    )
    db.session.add(action_type)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _error(f"Action type code '{code}' already exists", 409)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to create deployment action type")
        return _error("Internal Server Error", 500)

    return jsonify(action_type.to_dict()), 201


@deployment_actions_bp.route(
    "/deployment-action-types/<int:action_type_id>", methods=["PUT"]
)
@require_user_permission("settings:admin")
def update_action_type(action_type_id):
    action_type = db.session.get(DeploymentActionType, action_type_id)
    if action_type is None:
        return _error("Action type not found", 404)

    data = request.get_json(silent=True)
    error = _validate_action_type_data(data)
    if error:
        return _error(error, 400)

    for field in ("label", "description", "is_active"):
        if field in data:
            value = data[field]
            setattr(action_type, field, value.strip() if field == "label" else value)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Failed to update deployment action type %s", action_type_id
        )
        return _error("Internal Server Error", 500)

    return jsonify(action_type.to_dict()), 200


@deployment_actions_bp.route(
    "/deployment-action-types/<int:action_type_id>", methods=["DELETE"]
)
@require_user_permission("settings:admin")
def delete_action_type(action_type_id):
    action_type = db.session.get(DeploymentActionType, action_type_id)
    if action_type is None:
        return _error("Action type not found", 404)

    if (
        DeploymentAction.query.filter_by(action_type_id=action_type_id).first()
        is not None
    ):
        return _error(
            "Action type cannot be deleted because it is referenced by deployment actions; "
            "set is_active to false instead",
            409,
        )

    try:
        db.session.delete(action_type)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _error(
            "Action type cannot be deleted because it is referenced by deployment actions; "
            "set is_active to false instead",
            409,
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Failed to delete deployment action type %s", action_type_id
        )
        return _error("Internal Server Error", 500)

    return jsonify({"message": f"Action type {action_type_id} deleted"}), 200


# ---------------------------------------------------------------------------
# Immutable deployment actions
# ---------------------------------------------------------------------------
@deployment_actions_bp.route(
    "/deployments/<int:dep_id>/actions", methods=["GET"]
)
@require_permission("deployments:read")
def list_deployment_actions(dep_id):
    deployment = db.session.get(Deployment, dep_id)
    if deployment is None:
        return _error("Deployment not found", 404)

    actions = (
        deployment.actions
        .order_by(
            DeploymentAction.performed_at.desc(),
            DeploymentAction.id.desc(),
        )
        .all()
    )
    return jsonify([action.to_dict() for action in actions]), 200


@deployment_actions_bp.route(
    "/deployments/<int:dep_id>/actions", methods=["POST"]
)
@require_permission("deployments:update")
def create_deployment_action(dep_id):
    deployment = db.session.get(Deployment, dep_id)
    if deployment is None:
        return _error("Deployment not found", 404)
    if deployment.status != "active":
        return _error("Actions can only be added to active deployments", 409)

    raw_action_type_id = request.form.get("action_type_id")
    try:
        action_type_id = int(raw_action_type_id)
    except (TypeError, ValueError):
        return _error("Field 'action_type_id' must be an integer", 400)

    action_type = db.session.get(DeploymentActionType, action_type_id)
    if action_type is None:
        return _error("Action type not found", 404)
    if not action_type.is_active:
        return _error("Action type is inactive", 409)

    picture = request.files.get("picture")
    if picture is None:
        return _error("Field 'picture' is required", 400)
    if not picture.filename:
        return _error("No picture selected", 400)

    picture_filename = secure_filename(picture.filename)
    if not picture_filename:
        return _error("Picture filename is invalid", 400)
    if not allowed_file(picture_filename):
        return _error("File type not allowed (jpg, jpeg, png, gif)", 400)

    notes = request.form.get("notes")
    if notes == "":
        notes = None
    if notes is not None and len(notes) > 5000:
        return _error("Field 'notes' exceeds max length of 5000", 400)

    extension = picture_filename.rsplit(".", 1)[1].lower()
    stored_filename = f"{uuid.uuid4().hex}.{extension}"
    stored_path = os.path.join(upload_dir(), stored_filename)

    try:
        os.makedirs(upload_dir(), exist_ok=True)
        picture.save(stored_path)
        action = DeploymentAction(
            deployment_id=deployment.id,
            action_type_id=action_type.id,
            notes=notes,
            picture_url=stored_filename,
            picture_filename=picture_filename,
            performed_by=current_actor(),
        )
        db.session.add(action)
        db.session.commit()
    except Exception:
        db.session.rollback()
        if os.path.isfile(stored_path):
            os.remove(stored_path)
        current_app.logger.exception(
            "Failed to create action for deployment %s", dep_id
        )
        return _error("Internal Server Error", 500)

    return jsonify(action.to_dict()), 201


@deployment_actions_bp.route(
    "/deployment-actions/<int:action_id>/picture", methods=["GET"]
)
@require_permission("deployments:read")
def get_deployment_action_picture(action_id):
    action = db.session.get(DeploymentAction, action_id)
    if action is None:
        return _error("Deployment action not found", 404)

    file_path = stored_file_path(action.stored_filename)
    if file_path is None:
        return _error("Action picture not found", 404)

    mimetype = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    return send_file(
        file_path,
        mimetype=mimetype,
        download_name=action.picture_filename,
        conditional=True,
    )
