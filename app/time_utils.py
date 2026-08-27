"""Application timezone helpers.

Database timestamps remain UTC. These helpers provide the configured local
timezone for API serialization, logs, and frontend display.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:
    from backports.zoneinfo import ZoneInfo, ZoneInfoNotFoundError


from flask import current_app, has_app_context


DEFAULT_TIMEZONE = "Asia/Kuala_Lumpur"
DEFAULT_UTC_PLUS_8 = timezone(timedelta(hours=8))


def _configured_timezone_name(config=None):
    if config is None and has_app_context():
        config = current_app.config
    if config is not None:
        return config.get("APP_TIMEZONE") or DEFAULT_TIMEZONE
    return os.getenv("APP_TIMEZONE", DEFAULT_TIMEZONE)


def get_app_timezone(config=None):
    """Return the configured IANA timezone, with a UTC+8 fallback."""
    name = _configured_timezone_name(config)
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return DEFAULT_UTC_PLUS_8


def _as_utc(value):
    """Treat SQLite's naive datetime values as UTC before converting them."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def format_app_datetime(value, config=None):
    """Serialize a stored UTC datetime in the configured application zone."""
    if value is None:
        return None
    return _as_utc(value).astimezone(get_app_timezone(config)).isoformat()


class AppTimezoneFormatter(logging.Formatter):
    """Logging formatter that renders ``asctime`` in the app timezone."""

    def __init__(self, *args, timezone_name=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.timezone_name = timezone_name

    def formatTime(self, record, datefmt=None):
        config = {"APP_TIMEZONE": self.timezone_name} if self.timezone_name else None
        value = datetime.fromtimestamp(record.created, tz=timezone.utc).astimezone(
            get_app_timezone(config)
        )
        if datefmt:
            return value.strftime(datefmt)
        return value.isoformat(timespec="milliseconds")
