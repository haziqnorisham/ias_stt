"""CRUD API for Geofencing (/api/geofencing)."""
from decimal import Decimal

from flask import Blueprint, current_app, jsonify, request

from app.auth import require_api_key
from app.models.database import db
from app.models.server_configuration import server_configuration

server_configuration_bp = Blueprint("server_configuration", __name__, url_prefix="/api/server_configuration")

@server_configuration_bp.route("", methods=["POST"])
@require_api_key
def create_server_configuration():
    current_app.logger.info("Redirecting to /server_configuration")

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    config_group = data.get("config_key")
    if not isinstance(config_group, dict):
        return jsonify({"error": "Expected 'config_key' object"}), 400


    new_server_configurations = []

    try:
        for config_type, payload in config_group.items():
            if not isinstance(payload, dict):
                return jsonify({
                    "error": f"Expected '{config_type}' payload to be an object"
                }), 400

        for field_name, field_value in payload.items():
            config_key = f"{config_type}_{field_name}"
            row = server_configuration(
                config_key=config_key,
                value=str(field_value),
            )
            db.session.add(row)
            new_server_configurations.append(
                {
                    "config_key": config_key,
                    "value": str(field_value),
                }
            )

        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to save server configuration")
        return jsonify({"error": "Internal Server Error"}), 500

    return jsonify(
        {
            "message": "Server configuration data received",
            "saved_rows": new_server_configurations,
        }
    ), 201


@server_configuration_bp.route("", methods=["GET"])
@require_api_key
def get_server_configuration():
    # Query ALL server configuration entries currently saved in the database
    all_server_configuration = server_configuration.query.all()

    output = []
    for config in all_server_configuration:
        output.append(
            {
                "id": config.id,
                "config_key": config.config_key,
                "value": config.value,
                "created_at": config.created_at.isoformat() if config.created_at else None,
                "updated_at": config.updated_at.isoformat() if config.updated_at else None,
            }
        )

    return jsonify(
        {
            "message": "Server configuration data retrieval endpoint",
            "server_configuration_data": output,
        }
    ), 200
