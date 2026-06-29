"""Outbound notification helpers (Telegram via Node-RED)."""
import logging

import requests

from app.models.database import get_engine
from sqlalchemy import select

logger = logging.getLogger("app.notification")

NODE_RED_URL = "https://nodered.camartcctv.com/telegram/sender"
CHAT_ID = "-1004391734174"


def send_tilt_alert(device_eui, trap_id, lat, lng):
    """Fire a Telegram notification when a trap closes (tilt → normal).

    The HTTP call is fire-and-forget — failures are logged but never block
    the caller.
    """
    map_url = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lng}"
    html = (
        f"Cage <b>{trap_id}</b> closed.\n"
        f'Location: <a href="{map_url}">{lat},{lng}</a>'
    )

    body = {
        "chatId": CHAT_ID,
        "type": "message",
        "content": html,
        "options": {"parse_mode": "html"},
    }

    try:
        resp = requests.post(NODE_RED_URL, json=body, timeout=10)
        resp.raise_for_status()
        logger.info(
            "Tilt alert sent for cage %s (device %s)", trap_id, device_eui
        )
    except Exception:
        logger.exception(
            "Failed to send tilt alert for cage %s (device %s)",
            trap_id,
            device_eui,
        )


def _get_trap_info(device_eui):
    """Return (trap_id, lat, lng) for the trap linked to *device_eui*."""
    from app.models.trap import Trap
    from app.models.smart_trap_tracker import SmartTrapTracker as STT

    with get_engine().connect() as conn:
        # Look up the trap by tracker_id == device_eui
        trap_row = conn.execute(
            select(Trap.trap_id, Trap.tracker_id)
            .where(Trap.tracker_id == device_eui)
            .limit(1)
        ).first()
        if trap_row is None:
            return None, None, None

        # Look up coordinates from the tracker
        tracker_row = conn.execute(
            select(STT.latitude, STT.longitude)
            .where(STT.device_eui == device_eui)
            .limit(1)
        ).first()
        if tracker_row is None or tracker_row.latitude is None or tracker_row.longitude is None:
            return trap_row.trap_id, None, None

        return (
            trap_row.trap_id,
            float(tracker_row.latitude),
            float(tracker_row.longitude),
        )


def notify_if_trap_closed(device_eui):
    """Check if a trap linked to *device_eui* should get a closure alert.

    Returns True if the notification was sent, False otherwise.
    """
    trap_id, lat, lng = _get_trap_info(device_eui)
    if trap_id is None:
        logger.warning("No trap linked to device %s — skipping tilt alert", device_eui)
        return False
    if lat is None or lng is None:
        logger.warning(
            "No coordinates for device %s (trap %s) — skipping tilt alert",
            device_eui,
            trap_id,
        )
        return False

    send_tilt_alert(device_eui, trap_id, lat, lng)
    return True
