from __future__ import annotations

import math
import tempfile
import unittest
import wave
from array import array

from server.app.radio import (
    begin_radio_session,
    cancel_radio_session,
    finish_radio_session,
    is_radio_playing,
    radio_intro_text,
    radio_route_text,
    radio_text,
    voice_for_aircraft,
    _wav_envelope,
)


class RadioTests(unittest.TestCase):
    def test_duplicate_session_for_same_aircraft_is_reused(self) -> None:
        first, first_created = begin_radio_session("7823B7")
        duplicate, duplicate_created = begin_radio_session("7823B7")
        try:
            self.assertTrue(first_created)
            self.assertFalse(duplicate_created)
            self.assertIs(first, duplicate)
            self.assertFalse(first.cancelled.is_set())
        finally:
            finish_radio_session(first)

    def test_active_session_can_be_cancelled_for_push_to_talk(self) -> None:
        session, _ = begin_radio_session("7823B7")

        self.assertEqual(cancel_radio_session(), "7823B7")
        self.assertTrue(session.cancelled.is_set())
        self.assertIsNone(cancel_radio_session())

    def test_radio_text_uses_spoken_callsign_and_route(self) -> None:
        text = radio_text(
            {
                "icao": "7823B7",
                "route_callsign_iata": "CZ3756",
                "origin_city": "Guangzhou",
                "origin_iata": "CAN",
                "destination_city": "Shanghai",
                "destination_iata": "SHA",
            }
        )

        self.assertIn("charlie zulu three seven five six", text)
        self.assertIn("Guangzhou CAN", text)
        self.assertIn("Shanghai SHA", text)

    def test_radio_intro_can_play_before_route_is_known(self) -> None:
        text = radio_intro_text({"icao": "7823B7", "callsign": "CSN3756"})

        self.assertIn("charlie sierra november three seven five six", text)
        self.assertNotIn("unconfirmed", text)

    def test_unconfirmed_route_sounds_natural(self) -> None:
        text = radio_route_text({"icao": "7823B7", "callsign": "CSN3756"})

        self.assertNotIn("from unconfirmed to unconfirmed", text)
        self.assertIn("route", text.lower())

    def test_voice_is_stable_per_aircraft(self) -> None:
        self.assertEqual(voice_for_aircraft("7823B7"), voice_for_aircraft("7823b7"))

    def test_radio_is_idle_without_audio_playback(self) -> None:
        self.assertFalse(is_radio_playing())

    def test_wav_envelope_tracks_audio_amplitude(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav") as audio:
            with wave.open(audio.name, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(1000)
                quiet = [int(1000 * math.sin(index)) for index in range(30)]
                loud = [int(12000 * math.sin(index)) for index in range(30)]
                output.writeframes(array("h", quiet + loud).tobytes())
            envelope = _wav_envelope(audio.name)

        self.assertEqual(len(envelope), 2)
        self.assertLess(envelope[0], envelope[1])
        self.assertEqual(envelope[1], 1.0)


if __name__ == "__main__":
    unittest.main()
