"""RSSI summaries from the latest stored inbound message for each tracker."""
import json
import math

from sqlalchemy import select

from app.models.database import db
from app.models.smart_trap_tracker import SmartTrapTracker
from app.models.tracker_uplink import TrackerUplink
from app.time_utils import format_app_datetime


def parse_uplink_rssi(payload):
    """Return the strongest finite gateway RSSI, or None when unavailable."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            return None
    if not isinstance(payload, dict):
        return None

    receptions = payload.get("rxInfo", payload.get("rx_info"))
    if not isinstance(receptions, list):
        return None
    readings = []
    for reception in receptions:
        value = reception.get("rssi") if isinstance(reception, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        try:
            value = float(value)
        except (ValueError, OverflowError):
            continue
        if math.isfinite(value):
            readings.append(value)
    return max(readings) if readings else None


def get_latest_tracker_signals(device_euis):
    """Fetch one latest payload per tracker in a single SQL query.

    The correlated lookup uses the existing device/received-at index. Only
    the newest payload is fetched, ordered by receipt time and then row ID;
    a missing RSSI in that payload must not fall back to an older message.
    """
    device_euis = {value for value in device_euis if value}
    if not device_euis:
        return {}

    latest_uplink_id = (
        select(TrackerUplink.id)
        .where(TrackerUplink.device_eui == SmartTrapTracker.device_eui)
        .order_by(TrackerUplink.received_at.desc(), TrackerUplink.id.desc())
        .limit(1)
        .correlate(SmartTrapTracker)
        .scalar_subquery()
    )
    stmt = (
        select(
            SmartTrapTracker.device_eui,
            TrackerUplink.received_at,
            TrackerUplink.raw_payload,
        )
        .outerjoin(TrackerUplink, TrackerUplink.id == latest_uplink_id)
        .where(SmartTrapTracker.device_eui.in_(device_euis))
    )
    return {
        row.device_eui: {
            "rssi": parse_uplink_rssi(row.raw_payload),
            "rssi_received_at": format_app_datetime(row.received_at),
        }
        for row in db.session.execute(stmt)
    }


def add_latest_rssi(items, *, device_eui_field="device_eui", prefix=""):
    """Enrich an API result page without a separate lookup for every row."""
    signals = get_latest_tracker_signals(item.get(device_eui_field) for item in items)
    for item in items:
        signal = signals.get(item.get(device_eui_field), {})
        item[f"{prefix}rssi"] = signal.get("rssi")
        item[f"{prefix}rssi_received_at"] = signal.get("rssi_received_at")
    return items
