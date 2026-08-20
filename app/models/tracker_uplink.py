"""Historical decoded uplinks received from registered tracker devices."""
from datetime import datetime, timezone

from app.models.database import db
from app.time_utils import format_app_datetime


def _utcnow():
    return datetime.now(timezone.utc)


class TrackerUplink(db.Model):
    """One persisted uplink received from a known tracker device."""

    __tablename__ = "tracker_uplinks"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    device_eui = db.Column(db.String(100), nullable=False, index=True)
    received_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False, index=True)
    source = db.Column(db.String(20), nullable=False, default="mqtt")
    topic = db.Column(db.String(512))
    latitude = db.Column(db.Numeric(8, 5))
    longitude = db.Column(db.Numeric(8, 5))
    tilt_status = db.Column(db.String(50))
    battery = db.Column(db.Integer)
    raw_payload = db.Column(db.Text, nullable=False)

    __table_args__ = (
        db.Index(
            "ix_tracker_uplinks_device_received",
            "device_eui",
            "received_at",
        ),
    )

    def to_dict(self, include_raw=False, display_name=None):
        result = {
            "id": self.id,
            "device_eui": self.device_eui,
            "display_name": display_name,
            "received_at": format_app_datetime(self.received_at),
            "source": self.source,
            "topic": self.topic,
            "latitude": float(self.latitude) if self.latitude is not None else None,
            "longitude": float(self.longitude)
            if self.longitude is not None
            else None,
            "tilt_status": self.tilt_status,
            "battery": self.battery,
        }
        if include_raw:
            result["raw_payload"] = self.raw_payload
        return result

    def __repr__(self):
        return (
            f"<TrackerUplink id={self.id} device_eui={self.device_eui!r}"
            f" received_at={self.received_at!r}>"
        )
