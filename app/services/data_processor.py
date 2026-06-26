"""MQTT message processing — currently log-only; hook for future logic."""
import json
import logging

logger = logging.getLogger("app.data_processor")


def device_exists(dev_eui):
    """Check whether *dev_eui* is known in the traps tracker_id column.

    Currently a stub — always returns True. Will be replaced with a database
    query when the processing layer is wired to the traps table.
    """
    return True


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
