"""Local application users used to authenticate JWTs."""
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from app.models.database import db
from app.time_utils import format_app_datetime


def _utcnow():
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(150), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(255))
    email = db.Column(db.String(255))
    role = db.Column(db.String(32), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    notification_states = db.relationship(
        "NotificationUserState",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def set_password(self, password):
        # Explicit PBKDF2 avoids relying on optional OpenSSL scrypt support.
        self.password_hash = generate_password_hash(
            password,
            method="pbkdf2:sha256:600000",
        )

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_public_dict(self, permissions):
        return {
            "username": self.username,
            "display_name": self.display_name,
            "email": self.email,
            "role": self.role,
            "permissions": permissions,
        }

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "email": self.email,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": format_app_datetime(self.created_at),
            "updated_at": format_app_datetime(self.updated_at),
        }
