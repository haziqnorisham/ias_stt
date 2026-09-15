import unittest
from datetime import datetime, timedelta, timezone

from app import create_app
from app.config import Config
from app.models.database import db
from app.models.notification import Notification, NotificationUserState
from app.models.user import User


class NotificationsApiTestConfig(Config):
    API_KEY = None
    ENABLE_FRONTEND = False
    LOG_DIR = "/tmp/ias_stt_notifications_test_logs"
    LOG_LEVEL = "CRITICAL"
    MQTT_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    TESTING = True
    JWT_SECRET_KEY = "notifications-api-test-secret-with-enough-entropy"


class NotificationsApiTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(NotificationsApiTestConfig)
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

        self.admin = self._add_user(
            "admin",
            "administrator",
            "admin-password",
        )
        self.alice = self._add_user("alice", "field_operator", "alice-password")
        self.bob = self._add_user("bob", "read_only", "bob-password")

        self.first_notification = Notification(
            event_type="trap_closed",
            severity="warning",
            title="Trap closed",
            message="Trap TRAP-001 has closed.",
            entity_type="trap",
            entity_id="1",
            source_type="tracker_uplink",
            source_id="100",
            payload={"new_tilt_status": "normal"},
        )
        self.second_notification = Notification(
            event_type="system_maintenance",
            severity="info",
            title="Scheduled maintenance",
            message="Maintenance is scheduled.",
        )
        expired = Notification(
            event_type="expired_event",
            severity="info",
            title="Expired event",
            message="This event should not be visible.",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        db.session.add_all(
            [self.first_notification, self.second_notification, expired]
        )
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    @staticmethod
    def _add_user(username, role, password):
        user = User(
            username=username,
            display_name=username.title(),
            role=role,
            is_active=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        return user

    def _login(self, username, password):
        response = self.client.post(
            "/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200)
        return response.get_json()["access_token"]

    @staticmethod
    def _headers(token):
        return {"Authorization": f"Bearer {token}"}

    def test_list_summary_and_dismissal_are_per_user(self):
        alice_headers = self._headers(self._login("alice", "alice-password"))

        listed = self.client.get("/api/notifications", headers=alice_headers)
        self.assertEqual(listed.status_code, 200)
        listed_body = listed.get_json()
        self.assertEqual(len(listed_body["items"]), 2)
        self.assertEqual(listed_body["unread_count"], 2)
        self.assertEqual(listed_body["total_count"], 2)
        self.assertIsNone(listed_body["items"][0]["dismissed_at"])

        notification_id = self.first_notification.id
        dismissed = self.client.post(
            f"/api/notifications/{notification_id}/dismiss",
            headers=alice_headers,
        )
        self.assertEqual(dismissed.status_code, 200)
        self.assertIsNotNone(dismissed.get_json()["dismissed_at"])

        active = self.client.get("/api/notifications", headers=alice_headers)
        self.assertEqual(active.status_code, 200)
        self.assertEqual(active.get_json()["total_count"], 1)
        self.assertEqual(active.get_json()["unread_count"], 1)

        dismissed_list = self.client.get(
            "/api/notifications?status=dismissed",
            headers=alice_headers,
        )
        self.assertEqual(dismissed_list.status_code, 200)
        self.assertEqual(dismissed_list.get_json()["total_count"], 1)

        bob_headers = self._headers(self._login("bob", "bob-password"))
        bob_active = self.client.get("/api/notifications", headers=bob_headers)
        self.assertEqual(bob_active.status_code, 200)
        self.assertEqual(bob_active.get_json()["total_count"], 2)
        self.assertEqual(bob_active.get_json()["unread_count"], 2)

        states = NotificationUserState.query.all()
        self.assertEqual(len(states), 1)
        self.assertEqual(states[0].user_id, self.alice.id)

    def test_read_and_dismiss_are_idempotent(self):
        headers = self._headers(self._login("alice", "alice-password"))
        notification_id = self.second_notification.id

        for _ in range(2):
            response = self.client.post(
                f"/api/notifications/{notification_id}/read",
                headers=headers,
            )
            self.assertEqual(response.status_code, 200)
            self.assertIsNotNone(response.get_json()["read_at"])
            self.assertIsNone(response.get_json()["dismissed_at"])

        for _ in range(2):
            response = self.client.post(
                f"/api/notifications/{notification_id}/dismiss",
                headers=headers,
            )
            self.assertEqual(response.status_code, 200)
            self.assertIsNotNone(response.get_json()["read_at"])
            self.assertIsNotNone(response.get_json()["dismissed_at"])

        self.assertEqual(
            NotificationUserState.query.filter_by(
                notification_id=notification_id,
                user_id=self.alice.id,
            ).count(),
            1,
        )

    def test_summary_and_detail_include_current_user_state(self):
        headers = self._headers(self._login("alice", "alice-password"))
        notification_id = self.first_notification.id

        summary = self.client.get(
            "/api/notifications/summary",
            headers=headers,
        )
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.get_json(), {"active_count": 2, "unread_count": 2})

        read = self.client.post(
            f"/api/notifications/{notification_id}/read",
            headers=headers,
        )
        self.assertEqual(read.status_code, 200)

        detail = self.client.get(
            f"/api/notifications/{notification_id}",
            headers=headers,
        )
        self.assertEqual(detail.status_code, 200)
        self.assertIsNotNone(detail.get_json()["read_at"])
        self.assertIsNone(detail.get_json()["dismissed_at"])

    def test_expired_and_unknown_notifications_are_not_available(self):
        headers = self._headers(self._login("alice", "alice-password"))

        expired = self.client.get("/api/notifications?status=all", headers=headers)
        self.assertEqual(expired.status_code, 200)
        self.assertEqual(expired.get_json()["total_count"], 2)

        unknown = self.client.get("/api/notifications/9999", headers=headers)
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(unknown.get_json()["error"]["code"], "NOT_FOUND")

    def test_notification_state_requires_user_jwt(self):
        response = self.client.get("/api/notifications")
        self.assertEqual(response.status_code, 401)

        self.app.config["API_KEY"] = "legacy-service-key"
        response = self.client.get(
            "/api/notifications",
            headers={"Authorization": "Bearer legacy-service-key"},
        )
        self.assertEqual(response.status_code, 401)

    def test_administrator_can_create_custom_test_notification(self):
        admin_headers = self._headers(self._login("admin", "admin-password"))
        response = self.client.post(
            "/api/notifications/test",
            json={
                "title": "Frontend test",
                "message": "The notification panel is working.",
                "severity": "critical",
            },
            headers=admin_headers,
        )

        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        self.assertEqual(body["event_type"], "test_notification")
        self.assertEqual(body["title"], "Frontend test")
        self.assertEqual(body["message"], "The notification panel is working.")
        self.assertEqual(body["severity"], "critical")
        self.assertEqual(body["source_type"], "admin_test")
        self.assertEqual(body["source_id"], str(self.admin.id))
        self.assertEqual(body["payload"]["test"], True)
        self.assertEqual(body["payload"]["created_by"], "admin")

        alice_headers = self._headers(self._login("alice", "alice-password"))
        listed = self.client.get("/api/notifications", headers=alice_headers)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.get_json()["total_count"], 3)

    def test_test_notification_requires_administrator_and_valid_data(self):
        alice_headers = self._headers(self._login("alice", "alice-password"))
        forbidden = self.client.post(
            "/api/notifications/test",
            headers=alice_headers,
        )
        self.assertEqual(forbidden.status_code, 403)

        admin_headers = self._headers(self._login("admin", "admin-password"))
        invalid = self.client.post(
            "/api/notifications/test",
            json={"severity": "emergency"},
            headers=admin_headers,
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(
            invalid.get_json()["error"]["code"],
            "VALIDATION_ERROR",
        )


if __name__ == "__main__":
    unittest.main()
