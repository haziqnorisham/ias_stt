"""Location-history entry for a deployment."""
from datetime import datetime, timezone

from app.models.database import db


def _utcnow():
    return datetime.now(timezone.utc)


class DeploymentLocation(db.Model):
    __tablename__ = "deployment_locations"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    deployment_id = db.Column(
        db.Integer, db.ForeignKey("deployments.id", ondelete="CASCADE"), nullable=False
    )
    location = db.Column(db.String(50), nullable=False)
    recorded_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "deployment_id": self.deployment_id,
            "location": self.location,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return (
            f"<DeploymentLocation id={self.id} deployment_id={self.deployment_id}"
            f" location={self.location!r}>"
        )
