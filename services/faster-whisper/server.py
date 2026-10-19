from __future__ import annotations

import base64
import os
import tempfile
import time

from faster_whisper import WhisperModel
from flask import Flask, jsonify, request


MODEL = os.getenv("FASTER_WHISPER_MODEL", "small.en")
MODEL_PATH = os.getenv("FASTER_WHISPER_MODEL_PATH", f"/models/{MODEL}")
CPU_THREADS = int(os.getenv("FASTER_WHISPER_CPU_THREADS", "3"))
BEAM_SIZE = int(os.getenv("FASTER_WHISPER_BEAM_SIZE", "5"))
INITIAL_PROMPT = os.getenv(
    "FASTER_WHISPER_INITIAL_PROMPT",
    (
        "A visitor is speaking English to an aircraft pilot. Questions may mention "
        "a callsign, altitude, attitude, speed, heading, course, destination, origin, "
        "route, climbing, descending, aircraft, flight, or ask the pilot to tell a joke."
    ),
)
HOTWORDS = os.getenv(
    "FASTER_WHISPER_HOTWORDS",
    (
        "aircraft, pilot, callsign, altitude, attitude, airspeed, ground speed, heading, "
        "course, destination, origin, route, climb, climbing, descend, descending, flight"
    ),
)
app = Flask(__name__)
model = WhisperModel(MODEL_PATH, device="cpu", cpu_threads=CPU_THREADS, compute_type="int8")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "model": MODEL, "beam_size": BEAM_SIZE}


@app.post("/recognize")
def recognize():
    payload = request.get_json(force=True, silent=True) or {}
    encoded = payload.get("base64")
    if not encoded:
        return jsonify({"error": "base64 audio is required"}), 400
    descriptor, path = tempfile.mkstemp(suffix=".wav")
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(base64.b64decode(encoded, validate=True))
        started = time.perf_counter()
        segments, info = model.transcribe(
            path,
            language=payload.get("language") or "en",
            beam_size=BEAM_SIZE,
            patience=1.2,
            temperature=0.0,
            condition_on_previous_text=False,
            initial_prompt=INITIAL_PROMPT,
            hotwords=HOTWORDS,
            repetition_penalty=1.05,
            no_repeat_ngram_size=3,
            vad_filter=True,
            vad_parameters={
                "min_silence_duration_ms": 350,
                "speech_pad_ms": 250,
            },
        )
        text = "".join(segment.text for segment in segments).strip()
        return {
            "recognition": text,
            "language": info.language,
            "time_cost": round(time.perf_counter() - started, 3),
        }
    finally:
        os.unlink(path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8803, threaded=False)
