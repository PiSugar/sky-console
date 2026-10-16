from __future__ import annotations

import sys
import tempfile
import unittest
import json
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parents[1] / "client"))

from agent import Agent, Config, Spool, extract_icao, mode_s_syndrome, parse_frame  # noqa: E402


class ClientDecoderTests(unittest.TestCase):
    def test_df17_frame(self) -> None:
        raw = "8D40621D58C382D690C8AC2863A7"
        message = parse_frame(f"*{raw};", timestamp_ms=123)
        self.assertIsNotNone(message)
        self.assertEqual(message["icao"], "40621D")
        self.assertEqual(message["df"], 17)
        self.assertEqual(message["type_code"], 11)
        self.assertEqual(mode_s_syndrome(raw), 0)

    def test_comm_b_address_from_parity(self) -> None:
        raw = "A000149CFFFB6139FFFCE5601E1D"
        self.assertEqual(extract_icao(raw, 20), "7823B7")

    def test_timestamped_avr_frame_uses_full_message(self) -> None:
        line = "@000000ABCDEF8D7823B79915C18E58045AA33D7E;"
        message = parse_frame(line, timestamp_ms=456)
        self.assertEqual(message["raw"], "8D7823B79915C18E58045AA33D7E")
        self.assertEqual(message["icao"], "7823B7")

    def test_invalid_line_is_ignored(self) -> None:
        self.assertIsNone(parse_frame("not-a-frame"))

    def test_spool_commits_enqueued_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            spool = Spool(str(Path(tempdir) / "spool.sqlite3"))
            spool.enqueue("batch-1", b"{}")
            self.assertEqual(spool.count(), 1)
            row = spool.oldest_due()
            self.assertEqual(row["batch_id"], "batch-1")
            spool.delete(row["id"])
            self.assertEqual(spool.count(), 0)

    def test_aircraft_position_uses_seen_pos_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state_path = root / "aircraft.json"
            state_path.write_text(
                json.dumps(
                    {
                        "now": 1_700_000_000.0,
                        "aircraft": [
                            {
                                "hex": "7823b7",
                                "seen": 0.2,
                                "seen_pos": 4.5,
                                "lat": 22.598419,
                                "lon": 112.499051,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            config = Config(
                server_url="https://example.invalid",
                api_key="integration-test-secret-key",
                receiver_id="devpn",
                receiver_name="DEVPN ADS-B",
                receiver_lat=None,
                receiver_lon=None,
                upload_interval=5,
                active_window=120,
                max_batch_messages=2000,
                max_spool_batches=10000,
                send_raw_messages=False,
                status_interval=60,
                state_path=str(state_path),
                raw_host="127.0.0.1",
                raw_port=30002,
                spool_path=str(root / "spool.sqlite3"),
            )

            aircraft = Agent(config).read_aircraft()[0]

            self.assertEqual(aircraft["observed_at_ms"], 1_699_999_999_800)
            self.assertEqual(aircraft["position_at_ms"], 1_699_999_995_500)


if __name__ == "__main__":
    unittest.main()
