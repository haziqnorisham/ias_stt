"""MQTT message processing — currently log-only; hook for future logic."""
import json
import logging

from app.models.trap import Trap

logger = logging.getLogger("app.data_processor")


def device_exists(dev_eui):
    """Check whether *dev_eui* is known in the traps tracker_id column."""
    logger.info("Checking device existence for devEui: %s", dev_eui)
    try:
        found = Trap.exists_by_tracker_id(dev_eui)
        logger.info("device_exists('%s') → %s", dev_eui, found)
        return found
    except Exception:
        logger.exception(
            "Database error while checking devEui '%s'", dev_eui
        )
        return False


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
    else:
        logger.warning(
            "deviceEui not found in payload on topic '%s'", topic
        )

    logger.info(
        "Topic: %s\nParsed JSON:\n%s", topic, json.dumps(data, indent=2)
    )
