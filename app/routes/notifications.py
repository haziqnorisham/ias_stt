"""Per-user notification API endpoints (/api/notifications)."""
from datetime import datetime, timezone

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError

from app.auth import auth_error, current_actor, require_user_permission
from app.models.database import db
from app.models.notification import Notification, NotificationUserState
from app.models.user import User


notifications_bp = Blueprint(
    "notifications",
    __name__,
    url_prefix="/api/notifications",
)

DEFAULT_LIMIT = 25
MAX_LIMIT = 100
VALID_STATUSES = {"active", "unread", "read", "dismissed", "all"}
TEST_NOTIFICATION_FIELDS = {"title", "message", "severity"}
TEST_NOTIFICATION_SEVERITIES = {"info", "warning", "critical"}


def _utcnow():
    return datetime.now(timezone.utc)


def _validation_error(message):
    return auth_error("VALIDATION_ERROR", message, 422)


def _not_found():
    return auth_error("NOT_FOUND", "Notification not found.", 404)


def _current_user():
    """Resolve the already-validated JWT principal to its local user row."""
    principal = getattr(g, "auth_principal", None) or {}
    user_id = principal.get("user_id")
    if not user_id:
        return None
    user = db.session.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user


def _current_user_or_error():
    user = _current_user()
    if user is None:
        return None, auth_error(
            "AUTHENTICATION_REQUIRED",
            "Authentication is required.",
            401,
        )
    return user, None


def _parse_pagination():
    try:
        limit = int(request.args.get("limit", DEFAULT_LIMIT))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        return None, None, _validation_error(
            "'limit' and 'offset' must be integers"
        )

    if limit < 0 or limit > MAX_LIMIT or offset < 0:
        return None, None, _validation_error(
            f"'limit' must be between 0 and {MAX_LIMIT}; 'offset' must be non-negative"
        )
    return limit, offset, None


def _notification_query(user_id):
    """Return notifications joined to state for exactly one user.

    A left join makes a missing state row equivalent to an unread,
    non-dismissed notification without causing one query per notification.
    """
    return db.session.query(Notification, NotificationUserState).outerjoin(
        NotificationUserState,
        and_(
            NotificationUserState.notification_id == Notification.id,
            NotificationUserState.user_id == user_id,
        ),
    )


def _not_expired(query, now=None):
    now = now or _utcnow()
    return query.filter(
        or_(
            Notification.expires_at.is_(None),
            Notification.expires_at > now,
        )
    )


def _apply_status(query, status):
    if status == "active":
        return query.filter(NotificationUserState.dismissed_at.is_(None))
    if status == "unread":
        return query.filter(
            NotificationUserState.dismissed_at.is_(None),
            or_(
                NotificationUserState.id.is_(None),
                NotificationUserState.read_at.is_(None),
            ),
        )
    if status == "read":
        return query.filter(
            NotificationUserState.dismissed_at.is_(None),
            NotificationUserState.read_at.is_not(None),
        )
    if status == "dismissed":
        return query.filter(NotificationUserState.dismissed_at.is_not(None))
    return query


def _counts_for_user(user_id, now=None):
    now = now or _utcnow()
    active = _not_expired(_notification_query(user_id), now).filter(
        NotificationUserState.dismissed_at.is_(None)
    )
    unread = active.filter(
        or_(
            NotificationUserState.id.is_(None),
            NotificationUserState.read_at.is_(None),
        )
    )
    return active.count(), unread.count()


def _find_notification(notification_id, now=None):
    now = now or _utcnow()
    return (
        Notification.query.filter(Notification.id == notification_id)
        .filter(
            or_(
                Notification.expires_at.is_(None),
                Notification.expires_at > now,
            )
        )
        .first()
    )


def _find_user_state(notification_id, user_id):
    return NotificationUserState.query.filter_by(
        notification_id=notification_id,
        user_id=user_id,
    ).first()


def _test_notification_data(data):
    """Validate optional overrides for the administrator test endpoint."""
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return None, _validation_error("Request body must be a JSON object")

    unknown = set(data) - TEST_NOTIFICATION_FIELDS
    if unknown:
        return None, _validation_error(
            f"Unknown field(s): {', '.join(sorted(unknown))}"
        )

    title = data.get("title", "Test notification")
    message = data.get("message", "This is a test notification.")
    severity = data.get("severity", "info")

    if not isinstance(title, str) or not title.strip():
        return None, _validation_error(
            "Field 'title' must be a non-empty string"
        )
    if len(title) > 255:
        return None, _validation_error(
            "Field 'title' exceeds max length of 255"
        )
    if not isinstance(message, str) or not message.strip():
        return None, _validation_error(
            "Field 'message' must be a non-empty string"
        )
    if len(message) > 2000:
        return None, _validation_error(
            "Field 'message' exceeds max length of 2000"
        )
    if not isinstance(severity, str) or severity.lower() not in TEST_NOTIFICATION_SEVERITIES:
        return None, _validation_error(
            "Field 'severity' must be one of: critical, info, warning"
        )

    return {
        "title": title.strip(),
        "message": message.strip(),
        "severity": severity.lower(),
    }, None


