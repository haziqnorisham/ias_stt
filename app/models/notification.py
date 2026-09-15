"""Persistent in-app notification events and per-user state."""
from datetime import datetime, timezone

from app.models.database import db
from app.time_utils import format_app_datetime


def _utcnow():
    return datetime.now(timezone.utc)


class Notification(db.Model):
    """An immutable event that can be shown in the notification panel."""

    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    event_type = db.Column(db.String(100), nullable=False)
    severity = db.Column(db.String(20), nullable=False, default="info")
    title = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)

    # Generic entity/source references keep this model usable for traps,
    # trackers, deployments, and future notification-producing features.
    entity_type = db.Column(db.String(50))
    entity_id = db.Column(db.String(100))
    source_type = db.Column(db.String(50))
    source_id = db.Column(db.String(100))

    # Stores structured event context such as coordinates or the old/new state.
    payload = db.Column(db.JSON)
    dedupe_key = db.Column(db.String(255), unique=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True))

    user_states = db.relationship(
        "NotificationUserState",
        back_populates="notification",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.Index("ix_notifications_created_id", "created_at", "id"),
        db.Index("ix_notifications_event_created", "event_type", "created_at"),
    )

    def to_dict(self, user_state=None):
        """Serialize the event and optional state for one authenticated user."""
        return {
            "id": self.id,
            "event_type": self.event_type,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "payload": self.payload,
            "dedupe_key": self.dedupe_key,
            "created_at": format_app_datetime(self.created_at),
            "expires_at": format_app_datetime(self.expires_at),
            "read_at": format_app_datetime(user_state.read_at)
            if user_state is not None
            else None,
            "dismissed_at": format_app_datetime(user_state.dismissed_at)
            if user_state is not None
            else None,
        }

    def __repr__(self):
        return (
            f"<Notification id={self.id} event_type={self.event_type!r}"
            f" severity={self.severity!r}>"
        )


class NotificationUserState(db.Model):
    """Read and dismissal state for one user and one notification event."""

    __tablename__ = "notification_user_states"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    notification_id = db.Column(
        db.Integer,
        db.ForeignKey("notifications.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    read_at = db.Column(db.DateTime(timezone=True))
    dismissed_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    notification = db.relationship(
        "Notification",
        back_populates="user_states",
    )
    user = db.relationship(
        "User",
        back_populates="notification_states",
    )

    __table_args__ = (
        db.UniqueConstraint(
            "notification_id",
            "user_id",
            name="uq_notification_user_state",
        ),
        db.Index(
            "ix_notification_user_states_user_status",
            "user_id",
            "dismissed_at",
            "read_at",
            "notification_id",
        ),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "notification_id": self.notification_id,
            "user_id": self.user_id,
            "read_at": format_app_datetime(self.read_at),
            "dismissed_at": format_app_datetime(self.dismissed_at),
            "created_at": format_app_datetime(self.created_at),
        }

    def __repr__(self):
        return (
            f"<NotificationUserState notification_id={self.notification_id}"
            f" user_id={self.user_id} dismissed={self.dismissed_at is not None}>"
        )
