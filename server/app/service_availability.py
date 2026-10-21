"""Bounded readiness checks for optional ASR and model services."""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def _http_url(value: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        return False


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=2) as response:
        body = response.read(1_000_001)
    if len(body) > 1_000_000:
        raise ValueError("service response is too large")
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("invalid service response")
    return data


class ServiceAvailability:
    def __init__(self, asr_url: str, ollama_url: str, model: str, asr_health_url: str = ""):
        self.asr_url = asr_url.strip()
        self.asr_health_url = asr_health_url.strip() or urllib.parse.urljoin(self.asr_url, "healthz")
        self.ollama_url = ollama_url.strip().rstrip("/")
        self.model = model.strip()
        self._lock = threading.Lock()
        self._checked_at = 0.0
        self._result = {
            name: {"available": False, "reason": "Checking service availability…"}
            for name in ("dialogue_enabled", "dialogue_llm_enabled")
        }

    def cached(self) -> dict:
        # Results are replaced atomically and never modified after publication.
        return self._result

    def check(self, force: bool = False) -> dict:
        with self._lock:
            if not force and time.monotonic() - self._checked_at < 15:
                return self._result
            with ThreadPoolExecutor(max_workers=2) as pool:
                asr_future = pool.submit(self._check_asr)
                llm_future = pool.submit(self._check_llm)
                asr, llm = asr_future.result(), llm_future.result()
            if not asr["available"] and llm["available"]:
                llm = {"available": False, "reason": "Set up the speech recognition service first."}
            self._result = {"dialogue_enabled": asr, "dialogue_llm_enabled": llm}
            self._checked_at = time.monotonic()
            return self._result

    def _check_asr(self) -> dict:
        if not _http_url(self.asr_url) or not _http_url(self.asr_health_url):
            return {"available": False, "reason": "Speech recognition service is not configured."}
        try:
            if _get_json(self.asr_health_url).get("status") != "ok":
                raise ValueError("not ready")
        except (OSError, ValueError):
            return {"available": False, "reason": "Speech recognition service is unavailable. Configure or start it, then retry."}
        return {"available": True, "reason": "Speech recognition service is ready."}

    def _check_llm(self) -> dict:
        if not _http_url(self.ollama_url) or not self.model:
            return {"available": False, "reason": "Model service and model are not configured."}
        try:
            models = _get_json(f"{self.ollama_url}/api/tags").get("models", [])
            expected = self.model if ":" in self.model.rsplit("/", 1)[-1] else f"{self.model}:latest"
            if not any(isinstance(item, dict) and (item.get("name") or item.get("model")) in {self.model, expected} for item in models):
                return {"available": False, "reason": "The configured model is not installed. Install it, then retry."}
        except (OSError, ValueError, TypeError):
            return {"available": False, "reason": "Model service is unavailable. Configure or start it, then retry."}
        return {"available": True, "reason": "Model service and model are ready."}
