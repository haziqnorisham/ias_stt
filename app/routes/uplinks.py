"""Historical tracker uplink API endpoints."""
from flask import Blueprint, jsonify, request

from app.auth import require_api_key
from app.models.database import db
from app.models.smart_trap_tracker import SmartTrapTracker
from app.models.tracker_uplink import TrackerUplink


uplinks_bp = Blueprint("uplinks", __name__, url_prefix="/api/uplinks")


def _error(message, code):
    return jsonify({"error": message}), code


def _parse_pagination():
    try:
        limit = int(request.args.get("limit", 25))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        return None, None
    if limit < 0 or offset < 0:
        return None, None
    return limit, offset


def _query_with_tracker_name():
    return db.session.query(
        TrackerUplink,
        SmartTrapTracker.display_name,
    ).outerjoin(
        SmartTrapTracker,
        SmartTrapTracker.device_eui == TrackerUplink.device_eui,
    )


@uplinks_bp.route("", methods=["GET"])
@require_api_key
def list_uplinks():
    limit, offset = _parse_pagination()
    if limit is None:
        return _error("'limit' and 'offset' must be non-negative integers", 400)

    query = _query_with_tracker_name()
    device_eui = request.args.get("device_eui", "").strip()
    source = request.args.get("source", "").strip()
    if device_eui:
        query = query.filter(TrackerUplink.device_eui == device_eui)
    if source:
        query = query.filter(TrackerUplink.source == source)

    rows = (
        query.order_by(
            TrackerUplink.received_at.desc(),
            TrackerUplink.id.desc(),
        )
        .limit(limit)
        .offset(offset)
        .all()
    )
    return jsonify(
        [uplink.to_dict(display_name=display_name) for uplink, display_name in rows]
    ), 200


@uplinks_bp.route("/<int:uplink_id>", methods=["GET"])
@require_api_key
def get_uplink(uplink_id):
    row = (
        _query_with_tracker_name()
        .filter(TrackerUplink.id == uplink_id)
        .first()
    )
    if row is None:
        return _error("Uplink not found", 404)

    uplink, display_name = row
    return jsonify(uplink.to_dict(include_raw=True, display_name=display_name)), 200
