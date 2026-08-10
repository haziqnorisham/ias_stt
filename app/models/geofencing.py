# app/models/geofencing.py
from app.models.database import db
from app.models.deployment_location import _utcnow

class Geofencing(db.Model):
    __tablename__ = "geofencing"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    trap_id = db.Column(db.String(50), db.ForeignKey("traps.id"), nullable=False)
    latitude = db.Column(db.Numeric(8, 5))
    longitude = db.Column(db.Numeric(8, 5))
    diameter = db.Column(db.Numeric(5, 2))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
