#!/usr/bin/env python3
"""Bridge M5Stack controls and the Whisplay button to the SkyTrace UI."""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
import struct
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Any


LOGGER = logging.getLogger("skytrace.hardware")
JOYSTICK_ADDRESS = 0x63
JOYSTICK_OFFSET_8_REGISTER = 0x60
JOYSTICK_BUTTON_REGISTER = 0x20
SCROLL_ADDRESS = 0x40
SCROLL_ENCODER_REGISTER = 0x10
WHISPLAY_BUTTON_LINE = 17
WHISPLAY_RED_LINE = 25
WHISPLAY_GREEN_LINE = 24
WHISPLAY_BLUE_LINE = 23
SIGNAL_PULSE_SECONDS = 0.12
SIGNAL_PERIOD_SECONDS = 2.0
SIGNAL_POLL_SECONDS = 0.5
AUDIO_METER_POLL_SECONDS = 0.03
GREEN_PWM_PERIOD_SECONDS = 0.01
AUDIO_METER = struct.Struct("<BfQ")


def normalize_axis(value: int, deadzone: int = 18) -> float:
    """Map a signed joystick byte to -1..1 with a quiet center."""

    value = max(-127, min(127, int(value)))
    magnitude = abs(value)
    if magnitude <= deadzone:
        return 0.0
    normalized = (magnitude - deadzone) / (127 - deadzone)
    curved = normalized * normalized
    return round(curved if value > 0 else -curved, 3)


def signed_counter_delta(current: int, previous: int) -> int:
    """Return the shortest delta between wrapping signed 16-bit counters."""

    return ((current - previous + 32768) % 65536) - 32768


def gpio_is_active(value: Any) -> bool:
    """Support both gpiod v1 integer values and v2 Value enums."""

    name = getattr(value, "name", "")
    return name == "ACTIVE" or value is True or value == 1


def post_event(endpoint: str, event: dict[str, object]) -> dict[str, object]:
    payload = json.dumps(event, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=0.8) as response:
        payload = response.read()
    return json.loads(payload) if payload else {}


def get_status(endpoint: str) -> dict[str, object]:
    request = urllib.request.Request(endpoint, method="GET")
    with urllib.request.urlopen(request, timeout=0.8) as response:
        return json.load(response)


def post_audio_question(endpoint: str, audio_path: str) -> dict[str, object]:
    audio_base64 = base64.b64encode(Path(audio_path).read_bytes()).decode("ascii")
    payload = json.dumps({"audio_base64": audio_base64}).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=150) as response:
        return json.load(response)


def read_signal_active(path: str, active_window: float = 90.0) -> bool:
    try:
        with open(path, encoding="utf-8") as source:
            payload = json.load(source)
    except (OSError, json.JSONDecodeError):
        return False
    return any(float(item.get("seen", active_window + 1)) <= active_window for item in payload.get("aircraft", []))


def read_audio_meter(path: str, stale_seconds: float = 0.5) -> tuple[bool, float]:
    try:
        with open(path, "rb") as source:
            payload = source.read(AUDIO_METER.size)
        active, level, updated_at_ns = AUDIO_METER.unpack(payload)
    except (OSError, struct.error):
        return False, 0.0
    if time.time_ns() - updated_at_ns > int(stale_seconds * 1_000_000_000):
        return False, 0.0
    return bool(active), max(0.0, min(1.0, float(level)))


def open_button() -> tuple[Any, Any]:
    import gpiod

    if hasattr(gpiod, "LineSettings"):
        from gpiod.line import Direction

        chip = gpiod.Chip("/dev/gpiochip0")
        request = chip.request_lines(
            consumer="skytrace-hardware",
            config={WHISPLAY_BUTTON_LINE: gpiod.LineSettings(direction=Direction.INPUT)},
        )
        return request, chip

    chip = gpiod.Chip("gpiochip0")
    line = chip.get_line(WHISPLAY_BUTTON_LINE)
    line.request(consumer="skytrace-hardware", type=gpiod.LINE_REQ_DIR_IN)
    return line, chip


def read_button(button: Any) -> bool:
    if hasattr(button, "get_value"):
        try:
            return gpio_is_active(button.get_value(WHISPLAY_BUTTON_LINE))
        except TypeError:
            return gpio_is_active(button.get_value())
    return False


