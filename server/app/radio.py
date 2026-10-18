from __future__ import annotations

import array
import hashlib
import json
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_session_lock = threading.Lock()
_current_session: "RadioSession | None" = None
_audio_lock = threading.Lock()
_audio_playbacks = 0
AUDIO_METER_PATH = os.getenv("SKYTRACE_RADIO_METER_PATH", "/tmp/skytrace-radio-meter")
AUDIO_METER = struct.Struct("<BfQ")
AUDIO_ENVELOPE_SECONDS = 0.03


@dataclass(frozen=True, slots=True)
class RadioVoice:
    name: str
    model_path: str
    config_path: str
    length_scale: float
    noise_scale: float
    noise_w_scale: float
    volume: float
    pitch_cents: int
    tempo: float
    gain_db: float


RADIO_VOICES = (
    RadioVoice("captain-hfc", "/home/pi/piper/en_US-hfc_male-medium.onnx", "/home/pi/piper/en_US-hfc_male-medium.onnx.json", 0.92, 0.60, 0.78, 1.02, -70, 1.02, 0.0),
)

RADIO_TEMPLATES = (
    "SkyTrace, {flight}, standing by.",
    "{flight} checking in with SkyTrace.",
    "SkyTrace radio, {flight}, on frequency.",
    "{flight} on frequency with SkyTrace.",
    "SkyTrace, {flight} here.",
)

ROUTE_TEMPLATES = (
    "We are showing {origin} to {destination}.",
    "Filed route reads {origin} to {destination}.",
    "Route information is now in: {origin} to {destination}.",
    "This sector is listed as {origin} to {destination}.",
)

UNCONFIRMED_ROUTE_TEMPLATES = (
    "Route details are not confirmed yet. We'll keep the city pair off the air for now.",
    "The flight plan has not come through yet. Callsign confirmed, route still pending.",
    "Departure and destination are not reliable yet. We'll update when the route settles.",
    "No trusted city pair is available yet. We'll stay with the callsign for now.",
)

_DIGIT_WORDS = {
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "niner",
}

_LETTER_WORDS = {
    "A": "alpha",
    "B": "bravo",
    "C": "charlie",
    "D": "delta",
    "E": "echo",
    "F": "foxtrot",
    "G": "golf",
    "H": "hotel",
    "I": "india",
    "J": "juliett",
    "K": "kilo",
    "L": "lima",
    "M": "mike",
    "N": "november",
    "O": "oscar",
    "P": "papa",
    "Q": "quebec",
    "R": "romeo",
    "S": "sierra",
    "T": "tango",
    "U": "uniform",
    "V": "victor",
    "W": "whiskey",
    "X": "x-ray",
    "Y": "yankee",
    "Z": "zulu",
}


def _stable_index(value: str, size: int, salt: str = "") -> int:
    digest = hashlib.sha256(f"{salt}:{value}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % size


def voice_for_aircraft(icao: str) -> RadioVoice:
    return RADIO_VOICES[_stable_index(icao.upper(), len(RADIO_VOICES), "voice")]


class RadioSession:
    def __init__(self, icao: str) -> None:
        self.icao = icao
        self.cancelled = threading.Event()
        self._process_lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    def set_process(self, process: subprocess.Popen[str] | None) -> None:
        with self._process_lock:
            self._process = process
            if process is not None and self.cancelled.is_set():
                self._terminate_process(process)

    def cancel(self) -> None:
        self.cancelled.set()
        with self._process_lock:
            if self._process is not None:
                self._terminate_process(self._process)

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=0.8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)


def begin_radio_session(icao: str) -> tuple[RadioSession, bool]:
    global _current_session
    with _session_lock:
        if (
            _current_session is not None
            and _current_session.icao == icao
            and not _current_session.cancelled.is_set()
        ):
            return _current_session, False
        if _current_session is not None:
            _current_session.cancel()
        session = RadioSession(icao)
        _current_session = session
    return session, True


def finish_radio_session(session: RadioSession) -> None:
    global _current_session
    with _session_lock:
        if _current_session is session:
            _current_session = None


def cancel_radio_session() -> str | None:
    """Stop the active pilot transmission and return its aircraft ICAO."""

    global _current_session
    with _session_lock:
        session = _current_session
        _current_session = None
    if session is None:
        return None
    session.cancel()
    return session.icao


def is_radio_playing() -> bool:
    with _audio_lock:
        return _audio_playbacks > 0


def _set_audio_playing(active: bool) -> None:
    global _audio_playbacks
    with _audio_lock:
        _audio_playbacks = max(0, _audio_playbacks + (1 if active else -1))


