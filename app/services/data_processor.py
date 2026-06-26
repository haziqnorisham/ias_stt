"""MQTT message processing — currently log-only; hook for future logic."""
import logging

logger = logging.getLogger("app.data_processor")


def process_message(topic, payload):
    """Single entry-point for every incoming MQTT message.

    For now the only behaviour is console logging. The *topic* and a decoded
    string *payload* are expected, so the MQTT service handles raw→string
    conversion before calling this method.
    """
    logger.info("Topic: %s\nPayload: %s", topic, payload)
