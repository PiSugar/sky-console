"""Device-wide feature preferences, persisted independently of deployment defaults."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from pydantic import BaseModel, ConfigDict, StrictBool


class FeatureUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enrichment_enabled: StrictBool | None = None
    radio_enabled: StrictBool | None = None
    dialogue_enabled: StrictBool | None = None
    dialogue_llm_enabled: StrictBool | None = None


class FeatureSettings:
    def __init__(self, path: Path, **defaults: bool):
        self.path = path
        self.lock = threading.RLock()
        self._values = {"enrichment_enabled": True, **defaults}
        self.revision = 0
        self.audio_epoch = 0

    def load(self) -> None:
        with self.lock:
            if not self.path.exists():
                return
            saved = FeatureUpdate.model_validate_json(self.path.read_text())
            self._values.update(saved.model_dump(exclude_none=True))

    def snapshot(self) -> dict:
        with self.lock:
            return {"features": dict(self._values), "revision": self.revision}

    def enabled(self, name: str) -> bool:
        with self.lock:
            return self._values[name]

    def update(self, changes: FeatureUpdate) -> dict:
        with self.lock:
            values = {**self._values, **changes.model_dump(exclude_none=True)}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent, delete=False) as handle:
                    temporary = handle.name
                    json.dump(values, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
            if values["radio_enabled"] != self._values["radio_enabled"] or values["dialogue_enabled"] != self._values["dialogue_enabled"]:
                self.audio_epoch += 1
            self._values = values
            self.revision += 1
            return self.snapshot()
