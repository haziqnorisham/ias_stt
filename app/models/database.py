"""Shared SQLAlchemy database instance.

Imported by the models and by the application factory (``db.init_app(app)``).
SQLite is used as a file-based store; no external server is required.
"""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
