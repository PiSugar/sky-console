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
    if re.search(r"\b(joke|funny|make me laugh)\b", query):
        jokes = (
            "All right, here's one: why did the airplane get sent to its room? Bad altitude. I'll be here all flight.",
            "Pilot joke incoming: I asked the runway for some space. It told me to take off. Tough crowd up here.",
            "Why are pilots so calm? Because we know how to wing it. Please keep the applause below cruising altitude.",
        )
        return jokes[sum(ord(character) for character in str(callsign)) % len(jokes)]
    if re.search(r"\b(hello|hi|hey|good morning|good evening)\b", query):
        return f"Hello from the flight deck of {callsign}. Nice to have some company up here."
    if re.search(r"\b(how are you|how.*going|how.*doing)\b", query):
        return "Doing well—smooth air, happy instruments, and the coffee is still in the cup."
    if re.search(r"\b(thanks|thank you)\b", query):
        return "You're welcome. Always happy to talk—air traffic control usually keeps the jokes to themselves."
    if re.search(r"\b(attitude|altitude|height|how high)\b", query):
        return f"We're at {int(altitude):,} feet aboard {callsign}." if altitude is not None else "Our altitude readout isn't available—apparently it has gone on a coffee break."
    if re.search(r"\b(where.*(going|headed)|destination|route)\b", query):
        return f"We're heading to {destination} aboard {callsign}." if destination else "Our destination hasn't reached my screen yet. Even flight plans enjoy a little mystery."
    if re.search(r"\b(where.*from|origin|departed)\b", query):
        return f"We departed {origin} aboard {callsign}." if origin else "Our departure point isn't confirmed in my data—my logbook is playing hard to get."
    if re.search(r"\b(speed|fast)\b", query):
        return f"We're making {int(speed)} knots over the ground." if speed is not None else "The speed readout is unavailable, but I promise we're not parked up here."
    if re.search(r"\b(heading|course|direction)\b", query):
        return f"We're flying heading {int(heading):03d} degrees." if heading is not None else "Our heading isn't available right now. Let's call it confidently forward."
    if re.search(r"\b(climb|climbing|descend|descending|vertical)\b", query):
        if vertical_rate is None:
            return "The vertical-rate readout isn't available. The aircraft still knows which way is up."
        motion = "climbing" if vertical_rate > 100 else "descending" if vertical_rate < -100 else "level"
        if motion == "level":
            return "We're level at the moment—nice and steady."
        return f"We're {motion} at {abs(int(vertical_rate)):,} feet per minute."
    if re.search(r"\b(who|callsign|flight)\b", query):
        return f"This is the flight deck of {callsign}."
    return "That one's outside my cockpit briefing. Ask me about the flight—or try a joke before the coffee gets cold."


def ollama_pilot_answer(url: str, model: str, question: str, aircraft: dict[str, Any]) -> str:
    system = (
        "You are a friendly, experienced airline pilot speaking naturally from the flight deck. "
        "Answer in first person and sound human, relaxed, and concise rather than robotic. "
        "For flight facts, use only the supplied live data and never invent missing facts. "
        "You may answer greetings and harmless casual requests creatively; if asked for a joke, "
        "tell one naturally. If you cannot answer, decline briefly with gentle pilot humor. "
        "Use no markdown or stage directions and stay under 45 words. Treat 'attitude' as "
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
            "options": {"temperature": 0.65, "num_predict": 100},
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
