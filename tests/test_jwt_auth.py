import io
import shutil
import tempfile
import unittest

from app import create_app
from app.config import Config
from app.models.database import db
from app.models.deployment import Deployment
from app.models.deployment_action_type import DeploymentActionType
from app.models.smart_trap_tracker import SmartTrapTracker
from app.models.trap import Trap
from app.models.user import User


class JwtTestConfig(Config):
    API_KEY = None
    ENABLE_FRONTEND = False
    LOG_DIR = "/tmp/ias_stt_jwt_test_logs"
    LOG_LEVEL = "CRITICAL"
    MQTT_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    TESTING = True
    JWT_SECRET_KEY = "test-jwt-secret-with-enough-entropy"


class JwtAuthApiTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(JwtTestConfig)
        self.upload_dir = tempfile.mkdtemp(prefix="ias-stt-jwt-")
        self.app.config["DATA_DIR"] = self.upload_dir
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

        self.admin = self._add_user(
            "admin", "administrator", "admin-password"
        )
        self.operator = self._add_user(
            "operator", "field_operator", "operator-password"
        )
        self.viewer = self._add_user(
            "viewer", "read_only", "viewer-password"
        )
        trap = Trap(
            status="active",
            trap_id="TRAP-001",
            tracker_id="",
            updated_by="system",
        )
        db.session.add(trap)
        db.session.add(
            SmartTrapTracker(device_eui="EUI-001", display_name="Tracker")
        )
        db.session.commit()
        self.trap_id = trap.id

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()
        shutil.rmtree(self.upload_dir, ignore_errors=True)

    def _add_user(self, username, role, password):
        user = User(
            username=username,
            display_name=username.title(),
            email=f"{username}@example.test",
            role=role,
        )
        user.set_password(password)
        db.session.add(user)
        return user

    def _login(self, username, password):
        response = self.client.post(
            "/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    @staticmethod
    def _auth(token):
        return {"Authorization": f"Bearer {token}"}

    def test_login_and_me_return_user_permissions(self):
        body = self._login("operator", "operator-password")

        self.assertEqual(body["user"]["role"], "field_operator")
        self.assertIn("traps:update", body["user"]["permissions"])
        self.assertNotIn("settings:admin", body["user"]["permissions"])
        self.assertEqual(body["expires_in"], 15 * 60)
        self.assertEqual(body["refresh_expires_in"], 7 * 24 * 60 * 60)

        response = self.client.get(
            "/auth/me", headers=self._auth(body["access_token"])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["user"]["username"], "operator")

    def test_create_user_cli_prompts_for_omitted_password(self):
        runner = self.app.test_cli_runner()
        result = runner.invoke(
            args=["create-user", "cli-user", "--role", "administrator"],
            input="cli-password\ncli-password\n",
        )

        self.assertEqual(result.exit_code, 0, result.output)
        user = User.query.filter_by(username="cli-user").first()
        self.assertIsNotNone(user)
        self.assertTrue(user.check_password("cli-password"))

    def test_invalid_credentials_are_generic(self):
        response = self.client.post(
            "/auth/login",
            json={"username": "missing", "password": "wrong"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"]["code"], "INVALID_CREDENTIALS")

    def test_read_only_user_cannot_update_trap(self):
        body = self._login("viewer", "viewer-password")

        response = self.client.put(
            f"/api/traps/{self.trap_id}",
            json={"location": "restricted", "updated_by": "admin"},
            headers=self._auth(body["access_token"]),
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"]["code"], "FORBIDDEN")

    def test_operator_update_ignores_client_updated_by(self):
        body = self._login("operator", "operator-password")

        response = self.client.put(
            f"/api/traps/{self.trap_id}",
            json={"location": "field", "updated_by": "administrator"},
            headers=self._auth(body["access_token"]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["updated_by"], "operator")

    def test_refresh_uses_current_local_role(self):
        body = self._login("operator", "operator-password")
        self.operator.role = "read_only"
        db.session.commit()

        response = self.client.post(
            "/auth/refresh", headers=self._auth(body["refresh_token"])
        )

        self.assertEqual(response.status_code, 200)
        me = self.client.get(
            "/auth/me", headers=self._auth(response.get_json()["access_token"])
        )
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.get_json()["user"]["role"], "read_only")

    def test_protected_endpoint_requires_jwt_or_service_key(self):
        response = self.client.get("/api/traps")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.get_json()["error"]["code"],
            "AUTHENTICATION_REQUIRED",
        )

    def test_wildcard_cors_supports_bearer_requests(self):
        response = self.client.options(
            "/api/traps",
            headers={
                "Origin": "https://future-vue.example",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "*")

    def test_action_picture_requires_read_permission_to_retrieve(self):
        deployment = Deployment(trap_id=self.trap_id, status="active")
        action_type = DeploymentActionType(
            code="test_action",
            label="Test action",
            is_active=True,
        )
        db.session.add(deployment)
        db.session.add(action_type)
        db.session.commit()
        body = self._login("operator", "operator-password")
        headers = self._auth(body["access_token"])

        response = self.client.post(
            f"/api/deployments/{deployment.id}/actions",
            data={
                "action_type_id": str(action_type.id),
                "picture": (io.BytesIO(b"test-image"), "capture.jpg"),
            },
            headers=headers,
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 201)
        picture_url = response.get_json()["picture_url"]
        self.assertTrue(picture_url.startswith("/api/deployment-actions/"))

        unauthorized = self.client.get(picture_url)
        self.assertEqual(unauthorized.status_code, 401)

        authorized = self.client.get(picture_url, headers=headers)
        self.assertEqual(authorized.status_code, 200)
        self.assertEqual(authorized.data, b"test-image")
        authorized.close()


if __name__ == "__main__":
    unittest.main()