def _publish_audio_meter(active: bool, level: float) -> None:
    payload = AUDIO_METER.pack(active, max(0.0, min(1.0, level)), time.time_ns())
    try:
        descriptor = os.open(AUDIO_METER_PATH, os.O_WRONLY | os.O_CREAT, 0o644)
        try:
            os.pwrite(descriptor, payload, 0)
        finally:
            os.close(descriptor)
    except OSError:
        # Metering must never prevent the pilot audio itself from playing.
        pass


def _wav_envelope(path: str, window_seconds: float = AUDIO_ENVELOPE_SECONDS) -> list[float]:
    """Calculate a normalized RMS envelope for 16-bit PCM playback."""

    with wave.open(path, "rb") as source:
        if source.getsampwidth() != 2:
            return [1.0]
        channels = source.getnchannels()
        sample_rate = source.getframerate()
        samples = array.array("h")
        samples.frombytes(source.readframes(source.getnframes()))
    if sys.byteorder != "little":
        samples.byteswap()
    window_samples = max(channels, int(sample_rate * channels * window_seconds))
    rms_values = []
    for start in range(0, len(samples), window_samples):
        window = samples[start : start + window_samples]
        if not window:
            continue
        rms_values.append(math.sqrt(sum(sample * sample for sample in window) / len(window)))
    peak = max(rms_values, default=0.0)
    if peak <= 0:
        return [0.0] * max(1, len(rms_values))
    return [round(math.sqrt(value / peak), 4) for value in rms_values]


def _route_label(aircraft: dict[str, Any], prefix: str) -> str:
    code = aircraft.get(f"{prefix}_iata") or aircraft.get(f"{prefix}_icao")
    city = aircraft.get(f"{prefix}_city")
    name = aircraft.get(f"{prefix}_name")
    country = aircraft.get(f"{prefix}_country")
    if city and code:
        return f"{city} {code}"
    if name and code:
        return f"{name} {code}"
    if city and country:
        return f"{city}, {country}"
    if name:
        return str(name)
    if code:
        return str(code)
    return "unconfirmed"


def has_confirmed_route(aircraft: dict[str, Any]) -> bool:
    return any(
        aircraft.get(key)
        for key in (
            "origin_name",
            "origin_iata",
            "origin_icao",
            "origin_city",
            "destination_name",
            "destination_iata",
            "destination_icao",
            "destination_city",
        )
    )


def _spoken_callsign(value: str) -> str:
    tokens = re.findall(r"[A-Z]+|\d+", value.upper())
    words: list[str] = []
    for token in tokens:
        if token.isdigit():
            words.extend(_DIGIT_WORDS[digit] for digit in token)
        else:
            words.extend(_LETTER_WORDS.get(letter, letter) for letter in token)
    return " ".join(words) or "unknown traffic"


def _flight_value(aircraft: dict[str, Any]) -> str:
    icao = str(aircraft.get("icao") or "").upper()
    return str(
        aircraft.get("route_callsign_iata")
        or aircraft.get("route_callsign_icao")
        or aircraft.get("callsign")
        or aircraft.get("registration")
        or f"ICAO {icao}"
    )


def radio_intro_text(aircraft: dict[str, Any]) -> str:
    icao = str(aircraft.get("icao") or "").upper()
    template = RADIO_TEMPLATES[_stable_index(icao or _flight_value(aircraft), len(RADIO_TEMPLATES), "intro")]
    return template.format(flight=_spoken_callsign(_flight_value(aircraft)))


def radio_route_text(aircraft: dict[str, Any]) -> str:
    icao = str(aircraft.get("icao") or "").upper()
    if not has_confirmed_route(aircraft):
        template = UNCONFIRMED_ROUTE_TEMPLATES[
            _stable_index(icao or _flight_value(aircraft), len(UNCONFIRMED_ROUTE_TEMPLATES), "unconfirmed")
        ]
        return template
    template = ROUTE_TEMPLATES[_stable_index(icao or _flight_value(aircraft), len(ROUTE_TEMPLATES), "route")]
    return template.format(
        origin=_route_label(aircraft, "origin"),
        destination=_route_label(aircraft, "destination"),
    )


def radio_text(aircraft: dict[str, Any]) -> str:
    return f"{radio_intro_text(aircraft)} {radio_route_text(aircraft)}"


