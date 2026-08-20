"""CRUD API for Server Configuration (/api/server_configuration)."""
from decimal import Decimal

from flask import Blueprint, current_app, jsonify, request

from app.auth import require_api_key
from app.models.database import db
from app.models.server_configuration import server_configuration
from app.time_utils import format_app_datetime

server_configuration_bp = Blueprint("server_configuration", __name__, url_prefix="/api/server_configuration")

@server_configuration_bp.route("", methods=["POST"])
@require_api_key
def create_server_configuration():
    current_app.logger.info("Redirecting to /server_configuration")

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    new_server_configurations = []

    try:
        """Determines whether to update existing server_configurationdata or add a new one.
        If the request body contains an 'id' and 'value', it updates the existing row with that id.
        If the request body contains a 'config_key', it adds a new row with that config_key and value.
        """
        if "id" in data and "value" in data:
            row_id = data["id"]
            field_value = str(data.get("value"))

            existing_row = server_configuration.query.filter_by(id=row_id).first()
            if not existing_row:
                return jsonify({"error": f"No server configuration found with id {row_id}"}), 404

            existing_row.value = field_value

            new_server_configurations.append({
                "id": existing_row.id,
                "config_key": existing_row.config_key,
                "value": existing_row.value,
            })
            db.session.add(existing_row)

        elif "config_key" in data:
            config_group = data.get("config_key")
            if not isinstance(config_group, dict):
                return jsonify({"error": "Expected 'config_key' payload to be an object"}), 400

            for config_type, payload in config_group.items():
                if not isinstance(payload, dict):
                    return jsonify({"error": f"Expected '{config_type}' payload to be an object"}), 400

            for config_type, payload in config_group.items():
                for field_name, field_data in payload.items():
                    config_key = f"{config_type}_{field_name}"
                    field_value = str(field_data)

                    new_row = server_configuration(
                        config_key=config_key, 
                        value=field_value
                    )

                    db.session.add(new_row)
                    db.session.flush()  # Flush to get the ID of the new row
                    new_server_configurations.append({
                        "id": new_row.id,
                        "config_key": config_key,
                        "value": field_value,
                    })

        else:
            return jsonify({"error": "Request body must contain either 'id' and 'value' or 'config_key'"}), 400

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
                    "created_at": format_app_datetime(config.created_at),
                    "updated_at": format_app_datetime(config.updated_at),
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
                    "created_at": format_app_datetime(config.created_at),
                    "updated_at": format_app_datetime(config.updated_at),
                }
            )

    return jsonify(
        {
            "message": "Server configuration data retrieval endpoint",
            "server_configuration_data": output,
        }
    ), 200
