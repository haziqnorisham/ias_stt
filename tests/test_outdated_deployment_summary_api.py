import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import event

from app import create_app
from app.config import Config
from app.models.database import db
from app.models.deployment import Deployment
from app.models.deployment_action import DeploymentAction
from app.models.deployment_action_type import DeploymentActionType, seed_default_action_types
from app.models.trap import Trap
from app.models.user import User
from app.services.deployment_service import get_outdated_deployment_summary


class OutdatedDeploymentSummaryConfig(Config):
    API_KEY = "summary-read-limited-key"
    API_KEY_PERMISSIONS = ["traps:read"]
    ENABLE_FRONTEND = False
    LOG_DIR = "/tmp/ias_stt_outdated_summary_test_logs"
    LOG_LEVEL = "CRITICAL"
    MQTT_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    TESTING = True
    JWT_SECRET_KEY = "outdated-summary-test-secret-with-enough-entropy"


class OutdatedDeploymentSummaryApiTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(OutdatedDeploymentSummaryConfig)
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        seed_default_action_types()
        self.client = self.app.test_client()
        self.action_type = DeploymentActionType.query.filter_by(code="bait_added").one()
        self.trap = Trap(
            status="active",
            trap_id="TRAP-SUMMARY-001",
            tracker_id="",
            updated_by="system",
        )
        db.session.add(self.trap)
        db.session.flush()
        self.user = User(
            username="admin",
            display_name="Admin",
            email="admin@example.test",
            role="administrator",
            is_active=True,
        )
        self.user.set_password("admin-password")
        db.session.add(self.user)
        db.session.commit()
        self.headers = self._login_headers()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def _login_headers(self):
        response = self.client.post(
            "/auth/login",
            json={"username": "admin", "password": "admin-password"},
        )
        self.assertEqual(response.status_code, 200)
        return {"Authorization": f"Bearer {response.get_json()['access_token']}"}

    def _deployment(self, **fields):
        status = fields.pop("status", "active")
        deployment = Deployment(
            trap_id=self.trap.id,
            status=status,
            **fields,
        )
        db.session.add(deployment)
        db.session.flush()
        return deployment

    def _action(self, deployment, performed_at):
        db.session.add(DeploymentAction(
            deployment_id=deployment.id,
            action_type_id=self.action_type.id,
            picture_url="summary-test.jpg",
            picture_filename="summary-test.jpg",
            performed_at=performed_at,
            performed_by="tester",
        ))

    def test_route_requires_authentication_and_deployments_read(self):
        unauthorized = self.client.get("/api/deployments/outdated-summary")
        self.assertEqual(unauthorized.status_code, 401)

        forbidden = self.client.get(
            "/api/deployments/outdated-summary",
            headers={"Authorization": f"Bearer {OutdatedDeploymentSummaryConfig.API_KEY}"},
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_latest_action_controls_strict_twelve_hour_threshold(self):
        now = datetime(2026, 9, 28, 7, 0, tzinfo=timezone.utc)
        old = self._deployment(start_date=now, updated_at=now)
        recently_acted = self._deployment(start_date=now - timedelta(days=2))
        exact = self._deployment(start_date=now, updated_at=now)
        future = self._deployment(start_date=now - timedelta(days=2))
        no_actions_old_start = self._deployment(start_date=now - timedelta(hours=13))
        no_actions_old_creation = self._deployment(
            created_at=now - timedelta(hours=13),
        )
        no_timestamp = self._deployment()
        no_actions_old_creation.start_date = None
        no_timestamp.start_date = None
        no_timestamp.created_at = None
        closed = self._deployment(status="closed", start_date=now - timedelta(days=2))

        self._action(old, now - timedelta(hours=13))
        self._action(recently_acted, now - timedelta(hours=13))
        self._action(recently_acted, now - timedelta(hours=11))
        self._action(exact, now - timedelta(hours=12))
        self._action(future, now + timedelta(minutes=1))
        self._action(closed, now - timedelta(days=2))
        db.session.commit()

        summary = get_outdated_deployment_summary(now=now)

        self.assertEqual(summary["active_deployment_count"], 7)
        self.assertEqual(summary["outdated_deployment_count"], 3)
        self.assertEqual(summary["threshold_hours"], 12)
        self.assertEqual(summary["as_of"], "2026-09-28T15:00:00+08:00")

    def test_empty_result_and_more_than_one_hundred_active_are_counted_in_one_query(self):
        empty = self.client.get(
            "/api/deployments/outdated-summary",
            headers=self.headers,
        )
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.get_json()["active_deployment_count"], 0)
        self.assertEqual(empty.get_json()["outdated_deployment_count"], 0)

        now = datetime.now(timezone.utc)
        db.session.add_all([
            Deployment(
                trap_id=self.trap.id,
                status="active",
                start_date=now,
            )
            for _ in range(105)
        ])
        db.session.commit()

        statements = []
        engine = db.engine

        def record_statement(_conn, _cursor, statement, _parameters, _context, _many):
            if "select" in statement.lower() and "from deployments" in statement.lower():
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", record_statement)
        try:
            response = self.client.get(
                "/api/deployments/outdated-summary",
                headers=self.headers,
            )
        finally:
            event.remove(engine, "before_cursor_execute", record_statement)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["active_deployment_count"], 105)
        self.assertEqual(response.get_json()["outdated_deployment_count"], 0)
        self.assertEqual(len(statements), 1)


if __name__ == "__main__":
    unittest.main()
