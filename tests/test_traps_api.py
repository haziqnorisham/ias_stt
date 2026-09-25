import unittest

from sqlalchemy import create_engine, inspect

from app import create_app
from app.config import Config
from app.models.database import db
from app.models.trap import Trap
from app.models.user import User
from app.schema_migrations import upgrade_schema


class TrapsApiTestConfig(Config):
    API_KEY = None
    ENABLE_FRONTEND = False
    LOG_DIR = "/tmp/ias_stt_traps_test_logs"
    LOG_LEVEL = "CRITICAL"
    MQTT_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    TESTING = True
    JWT_SECRET_KEY = "traps-api-test-secret-with-enough-entropy"


class TrapsApiTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TrapsApiTestConfig)
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

        user = User(
            username="admin",
            display_name="Admin",
            email="admin@example.test",
            role="administrator",
            is_active=True,
        )
        user.set_password("admin-password")
        db.session.add(user)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def _headers(self):
        response = self.client.post(
            "/auth/login",
            json={"username": "admin", "password": "admin-password"},
        )
        self.assertEqual(response.status_code, 200)
        token = response.get_json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def _create_trap(self, headers, **fields):
        data = {
            "status": "inactive",
            "trap_id": "TRAP-001",
            **fields,
        }
        return self.client.post("/api/traps", json=data, headers=headers)

    def test_asset_number_supports_nullable_crud_and_serialization(self):
        headers = self._headers()

        created = self._create_trap(headers, asset_number="ASSET-001")
        self.assertEqual(created.status_code, 201)
        created_body = created.get_json()
        self.assertEqual(created_body["asset_number"], "ASSET-001")
        trap_id = created_body["id"]

        listed = self.client.get("/api/traps", headers=headers)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.get_json()[0]["asset_number"], "ASSET-001")

        detail = self.client.get(f"/api/traps/{trap_id}", headers=headers)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.get_json()["asset_number"], "ASSET-001")

        cleared = self.client.put(
            f"/api/traps/{trap_id}",
            json={"asset_number": None},
            headers=headers,
        )
        self.assertEqual(cleared.status_code, 200)
        self.assertIsNone(cleared.get_json()["asset_number"])

        deleted = self.client.delete(
            f"/api/traps/{trap_id}",
            headers=headers,
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertIsNone(db.session.get(Trap, trap_id))

    def test_asset_number_is_optional_and_not_unique(self):
        headers = self._headers()

        first = self._create_trap(headers, asset_number="SHARED-ASSET")
        self.assertEqual(first.status_code, 201)

        second = self._create_trap(
            headers,
            trap_id="TRAP-002",
            asset_number="SHARED-ASSET",
        )
        self.assertEqual(second.status_code, 201)

        third = self._create_trap(headers, trap_id="TRAP-003")
        self.assertEqual(third.status_code, 201)
        self.assertIsNone(third.get_json()["asset_number"])

    def test_asset_number_rejects_non_strings_and_values_over_100_characters(self):
        headers = self._headers()

        max_length = self._create_trap(
            headers,
            trap_id="TRAP-100",
            asset_number="A" * 100,
        )
        self.assertEqual(max_length.status_code, 201)

        too_long = self._create_trap(headers, asset_number="A" * 101)
        self.assertEqual(too_long.status_code, 400)
        self.assertIn("asset_number", too_long.get_json()["error"])

        invalid_type = self._create_trap(headers, asset_number=123)
        self.assertEqual(invalid_type.status_code, 400)
        self.assertIn("asset_number", invalid_type.get_json()["error"])

    def test_upgrade_schema_adds_asset_number_to_existing_traps_table(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE traps "
                "(id INTEGER PRIMARY KEY, trap_id VARCHAR(50) NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO traps (id, trap_id) VALUES (1, 'TRAP-001')"
            )

        upgrade_schema(engine)
        upgrade_schema(engine)

        columns = {
            column["name"]: column
            for column in inspect(engine).get_columns("traps")
        }
        self.assertIn("asset_number", columns)
        self.assertTrue(columns["asset_number"]["nullable"])
        self.assertEqual(str(columns["asset_number"]["type"]), "VARCHAR(100)")
        with engine.connect() as connection:
            self.assertEqual(
                connection.exec_driver_sql(
                    "SELECT trap_id, asset_number FROM traps WHERE id = 1"
                ).one(),
                ("TRAP-001", None),
            )


if __name__ == "__main__":
    unittest.main()
