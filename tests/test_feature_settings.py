from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch, Mock

from fastapi.testclient import TestClient
from pydantic import ValidationError

from server.app.feature_settings import FeatureSettings, FeatureUpdate


class FeatureSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "feature-settings.json"
        self.features = FeatureSettings(self.path, radio_enabled=True, dialogue_enabled=True, dialogue_llm_enabled=False, volume_percent=70)

    def test_partial_changes_persist_across_restart(self):
        self.features.update(FeatureUpdate(dialogue_llm_enabled=True))
        restarted = FeatureSettings(self.path, radio_enabled=False, dialogue_enabled=False, dialogue_llm_enabled=False, volume_percent=25)
        restarted.load()
        self.assertEqual(restarted.snapshot()["features"], dict(enrichment_enabled=True, radio_enabled=True, dialogue_enabled=True, dialogue_llm_enabled=True, volume_percent=70))

    def test_failed_save_keeps_previous_values(self):
        with patch("server.app.feature_settings.os.replace", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.features.update(FeatureUpdate(radio_enabled=False))
        self.assertTrue(self.features.enabled("radio_enabled"))
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_strict_validation(self):
        for data in [{"radio_enabled": "false"}, {"dialogue_enabled": 1}, {"volume_percent": 101}, {"volume_percent": 25.5}, {"unknown": True}]:
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
        self.features = FeatureSettings(Path(self.temp.name) / "settings.json", radio_enabled=True, dialogue_enabled=True, dialogue_llm_enabled=False, volume_percent=70)
        self.addCleanup(patch.stopall)
        patch.object(self.main, "features", self.features).start()
        self.availability = {name: {"available": True, "reason": "Ready"} for name in ("dialogue_enabled", "dialogue_llm_enabled")}
        self.services = Mock()
        self.services.check.return_value = self.availability
        self.services.cached.return_value = self.availability
        patch.object(self.main, "services", self.services).start()
        self.enricher = patch.object(self.main, "enricher").start()
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

    def test_aircraft_intro_and_route_publish_exact_spoken_text(self):
        from server.app.radio import RadioSession

        session = RadioSession("ABC123")

        def play(aircraft, text, **kwargs):
            kwargs["on_playback"](True)
            kwargs["on_playback"](False)
            return {"played": True}

        with patch.object(self.main, "play_radio_text", side_effect=play), patch.object(self.main.live_hub, "broadcast_from_thread") as publish:
            for segment, text in (("intro", "Test flight checking in."), ("route", "Guangzhou to Shanghai.")):
                self.main._play_radio_segment({"icao": "ABC123", "callsign": "TEST123"}, session, segment, text, False)
                start, end = [call.args[0] for call in publish.call_args_list[-2:]]
                self.assertEqual(start["text"], text)
                self.assertEqual(start["segment"], segment)
                self.assertTrue(start["active"])
                self.assertFalse(end["active"])
                self.assertEqual(start["id"], end["id"])
            self.assertNotEqual(publish.call_args_list[0].args[0]["id"], publish.call_args_list[2].args[0]["id"])

    def test_get_and_update_and_stop_audio(self):
        self.assertTrue(self.client.get("/api/v1/settings").json()["editable"])
        with patch.object(self.main, "cancel_radio_session") as stop:
            result = self.client.patch("/api/v1/settings", json={"radio_enabled": False})
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json()["features"]["radio_enabled"])
        self.assertTrue(result.json()["features"]["dialogue_enabled"])
        self.assertEqual(result.headers["cache-control"], "no-store")
        stop.assert_called_once()
        with patch.object(self.main.threading, "Thread") as thread:
            response = self.main.aircraft_radio("ABC123")
        self.main.cancel_radio_session()
        self.assertTrue(response["queued"])
        self.assertFalse(response["speech"])
        self.assertFalse(thread.call_args.kwargs["args"][-1])

    def test_volume_is_validated_saved_and_stops_active_audio(self):
        with patch.object(self.main, "cancel_radio_session") as stop:
            result = self.client.patch("/api/v1/settings", json={"volume_percent": 35})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["features"]["volume_percent"], 35)
        stop.assert_called_once()
        self.features.load()
        self.assertEqual(self.features.value("volume_percent"), 35)

    def test_disabled_voice_plays_selection_chirp_without_tts(self):
        from server.app.radio import RadioSession
        self.features.update(FeatureUpdate(radio_enabled=False))
        with patch.object(self.main, "play_radio_chirp", return_value={"played": True}) as chirp, patch.object(self.main, "_play_radio_segment") as speech:
            self.main._play_radio_background("ABC123", {"icao": "ABC123"}, RadioSession("ABC123"), False)
        chirp.assert_called_once()
        speech.assert_not_called()

    def test_unavailable_services_cannot_be_enabled_or_used(self):
        for value in self.availability.values():
            value.update(available=False, reason="Configure service first")
        self.features.update(FeatureUpdate(dialogue_enabled=False, dialogue_llm_enabled=False))
        for name in self.availability:
            response = self.client.patch("/api/v1/settings", json={name: True})
            self.assertEqual(response.status_code, 409)
            self.assertFalse(self.features.enabled(name))
            self.assertEqual(response.json()["detail"], "Configure service first")
        # Older persisted preferences still cannot bypass runtime readiness checks.
        self.features.update(FeatureUpdate(dialogue_enabled=True))
        self.assertEqual(self.ask().status_code, 409)
        self.recognize.assert_not_called()

    def test_flight_details_switch_updates_fetcher_and_persists(self):
        response = self.client.patch("/api/v1/settings", json={"enrichment_enabled": False})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.enricher.enabled)
        self.features.load()
        self.assertFalse(self.features.enabled("enrichment_enabled"))
        self.client.patch("/api/v1/settings", json={"enrichment_enabled": True})
        self.assertTrue(self.enricher.enabled)

    def test_startup_disables_legacy_preferences_without_ready_services(self):
        self.features.update(FeatureUpdate(dialogue_enabled=True, dialogue_llm_enabled=True))
        for service in self.availability.values():
            service.update(available=False, reason="Not configured")
        with patch.object(self.main.database, "initialize"), patch.object(self.main.database, "latest_state", return_value=[]), patch.object(self.main.live_store, "hydrate"):
            with TestClient(self.main.app):
                self.assertFalse(self.features.enabled("dialogue_enabled"))
                self.assertFalse(self.features.enabled("dialogue_llm_enabled"))
        self.features.load()
        self.assertFalse(self.features.enabled("dialogue_enabled"))

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
