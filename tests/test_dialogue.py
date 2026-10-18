from __future__ import annotations

import unittest

from server.app.dialogue import aircraft_facts, fixed_pilot_answer


AIRCRAFT = {
    "icao": "780E2E",
    "callsign": "CHH7981",
    "altitude_baro": 32100,
    "ground_speed": 438.7,
    "track": 92.4,
    "vertical_rate": -640,
    "origin_city": "Guangzhou",
    "destination_city": "Shanghai",
}


class PilotDialogueTests(unittest.TestCase):
    def test_attitude_is_treated_as_altitude(self) -> None:
        answer = fixed_pilot_answer("What is your attitude?", AIRCRAFT)
        self.assertIn("32,100 feet", answer)

    def test_destination_uses_real_route(self) -> None:
        answer = fixed_pilot_answer("Where are you going?", AIRCRAFT)
        self.assertIn("Shanghai", answer)

    def test_prompt_facts_include_live_motion(self) -> None:
        facts = aircraft_facts(AIRCRAFT)
        self.assertIn("ground speed knots: 438.7", facts)
        self.assertIn("vertical rate feet per minute: -640", facts)

    def test_joke_request_gets_a_natural_pilot_joke(self) -> None:
        answer = fixed_pilot_answer("Tell me a joke", AIRCRAFT)
        self.assertNotIn("I can report", answer)
        self.assertTrue(any(word in answer.lower() for word in ("airplane", "pilot", "wing")))

    def test_unknown_request_gets_a_humorous_refusal(self) -> None:
        answer = fixed_pilot_answer("Explain quantum gravity", AIRCRAFT)
        self.assertIn("cockpit", answer.lower())
        self.assertIn("coffee", answer.lower())
