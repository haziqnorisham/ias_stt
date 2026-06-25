"""Standalone MQTT wildcard diagnostic tool.

Connects to the broker configured in the environment (.env) and subscribes to
several topic-pattern variants side-by-side for a timed window, then prints how
many messages each pattern received plus a sample of the real topics observed.

This isolates wildcard behaviour: a single-level `+` must match exactly one
topic level, so a pattern with the wrong number of levels gets a SUBACK but
never receives messages.

Usage:
    venv/bin/python tests/mqtt_diag.py [seconds]

It is read-only: it only subscribes/observes, it never publishes.
"""
import os
import sys
import threading
import time

from dotenv import load_dotenv
import paho.mqtt.client as mqtt

load_dotenv()

HOST = os.getenv("MQTT_BROKER_HOST", "localhost")
PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))
USERNAME = os.getenv("MQTT_USERNAME") or None
PASSWORD = os.getenv("MQTT_PASSWORD") or None
WINDOW = int(sys.argv[1]) if len(sys.argv) > 1 else 30

_configured = (os.getenv("MQTT_TOPICS", "").split(",") or [""])[0].strip()
if "/device/" in _configured:
    APP_PREFIX = _configured.split("/device/")[0]
else:
    APP_PREFIX = _configured.rsplit("/", 1)[0] if "/" in _configured else _configured

PATTERNS = {
    "broken (+/event)": f"{APP_PREFIX}/device/+/event",
    "fixed  (+/event/+)": f"{APP_PREFIX}/device/+/event/+",
    "multi  (device/#)": f"{APP_PREFIX}/device/#",
}

counts = {name: 0 for name in PATTERNS}
samples = {name: [] for name in PATTERNS}
lock = threading.Lock()


def _matches(pattern, topic):
    p, t = pattern.split("/"), topic.split("/")
    i = 0
    for seg in p:
        if seg == "#":
            return True
        if i >= len(t):
            return False
        if seg != "+" and seg != t[i]:
            return False
        i += 1
    return i == len(t)


def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"CONNECT: {reason_code}")
    for name, pattern in PATTERNS.items():
        client.subscribe(pattern, 0)
        print(f"  subscribed [{name}] -> {pattern}")


def on_message(client, userdata, msg):
    with lock:
        for name, pattern in PATTERNS.items():
            if _matches(pattern, msg.topic):
                counts[name] += 1
                if len(samples[name]) < 5:
                    samples[name].append(msg.topic)


def main():
    if not APP_PREFIX:
        print("ERROR: could not derive a topic prefix from MQTT_TOPICS")
        sys.exit(1)

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="mqtt_diag_observer",
    )
    if USERNAME:
        client.username_pw_set(USERNAME, PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message

    print(f"Connecting to {HOST}:{PORT}, observing for {WINDOW}s...\n")
    client.connect(HOST, PORT, 60)
    client.loop_start()
    time.sleep(WINDOW)
    client.loop_stop()
    client.disconnect()

    print("\n===== DIAGNOSTIC RESULTS =====")
    for name in PATTERNS:
        print(f"\n[{name}]  pattern: {PATTERNS[name]}")
        print(f"  messages matched: {counts[name]}")
        for s in samples[name]:
            print(f"    e.g. {s}")
    print("\nConclusion: a pattern with the wrong level-count receives 0 even "
          "though the broker ACKs the subscription.")


if __name__ == "__main__":
    main()