def rgb_output_values(color: str) -> dict[int, int]:
    """Return active-low GPIO values for an RGB color."""

    enabled_lines = {
        "red": {WHISPLAY_RED_LINE},
        "green": {WHISPLAY_GREEN_LINE},
        "blue": {WHISPLAY_BLUE_LINE},
        "orange": {WHISPLAY_RED_LINE, WHISPLAY_GREEN_LINE},
    }.get(color, set())
    return {
        line: 0 if line in enabled_lines else 1
        for line in (WHISPLAY_RED_LINE, WHISPLAY_GREEN_LINE, WHISPLAY_BLUE_LINE)
    }


def open_rgb_led() -> tuple[Any, Any]:
    """Take over all active-low Whisplay RGB channels, initially off."""

    import gpiod

    if hasattr(gpiod, "LineSettings"):
        from gpiod.line import Direction, Value

        chip = gpiod.Chip("/dev/gpiochip0")
        request = chip.request_lines(
            consumer="skytrace-status-led",
            config={
                line: gpiod.LineSettings(
                    direction=Direction.OUTPUT,
                    output_value=Value.ACTIVE,
                )
                for line in (
                    WHISPLAY_RED_LINE,
                    WHISPLAY_GREEN_LINE,
                    WHISPLAY_BLUE_LINE,
                )
            },
        )
        return request, chip

    chip = gpiod.Chip("gpiochip0")
    lines = {}
    for offset in (WHISPLAY_RED_LINE, WHISPLAY_GREEN_LINE, WHISPLAY_BLUE_LINE):
        line = chip.get_line(offset)
        line.request(
            consumer="skytrace-status-led",
            type=gpiod.LINE_REQ_DIR_OUT,
            default_vals=[1],
        )
        lines[offset] = line
    return lines, chip


def set_rgb_led(led: Any, color: str) -> None:
    values = rgb_output_values(color)
    if isinstance(led, dict):
        for line, value in values.items():
            led[line].set_value(value)
        return

    try:
        from gpiod.line import Value

        values = {
            line: Value.INACTIVE if value == 0 else Value.ACTIVE
            for line, value in values.items()
        }
    except (ImportError, AttributeError):
        pass
    led.set_values(values)


class StatusLed:
    def __init__(
        self,
        signal_path: str,
        audio_meter_path: str,
        listening: threading.Event | None = None,
    ) -> None:
        self.signal_path = signal_path
        self.audio_meter_path = audio_meter_path
        self.listening = listening or threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name="skytrace-status-led",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        led = chip = None
        previous_state: str | None = None
        try:
            led, chip = open_rgb_led()
            LOGGER.info(
                "Whisplay status LED ready (red=%s green=%s blue=%s)",
                WHISPLAY_RED_LINE,
                WHISPLAY_GREEN_LINE,
                WHISPLAY_BLUE_LINE,
            )
            signal_active = radio_playing = False
            audio_level = 0.0
            next_signal_poll = next_audio_poll = next_pulse = 0.0
            pulse_until = 0.0
            previous_color: str | None = None
            while not self._stop.is_set():
                now = time.monotonic()
                if now >= next_signal_poll:
                    signal_active = read_signal_active(self.signal_path)
                    next_signal_poll = now + SIGNAL_POLL_SECONDS
                if now >= next_audio_poll:
                    radio_playing, audio_level = read_audio_meter(self.audio_meter_path)
                    next_audio_poll = now + AUDIO_METER_POLL_SECONDS

                state = "listening" if self.listening.is_set() else (
                    "speaking" if radio_playing else ("signal" if signal_active else "no-signal")
                )
                if state != previous_state:
                    LOGGER.info("Whisplay status LED state=%s", state)
                    previous_state = state
                    next_pulse = now

                if self.listening.is_set():
                    color = "orange"
                elif radio_playing:
                    duty_cycle = max(0.03, audio_level)
                    color = "green" if now % GREEN_PWM_PERIOD_SECONDS < duty_cycle * GREEN_PWM_PERIOD_SECONDS else "off"
                else:
                    if now >= next_pulse:
                        pulse_until = now + SIGNAL_PULSE_SECONDS
                        next_pulse = now + SIGNAL_PERIOD_SECONDS
                    color = ("blue" if signal_active else "red") if now < pulse_until else "off"
                if color != previous_color:
                    set_rgb_led(led, color)
                    previous_color = color
                self._stop.wait(0.001)
        except Exception:
            LOGGER.exception("Whisplay status LED unavailable")
        finally:
            if led is not None:
                set_rgb_led(led, "off")
                if isinstance(led, dict):
                    for line in led.values():
                        line.release()
                elif hasattr(led, "release"):
                    led.release()
            if chip is not None and hasattr(chip, "close"):
                chip.close()


