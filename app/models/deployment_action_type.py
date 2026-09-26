"""Configurable action types available for deployment activity."""
from datetime import datetime, timezone

from app.models.database import db
from app.time_utils import format_app_datetime


def _utcnow():
    return datetime.now(timezone.utc)


class DeploymentActionType(db.Model):
    __tablename__ = "deployment_action_types"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    code = db.Column(db.String(50), nullable=False, unique=True)
    label = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(500))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    deployment_actions = db.relationship(
        "DeploymentAction",
        back_populates="action_type",
        lazy="dynamic",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "label": self.label,
            "description": self.description,
            "is_active": self.is_active,
            "created_at": format_app_datetime(self.created_at),
            "updated_at": format_app_datetime(self.updated_at),
        }


DEFAULT_ACTION_TYPES = (
    {
        "code": "bait_added",
        "label": "Added bait",
        "description": "Bait was added to the trap.",
    },
    {
        "code": "routine_check",
        "label": "Routine check",
        "description": "The trap was inspected during a routine check.",
    },
    {
        "code": "bait_removed",
        "label": "Bait removed",
        "description": "Bait was removed from the trap.",
    },
)


def seed_default_action_types():
    """Create the initial action types without duplicating existing rows."""
    added = False
    for values in DEFAULT_ACTION_TYPES:
        if DeploymentActionType.query.filter_by(code=values["code"]).first():
            continue
        db.session.add(DeploymentActionType(**values))
        added = True

    if added:
        db.session.commit()
