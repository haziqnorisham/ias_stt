"""CRUD API for trap device configurations (/api/traps)."""
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import IntegrityError

from app.auth import require_api_key
from app.models.database import db
from app.models.trap import Trap

traps_bp = Blueprint("traps", __name__, url_prefix="/api/traps")

STRING_FIELDS = {
    "status": 20,
    "trap_id": 50,
    "tracker_id": 50,
    "location": 50,
    "door_status": 20,
    "notes": 255,
    "updated_by": 50,
}
REQUIRED_CREATE = ("status", "trap_id", "tracker_id")
EDITABLE_FIELDS = (
    "status",
    "trap_id",
    "tracker_id",
    "location",
    "door_status",
    "temperature",
    "notes",
    "updated_by",
)


def _error(message, code):
    return jsonify({"error": message}), code


def _validate_string(field, value):
    if not isinstance(value, str):
        return f"Field '{field}' must be a string"
    if len(value) > STRING_FIELDS[field]:
        return f"Field '{field}' exceeds max length of {STRING_FIELDS[field]}"
    return None


def _validate_temperature(value):
    """Return (decimal_value, error)."""
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, "Field 'temperature' must be numeric"
    try:
        return Decimal(str(value)), None
    except (InvalidOperation, ValueError, TypeError):
        return None, "Field 'temperature' must be numeric"


def _apply_fields(trap, data):
    """Validate and apply editable fields to a trap. Returns an error string or None."""
    for field in EDITABLE_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if field == "temperature":
            parsed, err = _validate_temperature(value)
            if err:
                return err
            trap.temperature = parsed
        else:
            if value is None and field not in REQUIRED_CREATE and field != "updated_by":
                setattr(trap, field, None)
                continue
            err = _validate_string(field, value)
            if err:
                return err
            setattr(trap, field, value)
    return None


@traps_bp.route("", methods=["GET"])
@require_api_key
def list_traps():
    try:
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        return _error("'limit' and 'offset' must be integers", 400)
    if limit < 0 or offset < 0:
        return _error("'limit' and 'offset' must be non-negative", 400)

    query = Trap.query
    status = request.args.get("status")
    if status:
        query = query.filter(Trap.status == status)

    traps = query.order_by(Trap.id).limit(limit).offset(offset).all()
    return jsonify([t.to_dict() for t in traps]), 200


@traps_bp.route("/<int:trap_pk>", methods=["GET"])
@require_api_key
def get_trap(trap_pk):
    trap = db.session.get(Trap, trap_pk)
    if trap is None:
        return _error("Trap not found", 404)
    return jsonify(trap.to_dict()), 200


@traps_bp.route("", methods=["POST"])
@require_api_key
def create_trap():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Request body must be a JSON object", 400)

    missing = [f for f in REQUIRED_CREATE if not data.get(f)]
    if missing:
        return _error(f"Missing required field(s): {', '.join(missing)}", 400)

    if Trap.query.filter_by(trap_id=data["trap_id"]).first() is not None:
        return _error(f"trap_id '{data['trap_id']}' already exists", 409)

    trap = Trap()
    err = _apply_fields(trap, data)
    if err:
        return _error(err, 400)
    if not trap.updated_by:
        trap.updated_by = "system"

    try:
        db.session.add(trap)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _error(f"trap_id '{data.get('trap_id')}' already exists", 409)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to create trap")
        return _error("Internal Server Error", 500)

    return jsonify(trap.to_dict()), 201


@traps_bp.route("/<int:trap_pk>", methods=["PUT"])
@require_api_key
def update_trap(trap_pk):
    trap = db.session.get(Trap, trap_pk)
    if trap is None:
        return _error("Trap not found", 404)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Request body must be a JSON object", 400)

    if not data.get("updated_by"):
        return _error("Field 'updated_by' is required on update", 400)

    new_trap_id = data.get("trap_id")
    if new_trap_id and new_trap_id != trap.trap_id:
        exists = Trap.query.filter_by(trap_id=new_trap_id).first()
        if exists is not None:
            return _error(f"trap_id '{new_trap_id}' already exists", 409)

    err = _apply_fields(trap, data)
    if err:
        return _error(err, 400)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _error(f"trap_id '{new_trap_id}' already exists", 409)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to update trap %s", trap_pk)
        return _error("Internal Server Error", 500)

    return jsonify(trap.to_dict()), 200


@traps_bp.route("/<int:trap_pk>", methods=["DELETE"])
@require_api_key
def delete_trap(trap_pk):
    trap = db.session.get(Trap, trap_pk)
    if trap is None:
        return _error("Trap not found", 404)
    try:
        db.session.delete(trap)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to delete trap %s", trap_pk)
        return _error("Internal Server Error", 500)
    return jsonify({"message": f"Trap {trap_pk} deleted"}), 200
