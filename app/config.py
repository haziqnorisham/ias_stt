"""Application configuration loaded from environment variables."""
import os
import uuid

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_optional(name: str):
    """Return the env value, or None when unset/empty/placeholder."""
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    if value == "" or value.lower() == "optional":
        return None
    return value


def _parse_topics(raw: str) -> list:
    if not raw:
        return []
    topics = []
    for t in raw.split(","):
        t = t.strip()
        # A trailing '/' adds an empty topic level and silently breaks matching.
        if len(t) > 1:
            t = t.rstrip("/")
        if t:
            topics.append(t)
    return topics


class Config:
    """Base configuration loaded from environment variables."""

    # Paths
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    DATA_DIR = os.path.join(BASE_DIR, "data")

    # Flask
    FLASK_ENV = os.getenv("FLASK_ENV", "development")
    FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
    DEBUG = FLASK_ENV == "development"

    # Logging
    LOG_DIR = os.getenv("LOG_DIR", "logs")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")

    # Frontend
    ENABLE_FRONTEND = _env_bool("ENABLE_FRONTEND", True)

    # Security
    API_KEY = _env_optional("API_KEY")

    # Database (SQLite, file-based)
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{os.path.join(DATA_DIR, 'traps.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # MQTT
    MQTT_ENABLED = _env_bool("MQTT_ENABLED", True)
    MQTT_BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "localhost")
    MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))
    MQTT_TOPICS = _parse_topics(os.getenv("MQTT_TOPICS", ""))
    MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID") or f"flask_service_{uuid.uuid4().hex[:8]}"
    MQTT_USERNAME = _env_optional("MQTT_USERNAME")
    MQTT_PASSWORD = _env_optional("MQTT_PASSWORD")
    MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "60"))
