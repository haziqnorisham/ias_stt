"""Application configuration loaded from environment variables."""
import os
import uuid
from datetime import timedelta
try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:
    from backports.zoneinfo import ZoneInfo, ZoneInfoNotFoundError


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


def _parse_csv(raw: str, default: str = "") -> list:
    value = raw if raw is not None else default
    return [item.strip() for item in value.split(",") if item.strip()]


def _env_timezone(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return default
    return value


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
    APP_TIMEZONE = _env_timezone("APP_TIMEZONE", "Asia/Kuala_Lumpur")

    # Frontend
    ENABLE_FRONTEND = _env_bool("ENABLE_FRONTEND", True)

    # Security
    API_KEY = _env_optional("API_KEY")
    JWT_SECRET_KEY = _env_optional("JWT_SECRET_KEY")
    JWT_TOKEN_LOCATION = ("headers",)
    JWT_HEADER_NAME = "Authorization"
    JWT_HEADER_TYPE = "Bearer"
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        minutes=int(os.getenv("JWT_ACCESS_TOKEN_MINUTES", "15"))
    )
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(
        days=int(os.getenv("JWT_REFRESH_TOKEN_DAYS", "7"))
    )
    TRUSTED_PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "0"))
    API_KEY_PERMISSIONS = _parse_csv(
        os.getenv("API_KEY_PERMISSIONS"),
        default="*",
    )

    # LDAP is opt-in so development and break-glass LOCAL authentication remain
    # available even when no directory is configured.
    LDAP_ENABLED = _env_bool("LDAP_ENABLED", False)
    LDAP_DIRECTORY_KEY = os.getenv("LDAP_DIRECTORY_KEY", "primary").strip()
    LDAP_DIRECTORY_TYPE = os.getenv("LDAP_DIRECTORY_TYPE", "lldap").strip().lower()
    LDAP_SERVER_URI = _env_optional("LDAP_SERVER_URI")
    LDAP_STARTTLS = _env_bool("LDAP_STARTTLS", False)
    LDAP_CA_CERT_FILE = _env_optional("LDAP_CA_CERT_FILE")
    LDAP_BIND_DN = _env_optional("LDAP_BIND_DN")
    LDAP_BIND_PASSWORD = _env_optional("LDAP_BIND_PASSWORD")
    LDAP_SEARCH_BASE = _env_optional("LDAP_SEARCH_BASE")
    LDAP_USER_FILTER = os.getenv("LDAP_USER_FILTER", "(objectClass=person)").strip()
    LDAP_USERNAME_ATTRIBUTE = os.getenv("LDAP_USERNAME_ATTRIBUTE", "uid").strip()
    LDAP_LOGIN_ATTRIBUTES = _parse_csv(
        os.getenv("LDAP_LOGIN_ATTRIBUTES"),
        default=LDAP_USERNAME_ATTRIBUTE,
    )
    LDAP_SUBJECT_ATTRIBUTE = _env_optional("LDAP_SUBJECT_ATTRIBUTE")
    LDAP_DISPLAY_NAME_ATTRIBUTE = os.getenv(
        "LDAP_DISPLAY_NAME_ATTRIBUTE", "displayName"
    ).strip()
    LDAP_EMAIL_ATTRIBUTE = os.getenv("LDAP_EMAIL_ATTRIBUTE", "mail").strip()
    LDAP_ENABLED_ATTRIBUTE = _env_optional("LDAP_ENABLED_ATTRIBUTE")
    LDAP_ENABLED_VALUES = {
        value.casefold()
        for value in _parse_csv(os.getenv("LDAP_ENABLED_VALUES"), default="true,1,yes")
    }
    # ldap3's Linux socket implementation packs these values as integers.
    # Keep them integer-valued to avoid struct.error during connection.open().
    LDAP_CONNECT_TIMEOUT = int(os.getenv("LDAP_CONNECT_TIMEOUT", "5"))
    LDAP_RECEIVE_TIMEOUT = int(os.getenv("LDAP_RECEIVE_TIMEOUT", "5"))
    LDAP_SEARCH_LIMIT = int(os.getenv("LDAP_SEARCH_LIMIT", "200"))

    # Database (SQLite, file-based)
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{os.path.join(DATA_DIR, 'traps.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # MQTT (disabled by default; telemetry is ingested via HTTP instead)
    MQTT_ENABLED = _env_bool("MQTT_ENABLED", False)
    MQTT_BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "localhost")
    MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))
    MQTT_TOPICS = _parse_topics(os.getenv("MQTT_TOPICS", ""))
    MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID") or f"flask_service_{uuid.uuid4().hex[:8]}"
    MQTT_USERNAME = _env_optional("MQTT_USERNAME")
    MQTT_PASSWORD = _env_optional("MQTT_PASSWORD")
    MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "60"))