@dataclass
class Bridge:
    endpoint: str
    signal_path: str
    audio_meter_path: str
    dialogue_endpoint: str
    stop_radio_endpoint: str
    dialogue_status_endpoint: str
    capture_device: str
    hold_seconds: float
    joystick_x_sign: int
    joystick_y_sign: int
    scroll_sign: int
    deadzone: int

    def __post_init__(self) -> None:
        self._recording_process: subprocess.Popen[bytes] | None = None
        self._recording_path: str | None = None
        self._button_pressed_at = 0.0
        self._question_blocked = False
        self._question_block_message = ""
        self._question_block_notified = False
        self._question_consumed = False
        self._question_interrupted = False
        self._question_generation = 0
        self._recording_aircraft_icao = ""
        self._recording_lock = threading.Lock()
        self._listening = threading.Event()

    def emit(self, event: dict[str, object]) -> None:
        try:
            post_event(self.endpoint, event)
        except Exception as exc:
            LOGGER.warning("event delivery failed: %s", exc)

    def begin_question(self) -> None:
        if self._recording_process is not None:
            return
        self._button_pressed_at = time.monotonic()
        self._question_blocked = False
        self._question_block_message = ""
        self._question_block_notified = False
        self._question_consumed = False
        self._question_interrupted = False
        self._question_generation += 1
        generation = self._question_generation
        try:
            status = post_event(self.stop_radio_endpoint, {})
        except Exception as exc:
            LOGGER.warning("pilot radio stop failed: %s", exc)
            status = {
                "ready": False,
                "message": "Aircraft status is unavailable",
                "reason": "unavailable",
            }
        if not status.get("ready"):
            self._question_blocked = True
            self._question_consumed = status.get("reason") == "photo_viewer"
            self._question_block_message = str(
                status.get("message") or "No aircraft are currently available"
            )
            if status.get("reason") == "no_aircraft":
                self.emit(
                    {
                        "action": "dialogue_unavailable",
                        "message": self._question_block_message,
                    }
                )
                self._question_block_notified = True
            return
        self._recording_path = f"/tmp/skytrace-question-{time.time_ns()}.wav"
        self._recording_aircraft_icao = str(status.get("selected") or "")
        self._listening.set()
        self.emit({"action": "dialogue_listening"})
        try:
            self._recording_process = subprocess.Popen(
                [
                    "arecord",
                    "-q",
                    "-D",
                    self.capture_device,
                    "-t",
                    "wav",
                    "-f",
                    "S16_LE",
                    "-r",
                    "16000",
                    "-c",
                    "1",
                    self._recording_path,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            LOGGER.info("pilot question recording started device=%s", self.capture_device)
            threading.Thread(
                target=self.monitor_question_aircraft,
                args=(self._recording_aircraft_icao, generation),
                name="skytrace-question-aircraft-monitor",
                daemon=True,
            ).start()
        except OSError as exc:
            LOGGER.warning("question recording failed to start: %s", exc)
            self._recording_process = None
            self._listening.clear()
            self.emit({"action": "dialogue_error", "message": "Microphone could not start"})

    def monitor_question_aircraft(self, selected_icao: str, generation: int) -> None:
        consecutive_errors = 0
        while self._listening.is_set() and generation == self._question_generation:
            time.sleep(0.35)
            if not self._listening.is_set() or generation != self._question_generation:
                return
            try:
                status = get_status(self.dialogue_status_endpoint)
                consecutive_errors = 0
            except Exception as exc:
                consecutive_errors += 1
                if consecutive_errors < 3:
                    continue
                LOGGER.warning("aircraft dialogue status failed: %s", exc)
                self.interrupt_question(
                    "Aircraft status was lost. Recording stopped.", generation
                )
                return
            if status.get("ready") and status.get("selected") == selected_icao:
                continue
            self.interrupt_question(
                str(
                    status.get("message")
                    or "The selected aircraft disconnected. Recording stopped."
                ),
                generation,
            )
            return

    def interrupt_question(self, message: str, generation: int) -> None:
        with self._recording_lock:
            if generation != self._question_generation or not self._listening.is_set():
                return
            process = self._recording_process
            path = self._recording_path
            self._recording_process = None
            self._recording_path = None
            self._recording_aircraft_icao = ""
            self._question_interrupted = True
            self._listening.clear()
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        if path:
            Path(path).unlink(missing_ok=True)
        LOGGER.warning("pilot question interrupted: %s", message)
        self.emit({"action": "dialogue_interrupted", "message": message})

    def finish_question(self) -> None:
        if self._question_interrupted:
            self._question_interrupted = False
            return
        if self._question_blocked:
            held_seconds = time.monotonic() - self._button_pressed_at
            self._question_blocked = False
            if self._question_consumed:
                self._question_consumed = False
            elif held_seconds < self.hold_seconds:
                self.emit({"action": "select_nearest"})
            elif not self._question_block_notified:
                self.emit(
                    {
                        "action": "dialogue_unavailable",
                        "message": self._question_block_message,
                    }
                )
            self._question_block_message = ""
            self._question_block_notified = False
            return
        held_seconds = time.monotonic() - self._button_pressed_at
        with self._recording_lock:
            process = self._recording_process
            path = self._recording_path
            selected_icao = self._recording_aircraft_icao
            self._recording_process = None
            self._recording_path = None
            self._recording_aircraft_icao = ""
            self._listening.clear()
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        recording_size = Path(path).stat().st_size if path and Path(path).is_file() else 0
        if held_seconds < self.hold_seconds:
            if path:
                Path(path).unlink(missing_ok=True)
            self.emit({"action": "dialogue_idle"})
            self.emit({"action": "select_nearest"})
            return
        try:
            final_status = get_status(self.dialogue_status_endpoint)
        except Exception:
            final_status = {"ready": True, "selected": selected_icao}
        if not final_status.get("ready") or final_status.get("selected") != selected_icao:
            if path:
                Path(path).unlink(missing_ok=True)
            self.emit(
                {
                    "action": "dialogue_interrupted",
                    "message": str(
                        final_status.get("message")
                        or "The selected aircraft disconnected. Recording stopped."
                    ),
                }
            )
            return
        if not path or recording_size <= 44:
            if path:
                Path(path).unlink(missing_ok=True)
            LOGGER.warning("pilot question recording is empty (bytes=%s)", recording_size)
            self.emit({"action": "dialogue_error", "message": "No microphone audio was captured"})
            return
        LOGGER.info("pilot question recorded seconds=%.2f bytes=%s", held_seconds, recording_size)
        self.emit({"action": "dialogue_transcribing"})
        threading.Thread(
            target=self.ask_pilot,
            args=(path,),
            name="skytrace-pilot-question",
            daemon=True,
        ).start()

    def ask_pilot(self, path: str) -> None:
        try:
            result = post_audio_question(self.dialogue_endpoint, path)
            LOGGER.info(
                "pilot dialogue mode=%s question=%r answer=%r",
                result.get("mode"),
                result.get("question"),
                result.get("answer"),
            )
            self.emit(
                {
                    "action": "dialogue_answer",
                    "question": str(result.get("question") or ""),
                    "answer": str(result.get("answer") or ""),
                    "mode": str(result.get("mode") or "fixed"),
                }
            )
        except Exception as exc:
            LOGGER.warning("pilot dialogue failed: %s", exc)
            message = "Select an aircraft first" if "409" in str(exc) else "Pilot dialogue failed"
            self.emit({"action": "dialogue_error", "message": message})
        finally:
            Path(path).unlink(missing_ok=True)

    def run(self) -> None:
        from smbus2 import SMBus

        button, chip = open_button()
        status_led = StatusLed(self.signal_path, self.audio_meter_path, self._listening)
        status_led.start()
        previous_whisplay_button = read_button(button)
        previous_joystick_button: int | None = None
        next_joystick_button_poll = 0.0
        previous_encoder: int | None = None
        LOGGER.info("hardware bridge ready (joystick=0x63 scroll=0x40 gpio=17)")
        try:
            with SMBus(1) as bus:
                while True:
                    loop_started = time.monotonic()
                    try:
                        raw_axes = bus.read_i2c_block_data(
                            JOYSTICK_ADDRESS, JOYSTICK_OFFSET_8_REGISTER, 2
                        )
                        raw_x, raw_y = struct.unpack("bb", bytes(raw_axes))
                        x = normalize_axis(raw_x * self.joystick_x_sign, self.deadzone)
                        y = normalize_axis(raw_y * self.joystick_y_sign, self.deadzone)
                        if x or y:
                            self.emit({"action": "pan", "x": x, "y": y})
                    except OSError as exc:
                        LOGGER.warning("joystick read failed: %s", exc)

                    if loop_started >= next_joystick_button_poll:
                        try:
                            joystick_button = bus.read_byte_data(
                                JOYSTICK_ADDRESS, JOYSTICK_BUTTON_REGISTER
                            )
                            if joystick_button == 0 and previous_joystick_button == 1:
                                self.emit({"action": "toggle_follow"})
                            previous_joystick_button = joystick_button
                        except OSError as exc:
                            LOGGER.warning("joystick button read failed: %s", exc)
                        next_joystick_button_poll = loop_started + 0.12

                    try:
                        raw_encoder = bus.read_i2c_block_data(
                            SCROLL_ADDRESS, SCROLL_ENCODER_REGISTER, 2
                        )
                        encoder = struct.unpack("<h", bytes(raw_encoder))[0]
                        if previous_encoder is not None:
                            delta = signed_counter_delta(encoder, previous_encoder)
                            if delta:
                                self.emit(
                                    {
                                        "action": "zoom",
                                        "delta": max(-8, min(8, delta * self.scroll_sign)),
                                    }
                                )
                        previous_encoder = encoder
                    except OSError as exc:
                        LOGGER.warning("scroll read failed: %s", exc)

                    pressed = read_button(button)
                    if pressed and not previous_whisplay_button:
                        self.begin_question()
                    elif not pressed and previous_whisplay_button:
                        self.finish_question()
                    previous_whisplay_button = pressed

                    remaining = 0.05 - (time.monotonic() - loop_started)
                    if remaining > 0:
                        time.sleep(remaining)
        finally:
            status_led.stop()
            if hasattr(button, "release"):
                button.release()
            if hasattr(chip, "close"):
                chip.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    bridge = Bridge(
        endpoint=os.getenv(
            "SKYTRACE_HARDWARE_ENDPOINT",
            "http://127.0.0.1:8931/api/v1/hardware/event",
        ),
        signal_path=os.getenv(
            "SKYTRACE_SIGNAL_PATH",
            "/home/pi/sky-tracker/run/readsb/aircraft.json",
        ),
        audio_meter_path=os.getenv(
            "SKYTRACE_RADIO_METER_PATH",
            "/tmp/skytrace-radio-meter",
        ),
        dialogue_endpoint=os.getenv(
            "SKYTRACE_DIALOGUE_ENDPOINT",
            "http://127.0.0.1:8931/api/v1/hardware/dialogue",
        ),
        stop_radio_endpoint=os.getenv(
            "SKYTRACE_STOP_RADIO_ENDPOINT",
            "http://127.0.0.1:8931/api/v1/hardware/radio/stop",
        ),
        dialogue_status_endpoint=os.getenv(
            "SKYTRACE_DIALOGUE_STATUS_ENDPOINT",
            "http://127.0.0.1:8931/api/v1/hardware/dialogue/status",
        ),
        capture_device=os.getenv("SKYTRACE_CAPTURE_DEVICE", "plughw:2,0"),
        hold_seconds=float(os.getenv("SKYTRACE_BUTTON_HOLD_SECONDS", "0.7")),
        joystick_x_sign=int(os.getenv("SKYTRACE_JOYSTICK_X_SIGN", "-1")),
        joystick_y_sign=int(os.getenv("SKYTRACE_JOYSTICK_Y_SIGN", "-1")),
        scroll_sign=int(os.getenv("SKYTRACE_SCROLL_SIGN", "1")),
        deadzone=int(os.getenv("SKYTRACE_JOYSTICK_DEADZONE", "18")),
    )
    bridge.run()


if __name__ == "__main__":
    main()
