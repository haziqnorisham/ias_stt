"""CRUD API for smart trap trackers (/api/stt)."""
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import IntegrityError

from app.auth import require_api_key
from app.models.database import db
from app.models.smart_trap_tracker import SmartTrapTracker

trackers_bp = Blueprint("trackers", __name__, url_prefix="/api/stt")

STRING_FIELDS = {
    "display_name": 255,
    "device_eui": 100,
    "tilt_status": 50,
}
REQUIRED_CREATE = ("device_eui", "display_name")
EDITABLE_FIELDS = (
    "display_name",
    "device_eui",
    "latitude",
    "longitude",
    "tilt_status",
    "battery",
)


def _error(message, code):
    return jsonify({"error": message}), code


def _validate_string(field, value):
    if not isinstance(value, str):
        return f"Field '{field}' must be a string"
    if len(value) > STRING_FIELDS[field]:
        return f"Field '{field}' exceeds max length of {STRING_FIELDS[field]}"
    return None


def _validate_numeric(field, value):
    """Return (decimal_value, error)."""
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, f"Field '{field}' must be numeric"
    try:
        return Decimal(str(value)), None
    except (InvalidOperation, ValueError, TypeError):
        return None, f"Field '{field}' must be numeric"


def _validate_battery(value):
    if value is None:
        return None, None
    try:
        ival = int(value)
    except (ValueError, TypeError):
        return None, "Field 'battery' must be an integer"
    if ival < 0 or ival > 100:
        return None, "Field 'battery' must be between 0 and 100"
    return ival, None


def _apply_fields(tracker, data):
    for field in EDITABLE_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if field in ("latitude", "longitude"):
            parsed, err = _validate_numeric(field, value)
            if err:
                return err
            setattr(tracker, field, parsed)
        elif field == "battery":
            parsed, err = _validate_battery(value)
            if err:
                return err
            setattr(tracker, field, parsed)
        else:
            if value is None and field not in REQUIRED_CREATE:
                setattr(tracker, field, None)
                continue
            err = _validate_string(field, value)
            if err:
                return err
            setattr(tracker, field, value)
    return None


@trackers_bp.route("", methods=["GET"])
@require_api_key
def list_trackers():
    try:
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        return _error("'limit' and 'offset' must be integers", 400)
    if limit < 0 or offset < 0:
        return _error("'limit' and 'offset' must be non-negative", 400)

    query = SmartTrapTracker.query
    device_eui = request.args.get("device_eui")
    if device_eui:
        query = query.filter(SmartTrapTracker.device_eui == device_eui)

    trackers = (
        query.order_by(SmartTrapTracker.id).limit(limit).offset(offset).all()
    )
    return jsonify([t.to_dict() for t in trackers]), 200


@trackers_bp.route("/<int:tracker_pk>", methods=["GET"])
@require_api_key
def get_tracker(tracker_pk):
    tracker = db.session.get(SmartTrapTracker, tracker_pk)
    if tracker is None:
        return _error("Tracker not found", 404)
    return jsonify(tracker.to_dict()), 200


@trackers_bp.route("", methods=["POST"])
@require_api_key
def create_tracker():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Request body must be a JSON object", 400)

    missing = [f for f in REQUIRED_CREATE if not data.get(f)]
    if missing:
        return _error(f"Missing required field(s): {', '.join(missing)}", 400)

    if (
        SmartTrapTracker.query.filter_by(device_eui=data["device_eui"]).first()
        is not None
    ):
        return _error(f"device_eui '{data['device_eui']}' already exists", 409)

    tracker = SmartTrapTracker()
    err = _apply_fields(tracker, data)
    if err:
        return _error(err, 400)

    try:
        db.session.add(tracker)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _error(f"device_eui '{data.get('device_eui')}' already exists", 409)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to create tracker")
        return _error("Internal Server Error", 500)

    return jsonify(tracker.to_dict()), 201


@trackers_bp.route("/<int:tracker_pk>", methods=["PUT"])
@require_api_key
def update_tracker(tracker_pk):
    tracker = db.session.get(SmartTrapTracker, tracker_pk)
    if tracker is None:
        return _error("Tracker not found", 404)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Request body must be a JSON object", 400)

    new_device_eui = data.get("device_eui")
    if new_device_eui and new_device_eui != tracker.device_eui:
        exists = (
            SmartTrapTracker.query.filter_by(device_eui=new_device_eui).first()
        )
        if exists is not None:
            return _error(f"device_eui '{new_device_eui}' already exists", 409)

    err = _apply_fields(tracker, data)
    if err:
        return _error(err, 400)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _error(f"device_eui '{new_device_eui}' already exists", 409)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to update tracker %s", tracker_pk)
        return _error("Internal Server Error", 500)

    return jsonify(tracker.to_dict()), 200


@trackers_bp.route("/<int:tracker_pk>", methods=["DELETE"])
@require_api_key
def delete_tracker(tracker_pk):
    tracker = db.session.get(SmartTrapTracker, tracker_pk)
    if tracker is None:
        return _error("Tracker not found", 404)
    try:
        db.session.delete(tracker)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to delete tracker %s", tracker_pk)
        return _error("Internal Server Error", 500)
    return jsonify({"message": f"Tracker {tracker_pk} deleted"}), 200
