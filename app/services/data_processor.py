"""MQTT message processing — currently log-only; hook for future logic."""
import json
import logging
from urllib import response
import requests
from geopy.distance import geodesic
from app.services import deployment_service
from app.models.trap import Trap
from app.models.database import db

from app.models.smart_trap_tracker import SmartTrapTracker

logger = logging.getLogger("app.data_processor")


def device_exists(dev_eui):
    """Check whether *dev_eui* is known in the traps tracker_id column."""
    logger.info("Checking device existence for devEui: %s", dev_eui)
    try:
        found = SmartTrapTracker.exists_by_device_eui(dev_eui)
        logger.info("device_exists('%s') → %s", dev_eui, found)
        return found
    except Exception:
        logger.exception(
            "Database error while checking devEui '%s'", dev_eui
        )
        return False


def _apply_inbound_update(data, dev_eui):
    """Map sensor keys from ``data['object']`` to tracker columns and persist.

    Only keys that are actually present in the payload are applied.  Unknown
    keys are silently ignored so that unrelated sensor readings (e.g.
    ``distance``) are not treated as errors.
    """
    if not device_exists(dev_eui):
        logger.warning(
            "Received update for unknown deviceEui '%s'; ignoring", dev_eui
        )
        return
    
    obj = data.get("object", {})
    if not isinstance(obj, dict) or not obj:
        return

    FIELD_MAP = {
        "latitude": "latitude",
        "longitude": "longitude",
        "position": "tilt_status",
        "battery": "battery",
    }

    updates = {}
    for mqtt_key, col in FIELD_MAP.items():
        if mqtt_key not in obj:
            continue
        value = obj[mqtt_key]
        if col == "battery":
            try:
                value = int(value)
            except (ValueError, TypeError):
                continue
        elif col in ("latitude", "longitude"):
            try:
                value = float(value)
            except (ValueError, TypeError):
                continue
        updates[col] = value

    latitude = updates.get("latitude")
    longitude = updates.get("longitude")

    if updates:
        old_tilt = None
        if "tilt_status" in updates:
            old_tilt = _get_current_tilt(dev_eui)

        SmartTrapTracker.update_by_device_eui(dev_eui, **updates)
        logger.info("Updated tracker %s with: %s", dev_eui, updates)

        if (
            "tilt_status" in updates
            and old_tilt != updates["tilt_status"]
            and updates["tilt_status"] == "normal"
        ):
            _notify_trap_closed(dev_eui)

    if latitude is not None and longitude is not None:
        _create_new_deployment(dev_eui, latitude, longitude)


def _create_new_deployment(dev_eui, latitude, longitude):
    """Create a new deployment if the sensor status is inactive and its position is outside the geofence, 
    or close the active deployment if the sensor position is inside the geofence.
    """
    stt_url = "/api/stt"
    server_config_url = "/server_configuration"

    """"fetch the geofence configuration from the server_configuration table"""
    response_config = requests.get(f"{server_config_url}?config_key=geofence")

    """"fetch the geofence data from the smart_trap_tracker table"""
    response_tracker = requests.get(f"{stt_url}")

    if not response_config.status_code == 200:
        print(f"Error {response_config.status_code}:", response_config.text)

    api_response = response_config.json()

    config_data = api_response.get("server_configuration_data", [])

    config_latitude = None
    config_longitude = None
    config_radius = None

    for item in config_data: 
        key = item.get("config_key")

        if key == "geofence_latitude":
            config_latitude = float(item.get("value"))
        elif key == "geofence_longitude":
            config_longitude = float(item.get("value"))
        elif key == "geofence_radius":
            config_radius = float(item.get("value"))

    user_coords = (latitude, longitude)
    fence_coords = (config_latitude, config_longitude)

    """Check if the user coordinates are within the geofence defined by the configuration."""
    within_geofence = is_within_geofence(user_coords, fence_coords, config_radius)
    logger.info(
        "Geofence center=(%s,%s) radius=%s km; device=(%s,%s) within_geofence=%s",
        config_latitude,
        config_longitude,
        config_radius,
        latitude,
        longitude,
        within_geofence,
    )

    """Check the deployment status of the trap based on its tracker_id and the geofence status."""
    trap = Trap.query.filter_by(tracker_id=dev_eui).first()
    if not trap:
        # no trap known for this device
        logger.info("No Trap found for tracker_id=%s", dev_eui)
        active = None
    else:
        active = trap.get_active_deployment()  # Deployment or None
        logger.info(
            "Found Trap id=%s tracker_id=%s active_deployment=%s",
            trap.id,
            trap.tracker_id,
            getattr(active, "id", None),
        )

        """Determine the action to take based on the geofence status and deployment status."""
        if within_geofence and active:
                # if the trap is within the geofence and has an active deployment, close it
                logger.info("Within geofence and active deployment exists; closing deployment for trap id=%s", trap.id)
                deployment_service.close_active_deployment(trap)
                db.session.commit()
        elif within_geofence and not active:
                # if the trap is within the geofence and has no active deployment, do nothing
                logger.info("Within geofence and no active deployment; no action for trap id=%s", getattr(trap, "id", None))
        
        elif not within_geofence and active:
                # if the trap is outside the geofence and has an active deployment, do nothing
                logger.info("Outside geofence and active deployment exists; no action for trap id=%s", trap.id)
        elif not within_geofence and not active:
                # if the trap is outside the geofence and has no active deployment, create one
                logger.info("Outside geofence and no active deployment; creating deployment for trap id=%s", getattr(trap, "id", None))
                deployment_service.create_deployment(trap, location=f"{latitude},{longitude}")
                db.session.commit()
    

def is_within_geofence(user_coords, fence_coords, radius_km):
    """Checks if user_coords is within radius_km of fence_coords.
    Parameters are passed as (latitude, longitude) tuples.
    """
    # geodesic() calculates the high-accuracy distance on the Earth's ellipsoid
    distance = geodesic(user_coords, fence_coords).km
    return distance <= radius_km
    

def _get_current_tilt(dev_eui):
    """Return the current tilt_status for *dev_eui*, or None."""
    from app.models.database import get_engine
    from sqlalchemy import select as sa_select

    stmt = (
        sa_select(SmartTrapTracker.tilt_status)
        .where(SmartTrapTracker.device_eui == dev_eui)
        .limit(1)
    )
    with get_engine().connect() as conn:
        row = conn.execute(stmt).first()
        return row[0] if row else None


def _notify_trap_closed(dev_eui):
    from app.services.notification import notify_if_trap_closed

    notify_if_trap_closed(dev_eui)


def process_message(topic, payload):
    """Single entry-point for every incoming MQTT message.

    Attempts to parse *payload* as JSON. Valid JSON is pretty-printed at INFO
    level; invalid payloads are logged at ERROR level and discarded.
    """
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.error(
            "Invalid JSON payload received on topic '%s': %s", topic, payload
        )
        return

    dev_eui = data.get("deviceInfo", {}).get("devEui")
    if dev_eui:
        logger.info("deviceEui: %s", dev_eui)
        known = device_exists(dev_eui)
        logger.info("device_exists('%s') → %s", dev_eui, known)
        if known:
            _apply_inbound_update(data, dev_eui)
    else:
        logger.warning(
            "deviceEui not found in payload on topic '%s'", topic
        )

    logger.info(
        "Topic: %s\nParsed JSON:\n%s", topic, json.dumps(data, indent=2)
    )
