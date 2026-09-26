"""Immutable user activity recorded during a deployment."""
from datetime import datetime, timezone

from app.models.database import db
from app.time_utils import format_app_datetime


def _utcnow():
    return datetime.now(timezone.utc)


class DeploymentAction(db.Model):
    __tablename__ = "deployment_actions"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    deployment_id = db.Column(
        db.Integer,
        db.ForeignKey("deployments.id", ondelete="CASCADE"),
        nullable=False,
    )
    action_type_id = db.Column(
        db.Integer,
        db.ForeignKey("deployment_action_types.id", ondelete="RESTRICT"),
        nullable=False,
    )
    notes = db.Column(db.String(5000))
    picture_url = db.Column(db.String(500), nullable=False)
    picture_filename = db.Column(db.String(255), nullable=False)
    performed_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    performed_by = db.Column(db.String(150), nullable=False)

    deployment = db.relationship("Deployment", back_populates="actions")
    action_type = db.relationship(
        "DeploymentActionType",
        back_populates="deployment_actions",
    )

    @property
    def stored_filename(self):
        """Return the generated filename kept in the picture storage."""
        return self.picture_url

    def to_dict(self):
        return {
            "id": self.id,
            "deployment_id": self.deployment_id,
            "action_type": self.action_type.to_dict() if self.action_type else None,
            "notes": self.notes,
            "picture_url": (
                f"/api/deployment-actions/{self.id}/picture"
                if self.id is not None
                else None
            ),
            "picture_filename": self.picture_filename,
            "performed_at": format_app_datetime(self.performed_at),
            "performed_by": self.performed_by,
        }

    def __repr__(self):
        return (
            f"<DeploymentAction id={self.id} deployment_id={self.deployment_id}"
            f" action_type_id={self.action_type_id}>"
        )
