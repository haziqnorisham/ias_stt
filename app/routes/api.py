"""API routes: public Hello World plus the auth verification endpoint."""
from app.models.geofencing import Geofencing
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

@api_bp.route("/api/geofencing", methods=["GET", "POST"])
def geofencing():
    current_app.logger.info("Redirecting to /geofencing")

    if request.method == 'POST':
        data = request.get_json()
        # Extract and validate incoming data with variable `data`.
        id = data.get('id')
        trap_id = data.get('trap_id')
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        diameter = data.get('diameter')
        if not id or not trap_id or not latitude or not longitude or not diameter:
            return jsonify({"error": "Missing required fields"}), 400

        new_geofencing = Geofencing(
            id=id,
            trap_id=trap_id,
            latitude=latitude,
            longitude=longitude,
            diameter=diameter
        )
        db.session.add(new_geofencing)
        db.session.commit()
        return jsonify({
            "message": "Geofencing data received"
        }), 201

    elif request.method == 'GET':
        # Query ALL geofencing entries currently saved in the database
        all_geofencing = Geofencing.query.all()

        # Convert the database row objects into a clean Python list of dictionaries
        output = []
        for geofencing in all_geofencing:
            output.append({
                "id": geofencing.id,
                "trap_id": geofencing.trap_id,
                "latitude": geofencing.latitude,
                "longitude": geofencing.longitude,
                "diameter": geofencing.diameter,
                "created_at": geofencing.created_at.isoformat() if geofencing.created_at else None,
                "updated_at": geofencing.updated_at.isoformat() if geofencing.updated_at else None
            })
        return jsonify({
            "message": "Geofencing data retrieval endpoint",
            "geofencing data": output
        }), 200

    return jsonify({"message": "Unsupported method"}), 405


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