def _run_cancelable(
    args: list[str],
    *,
    session: RadioSession,
    input_text: str | None = None,
    timeout: float,
    audio_playback: bool = False,
) -> None:
    if session.cancelled.is_set():
        raise subprocess.SubprocessError("radio session cancelled")
    process = subprocess.Popen(
        args,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    session.set_process(process)
    try:
        envelope = _wav_envelope(args[-1]) if audio_playback else []
    except (OSError, wave.Error):
        envelope = [1.0] if audio_playback else []
    if audio_playback:
        _set_audio_playing(True)
        _publish_audio_meter(True, envelope[0] if envelope else 0.0)
    started_at = time.monotonic()
    try:
        if input_text is not None and process.stdin is not None:
            process.stdin.write(input_text)
            process.stdin.close()
        while process.poll() is None:
            elapsed = time.monotonic() - started_at
            if audio_playback:
                index = min(len(envelope) - 1, int(elapsed / AUDIO_ENVELOPE_SECONDS))
                _publish_audio_meter(True, envelope[index] if envelope else 0.0)
            if session.cancelled.is_set():
                raise subprocess.SubprocessError("radio session cancelled")
            if elapsed > timeout:
                raise subprocess.TimeoutExpired(args, timeout)
            time.sleep(AUDIO_ENVELOPE_SECONDS if audio_playback else 0.05)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, args)
    finally:
        if process.poll() is None:
            RadioSession._terminate_process(process)
        session.set_process(None)
        if audio_playback:
            _publish_audio_meter(False, 0.0)
            _set_audio_playing(False)


def _audio_paths_for_segment(directory: str, segment: str) -> tuple[Path, Path, Path]:
    return (
        Path(directory) / f"chirp-{segment}.wav",
        Path(directory) / f"raw-{segment}.wav",
        Path(directory) / f"radio-{segment}.wav",
    )


def _synthesize_http(url: str, text: str, output_path: Path, length_scale: float) -> None:
    payload = json.dumps({"text": text, "length_scale": length_scale}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        output_path.write_bytes(response.read())


def play_radio_text(
    aircraft: dict[str, Any],
    text: str,
    *,
    session: RadioSession,
    segment: str,
    tts_command: str,
    voice_model: str,
    voice_config: str,
    audio_device: str,
    tmp_dir: str,
    chirp: bool = False,
    tts_http_url: str = "",
    tts_length_scale: float = 1.0,
) -> dict[str, Any]:
    flight = (
        aircraft.get("route_callsign_iata")
        or aircraft.get("route_callsign_icao")
        or aircraft.get("callsign")
        or aircraft.get("registration")
        or aircraft.get("icao")
    )
    try:
        voice = voice_for_aircraft(str(aircraft.get("icao") or ""))
        tmp_root = Path(tmp_dir)
        tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="skytrace-radio-", dir=tmp_root) as directory:
            chirp_wav, raw_wav, radio_wav = _audio_paths_for_segment(directory, segment)
            model_path = voice.model_path if Path(voice.model_path).is_file() else voice_model
            config_path = voice.config_path if Path(voice.config_path).is_file() else voice_config
            if chirp:
                _run_cancelable(
                    [
                        "sox",
                        "-n",
                        "-r",
                        "48000",
                        "-c",
                        "2",
                        str(chirp_wav),
                        "synth",
                        "0.07",
                        "sine",
                        "880",
                        "vol",
                        "0.16",
                        "pad",
                        "0",
                        "0.04",
                    ],
                    session=session,
                    timeout=5,
                )
                _run_cancelable(
                    ["aplay", "-q", "-D", audio_device, str(chirp_wav)],
                    session=session,
                    timeout=5,
                    audio_playback=True,
                )
            if tts_http_url:
                _synthesize_http(tts_http_url, text, raw_wav, tts_length_scale)
            else:
                _run_cancelable(
                    [
                        tts_command,
                        "--model",
                        model_path,
                        "--config",
                        config_path,
                        "--output-file",
                        str(raw_wav),
                        "--length-scale",
                        str(voice.length_scale),
                        "--noise-scale",
                        str(voice.noise_scale),
                        "--noise-w-scale",
                        str(voice.noise_w_scale),
                        "--sentence-silence",
                        "0.18",
                        "--volume",
                        str(voice.volume),
                    ],
                    session=session,
                    input_text=text,
                    timeout=20,
                )
            _run_cancelable(
                [
                    "sox",
                    str(raw_wav),
                    "-r",
                    "48000",
                    "-c",
                    "2",
                    str(radio_wav),
                    "pitch",
                    str(voice.pitch_cents),
                    "tempo",
                    str(voice.tempo),
                    "highpass",
                    "280",
                    "lowpass",
                    "3100",
                    "overdrive",
                    "6",
                    "12",
                    "gain",
                    str(voice.gain_db),
                    "pad",
                    "0.05",
                    "0.08",
                ],
                session=session,
                timeout=10,
            )
            _run_cancelable(
                ["aplay", "-q", "-D", audio_device, str(radio_wav)],
                session=session,
                timeout=20,
                audio_playback=True,
            )
        return {"played": True, "voice": voice.name, "model": model_path, "flight": flight, "text": text}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"played": False, "reason": f"{type(exc).__name__}: {exc}"}
