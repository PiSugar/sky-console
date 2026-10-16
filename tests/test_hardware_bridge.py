from __future__ import annotations

import importlib.util
import io
import sys
import unittest
from unittest.mock import patch
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

    def test_joystick_button_toggles_aircraft_follow(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")

        self.assertIn("JOYSTICK_BUTTON_REGISTER = 0x20", source)
        self.assertIn('self.emit({"action": "toggle_follow"})', source)

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

    def test_active_aircraft_count_uses_live_snapshot(self) -> None:
        response = io.BytesIO(b'{"aircraft":[{"icao":"ABC123"},{"icao":"DEF456"}]}')
        response.__enter__ = lambda value: value
        response.__exit__ = lambda *_args: None

        with patch.object(hardware_bridge.urllib.request, "urlopen", return_value=response):
            self.assertEqual(
                hardware_bridge.fetch_active_aircraft_count("http://example.test/live"),
                2,
            )

    def test_whisplay_blue_led_is_active_low_gpio23(self) -> None:
        class Led:
            def __init__(self) -> None:
                self.values: list[int] = []

            def set_value(self, value: int) -> None:
                self.values.append(value)

        led = Led()
        with patch.dict(sys.modules, {"gpiod.line": None}):
            hardware_bridge.set_blue_led(led, True)
            hardware_bridge.set_blue_led(led, False)

        self.assertEqual(hardware_bridge.WHISPLAY_BLUE_LINE, 23)
        self.assertEqual(led.values, [0, 1])
