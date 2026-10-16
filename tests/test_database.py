from __future__ import annotations

import sys
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parents[1] / "server"))

from app.db import Database  # noqa: E402
from app.live_store import LiveStore  # noqa: E402
from app.models import IngestBatch  # noqa: E402


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = Database(
            str(Path(self.tempdir.name) / "adsb.sqlite3"), retention_days=90, active_seconds=90
        )
        self.database.initialize()
        self.now = int(time.time() * 1000)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def batch(self, batch_id: str = "devpn:test-batch-0001") -> IngestBatch:
        return IngestBatch.model_validate(
            {
                "batch_id": batch_id,
                "emitted_at_ms": self.now,
                "receiver": {
                    "id": "devpn",
                    "name": "DEVPN ADS-B",
                    "latitude": 22.60,
                    "longitude": 112.50,
                    "version": "test",
                },
                "aircraft": [
                    {
                        "icao": "7823b7",
                        "observed_at_ms": self.now,
                        "callsign": "csn3756 ",
                        "latitude": 22.598419,
                        "longitude": 112.499051,
                        "altitude_baro": 32100,
                        "ground_speed": 464.5,
                        "track": 255.66,
                        "messages": 53,
                    }
                ],
                "messages": [
                    {
                        "ts_ms": self.now,
                        "raw": "8D7823B79915C18E58045AA33D7E",
                        "icao": "7823b7",
                        "df": 17,
                        "type_code": 19,
                    },
                    {
                        "ts_ms": self.now + 1,
                        "raw": "8D7823B758A5C3169E6B458B94E9",
                        "icao": "7823B7",
                        "df": 17,
                        "type_code": 11,
                    },
                ],
            }
        )

    def test_ingest_queries_and_duplicate_protection(self) -> None:
        result = self.database.ingest(self.batch())
        self.assertEqual(result["messages"], 2)
        duplicate = self.database.ingest(self.batch())
        self.assertTrue(duplicate["duplicate"])

        stats = self.database.stats()
        self.assertEqual(stats["active_aircraft"], 1)
        self.assertEqual(stats["stored_messages"], 2)

        live = self.database.live_aircraft()
        self.assertEqual(live["aircraft"][0]["callsign"], "CSN3756")
        self.assertEqual(live["aircraft"][0]["position_at_ms"], self.now)
        self.assertEqual(live["receivers"][0]["id"], "devpn")

        archive = self.database.list_aircraft("CSN", 1, 50)
        self.assertEqual(archive["total"], 1)

        detail = self.database.aircraft_detail("7823B7", 24)
        self.assertEqual(detail["aircraft"]["stored_messages"], 2)
        self.assertEqual(len(detail["positions"]), 1)

        first_page = self.database.aircraft_messages("7823B7", None, 1)
        self.assertIsNotNone(first_page["next_cursor"])
        second_page = self.database.aircraft_messages(
            "7823B7", first_page["next_cursor"], 1
        )
        self.assertEqual(len(second_page["items"]), 1)

    def test_newer_non_position_signal_does_not_retimestamp_old_coordinates(self) -> None:
        self.database.ingest(self.batch())
        payload = self.batch("devpn:test-batch-0002").model_dump(mode="json")
        payload["aircraft"][0].update(
            {
                "observed_at_ms": self.now + 5_000,
                "position_at_ms": self.now - 1_000,
                "latitude": 23.0,
                "longitude": 113.0,
                "ground_speed": 100.0,
                "track": 10.0,
            }
        )
        payload["messages"] = []

        self.database.ingest(IngestBatch.model_validate(payload))
        live = self.database.live_aircraft()["aircraft"][0]

        self.assertEqual(live["last_seen_ms"], self.now + 5_000)
        self.assertEqual(live["position_at_ms"], self.now)
        self.assertEqual(live["latitude"], 22.598419)
        self.assertEqual(live["longitude"], 112.499051)
        self.assertEqual(live["ground_speed"], 464.5)
        positions = self.database.aircraft_detail("7823B7", 24)["positions"]
        self.assertEqual(len(positions), 2)
        self.assertEqual(positions[-1]["observed_at_ms"], self.now)

    def test_initialize_migrates_existing_aircraft_table(self) -> None:
        old_path = Path(self.tempdir.name) / "old.sqlite3"
        connection = sqlite3.connect(old_path)
        try:
            connection.execute(
                """
                CREATE TABLE aircraft (
                    icao TEXT PRIMARY KEY,
                    first_seen_ms INTEGER NOT NULL,
                    last_seen_ms INTEGER NOT NULL
                )
                """
            )
            connection.commit()
        finally:
            connection.close()
        migrated = Database(str(old_path), retention_days=90, active_seconds=90)

        migrated.initialize()

        with migrated.connection() as connection:
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(aircraft)")
            }
        self.assertIn("position_at_ms", columns)

    def test_cleanup_supports_hour_level_retention(self) -> None:
        database = Database(
            str(Path(self.tempdir.name) / "short-retention.sqlite3"),
            retention_hours=12,
            active_seconds=90,
        )
        database.initialize()
        recent_ms = self.now
        old_ms = self.now - (13 * 3_600_000)

        recent_payload = self.batch("devpn:recent-batch").model_dump(mode="json")
        old_payload = self.batch("devpn:old-batch").model_dump(mode="json")
        recent_payload["aircraft"][0]["icao"] = "7823B7"
        recent_payload["messages"][0]["icao"] = "7823B7"
        recent_payload["messages"][1]["icao"] = "7823B7"
        old_payload["aircraft"][0]["icao"] = "ABC123"
        old_payload["aircraft"][0]["observed_at_ms"] = old_ms
        old_payload["aircraft"][0]["position_at_ms"] = old_ms
        old_payload["messages"][0]["icao"] = "ABC123"
        old_payload["messages"][0]["ts_ms"] = old_ms
        old_payload["messages"][1]["icao"] = "ABC123"
        old_payload["messages"][1]["ts_ms"] = old_ms + 1

        database.ingest(IngestBatch.model_validate(old_payload))
        database.ingest(IngestBatch.model_validate(recent_payload))
        database._last_cleanup_ms = 0
        database.cleanup_if_due(recent_ms)

        with database.connection() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM aircraft WHERE icao = 'ABC123'").fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM aircraft WHERE icao = '7823B7'").fetchone()[0],
                1,
            )
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM positions").fetchone()[0], 1)

    def test_realtime_storage_flags_skip_heavy_tables(self) -> None:
        database = Database(
            str(Path(self.tempdir.name) / "realtime.sqlite3"),
            retention_hours=12,
            active_seconds=90,
            store_raw_messages=False,
            store_positions=False,
            store_ingest_batches=False,
        )
        database.initialize()

        database.ingest(self.batch())

        with database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM aircraft").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM receivers").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM positions").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM ingest_batches").fetchone()[0], 0)

    def test_live_store_snapshot_is_available_without_database_query(self) -> None:
        store = LiveStore(active_seconds=90)

        result = store.ingest(self.batch())
        snapshot = store.snapshot()
        stats = store.stats()
        detail = store.aircraft_detail("7823B7", 24)

        self.assertEqual(result["aircraft"], 1)
        self.assertEqual(snapshot["aircraft"][0]["icao"], "7823B7")
        self.assertEqual(snapshot["aircraft"][0]["callsign"], "CSN3756")
        self.assertEqual(stats["active_aircraft"], 1)
        self.assertEqual(stats["total_aircraft"], 1)
        self.assertEqual(stats["stored_messages"], 0)
        self.assertEqual(detail["positions"], [])


if __name__ == "__main__":
    unittest.main()
