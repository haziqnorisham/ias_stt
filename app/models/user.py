"""Locally managed application identities and authorization roles."""
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from app.models.database import db
from app.time_utils import format_app_datetime


def _utcnow():
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"
    __table_args__ = (
        db.Index(
            "uq_users_directory_identity",
            "directory_key",
            "directory_subject",
            unique=True,
        ),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(150), nullable=False, unique=True, index=True)
    auth_provider = db.Column(db.String(10), nullable=False, default="LOCAL")
    password_hash = db.Column(db.String(255))
    directory_key = db.Column(db.String(100))
    directory_subject = db.Column(db.String(255))
    ldap_dn = db.Column(db.String(1024))
    ldap_synced_at = db.Column(db.DateTime(timezone=True))
    display_name = db.Column(db.String(255))
    email = db.Column(db.String(255))
    role = db.Column(db.String(32), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    token_version = db.Column(db.Integer, nullable=False, default=0)
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
        if self.auth_provider not in (None, "LOCAL"):
            raise ValueError("Only LOCAL users can have a locally stored password")
        # Explicit PBKDF2 avoids relying on optional OpenSSL scrypt support.
        self.password_hash = generate_password_hash(
            password,
            method="pbkdf2:sha256:600000",
        )

    def check_password(self, password):
        return bool(
            self.auth_provider == "LOCAL"
            and self.password_hash
            and check_password_hash(self.password_hash, password)
        )

    def to_public_dict(self, permissions):
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "email": self.email,
            "role": self.role,
            "permissions": permissions,
            "auth_provider": self.auth_provider,
        }

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "auth_provider": self.auth_provider,
            "directory_key": self.directory_key,
            "directory_subject": self.directory_subject,
            "ldap_synced_at": format_app_datetime(self.ldap_synced_at),
            "display_name": self.display_name,
            "email": self.email,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": format_app_datetime(self.created_at),
            "updated_at": format_app_datetime(self.updated_at),
        }
