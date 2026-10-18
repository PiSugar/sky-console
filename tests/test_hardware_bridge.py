from __future__ import annotations

import importlib.util
import sys
import tempfile
import time
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

    def test_signal_comes_from_active_readsb_aircraft(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8") as state:
            state.write('{"aircraft":[{"hex":"ABC123","seen":1.2}]}')
            state.flush()
            self.assertTrue(hardware_bridge.read_signal_active(state.name))

        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("/home/pi/adsb-tracker/run/readsb/aircraft.json", source)

    def test_audio_meter_reads_fresh_waveform_level(self) -> None:
        with tempfile.NamedTemporaryFile() as meter:
            meter.write(hardware_bridge.AUDIO_METER.pack(True, 0.625, time.time_ns()))
            meter.flush()
            active, level = hardware_bridge.read_audio_meter(meter.name)
        self.assertTrue(active)
        self.assertAlmostEqual(level, 0.625)

    def test_whisplay_rgb_led_is_exclusive_and_active_low(self) -> None:
        self.assertEqual(hardware_bridge.WHISPLAY_RED_LINE, 25)
        self.assertEqual(hardware_bridge.WHISPLAY_GREEN_LINE, 24)
        self.assertEqual(hardware_bridge.WHISPLAY_BLUE_LINE, 23)
        self.assertEqual(hardware_bridge.rgb_output_values("red"), {25: 0, 24: 1, 23: 1})
        self.assertEqual(hardware_bridge.rgb_output_values("green"), {25: 1, 24: 0, 23: 1})
        self.assertEqual(hardware_bridge.rgb_output_values("blue"), {25: 1, 24: 1, 23: 0})
        self.assertEqual(hardware_bridge.rgb_output_values("orange"), {25: 0, 24: 0, 23: 1})
        self.assertEqual(hardware_bridge.rgb_output_values("off"), {25: 1, 24: 1, 23: 1})

    def test_long_press_emits_dialogue_progress(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")

        self.assertIn('self.emit({"action": "dialogue_listening"})', source)
        self.assertIn("post_event(self.stop_radio_endpoint, {})", source)
        self.assertIn('self.emit({"action": "dialogue_idle"})', source)
        self.assertIn('self.emit({"action": "dialogue_transcribing"})', source)
        self.assertIn('"action": "dialogue_answer"', source)
