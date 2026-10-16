#!/usr/bin/env python3
"""Bridge M5Stack controls and the Whisplay button to the SkyTrace UI."""

from __future__ import annotations

import json
import logging
import os
import struct
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
STATUS_POLL_SECONDS = 0.15


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


def post_event(endpoint: str, event: dict[str, object]) -> None:
    payload = json.dumps(event, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=0.8) as response:
        response.read()


def fetch_hardware_status(endpoint: str) -> tuple[bool, bool]:
    with urllib.request.urlopen(endpoint, timeout=0.8) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        return False, False
    return bool(payload.get("signal_active")), bool(payload.get("radio_playing"))


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
    """Return active-low GPIO values for one exclusive RGB color."""

    enabled_line = {
        "red": WHISPLAY_RED_LINE,
        "green": WHISPLAY_GREEN_LINE,
        "blue": WHISPLAY_BLUE_LINE,
    }.get(color)
    return {
        line: 0 if line == enabled_line else 1
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
    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
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
            next_status_poll = next_pulse = 0.0
            pulse_until = 0.0
            previous_color: str | None = None
            last_status_warning = 0.0
            while not self._stop.is_set():
                now = time.monotonic()
                if now >= next_status_poll:
                    try:
                        signal_active, radio_playing = fetch_hardware_status(self.endpoint)
                    except Exception as exc:
                        signal_active = radio_playing = False
                        if now - last_status_warning >= 10.0:
                            LOGGER.warning("hardware status read failed: %s", exc)
                            last_status_warning = now
                    next_status_poll = now + STATUS_POLL_SECONDS

                state = "speaking" if radio_playing else ("signal" if signal_active else "no-signal")
                if state != previous_state:
                    LOGGER.info("Whisplay status LED state=%s", state)
                    previous_state = state
                    next_pulse = now

                if radio_playing:
                    color = "green"
                else:
                    if now >= next_pulse:
                        pulse_until = now + SIGNAL_PULSE_SECONDS
                        next_pulse = now + SIGNAL_PERIOD_SECONDS
                    color = ("blue" if signal_active else "red") if now < pulse_until else "off"
                if color != previous_color:
                    set_rgb_led(led, color)
                    previous_color = color
                self._stop.wait(0.03)
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
    signal_endpoint: str
    joystick_x_sign: int
    joystick_y_sign: int
    scroll_sign: int
    deadzone: int

    def emit(self, event: dict[str, object]) -> None:
        try:
            post_event(self.endpoint, event)
        except Exception as exc:
            LOGGER.warning("event delivery failed: %s", exc)

    def run(self) -> None:
        from smbus2 import SMBus

        button, chip = open_button()
        status_led = StatusLed(self.signal_endpoint)
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
                        self.emit({"action": "select_nearest"})
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
            "http://127.0.0.1:38391/api/v1/hardware/event",
        ),
        signal_endpoint=os.getenv(
            "SKYTRACE_SIGNAL_ENDPOINT",
            "http://127.0.0.1:38391/api/v1/hardware/status",
        ),
        joystick_x_sign=int(os.getenv("SKYTRACE_JOYSTICK_X_SIGN", "-1")),
        joystick_y_sign=int(os.getenv("SKYTRACE_JOYSTICK_Y_SIGN", "-1")),
        scroll_sign=int(os.getenv("SKYTRACE_SCROLL_SIGN", "1")),
        deadzone=int(os.getenv("SKYTRACE_JOYSTICK_DEADZONE", "18")),
    )
    bridge.run()


if __name__ == "__main__":
    main()
