"""MQTT service (Phase 2).

This module is fully self-contained: all paho-mqtt logic lives here so it can be
debugged independently of the Flask application. The only Flask touch-point is
``init_mqtt(app)``, which reads configuration from ``app.config`` and starts the
client in a background thread.
"""
import atexit
import logging
import os
from datetime import datetime

import paho.mqtt.client as mqtt

logger = logging.getLogger("app.mqtt")


class MQTTService:
    """Thin wrapper around a paho-mqtt client (callback API v2)."""

    def __init__(
        self,
        broker_host,
        broker_port=1883,
        client_id=None,
        topics=None,
        username=None,
        password=None,
        keepalive=60,
    ):
        self.broker_host = broker_host
        self.broker_port = int(broker_port)
        self.client_id = client_id
        self.topics = topics or []
        self.keepalive = int(keepalive)

        # Track subscribe message-id -> topic so on_subscribe can report which
        # topic each SUBACK refers to.
        self._pending_subs = {}

        # paho-mqtt 2.x requires explicitly opting into a callback API version.
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
            clean_session=True,
        )

        if username:
            self.client.username_pw_set(username, password)

        # Exponential backoff between automatic reconnect attempts.
        self.client.reconnect_delay_set(min_delay=1, max_delay=60)

        # Wire up callbacks.
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.on_subscribe = self.on_subscribe
        self.client.on_log = self.on_log

        # Route paho's internal logs (incl. raw SUBSCRIBE/SUBACK packets) through
        # our logger at DEBUG level for full message-flow visibility.
        self.client.enable_logger(logger)

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def connect(self):
        """Connect to the broker without blocking and start the network loop.

        Uses ``connect_async`` + ``loop_start`` so that an unreachable broker
        never blocks or crashes the Flask server; paho keeps retrying in the
        background thread.
        """
        try:
            logger.info(
                "Connecting to MQTT broker %s:%s (client_id=%s)",
                self.broker_host,
                self.broker_port,
                self.client_id,
            )
            self.client.connect_async(
                self.broker_host, self.broker_port, keepalive=self.keepalive
            )
            self.client.loop_start()
        except Exception:
            logger.exception("Failed to initiate MQTT connection")

    def disconnect(self):
        """Cleanly stop the network loop and disconnect from the broker."""
        try:
            logger.info("Disconnecting from MQTT broker")
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            logger.exception("Error during MQTT disconnect")

    def _subscribe_all(self):
        for topic in self.topics:
            result, mid = self.client.subscribe(topic)
            if result == mqtt.MQTT_ERR_SUCCESS:
                self._pending_subs[mid] = topic
                logger.info("SUBSCRIBE sent for topic: %s (mid=%s)", topic, mid)
            else:
                logger.error(
                    "Failed to send SUBSCRIBE for topic '%s' (error code %s)",
                    topic,
                    result,
                )

    # ------------------------------------------------------------------ #
    # Callbacks (paho-mqtt callback API v2 signatures)
    # ------------------------------------------------------------------ #
    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            logger.info("Connected to MQTT broker successfully (flags=%s)", flags)
            # Subscribe here so subscriptions are restored on every reconnect.
            self._subscribe_all()
        else:
            logger.error("MQTT connection failed: %s", reason_code)

    def on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            logger.info("Disconnected from MQTT broker (clean)")
        else:
            logger.warning(
                "Unexpected MQTT disconnect (code %s); auto-reconnect in progress",
                reason_code,
            )

    def on_subscribe(self, client, userdata, mid, reason_code_list, properties=None):
        topic = self._pending_subs.pop(mid, "<unknown>")
        for rc in reason_code_list:
            # In MQTT a granted code >= 128 means the broker REJECTED the
            # subscription (e.g. ACL denial), even though a SUBACK was returned.
            is_failure = getattr(rc, "is_failure", None)
            if is_failure is None:
                is_failure = getattr(rc, "value", rc) >= 128
            if is_failure:
                logger.error(
                    "Subscription REJECTED for topic '%s' (mid=%s, reason=%s)",
                    topic,
                    mid,
                    rc,
                )
            else:
                logger.info(
                    "SUBACK: subscribed to '%s' (mid=%s, granted QoS=%s)",
                    topic,
                    mid,
                    rc,
                )

    def on_log(self, client, userdata, level, buf):
        # paho's internal protocol logs (raw SUBSCRIBE/SUBACK/PUBLISH packets).
        logger.debug("paho: %s", buf)

    def on_message(self, client, userdata, msg):
        """Phase 2: print received messages to the console."""
        try:
            raw = msg.payload
            try:
                decoded = raw.decode("utf-8")
            except (UnicodeDecodeError, AttributeError):
                decoded = repr(raw)

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            logger.info(
                "\n%s\n\U0001F4E8 MQTT Message Received\n"
                "Topic: %s\nQoS: %s | Retain: %s\nTimestamp: %s\nPayload: %s\n%s",
                "=" * 59,
                msg.topic,
                msg.qos,
                msg.retain,
                timestamp,
                decoded,
                "-" * 59,
            )
        except Exception:
            logger.exception("Error while handling incoming MQTT message")


def init_mqtt(app):
    """Build, connect, and register the MQTT service for the given Flask app.

    All MQTT concerns stay in this module; the Flask app only calls this once.
    """
    config = app.config

    if not config.get("MQTT_ENABLED", True):
        app.logger.info("MQTT is disabled (MQTT_ENABLED=false); skipping startup")
        return None

    # Flask's debug reloader spawns two processes. Without this guard the MQTT
    # client would connect twice with the same client_id, causing the broker to
    # repeatedly disconnect both. Only start in the reloaded worker process.
    if config.get("DEBUG") and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        app.logger.debug("Skipping MQTT init in reloader parent process")
        return None

    if not config.get("MQTT_BROKER_HOST"):
        app.logger.warning("MQTT_BROKER_HOST not set; MQTT service not started")
        return None

    if not config.get("MQTT_TOPICS"):
        app.logger.warning("No MQTT_TOPICS configured; MQTT service not started")
        return None

    service = MQTTService(
        broker_host=config["MQTT_BROKER_HOST"],
        broker_port=config["MQTT_BROKER_PORT"],
        client_id=config["MQTT_CLIENT_ID"],
        topics=config["MQTT_TOPICS"],
        username=config.get("MQTT_USERNAME"),
        password=config.get("MQTT_PASSWORD"),
        keepalive=config["MQTT_KEEPALIVE"],
    )
    service.connect()

    # Keep a handle on the app and ensure clean shutdown.
    app.mqtt_service = service
    atexit.register(service.disconnect)

    return service
