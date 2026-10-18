from __future__ import annotations

import os
from dataclasses import dataclass


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "true" if default else "false").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false")


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: str
    ingest_api_key: str
    retention_hours: int
    active_seconds: int
    public_base_url: str
    realtime_first: bool
    store_raw_messages: bool
    store_positions: bool
    enrichment_on_demand: bool
    enrichment_enabled: bool
    enrichment_base_url: str
    enrichment_success_hours: int
    enrichment_retry_hours: int
    enrichment_timeout_seconds: int
    radio_enabled: bool
    radio_tts_command: str
    radio_voice_model: str
    radio_voice_config: str
    radio_audio_device: str
    radio_tmp_dir: str
    radio_tts_http_url: str
    radio_tts_length_scale: float
    dialogue_asr_url: str
    dialogue_llm_enabled: bool
    dialogue_ollama_url: str
    dialogue_ollama_model: str

    @classmethod
    def from_env(cls) -> "Settings":
        key = os.getenv("INGEST_API_KEY", "")
        if len(key) < 16:
            raise RuntimeError("INGEST_API_KEY must contain at least 16 characters")
        return cls(
            database_path=os.getenv("DATABASE_PATH", "/data/adsb.sqlite3"),
            ingest_api_key=key,
            retention_hours=(
                _int_env("RETENTION_HOURS", 90 * 24, 1, 3650 * 24)
                if os.getenv("RETENTION_HOURS")
                else _int_env("RETENTION_DAYS", 90, 1, 3650) * 24
            ),
            active_seconds=_int_env("ACTIVE_SECONDS", 90, 10, 3600),
            public_base_url=os.getenv(
                "PUBLIC_BASE_URL", "https://hive.hahapiggy.vip:38391"
            ).rstrip("/"),
            realtime_first=_bool_env("REALTIME_FIRST", True),
            store_raw_messages=_bool_env("STORE_RAW_MESSAGES", False),
            store_positions=_bool_env("STORE_POSITIONS", False),
            enrichment_on_demand=_bool_env("ENRICHMENT_ON_DEMAND", True),
            enrichment_enabled=_bool_env("ENRICHMENT_ENABLED", False),
            enrichment_base_url=os.getenv(
                "ENRICHMENT_BASE_URL", "https://api.adsbdb.com/v0"
            ).rstrip("/"),
            enrichment_success_hours=_int_env(
                "ENRICHMENT_SUCCESS_HOURS", 168, 1, 24 * 365
            ),
            enrichment_retry_hours=_int_env("ENRICHMENT_RETRY_HOURS", 6, 1, 168),
            enrichment_timeout_seconds=_int_env(
                "ENRICHMENT_TIMEOUT_SECONDS", 3, 1, 30
            ),
            radio_enabled=_bool_env("RADIO_ENABLED", False),
            radio_tts_command=os.getenv("RADIO_TTS_COMMAND", "piper"),
            radio_voice_model=os.getenv(
                "RADIO_VOICE_MODEL", "/home/pi/piper/en_US-ryan-medium.onnx"
            ),
            radio_voice_config=os.getenv(
                "RADIO_VOICE_CONFIG", "/home/pi/piper/en_US-ryan-medium.onnx.json"
            ),
            radio_audio_device=os.getenv("RADIO_AUDIO_DEVICE", "plughw:2,0"),
            radio_tmp_dir=os.getenv("RADIO_TMP_DIR", "/tmp"),
            radio_tts_http_url=os.getenv("RADIO_TTS_HTTP_URL", "").rstrip("/"),
            radio_tts_length_scale=float(os.getenv("RADIO_TTS_LENGTH_SCALE", "1.0")),
            dialogue_asr_url=os.getenv(
                "DIALOGUE_ASR_URL", "http://faster-whisper:8803/recognize"
            ),
            dialogue_llm_enabled=_bool_env("DIALOGUE_LLM_ENABLED", False),
            dialogue_ollama_url=os.getenv(
                "DIALOGUE_OLLAMA_URL", "http://ollama:11434"
            ).rstrip("/"),
            dialogue_ollama_model=os.getenv("DIALOGUE_OLLAMA_MODEL", "gemma4:e2b"),
        )
