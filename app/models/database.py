"""Shared SQLAlchemy database instance.

Imported by the models and by the application factory (``db.init_app(app)``).
SQLite is used as a file-based store; no external server is required.
"""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

_raw_engine = None


def set_engine(engine):
    """Capture the raw SQLAlchemy Engine (call once during app startup)."""
    global _raw_engine
    _raw_engine = engine


def get_engine():
    """Return the stored engine, or fall back to db.engine when context exists."""
    if _raw_engine is not None:
        return _raw_engine
    return db.engine
