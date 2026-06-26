"""MQTT message processing — currently log-only; hook for future logic."""
import json
import logging

logger = logging.getLogger("app.data_processor")


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
    logger.info(
        "Topic: %s\nParsed JSON:\n%s", topic, json.dumps(data, indent=2)
    )
