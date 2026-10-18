from __future__ import annotations

import base64
import os
import tempfile
import time

from faster_whisper import WhisperModel
from flask import Flask, jsonify, request


MODEL = os.getenv("FASTER_WHISPER_MODEL", "tiny.en")
app = Flask(__name__)
model = WhisperModel(MODEL, device="cpu", cpu_threads=3, compute_type="int8")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "model": MODEL}


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
            vad_filter=True,
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
