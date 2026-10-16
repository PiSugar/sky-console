from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parents[1] / "server"))

from app.decoder import decode_mode_s  # noqa: E402


class ModeSDecoderTests(unittest.TestCase):
    def test_identification_message(self) -> None:
        decoded = decode_mode_s("8D4840D6202CC371C32CE0576098")

        self.assertEqual(decoded["df"], 17)
        self.assertEqual(decoded["type_code"], 4)
        self.assertEqual(decoded["summary"], "飞机识别：KLM1023")
        self.assertTrue(decoded["integrity"])
        self.assertTrue(any(field["name"] == "呼号/航班号" for field in decoded["fields"]))

    def test_airborne_position_message(self) -> None:
        decoded = decode_mode_s("8D40621D58C382D690C8AC2863A7")

        self.assertEqual(decoded["type_code"], 11)
        self.assertIn("38,000 ft", decoded["summary"])
        self.assertTrue(any(field["name"] == "CPR 纬度" for field in decoded["fields"]))

    def test_velocity_message(self) -> None:
        decoded = decode_mode_s("8D7823B79915C18E58045AA33D7E")

        self.assertEqual(decoded["type_code"], 19)
        self.assertIn("地速", decoded["summary"])
        self.assertTrue(any(field["name"] == "垂直速度" for field in decoded["fields"]))

    def test_comm_b_message_keeps_ambiguous_payload(self) -> None:
        decoded = decode_mode_s("A000149CFFFB6139FFFCE5601E1D")

        self.assertEqual(decoded["df"], 20)
        self.assertTrue(any(field["name"] == "Comm-B 数据块 MB" for field in decoded["fields"]))
        self.assertTrue(decoded["notes"])


if __name__ == "__main__":
    unittest.main()
