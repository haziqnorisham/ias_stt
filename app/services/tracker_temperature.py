"""Parse tracker temperatures and restore latest readings from stored uplinks."""
import json
import math

from sqlalchemy import and_, or_, select

from app.models.database import get_engine
from app.models.smart_trap_tracker import SmartTrapTracker
from app.models.tracker_uplink import TrackerUplink


def parse_temperature(value):
    """Return a finite Celsius reading, or None for an invalid value."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        temperature = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return temperature if math.isfinite(temperature) else None


def backfill_tracker_temperatures(batch_size=200):
    """Restore each tracker's latest valid reading without altering update dates.

    Pages are read newest first through the device/received-at index. The
    conditional tracker update protects readings that arrive during a backfill.
    """
    with get_engine().connect() as conn:
        device_euis = conn.execute(
            select(SmartTrapTracker.device_eui).where(
                SmartTrapTracker.temperature.is_(None)
            )
        ).scalars().all()

    updated = 0
    for device_eui in device_euis:
        cursor = None
        while True:
            stmt = (
                select(
                    TrackerUplink.id,
                    TrackerUplink.received_at,
                    TrackerUplink.raw_payload,
                )
                .where(TrackerUplink.device_eui == device_eui)
                .order_by(
                    TrackerUplink.received_at.desc(), TrackerUplink.id.desc()
                )
                .limit(batch_size)
            )
            if cursor is not None:
                received_at, uplink_id = cursor
                stmt = stmt.where(
                    or_(
                        TrackerUplink.received_at < received_at,
                        and_(
                            TrackerUplink.received_at == received_at,
                            TrackerUplink.id < uplink_id,
                        ),
                    )
                )

            with get_engine().connect() as conn:
                rows = conn.execute(stmt).all()
            if not rows:
                break

            found = False
            for row in rows:
                try:
                    payload = json.loads(row.raw_payload)
                except (TypeError, ValueError):
                    continue
                obj = payload.get("object") if isinstance(payload, dict) else None
                if not isinstance(obj, dict):
                    continue
                temperature = parse_temperature(obj.get("temperature"))
                if temperature is None:
                    continue

                updated += bool(SmartTrapTracker.update_temperature_by_device_eui(
                    device_eui,
                    temperature,
                    row.received_at,
                    touch_updated_date=False,
                ))
                found = True
                break

            if found or len(rows) < batch_size:
                break
            cursor = (rows[-1].received_at, rows[-1].id)

    return updated
