"""Trap deployment model — one deployment per active period in the field."""
from datetime import datetime, timezone

from app.models.database import db
from app.time_utils import format_app_datetime


def _utcnow():
    return datetime.now(timezone.utc)


class Picture(db.Model):
    __tablename__ = "pictures"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    deployment_id = db.Column(db.Integer, db.ForeignKey("deployments.id"), nullable=False)
    photo_url = db.Column(db.String(500))
    photo_filename = db.Column(db.String(255))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    def to_dict(self):
        return {
            "id": self.id,
            "deployment_id": self.deployment_id,
            "photo_url": self.photo_url,
            "photo_filename": self.photo_filename,
            "created_at": format_app_datetime(self.created_at),
            "updated_at": format_app_datetime(self.updated_at),
        }

