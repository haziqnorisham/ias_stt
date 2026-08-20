"""API routes: public Hello World plus the auth verification endpoint."""
import json

from app.models.server_configuration import server_configuration
from flask import Blueprint, current_app, jsonify, request, redirect
from sqlalchemy import select

from app.auth import require_api_key
from app.models.database import get_engine
from app.models.trap import Trap
from app.models.database import db 

api_bp = Blueprint("api", __name__)


@api_bp.route("/", methods=["GET"])
def root_to_traps():
    current_app.logger.info("Redirecting to /traps")
    return redirect("/traps")


@api_bp.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@api_bp.route("/api/telemetry/ingest", methods=["POST"])
@require_api_key
def telemetry_ingest():
    """Receive decoded GPS tracker payloads pushed by ChirpStack's HTTP integration.

    The body must be the ChirpStack JSON envelope (``deviceInfo`` + ``object``).
    Processing is identical to the MQTT path via :func:`process_message`.
    """
    raw = request.get_data(as_text=True)
    try:
        json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        current_app.logger.error("Invalid JSON payload received via HTTP ingest")
        return jsonify({"error": "Invalid JSON payload"}), 400

    try:
        from app.services.data_processor import process_message

        process_message(
            request.path or "/api/telemetry/ingest",
            raw,
            source="http",
        )
    except Exception:
        current_app.logger.exception("Error while handling HTTP telemetry ingest")
        return jsonify({"error": "Internal Server Error"}), 500

    return jsonify({"status": "processed"}), 200


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
                f'<a href="https://www.google.com/maps/dir/?api=1'
                f'&destination={lat},{lng}" target="_blank">'
                f'{lat},{lng}</a>'
            )
        else:
            item["latitude"] = None
            item["longitude"] = None
            item["map_url"] = None
        result.append(item)

    return jsonify(result), 200
