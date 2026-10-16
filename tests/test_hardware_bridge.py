from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "client" / "hardware_bridge.py"
SPEC = importlib.util.spec_from_file_location("hardware_bridge", MODULE_PATH)
assert SPEC and SPEC.loader
hardware_bridge = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = hardware_bridge
SPEC.loader.exec_module(hardware_bridge)


class HardwareBridgeTests(unittest.TestCase):
    def test_default_joystick_mapping_is_rotated_180_degrees(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")

        self.assertIn('SKYTRACE_JOYSTICK_X_SIGN", "-1"', source)
        self.assertIn('SKYTRACE_JOYSTICK_Y_SIGN", "-1"', source)

    def test_axis_deadzone_and_range(self) -> None:
        self.assertEqual(hardware_bridge.normalize_axis(0), 0.0)
        self.assertEqual(hardware_bridge.normalize_axis(18), 0.0)
        self.assertEqual(hardware_bridge.normalize_axis(127), 1.0)
        self.assertEqual(hardware_bridge.normalize_axis(-127), -1.0)
        self.assertGreater(hardware_bridge.normalize_axis(80), 0.0)

    def test_counter_delta_wraps(self) -> None:
        self.assertEqual(hardware_bridge.signed_counter_delta(101, 100), 1)
        self.assertEqual(hardware_bridge.signed_counter_delta(-32768, 32767), 1)
        self.assertEqual(hardware_bridge.signed_counter_delta(32767, -32768), -1)
