"""Trap device configuration model.

Note on SQLite type mapping: SQLite has no native SERIAL / NUMERIC / TIMESTAMPTZ
types, so we use an autoincrement Integer primary key, ``Numeric`` (returned as
``Decimal``) for temperature, and timezone-aware UTC ``DateTime`` values. The
behaviour is equivalent at the ORM layer.
"""
from datetime import datetime, timezone

from app.models.database import db


def _utcnow():
    return datetime.now(timezone.utc)


class Trap(db.Model):
    __tablename__ = "traps"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    status = db.Column(db.String(20), nullable=False)
    trap_id = db.Column(db.String(50), nullable=False, unique=True)
    tracker_id = db.Column(db.String(50), nullable=False)
    location = db.Column(db.String(50))
    door_status = db.Column(db.String(20))
    temperature = db.Column(db.Numeric(5, 2))
    notes = db.Column(db.String(255))
    updated_by = db.Column(db.String(50), nullable=False, default="system")
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    def to_dict(self):
        location = self.location
        door_status = self.door_status
        latitude = None
        longitude = None
        map_url = None

        if self.tracker_id:
            from app.models.database import get_engine
            from app.models.smart_trap_tracker import SmartTrapTracker
            from sqlalchemy import select as sa_select

            stmt = (
                sa_select(
                    SmartTrapTracker.latitude,
                    SmartTrapTracker.longitude,
                    SmartTrapTracker.tilt_status,
                )
                .where(SmartTrapTracker.device_eui == self.tracker_id)
                .limit(1)
            )
            with get_engine().connect() as conn:
                row = conn.execute(stmt).first()
                if row:
                    if row.latitude is not None and row.longitude is not None:
                        lat = float(row.latitude)
                        lng = float(row.longitude)
                        location = f"{lat},{lng}"
                        latitude = lat
                        longitude = lng
                        map_url = (
                            f"https://www.google.com/maps/dir/?api=1"
                            f"&destination={lat},{lng}"
                        )
                    if row.tilt_status is not None:
                        door_status = row.tilt_status

        return {
            "id": self.id,
            "status": self.status,
            "trap_id": self.trap_id,
            "tracker_id": self.tracker_id,
            "location": location,
            "door_status": door_status,
            "latitude": latitude,
            "longitude": longitude,
            "map_url": map_url,
            "temperature": float(self.temperature)
            if self.temperature is not None
            else None,
            "notes": self.notes,
            "updated_by": self.updated_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<Trap id={self.id} trap_id={self.trap_id!r} status={self.status!r}>"

    @classmethod
    def exists_by_tracker_id(cls, tracker_id):
        """Return True if a row exists with this tracker_id, False otherwise."""
        from app.models.database import get_engine

        stmt = (
            db.select(cls.tracker_id)
            .where(cls.tracker_id == tracker_id)
            .limit(1)
        )
        with get_engine().connect() as conn:
            return conn.execute(stmt).first() is not None

    # ---- Deployment helpers ------------------------------------------------
    deployments = db.relationship(
        "Deployment",
        backref="trap",
        lazy="dynamic",
    )

    def get_active_deployment(self):
        """Return the first active deployment for this trap, or None."""
        return self.deployments.filter_by(status="active").first()
