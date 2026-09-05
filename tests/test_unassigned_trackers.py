import unittest

from app import create_app
from app.config import Config
from app.models.database import db
from app.models.smart_trap_tracker import SmartTrapTracker
from app.models.trap import Trap


class TestConfig(Config):
    API_KEY = "test-key"
    ENABLE_FRONTEND = False
    LOG_DIR = "/tmp/ias_stt_test_logs"
    LOG_LEVEL = "CRITICAL"
    MQTT_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    TESTING = True


class UnassignedTrackersApiTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def _get_unassigned(self, **query):
        return self.client.get(
            "/api/stt/unassigned",
            headers={"Authorization": "Bearer test-key"},
            query_string=query,
        )

    def _add_tracker(self, device_eui, display_name):
        tracker = SmartTrapTracker(
            device_eui=device_eui,
            display_name=display_name,
        )
        db.session.add(tracker)
        return tracker

    def _add_trap(self, trap_id, tracker_id, status="inactive"):
        trap = Trap(
            status=status,
            trap_id=trap_id,
            tracker_id=tracker_id,
            updated_by="test",
        )
        db.session.add(trap)
        return trap

    def test_returns_trackers_without_a_matching_trap(self):
        self._add_tracker("EUI-UNASSIGNED", "Unassigned")
        self._add_tracker("EUI-ACTIVE", "Active assignment")
        self._add_tracker("EUI-INACTIVE", "Inactive assignment")
        self._add_trap("TRAP-ACTIVE", "EUI-ACTIVE", status="active")
        self._add_trap("TRAP-INACTIVE", "EUI-INACTIVE", status="inactive")
        self._add_trap("TRAP-NONE", "")
        db.session.commit()

        response = self._get_unassigned()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [tracker["device_eui"] for tracker in response.get_json()],
            ["EUI-UNASSIGNED"],
        )

    def test_supports_id_ordered_pagination(self):
        self._add_tracker("EUI-1", "First")
        self._add_tracker("EUI-2", "Second")
        self._add_tracker("EUI-3", "Third")
        db.session.commit()

        response = self._get_unassigned(limit=1, offset=1)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [tracker["device_eui"] for tracker in response.get_json()],
            ["EUI-2"],
        )

    def test_rejects_invalid_pagination(self):
        for query in ({"limit": "invalid"}, {"offset": -1}):
            with self.subTest(query=query):
                response = self._get_unassigned(**query)
                self.assertEqual(response.status_code, 400)

    def test_requires_api_key(self):
        response = self.client.get("/api/stt/unassigned")

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
