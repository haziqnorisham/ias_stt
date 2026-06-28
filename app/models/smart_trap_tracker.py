"""Smart Trap Tracker model."""
from datetime import datetime, timezone

from app.models.database import db


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
            "created_date": self.created_date.isoformat()
            if self.created_date
            else None,
            "updated_date": self.updated_date.isoformat()
            if self.updated_date
            else None,
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
