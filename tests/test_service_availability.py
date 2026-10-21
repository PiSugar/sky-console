import unittest
from unittest.mock import patch

from server.app.service_availability import ServiceAvailability


class ServiceAvailabilityTests(unittest.TestCase):
    def service(self):
        return ServiceAvailability("http://asr/recognize", "http://llm", "pilot")

    def test_unconfigured_services_are_unavailable_without_network(self):
        with patch("server.app.service_availability._get_json") as fetch:
            result = ServiceAvailability("", "", "").check()
        self.assertTrue(all(not value["available"] for value in result.values()))
        fetch.assert_not_called()

    def test_ready_asr_and_installed_model_enable_features(self):
        replies = {"http://asr/healthz": {"status": "ok"}, "http://llm/api/tags": {"models": [{"name": "pilot:latest"}]}}
        with patch("server.app.service_availability._get_json", side_effect=replies.__getitem__):
            result = self.service().check()
        self.assertTrue(all(value["available"] for value in result.values()))

    def test_missing_model_blocks_llm_only(self):
        with patch("server.app.service_availability._get_json", return_value={"status": "ok", "models": [{"name": "another:latest"}]}):
            result = self.service().check()
        self.assertTrue(result["dialogue_enabled"]["available"])
        self.assertFalse(result["dialogue_llm_enabled"]["available"])
        self.assertIn("not installed", result["dialogue_llm_enabled"]["reason"])

    def test_asr_failure_blocks_questions_and_llm(self):
        def fetch(url):
            if "asr" in url:
                raise OSError("offline")
            return {"models": [{"model": "pilot:latest"}]}
        with patch("server.app.service_availability._get_json", side_effect=fetch):
            result = self.service().check()
        self.assertTrue(all(not value["available"] for value in result.values()))

    def test_checks_are_cached_but_enable_can_force_revalidation(self):
        service = self.service()
        with patch("server.app.service_availability._get_json", return_value={"status": "ok", "models": [{"name": "pilot:latest"}]}) as fetch:
            service.check()
            service.check()
            self.assertEqual(fetch.call_count, 2)
            fetch.side_effect = OSError("service stopped")
            self.assertFalse(service.check(force=True)["dialogue_enabled"]["available"])
            self.assertEqual(fetch.call_count, 4)

    def test_custom_health_endpoint(self):
        service = ServiceAvailability("http://asr/api/transcribe", "", "", "http://asr/ready")
        with patch("server.app.service_availability._get_json", return_value={"status": "ok"}) as fetch:
            self.assertTrue(service.check()["dialogue_enabled"]["available"])
        fetch.assert_called_once_with("http://asr/ready")
