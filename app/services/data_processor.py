"""MQTT message processing — currently log-only; hook for future logic."""
import json
import logging

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
