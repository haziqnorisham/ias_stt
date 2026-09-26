import io
import os
import shutil
import tempfile
import time
import unittest

from app import create_app
from app.config import Config
from app.models.database import db
from app.models.deployment import Deployment
from app.models.deployment_action import DeploymentAction
from app.models.deployment_action_type import (
    DeploymentActionType,
    seed_default_action_types,
)
from app.models.trap import Trap
from app.models.user import User


class DeploymentActionsTestConfig(Config):
    API_KEY = None
    ENABLE_FRONTEND = False
    LOG_DIR = "/tmp/ias_stt_deployment_actions_test_logs"
    LOG_LEVEL = "CRITICAL"
    MQTT_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    TESTING = True
    JWT_SECRET_KEY = "deployment-actions-test-secret-with-enough-entropy"


class DeploymentActionsApiTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(DeploymentActionsTestConfig)
        self.upload_dir = tempfile.mkdtemp(prefix="ias-stt-actions-")
        self.app.config["DATA_DIR"] = self.upload_dir
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        seed_default_action_types()
        self.client = self.app.test_client()

        self.admin = self._add_user("admin", "administrator", "admin-password")
        self.operator = self._add_user(
            "operator", "field_operator", "operator-password"
        )
        self.viewer = self._add_user("viewer", "read_only", "viewer-password")
        self.trap = Trap(
            status="active",
            trap_id="TRAP-ACTIONS-001",
            tracker_id="",
            updated_by="system",
        )
        db.session.add(self.trap)
        db.session.flush()
        self.deployment = Deployment(trap_id=self.trap.id, status="active")
        db.session.add(self.deployment)
        db.session.commit()

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
            is_active=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user

    def _login(self, username, password):
        response = self.client.post(
            "/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200)
        return {"Authorization": f"Bearer {response.get_json()['access_token']}"}

    def _create_action_type(self, headers, **values):
        payload = {
            "code": "custom_action",
            "label": "Custom action",
            "description": "A custom action.",
            **values,
        }
        return self.client.post(
            "/api/deployment-action-types",
            json=payload,
            headers=headers,
        )

    def _create_action(self, headers, action_type_id, notes="Action note"):
        return self.client.post(
            f"/api/deployments/{self.deployment.id}/actions",
            data={
                "action_type_id": str(action_type_id),
                "notes": notes,
                "picture": (io.BytesIO(b"action-image"), "action.jpg"),
            },
            headers=headers,
            content_type="multipart/form-data",
        )

    def test_seeded_action_types_are_available_to_authenticated_readers(self):
        headers = self._login("operator", "operator-password")

        response = self.client.get(
            "/api/deployment-action-types",
            headers=headers,
        )

        self.assertEqual(response.status_code, 200)
        codes = {item["code"] for item in response.get_json()}
        self.assertEqual(codes, {"bait_added", "routine_check", "bait_removed"})

    def test_only_administrators_can_crud_action_types(self):
        admin_headers = self._login("admin", "admin-password")
        operator_headers = self._login("operator", "operator-password")

        forbidden_create = self._create_action_type(operator_headers)
        self.assertEqual(forbidden_create.status_code, 403)

        created = self._create_action_type(admin_headers)
        self.assertEqual(created.status_code, 201)
        body = created.get_json()
        self.assertEqual(body["code"], "custom_action")
        self.assertTrue(body["is_active"])
        original_updated_at = body["updated_at"]

        time.sleep(0.001)
        updated = self.client.put(
            f"/api/deployment-action-types/{body['id']}",
            json={"label": "Updated action", "is_active": False},
            headers=admin_headers,
        )
        self.assertEqual(updated.status_code, 200)
        updated_body = updated.get_json()
        self.assertEqual(updated_body["label"], "Updated action")
        self.assertFalse(updated_body["is_active"])
        self.assertNotEqual(updated_body["updated_at"], original_updated_at)

        code_change = self.client.put(
            f"/api/deployment-action-types/{body['id']}",
            json={"code": "changed_code"},
            headers=admin_headers,
        )
        self.assertEqual(code_change.status_code, 400)

        deleted = self.client.delete(
            f"/api/deployment-action-types/{body['id']}",
            headers=admin_headers,
        )
        self.assertEqual(deleted.status_code, 200)

    def test_referenced_action_type_cannot_be_deleted(self):
        admin_headers = self._login("admin", "admin-password")
        operator_headers = self._login("operator", "operator-password")
        created = self._create_action_type(admin_headers)
        self.assertEqual(created.status_code, 201)
        action_type_id = created.get_json()["id"]

        action_response = self._create_action(operator_headers, action_type_id)
        self.assertEqual(action_response.status_code, 201)

        deleted = self.client.delete(
            f"/api/deployment-action-types/{action_type_id}",
            headers=admin_headers,
        )
        self.assertEqual(deleted.status_code, 409)

        deactivated = self.client.put(
            f"/api/deployment-action-types/{action_type_id}",
            json={"is_active": False},
            headers=admin_headers,
        )
        self.assertEqual(deactivated.status_code, 200)

        visible_to_operator = self.client.get(
            "/api/deployment-action-types",
            headers=operator_headers,
        )
        self.assertEqual(visible_to_operator.status_code, 200)
        self.assertNotIn(
            action_type_id,
            {item["id"] for item in visible_to_operator.get_json()},
        )

        visible_to_admin = self.client.get(
            "/api/deployment-action-types?include_inactive=true",
            headers=admin_headers,
        )
        self.assertEqual(visible_to_admin.status_code, 200)
        inactive = next(
            item for item in visible_to_admin.get_json() if item["id"] == action_type_id
        )
        self.assertFalse(inactive["is_active"])

    def test_action_requires_picture_and_active_action_type(self):
        operator_headers = self._login("operator", "operator-password")
        action_type = DeploymentActionType(
            code="inactive_test",
            label="Inactive test",
            is_active=False,
        )
        db.session.add(action_type)
        db.session.commit()

        missing_picture = self.client.post(
            f"/api/deployments/{self.deployment.id}/actions",
            data={"action_type_id": str(action_type.id)},
            headers=operator_headers,
        )
        self.assertEqual(missing_picture.status_code, 409)

        active_type = DeploymentActionType(
            code="picture_required",
            label="Picture required",
            is_active=True,
        )
        db.session.add(active_type)
        db.session.commit()
        missing_picture = self.client.post(
            f"/api/deployments/{self.deployment.id}/actions",
            data={"action_type_id": str(active_type.id)},
            headers=operator_headers,
        )
        self.assertEqual(missing_picture.status_code, 400)
        self.assertIn("picture", missing_picture.get_json()["error"])

    def test_actions_are_immutable_and_picture_is_authenticated(self):
        operator_headers = self._login("operator", "operator-password")
        action_type = DeploymentActionType(
            code="immutable_test",
            label="Immutable test",
            is_active=True,
        )
        db.session.add(action_type)
        db.session.commit()

        created = self._create_action(operator_headers, action_type.id)
        self.assertEqual(created.status_code, 201)
        body = created.get_json()
        self.assertEqual(body["notes"], "Action note")
        self.assertEqual(body["performed_by"], "operator")
        self.assertIsNotNone(body["performed_at"])
        self.assertTrue(body["picture_url"].startswith("/api/deployment-actions/"))

        listed = self.client.get(
            f"/api/deployments/{self.deployment.id}/actions",
            headers=operator_headers,
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.get_json()), 1)

        unauthorized = self.client.get(body["picture_url"])
        self.assertEqual(unauthorized.status_code, 401)
        picture = self.client.get(body["picture_url"], headers=operator_headers)
        self.assertEqual(picture.status_code, 200)
        self.assertEqual(picture.data, b"action-image")
        picture.close()

        update = self.client.put(
            f"/api/deployments/{self.deployment.id}/actions/{body['id']}",
            json={"notes": "Changed"},
            headers=operator_headers,
        )
        self.assertEqual(update.status_code, 404)
        delete = self.client.delete(
            f"/api/deployments/{self.deployment.id}/actions/{body['id']}",
            headers=operator_headers,
        )
        self.assertEqual(delete.status_code, 404)

    def test_closed_deployments_reject_actions_and_delete_cascades(self):
        operator_headers = self._login("operator", "operator-password")
        action_type = DeploymentActionType(
            code="lifecycle_test",
            label="Lifecycle test",
            is_active=True,
        )
        db.session.add(action_type)
        db.session.commit()

        created = self._create_action(operator_headers, action_type.id)
        self.assertEqual(created.status_code, 201)
        action_id = created.get_json()["id"]
        stored_filename = db.session.get(DeploymentAction, action_id).stored_filename
        stored_path = os.path.join(self.upload_dir, "uploads", stored_filename)
        self.assertTrue(os.path.isfile(stored_path))

        self.deployment.status = "closed"
        db.session.commit()
        rejected = self.client.post(
            f"/api/deployments/{self.deployment.id}/actions",
            data={
                "action_type_id": str(action_type.id),
                "picture": (io.BytesIO(b"later-image"), "later.jpg"),
            },
            headers=operator_headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(rejected.status_code, 409)

        admin_headers = self._login("admin", "admin-password")
        deleted = self.client.delete(
            f"/api/deployments/{self.deployment.id}",
            headers=admin_headers,
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertIsNone(db.session.get(DeploymentAction, action_id))
        self.assertFalse(os.path.exists(stored_path))


if __name__ == "__main__":
    unittest.main()
