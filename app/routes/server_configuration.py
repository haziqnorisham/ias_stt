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

    for config_type, payload in config_group.items():
        if not isinstance(payload, dict):
            return jsonify({"error": f"Expected '{config_type}' payload to be an object"}), 400


    new_server_configurations = []

    try:

        for config_type, payload in config_group.items():
            if not isinstance(payload, dict):
                return jsonify({
                    "error": f"Expected '{config_type}' payload to be an object"
                }), 400

            for field_name, field_data in payload.items():
                if isinstance(field_data, dict):
                    row_id = field_data.get("id")
                    field_value = str(field_data.get("value", ""))
                else:
                    row_id = field_name
                    field_value = str(field_data)

                config_key = f"{config_type}_{field_name}"

                existing_row = None
                if row_id:
                    existing_row = server_configuration.query.filter_by(id=row_id).first()
                if existing_row:
                    existing_row.value = field_value
                    action = "updated"
                else:
                    new_row = server_configuration(config_key=config_key, value=field_value)
                    db.session.add(new_row)
                    action = "created"
                
                db.session.add(existing_row or new_row)
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
    args = request.args
    config_key = args.get('config_key', None)

    output = []
    if config_key is not None:
        # Filter configurations based on the 'config_key' parameter
        filtered_configurations = server_configuration.query.filter(server_configuration.config_key.startswith(config_key)).all()
        for config in filtered_configurations:
            output.append(
                {
                    "id": config.id,
                    "config_key": config.config_key,
                    "value": config.value,
                    "created_at": config.created_at.isoformat() if config.created_at else None,
                    "updated_at": config.updated_at.isoformat() if config.updated_at else None,
                }
            )

    elif config_key is None:
        # If 'config_key' parameter is not provided, return all configurations
        all_server_configuration = server_configuration.query.all()
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
