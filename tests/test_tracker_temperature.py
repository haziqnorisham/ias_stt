import json
import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, inspect, text

from app import create_app
from app.config import Config
from app.models.database import db
from app.models.smart_trap_tracker import SmartTrapTracker
from app.models.tracker_uplink import TrackerUplink
from app.schema_migrations import upgrade_schema
from app.services.data_processor import process_message
from app.services.tracker_temperature import backfill_tracker_temperatures


class TestConfig(Config):
    API_KEY = "test-key"
    ENABLE_FRONTEND = False
    LOG_DIR = "/tmp/ias_stt_temperature_test_logs"
    LOG_LEVEL = "CRITICAL"
    MQTT_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    TESTING = True


class TrackerTemperatureTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        db.session.add(SmartTrapTracker(device_eui="EUI-001", display_name="North"))
        db.session.add(SmartTrapTracker(device_eui="EUI-002", display_name="South"))
        db.session.commit()
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer test-key"}

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def _payload(self, value=None, *, include_temperature=True):
        obj = {"temperature": value} if include_temperature else {"battery": 80}
        return {"deviceInfo": {"devEui": "EUI-001"}, "object": obj}

    def _tracker(self):
        db.session.expire_all()
        return SmartTrapTracker.query.filter_by(device_eui="EUI-001").one()

    def test_http_ingest_exposes_latest_reading_and_preserves_it(self):
        for value in (0, -4.25):
            response = self.client.post(
                "/api/telemetry/ingest",
                data=json.dumps(self._payload(value)),
                headers=self.headers,
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self._tracker().temperature, value)

        reading_time = self._tracker().temperature_received_at
        for payload in (
            self._payload(include_temperature=False),
            self._payload("NaN"),
            self._payload(True),
            self._payload("not a number"),
        ):
            response = self.client.post(
                "/api/telemetry/ingest",
                data=json.dumps(payload),
                headers=self.headers,
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)

        self.assertEqual(self._tracker().temperature, -4.25)
        self.assertEqual(self._tracker().temperature_received_at, reading_time)
        self.assertEqual(TrackerUplink.query.count(), 6)

        listing = self.client.get("/api/stt", headers=self.headers)
        detail = self.client.get(
            f"/api/stt/{self._tracker().id}", headers=self.headers
        )
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(listing.get_json()[0]["temperature"], -4.25)
        self.assertIsNotNone(listing.get_json()[0]["temperature_received_at"])
        self.assertEqual(detail.get_json()["temperature"], -4.25)
        self.assertIsNone(listing.get_json()[1]["temperature"])
        self.assertEqual(self.client.get("/api/stt").status_code, 401)

    def test_mqtt_ingest_and_older_reading_do_not_replace_newer(self):
        process_message("application/demo/device/EUI-001/event/up",
                        json.dumps(self._payload(25.5)), source="mqtt")
        tracker = self._tracker()
        current_time = tracker.temperature_received_at
        self.assertEqual(tracker.temperature, 25.5)
        self.assertEqual(TrackerUplink.query.one().source, "mqtt")

        changed = SmartTrapTracker.update_temperature_by_device_eui(
            "EUI-001", 12, current_time - timedelta(hours=1),
            touch_updated_date=False,
        )
        self.assertEqual(changed, 0)
        self.assertEqual(self._tracker().temperature, 25.5)

    def test_backfill_finds_latest_valid_historical_reading(self):
        tracker = self._tracker()
        original_updated = datetime(2026, 1, 1, tzinfo=timezone.utc)
        tracker.updated_date = original_updated
        base = datetime(2026, 1, 2, tzinfo=timezone.utc)
        records = [
            (0, self._payload(18.5)),
            (1, self._payload(19.25)),
            (2, self._payload(include_temperature=False)),
            (3, "invalid json"),
            (4, self._payload("Infinity")),
        ]
        for hours, payload in records:
            db.session.add(TrackerUplink(
                device_eui="EUI-001",
                received_at=base + timedelta(hours=hours),
                source="http",
                raw_payload=payload if isinstance(payload, str)
                else json.dumps(payload),
            ))
        db.session.commit()

        self.assertEqual(backfill_tracker_temperatures(batch_size=2), 1)
        tracker = self._tracker()
        self.assertEqual(tracker.temperature, 19.25)
        self.assertEqual(
            tracker.temperature_received_at.replace(tzinfo=timezone.utc),
            base + timedelta(hours=1),
        )
        self.assertEqual(
            tracker.updated_date.replace(tzinfo=timezone.utc), original_updated
        )
        self.assertIsNone(SmartTrapTracker.query.filter_by(device_eui="EUI-002").one().temperature)
        self.assertEqual(backfill_tracker_temperatures(batch_size=2), 0)

    def test_backfill_cli_is_available(self):
        result = self.app.test_cli_runner().invoke(
            args=["backfill-tracker-temperatures"]
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Restored temperatures for 0 trackers.", result.output)

    def test_uplink_history_exposes_temperature_without_raw_list_payloads(self):
        base = datetime(2026, 1, 2, tzinfo=timezone.utc)
        readings = [
            ("EUI-001", "http", self._payload(-3.5)),
            ("EUI-001", "mqtt", self._payload(0)),
            ("EUI-002", "http", {
                "deviceInfo": {"devEui": "EUI-002"},
                "object": {"temperature": 99},
            }),
            ("EUI-001", "http", self._payload("NaN")),
            ("EUI-001", "mqtt", "invalid json"),
        ]
        for index, (device_eui, source, payload) in enumerate(readings):
            db.session.add(TrackerUplink(
                device_eui=device_eui,
                received_at=base + timedelta(minutes=index),
                source=source,
                raw_payload=payload if isinstance(payload, str)
                else json.dumps(payload),
            ))
        db.session.commit()

        response = self.client.get(
            "/api/uplinks",
            query_string={"device_eui": "EUI-001", "limit": 10},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        rows = response.get_json()
        self.assertEqual([row["temperature"] for row in rows], [None, None, 0, -3.5])
        self.assertEqual([row["source"] for row in rows],
                         ["mqtt", "http", "mqtt", "http"])
        self.assertTrue(all("raw_payload" not in row for row in rows))

        page = self.client.get(
            "/api/uplinks",
            query_string={"device_eui": "EUI-001", "limit": 2, "offset": 2},
            headers=self.headers,
        )
        self.assertEqual([row["temperature"] for row in page.get_json()], [0, -3.5])

        mqtt_only = self.client.get(
            "/api/uplinks",
            query_string={"device_eui": "EUI-001", "source": "mqtt"},
            headers=self.headers,
        )
        self.assertEqual(len(mqtt_only.get_json()), 2)
        detail = self.client.get(
            f"/api/uplinks/{rows[2]['id']}", headers=self.headers
        )
        self.assertEqual(detail.get_json()["temperature"], 0)
        self.assertIn("raw_payload", detail.get_json())
        self.assertEqual(self.client.get("/api/uplinks").status_code, 401)


class TrackerTemperatureSchemaTest(unittest.TestCase):
    def test_idempotent_upgrade_preserves_legacy_tracker(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE smart_trap_tracker ("
                "id INTEGER PRIMARY KEY, device_eui VARCHAR(100), "
                "updated_date DATETIME)"
            ))
            conn.execute(text(
                "INSERT INTO smart_trap_tracker (id, device_eui) "
                "VALUES (1, 'EUI-001')"
            ))

        upgrade_schema(engine)
        upgrade_schema(engine)

        columns = {
            column["name"] for column in inspect(engine).get_columns("smart_trap_tracker")
        }
        self.assertIn("temperature", columns)
        self.assertIn("temperature_received_at", columns)
        with engine.connect() as conn:
            self.assertEqual(
                conn.execute(text("SELECT device_eui FROM smart_trap_tracker")).scalar(),
                "EUI-001",
            )


if __name__ == "__main__":
    unittest.main()
