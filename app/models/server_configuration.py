# app/models/geofencing.py
from app.models.database import db
from app.models.deployment_location import _utcnow
from app.time_utils import format_app_datetime

class server_configuration(db.Model):
    __tablename__ = "server_configuration"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    config_key = db.Column(db.String(50), nullable=False)
    value = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    def to_dict(self):
        return {
            "id": self.id,
            "config_key": self.config_key,
            "value": self.value,
            "created_at": format_app_datetime(self.created_at),
            "updated_at": format_app_datetime(self.updated_at),
        }
