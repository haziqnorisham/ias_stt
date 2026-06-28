"""API routes: public Hello World plus the auth verification endpoint."""
from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import select

from app.auth import require_api_key
from app.models.database import get_engine
from app.models.trap import Trap

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


@api_bp.route("/api/dashboard_map", methods=["GET"])
@require_api_key
def dashboard_map():
    try:
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "'limit' and 'offset' must be integers"}), 400
    if limit < 0 or offset < 0:
        return jsonify({"error": "'limit' and 'offset' must be non-negative"}), 400

    query = Trap.query
    status = request.args.get("status")
    if status:
        query = query.filter(Trap.status == status)

    traps = query.order_by(Trap.id).limit(limit).offset(offset).all()

    # Batch-load linked trackers in one query to avoid N+1
    tracker_euis = [t.tracker_id for t in traps if t.tracker_id]
    trackers_by_eui = {}
    if tracker_euis:
        from app.models.smart_trap_tracker import SmartTrapTracker

        stmt = select(SmartTrapTracker).where(
            SmartTrapTracker.device_eui.in_(tracker_euis)
        )
        with get_engine().connect() as conn:
            for row in conn.execute(stmt).fetchall():
                trackers_by_eui[row.device_eui] = row

    result = []
    for trap in traps:
        item = trap.to_dict()
        tracker = trackers_by_eui.get(trap.tracker_id)
        if tracker and tracker.latitude is not None and tracker.longitude is not None:
            lat = float(tracker.latitude)
            lng = float(tracker.longitude)
            item["latitude"] = lat
            item["longitude"] = lng
            item["map_url"] = (
                f"https://www.google.com/maps/dir/?api=1&destination={lat},{lng}"
            )
        else:
            item["latitude"] = None
            item["longitude"] = None
            item["map_url"] = None
        result.append(item)

    return jsonify(result), 200
