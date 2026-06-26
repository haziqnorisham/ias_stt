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
        return {
            "id": self.id,
            "status": self.status,
            "trap_id": self.trap_id,
            "tracker_id": self.tracker_id,
            "location": self.location,
            "door_status": self.door_status,
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
        stmt = (
            db.select(cls.tracker_id)
            .where(cls.tracker_id == tracker_id)
            .limit(1)
        )
        return db.session.execute(stmt).first() is not None
