"""Trap deployment model — one deployment per active period in the field."""
from datetime import datetime, timezone

from app.models.database import db
from app.time_utils import format_app_datetime


def _utcnow():
    return datetime.now(timezone.utc)


class Deployment(db.Model):
    __tablename__ = "deployments"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    trap_id = db.Column(db.Integer, db.ForeignKey("traps.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="active")
    start_date = db.Column(db.DateTime(timezone=True), default=_utcnow)
    end_date = db.Column(db.DateTime(timezone=True))
    animal_capture = db.Column(db.String(255))
    photo_url = db.Column(db.String(500))
    photo_filename = db.Column(db.String(255))
    notes = db.Column(db.String(500))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    locations = db.relationship(
        "DeploymentLocation",
        backref="deployment",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "trap_id": self.trap_id,
            "status": self.status,
            "start_date": format_app_datetime(self.start_date),
            "end_date": format_app_datetime(self.end_date),
            "animal_capture": self.animal_capture,
            "photo_url": self.photo_url,
            "photo_filename": self.photo_filename,
            "notes": self.notes,
            "created_at": format_app_datetime(self.created_at),
            "updated_at": format_app_datetime(self.updated_at),
        }

    def close(self):
        """Mark this deployment as closed and record the end date."""
        self.status = "closed"
        self.end_date = _utcnow()

    def add_location(self, location, notes=None):
        """Record a new location entry under this deployment."""
        return DeploymentLocation(
            deployment_id=self.id,
            location=location,
            notes=notes,
        )

    def __repr__(self):
        return (
            f"<Deployment id={self.id} trap_id={self.trap_id}"
            f" status={self.status!r}>"
        )
