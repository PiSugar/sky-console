from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).parents[1] / "server"))

from app.db import Database  # noqa: E402
from app.enrichment import EnrichmentService  # noqa: E402
from app.models import IngestBatch  # noqa: E402


class EnrichmentCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = Database(
            str(Path(self.tempdir.name) / "adsb.sqlite3"),
            retention_days=90,
            active_seconds=90,
        )
        self.database.initialize()
        now = int(time.time() * 1000)
        batch = IngestBatch.model_validate(
            {
                "batch_id": "devpn:enrichment-0001",
                "emitted_at_ms": now,
                "receiver": {"id": "devpn", "name": "DEVPN ADS-B"},
                "aircraft": [
                    {
                        "icao": "40621D",
                        "observed_at_ms": now,
                        "callsign": "BAW123",
                        "latitude": 22.5,
                        "longitude": 113.5,
                    }
                ],
                "messages": [],
            }
        )
        self.database.ingest(batch)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_metadata_and_route_are_joined_into_aircraft_views(self) -> None:
        self.database.save_aircraft_metadata(
            "40621D",
            {
                "registration": "G-STBC",
                "manufacturer": "Boeing",
                "model": "777-300ER",
                "type_code": "B77W",
                "owner": "British Airways",
            },
            "ok",
        )
        self.database.save_flight_route(
            "BAW123",
            {
                "callsign_icao": "BAW123",
                "callsign_iata": "BA123",
                "airline_name": "British Airways",
                "airline_icao": "BAW",
                "airline_iata": "BA",
                "origin_name": "London Heathrow Airport",
                "origin_iata": "LHR",
                "destination_name": "Hong Kong International Airport",
                "destination_iata": "HKG",
            },
            "ok",
        )

        live_aircraft = self.database.live_aircraft()["aircraft"][0]
        self.assertEqual(live_aircraft["registration"], "G-STBC")
        self.assertEqual(live_aircraft["aircraft_type"], "B77W")
        self.assertEqual(live_aircraft["aircraft_manufacturer"], "Boeing")
        self.assertEqual(live_aircraft["airline_name"], "British Airways")
        self.assertEqual(live_aircraft["route_callsign_icao"], "BAW123")
        self.assertEqual(live_aircraft["route_callsign_iata"], "BA123")
        self.assertEqual(live_aircraft["origin_iata"], "LHR")
        self.assertEqual(live_aircraft["destination_iata"], "HKG")

        search = self.database.list_aircraft("British Airways", 1, 50)
        self.assertEqual(search["total"], 1)

    def test_successful_cache_is_not_immediately_due(self) -> None:
        self.database.save_aircraft_metadata("40621D", {}, "ok")
        self.assertFalse(
            self.database.aircraft_metadata_due("40621D", 3_600_000, 60_000)
        )
        self.assertTrue(
            self.database.aircraft_metadata_due("ABCDEF", 3_600_000, 60_000)
        )

    def test_service_normalizes_public_api_responses(self) -> None:
        service = EnrichmentService(
            self.database,
            enabled=True,
            base_url="https://example.invalid/v0",
            success_hours=168,
            retry_hours=6,
            timeout_seconds=2,
        )
        responses = {
            "aircraft/40621D": {
                "aircraft": {
                    "registration": " G-STBC ",
                    "manufacturer": "Boeing",
                    "type": "777-300ER",
                    "icao_type": "B77W",
                    "registered_owner": "British Airways",
                    "url_photo": "http://insecure.example/photo.jpg",
                }
            },
            "callsign/BAW123": {
                "flightroute": {
                    "callsign_icao": "BAW123",
                    "callsign_iata": "BA123",
                    "airline": {"name": "British Airways", "icao": "BAW", "iata": "BA"},
                    "origin": {"name": "London Heathrow", "iata_code": "LHR"},
                    "destination": {"name": "Hong Kong International", "iata_code": "HKG"},
                }
            },
        }
        with patch.object(service, "_get_json", side_effect=lambda endpoint: responses[endpoint]):
            service._lookup_aircraft("40621D")
            service._lookup_route("BAW123")

        aircraft = self.database.aircraft_detail("40621D", 24)["aircraft"]
        self.assertEqual(aircraft["registration"], "G-STBC")
        self.assertEqual(aircraft["aircraft_model"], "777-300ER")
        self.assertEqual(aircraft["airline_name"], "British Airways")
        self.assertEqual(aircraft["route_callsign_iata"], "BA123")
        self.assertEqual(aircraft["origin_iata"], "LHR")
        self.assertEqual(aircraft["destination_iata"], "HKG")
        self.assertIsNone(aircraft["aircraft_photo_url"])


if __name__ == "__main__":
    unittest.main()
