"""Smart Trap Tracker model."""
from datetime import datetime, timezone

from app.models.database import db
from app.time_utils import format_app_datetime


def _utcnow():
    return datetime.now(timezone.utc)


class SmartTrapTracker(db.Model):
    __tablename__ = "smart_trap_tracker"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    display_name = db.Column(db.String(255))
    device_eui = db.Column(db.String(100), unique=True, nullable=False)
    latitude = db.Column(db.Numeric(8, 5))
    longitude = db.Column(db.Numeric(8, 5))
    tilt_status = db.Column(db.String(50))
    battery = db.Column(db.Integer)
    tamper_status = db.Column(db.String(50), nullable=True)
    rssi = db.Column(db.Integer, nullable=True)
    snr = db.Column(db.Numeric(5, 2), nullable=True)
    created_date = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_date = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    def to_dict(self):
        return {
            "id": self.id,
            "display_name": self.display_name,
            "device_eui": self.device_eui,
            "latitude": float(self.latitude) if self.latitude is not None else None,
            "longitude": float(self.longitude) if self.longitude is not None else None,
            "tilt_status": self.tilt_status,
            "battery": self.battery,
            "tamper_status": self.tamper_status,
            "rssi": self.rssi,
            "snr": float(self.snr) if self.snr is not None else None,
            "signal_quality": self.signal_quality,
            "created_date": format_app_datetime(self.created_date),
            "updated_date": format_app_datetime(self.updated_date),
        }

    def __repr__(self):
        return (
            f"<SmartTrapTracker id={self.id} device_eui={self.device_eui!r}>"
        )

    @classmethod
    def exists_by_device_eui(cls, device_eui):
        """Return True if a row exists with this device_eui, False otherwise."""
        from app.models.database import get_engine

        stmt = (
            db.select(cls.device_eui)
            .where(cls.device_eui == device_eui)
            .limit(1)
        )
        with get_engine().connect() as conn:
            return conn.execute(stmt).first() is not None

    @classmethod
    def update_by_device_eui(cls, device_eui, **fields):
        """Update columns of the row matching *device_eui* using the raw engine.

        ``updated_date`` is auto-bumped regardless of which fields are passed.
        Uses the stored raw engine so the call works from the MQTT thread
        without a Flask application context.
        """
        from app.models.database import get_engine
        from sqlalchemy import update as sa_update

        stmt = (
            sa_update(cls)
            .where(cls.device_eui == device_eui)
            .values(updated_date=_utcnow(), **fields)
        )
        with get_engine().connect() as conn:
            conn.execute(stmt)
            conn.commit()

    @property
    def signal_quality(self):
      if self.rssi is None or self.snr is None:
        return "Unknown"
      if self.rssi >= -90 and float(self.snr) >= 5:
        return "Excellent"
      elif self.rssi >= -105 and float(self.snr) >= 0:
        return "Good"
      elif self.rssi >= -115 and float(self.snr) >= -7:
        return "Fair"
      return "Weak"
