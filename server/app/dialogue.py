from __future__ import annotations

import json
import re
import urllib.request
from typing import Any


def recognize_question(asr_url: str, audio_base64: str) -> str:
    payload = json.dumps({"base64": audio_base64, "language": "en"}).encode("utf-8")
    request = urllib.request.Request(
        asr_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        result = json.load(response)
    return str(result.get("recognition") or "").strip()


def aircraft_facts(aircraft: dict[str, Any]) -> str:
    fields = {
        "ICAO": aircraft.get("icao"),
        "callsign": aircraft.get("route_callsign_iata") or aircraft.get("callsign"),
        "registration": aircraft.get("registration"),
        "aircraft type": aircraft.get("aircraft_type"),
        "barometric altitude feet": aircraft.get("altitude_baro"),
        "ground speed knots": aircraft.get("ground_speed"),
        "heading degrees": aircraft.get("track"),
        "vertical rate feet per minute": aircraft.get("vertical_rate"),
        "latitude": aircraft.get("latitude"),
        "longitude": aircraft.get("longitude"),
        "origin": aircraft.get("origin_city") or aircraft.get("origin_name") or aircraft.get("origin_iata"),
        "destination": aircraft.get("destination_city") or aircraft.get("destination_name") or aircraft.get("destination_iata"),
    }
    return "\n".join(f"{key}: {value}" for key, value in fields.items() if value not in (None, ""))


def fixed_pilot_answer(question: str, aircraft: dict[str, Any]) -> str:
    query = question.lower()
    callsign = aircraft.get("route_callsign_iata") or aircraft.get("callsign") or aircraft.get("icao") or "this aircraft"
    altitude = aircraft.get("altitude_baro")
    destination = aircraft.get("destination_city") or aircraft.get("destination_name") or aircraft.get("destination_iata")
    origin = aircraft.get("origin_city") or aircraft.get("origin_name") or aircraft.get("origin_iata")
    speed = aircraft.get("ground_speed")
    heading = aircraft.get("track")
    vertical_rate = aircraft.get("vertical_rate")
    if re.search(r"\b(attitude|altitude|height|how high)\b", query):
        return f"{callsign}, we are at {int(altitude):,} feet." if altitude is not None else f"{callsign}, altitude is not available right now."
    if re.search(r"\b(where.*(going|headed)|destination|route)\b", query):
        return f"{callsign}, we are heading to {destination}." if destination else f"{callsign}, our destination is not confirmed yet."
    if re.search(r"\b(where.*from|origin|departed)\b", query):
        return f"{callsign}, we departed {origin}." if origin else f"{callsign}, our departure point is not confirmed."
    if re.search(r"\b(speed|fast)\b", query):
        return f"{callsign}, ground speed is {int(speed)} knots." if speed is not None else f"{callsign}, speed data is unavailable."
    if re.search(r"\b(heading|course|direction)\b", query):
        return f"{callsign}, heading {int(heading):03d} degrees." if heading is not None else f"{callsign}, heading data is unavailable."
    if re.search(r"\b(climb|climbing|descend|descending|vertical)\b", query):
        if vertical_rate is None:
            return f"{callsign}, vertical rate is unavailable."
        motion = "climbing" if vertical_rate > 100 else "descending" if vertical_rate < -100 else "level"
        return f"{callsign}, we are {motion} at {abs(int(vertical_rate)):,} feet per minute."
    if re.search(r"\b(who|callsign|flight)\b", query):
        return f"This is {callsign}."
    return f"{callsign}, I can report our altitude, speed, heading, origin, or destination."


def ollama_pilot_answer(url: str, model: str, question: str, aircraft: dict[str, Any]) -> str:
    system = (
        "You are the pilot of the aircraft described below, speaking over aviation radio. "
        "Answer in first person, in concise natural English, using only supplied live data. "
        "Never invent missing facts. Keep the answer under 45 words. Treat 'attitude' as "
        "'altitude' when that fits the question.\n\nLIVE AIRCRAFT DATA:\n" + aircraft_facts(aircraft)
    )
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
            "stream": False,
            "think": False,
            "keep_alive": -1,
            "options": {"temperature": 0.35, "num_predict": 100},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        result = json.load(response)
    answer = str(result.get("message", {}).get("content") or "").strip()
    if not answer:
        raise ValueError("Ollama returned an empty response")
    return answer
