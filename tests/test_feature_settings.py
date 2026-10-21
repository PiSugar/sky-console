from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from server.app.feature_settings import FeatureSettings, FeatureUpdate


class FeatureSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "feature-settings.json"
        self.features = FeatureSettings(self.path, radio_enabled=True, dialogue_enabled=True, dialogue_llm_enabled=False)

    def test_partial_changes_persist_across_restart(self):
        self.features.update(FeatureUpdate(dialogue_llm_enabled=True))
        restarted = FeatureSettings(self.path, radio_enabled=False, dialogue_enabled=False, dialogue_llm_enabled=False)
        restarted.load()
        self.assertEqual(restarted.snapshot()["features"], dict(radio_enabled=True, dialogue_enabled=True, dialogue_llm_enabled=True))

    def test_failed_save_keeps_previous_values(self):
        with patch("server.app.feature_settings.os.replace", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.features.update(FeatureUpdate(radio_enabled=False))
        self.assertTrue(self.features.enabled("radio_enabled"))
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_strict_validation(self):
        for data in [{"radio_enabled": "false"}, {"dialogue_enabled": 1}, {"unknown": True}]:
            with self.subTest(data=data), self.assertRaises(ValidationError):
                FeatureUpdate.model_validate(data)

    def test_concurrent_partial_updates_preserve_both_changes(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(self.features.update, [FeatureUpdate(radio_enabled=False), FeatureUpdate(dialogue_llm_enabled=True)]))
        self.assertFalse(self.features.enabled("radio_enabled"))
        self.assertTrue(self.features.enabled("dialogue_llm_enabled"))


class FeatureSettingsAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {"INGEST_API_KEY": "feature-settings-test-key"}):
            cls.main = importlib.import_module("server.app.main")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.features = FeatureSettings(Path(self.temp.name) / "settings.json", radio_enabled=True, dialogue_enabled=True, dialogue_llm_enabled=False)
        self.addCleanup(patch.stopall)
        patch.object(self.main, "features", self.features).start()
        patch.object(self.main, "is_local_or_docker_request", return_value=True).start()
        patch.object(self.main, "hardware_selected_icao", "ABC123").start()
        patch.object(self.main, "live_snapshot", return_value={"aircraft": [{"icao": "ABC123"}]}).start()
        patch.object(self.main, "_radio_aircraft_payload", return_value={"icao": "ABC123", "callsign": "TEST123"}).start()
        self.recognize = patch.object(self.main, "recognize_question", return_value="What is your altitude?").start()
        self.llm = patch.object(self.main, "ollama_pilot_answer", return_value="Model answer").start()
        self.play = patch.object(self.main, "play_pilot_dialogue").start()
        self.client = TestClient(self.main.app)
        self.addCleanup(self.client.close)

    def ask(self):
        return self.client.post("/api/v1/hardware/dialogue", json={"audio_base64": "UklGRgAAAAAAAAAAAAAA"})

    def test_get_and_update_and_stop_audio(self):
        self.assertTrue(self.client.get("/api/v1/settings").json()["editable"])
        with patch.object(self.main, "cancel_radio_session") as stop:
            result = self.client.patch("/api/v1/settings", json={"radio_enabled": False})
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json()["features"]["radio_enabled"])
        self.assertTrue(result.json()["features"]["dialogue_enabled"])
        self.assertEqual(result.headers["cache-control"], "no-store")
        stop.assert_called_once()
        self.assertEqual(self.client.post("/api/v1/aircraft/ABC123/radio").status_code, 503)

    def test_settings_are_sent_to_connected_pages(self):
        with self.client.websocket_connect("/ws/v1/live") as socket:
            initial = socket.receive_json()
            self.assertFalse(initial["settings"]["features"]["dialogue_llm_enabled"])
            self.client.patch("/api/v1/settings", json={"dialogue_llm_enabled": True})
            updated = socket.receive_json()
            self.assertEqual(updated["type"], "settings")
            self.assertTrue(updated["features"]["dialogue_llm_enabled"])

    def test_remote_settings_are_read_only_without_key(self):
        with patch.object(self.main, "is_local_or_docker_request", return_value=False):
            self.assertFalse(self.client.get("/api/v1/settings").json()["editable"])
            self.assertEqual(self.client.patch("/api/v1/settings", json={"radio_enabled": False}).status_code, 403)
            result = self.client.patch("/api/v1/settings", json={"radio_enabled": False}, headers={"Authorization": f"Bearer {self.main.settings.ingest_api_key}"})
            self.assertEqual(result.status_code, 200)

    def test_cross_origin_and_invalid_changes_are_rejected(self):
        self.assertEqual(self.client.patch("/api/v1/settings", json={"radio_enabled": False}, headers={"Origin": "https://other.example"}).status_code, 403)
        for data in [{"radio_enabled": "false"}, {"surprise": True}]:
            self.assertEqual(self.client.patch("/api/v1/settings", json=data).status_code, 422)

    def test_failed_save_returns_error_without_changing_state(self):
        with patch.object(self.features, "update", side_effect=OSError("disk full")):
            self.assertEqual(self.client.patch("/api/v1/settings", json={"radio_enabled": False}).status_code, 503)
        self.assertTrue(self.features.enabled("radio_enabled"))

    def test_disabled_voice_preserves_text_without_playback(self):
        self.features.update(FeatureUpdate(radio_enabled=False))
        response = self.ask()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["mode"], "fixed")
        self.assertFalse(response.json()["queued"])
        self.play.assert_not_called()
        self.llm.assert_not_called()

    def test_disabled_questions_prevent_asr_and_llm(self):
        self.features.update(FeatureUpdate(dialogue_enabled=False, dialogue_llm_enabled=True))
        self.assertFalse(self.client.get("/api/v1/hardware/dialogue/status").json()["ready"])
        self.assertEqual(self.ask().status_code, 409)
        self.recognize.assert_not_called()
        self.llm.assert_not_called()

    def test_llm_enabled_and_failure_falls_back(self):
        self.features.update(FeatureUpdate(dialogue_llm_enabled=True))
        self.assertEqual(self.ask().json()["mode"], "llm")
        self.llm.side_effect = OSError("model offline")
        self.assertEqual(self.ask().json()["mode"], "fixed-fallback")

    def test_disabling_llm_during_generation_discards_model_answer(self):
        self.features.update(FeatureUpdate(dialogue_llm_enabled=True))
        def answer(*args):
            self.features.update(FeatureUpdate(dialogue_llm_enabled=False))
            return "Model answer"
        self.llm.side_effect = answer
        response = self.ask().json()
        self.assertEqual(response["mode"], "fixed")
        self.assertNotEqual(response["answer"], "Model answer")

    def test_disabling_questions_during_asr_prevents_response(self):
        def recognize(*args):
            self.features.update(FeatureUpdate(dialogue_enabled=False))
            return "Hello"
        self.recognize.side_effect = recognize
        self.assertEqual(self.ask().status_code, 409)
        self.play.assert_not_called()

    def test_disabling_then_enabling_voice_does_not_play_old_question(self):
        def recognize(*args):
            self.features.update(FeatureUpdate(radio_enabled=False))
            self.features.update(FeatureUpdate(radio_enabled=True))
            return "Hello"
        self.recognize.side_effect = recognize
        self.assertFalse(self.ask().json()["queued"])
        self.play.assert_not_called()


if __name__ == "__main__":
    unittest.main()
