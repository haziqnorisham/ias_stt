import unittest

from app import create_app
from app.config import Config
from app.models.database import db
from app.models.user import User


class UsersApiTestConfig(Config):
    API_KEY = None
    ENABLE_FRONTEND = False
    LOG_DIR = "/tmp/ias_stt_users_test_logs"
    LOG_LEVEL = "CRITICAL"
    MQTT_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    TESTING = True
    JWT_SECRET_KEY = "users-api-test-secret-with-enough-entropy"


class UsersApiTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(UsersApiTestConfig)
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

        self.admin = self._add_user("admin", "administrator", "admin-password")
        self.operator = self._add_user(
            "operator", "field_operator", "operator-password"
        )
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def _add_user(self, username, role, password):
        user = User(username=username, role=role, display_name=username.title())
        user.set_password(password)
        db.session.add(user)
        return user

    def _token(self, username="admin", password="admin-password"):
        response = self.client.post(
            "/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200)
        return response.get_json()["access_token"]

    @staticmethod
    def _headers(token):
        return {"Authorization": f"Bearer {token}"}

    def test_admin_can_list_create_get_update_and_delete_users(self):
        headers = self._headers(self._token())

        listed = self.client.get("/api/users", headers=headers)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.get_json()), 2)
        self.assertNotIn("password_hash", listed.get_json()[0])

        created = self.client.post(
            "/api/users",
            json={
                "auth_provider": "LOCAL",
                "username": "viewer",
                "password": "viewer-password",
                "role": "read_only",
                "display_name": "Read Only User",
                "email": "viewer@example.test",
            },
            headers=headers,
        )
        self.assertEqual(created.status_code, 201)
        created_body = created.get_json()
        self.assertEqual(created_body["role"], "read_only")
        self.assertNotIn("password_hash", created_body)
        user_id = created_body["id"]

        fetched = self.client.get(f"/api/users/{user_id}", headers=headers)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.get_json()["username"], "viewer")

        updated = self.client.put(
            f"/api/users/{user_id}",
            json={"role": "field_operator", "password": "updated-password"},
            headers=headers,
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["role"], "field_operator")

        login = self.client.post(
            "/auth/login",
            json={"username": "viewer", "password": "updated-password"},
        )
        self.assertEqual(login.status_code, 200)

        deleted = self.client.delete(f"/api/users/{user_id}", headers=headers)
        self.assertEqual(deleted.status_code, 200)
        self.assertIsNone(db.session.get(User, user_id))

    def test_non_administrator_cannot_manage_users(self):
        headers = self._headers(self._token("operator", "operator-password"))

        listed = self.client.get("/api/users", headers=headers)
        self.assertEqual(listed.status_code, 403)
        self.assertEqual(listed.get_json()["error"]["code"], "FORBIDDEN")

        created = self.client.post(
            "/api/users",
            json={
                "auth_provider": "LOCAL",
                "username": "blocked",
                "password": "blocked-password",
                "role": "read_only",
            },
            headers=headers,
        )
        self.assertEqual(created.status_code, 403)

    def test_create_requires_role_and_enforces_duplicate_and_password_rules(self):
        headers = self._headers(self._token())

        missing_role = self.client.post(
            "/api/users",
            json={
                "auth_provider": "LOCAL",
                "username": "missing-role",
                "password": "password",
            },
            headers=headers,
        )
        self.assertEqual(missing_role.status_code, 422)

        short_password = self.client.post(
            "/api/users",
            json={
                "auth_provider": "LOCAL",
                "username": "short-password",
                "password": "short",
                "role": "read_only",
            },
            headers=headers,
        )
        self.assertEqual(short_password.status_code, 422)

        duplicate = self.client.post(
            "/api/users",
            json={
                "auth_provider": "LOCAL",
                "username": "operator",
                "password": "operator-password",
                "role": "field_operator",
            },
            headers=headers,
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.get_json()["error"]["code"], "CONFLICT")

    def test_admin_lockout_protection(self):
        headers = self._headers(self._token())

        delete_self = self.client.delete(
            f"/api/users/{self.admin.id}", headers=headers
        )
        self.assertEqual(delete_self.status_code, 409)

        demote_self = self.client.put(
            f"/api/users/{self.admin.id}",
            json={"role": "read_only"},
            headers=headers,
        )
        self.assertEqual(demote_self.status_code, 409)

        deactivate_self = self.client.put(
            f"/api/users/{self.admin.id}",
            json={"is_active": False},
            headers=headers,
        )
        self.assertEqual(deactivate_self.status_code, 409)

    def test_user_management_requires_user_jwt_not_legacy_service_key(self):
        self.app.config["API_KEY"] = "legacy-service-key"

        response = self.client.get(
            "/api/users",
            headers={"Authorization": "Bearer legacy-service-key"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"]["code"], "INVALID_TOKEN")


if __name__ == "__main__":
    unittest.main()