def _apply_state_action(notification_id, user_id, action):
    """Create or update one user's state and commit it atomically."""
    now = _utcnow()
    state = _find_user_state(notification_id, user_id)
    if state is None:
        state = NotificationUserState(
            notification_id=notification_id,
            user_id=user_id,
        )
        db.session.add(state)

    if state.read_at is None:
        state.read_at = now
    if action == "dismiss" and state.dismissed_at is None:
        state.dismissed_at = now

    try:
        db.session.commit()
    except IntegrityError:
        # Two browser requests can race to create the same state row. Retry
        # against the row created by the winning transaction.
        db.session.rollback()
        state = _find_user_state(notification_id, user_id)
        if state is None:
            raise
        if state.read_at is None:
            state.read_at = now
        if action == "dismiss" and state.dismissed_at is None:
            state.dismissed_at = now
        db.session.commit()

    return state


@notifications_bp.route("", methods=["GET"])
@require_user_permission("notifications:read")
def list_notifications():
    user, error = _current_user_or_error()
    if error is not None:
        return error

    limit, offset, error = _parse_pagination()
    if error is not None:
        return error

    status = request.args.get("status", "active").strip().lower()
    if status not in VALID_STATUSES:
        return _validation_error(
            f"'status' must be one of: {', '.join(sorted(VALID_STATUSES))}"
        )

    query = _not_expired(_notification_query(user.id))
    query = _apply_status(query, status)

    event_type = request.args.get("event_type", "").strip()
    if event_type:
        query = query.filter(Notification.event_type == event_type)

    severity = request.args.get("severity", "").strip().lower()
    if severity:
        query = query.filter(Notification.severity == severity)

    entity_type = request.args.get("entity_type", "").strip()
    if entity_type:
        query = query.filter(Notification.entity_type == entity_type)

    total_count = query.order_by(None).count()
    rows = (
        query.order_by(
            Notification.created_at.desc(),
            Notification.id.desc(),
        )
        .limit(limit)
        .offset(offset)
        .all()
    )
    _, unread_count = _counts_for_user(user.id)

    return jsonify(
        {
            "items": [
                notification.to_dict(user_state=state)
                for notification, state in rows
            ],
            "unread_count": unread_count,
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
        }
    ), 200


@notifications_bp.route("/test", methods=["POST"])
@require_user_permission("settings:admin")
def create_test_notification():
    """Create an in-app test event for administrator verification."""
    user, error = _current_user_or_error()
    if error is not None:
        return error

    data, error = _test_notification_data(request.get_json(silent=True))
    if error is not None:
        return error

    notification = Notification(
        event_type="test_notification",
        severity=data["severity"],
        title=data["title"],
        message=data["message"],
        source_type="admin_test",
        source_id=str(user.id),
        payload={
            "test": True,
            "created_by": current_actor(),
        },
    )

    try:
        db.session.add(notification)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Failed to create test notification for user %s",
            user.id,
        )
        return auth_error(
            "INTERNAL_ERROR",
            "Unable to create test notification.",
            500,
        )

    return jsonify(notification.to_dict()), 201


@notifications_bp.route("/summary", methods=["GET"])
@require_user_permission("notifications:read")
def notification_summary():
    user, error = _current_user_or_error()
    if error is not None:
        return error

    active_count, unread_count = _counts_for_user(user.id)
    return jsonify(
        {
            "active_count": active_count,
            "unread_count": unread_count,
        }
    ), 200


@notifications_bp.route("/<int:notification_id>", methods=["GET"])
@require_user_permission("notifications:read")
def get_notification(notification_id):
    user, error = _current_user_or_error()
    if error is not None:
        return error

    query = _not_expired(_notification_query(user.id))
    row = query.filter(Notification.id == notification_id).first()
    if row is None:
        return _not_found()

    notification, state = row
    return jsonify(notification.to_dict(user_state=state)), 200


def _update_notification_state(notification_id, action):
    user, error = _current_user_or_error()
    if error is not None:
        return error

    notification = _find_notification(notification_id)
    if notification is None:
        return _not_found()

    try:
        state = _apply_state_action(notification.id, user.id, action)
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Failed to update notification %s state for user %s",
            notification_id,
            user.id,
        )
        return auth_error(
            "INTERNAL_ERROR",
            "Unable to update notification state.",
            500,
        )

    return jsonify(notification.to_dict(user_state=state)), 200


@notifications_bp.route("/<int:notification_id>/read", methods=["POST"])
@require_user_permission("notifications:state:update")
def mark_notification_read(notification_id):
    return _update_notification_state(notification_id, "read")


@notifications_bp.route("/<int:notification_id>/dismiss", methods=["POST"])
@require_user_permission("notifications:state:update")
def dismiss_notification(notification_id):
    return _update_notification_state(notification_id, "dismiss")
