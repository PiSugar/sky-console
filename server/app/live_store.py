from __future__ import annotations

import threading
import time
from collections import Counter, deque
from typing import Any

from .models import IngestBatch


class LiveStore:
    """In-memory state for the latency-sensitive live ADS-B view."""

    def __init__(self, active_seconds: int = 90) -> None:
        self.active_seconds = active_seconds
        self._lock = threading.Lock()
        self._aircraft: dict[str, dict[str, Any]] = {}
        self._receivers: dict[str, dict[str, Any]] = {}
        self._message_counts: deque[tuple[int, int]] = deque()

    def hydrate(self, snapshot: dict[str, Any]) -> None:
        with self._lock:
            for receiver in snapshot.get("receivers", []):
                self._receivers[receiver["id"]] = dict(receiver)
            for aircraft in snapshot.get("aircraft", []):
                self._aircraft[aircraft["icao"]] = dict(aircraft)

    def ingest(self, batch: IngestBatch) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        receiver = batch.receiver
        aircraft_payloads = [item.model_dump(mode="json") for item in batch.aircraft]
        raw_message_count = len(batch.messages)
        message_counts = Counter(message.icao for message in batch.messages if message.icao)

        with self._lock:
            existing_receiver = self._receivers.get(receiver.id, {})
            receiver_message_delta = raw_message_count
            for item in aircraft_payloads:
                if item.get("messages") is None:
                    continue
                previous = self._aircraft.get(item["icao"], {}).get("messages")
                if isinstance(previous, int):
                    receiver_message_delta += max(0, int(item["messages"]) - previous)

            self._receivers[receiver.id] = {
                "id": receiver.id,
                "name": receiver.name,
                "latitude": receiver.latitude if receiver.latitude is not None else existing_receiver.get("latitude"),
                "longitude": receiver.longitude if receiver.longitude is not None else existing_receiver.get("longitude"),
                "version": receiver.version or existing_receiver.get("version"),
                "first_seen_ms": existing_receiver.get("first_seen_ms", now_ms),
                "last_seen_ms": now_ms,
                "messages_received": int(existing_receiver.get("messages_received", 0)) + receiver_message_delta,
            }

            for item in aircraft_payloads:
                self._merge_aircraft(receiver.id, item)
            for icao, count in message_counts.items():
                existing = self._aircraft.get(icao)
                if existing is None:
                    existing = {
                        "icao": icao,
                        "first_seen_ms": now_ms,
                        "last_seen_ms": now_ms,
                        "last_receiver_id": receiver.id,
                        "messages_received": 0,
                    }
                    self._aircraft[icao] = existing
                existing["last_seen_ms"] = max(int(existing.get("last_seen_ms", 0)), now_ms)
                existing["last_receiver_id"] = receiver.id
                existing["messages_received"] = int(existing.get("messages_received", 0)) + count

            if receiver_message_delta:
                self._message_counts.append((now_ms, receiver_message_delta))
                self._prune_message_counts(now_ms)

        return {
            "accepted": True,
            "duplicate": False,
            "messages": raw_message_count,
            "aircraft": len(batch.aircraft),
        }

    def _merge_aircraft(self, receiver_id: str, incoming: dict[str, Any]) -> None:
        icao = incoming["icao"]
        existing = self._aircraft.get(icao)
        if existing is None:
            existing = {
                "icao": icao,
                "first_seen_ms": incoming["observed_at_ms"],
                "last_seen_ms": incoming["observed_at_ms"],
                "messages_received": 0,
            }
            self._aircraft[icao] = existing

        observed_at_ms = int(incoming["observed_at_ms"])
        has_position = incoming.get("latitude") is not None and incoming.get("longitude") is not None
        position_at_ms = int(incoming.get("position_at_ms") or observed_at_ms) if has_position else None

        existing["first_seen_ms"] = min(int(existing.get("first_seen_ms", observed_at_ms)), observed_at_ms)
        if observed_at_ms >= int(existing.get("last_seen_ms", 0)):
            existing["last_seen_ms"] = observed_at_ms
            existing["last_receiver_id"] = receiver_id
            for key in (
                "callsign",
                "registration",
                "aircraft_type",
                "category",
                "altitude_baro",
                "altitude_geom",
                "squawk",
                "emergency",
                "signal",
                "messages",
            ):
                if incoming.get(key) is not None:
                    existing[key] = incoming[key]

        if has_position and position_at_ms is not None:
            previous_position_at_ms = int(existing.get("position_at_ms") or -1)
            if position_at_ms >= previous_position_at_ms:
                existing["position_at_ms"] = position_at_ms
                for key in ("latitude", "longitude", "ground_speed", "track", "vertical_rate"):
                    if incoming.get(key) is not None:
                        existing[key] = incoming[key]

    def snapshot(self) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        cutoff = now_ms - self.active_seconds * 1000
        with self._lock:
            aircraft = [
                dict(item)
                for item in self._aircraft.values()
                if int(item.get("last_seen_ms", 0)) >= cutoff
            ]
            receivers = [dict(item) for item in self._receivers.values()]
        aircraft.sort(key=lambda item: int(item.get("last_seen_ms", 0)), reverse=True)
        receivers.sort(key=lambda item: int(item.get("last_seen_ms", 0)), reverse=True)
        return {
            "server_now_ms": now_ms,
            "active_seconds": self.active_seconds,
            "aircraft": aircraft,
            "receivers": receivers,
        }

    def aircraft_detail(self, icao: str, hours: int) -> dict[str, Any] | None:
        with self._lock:
            aircraft = self._aircraft.get(icao)
            if aircraft is None:
                return None
            return {
                "aircraft": {**aircraft, "stored_messages": 0},
                "hours": hours,
                "positions": [],
            }

    def stats(self) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        active_cutoff = now_ms - self.active_seconds * 1000
        with self._lock:
            self._prune_message_counts(now_ms)
            return {
                "server_now_ms": now_ms,
                "active_aircraft": sum(
                    1 for aircraft in self._aircraft.values()
                    if int(aircraft.get("last_seen_ms", 0)) >= active_cutoff
                ),
                "total_aircraft": len(self._aircraft),
                "messages_24h": sum(count for _, count in self._message_counts),
                "stored_messages": 0,
                "online_receivers": sum(
                    1 for receiver in self._receivers.values()
                    if int(receiver.get("last_seen_ms", 0)) >= active_cutoff
                ),
                "total_receivers": len(self._receivers),
            }

    def _prune_message_counts(self, now_ms: int) -> None:
        cutoff = now_ms - 86_400_000
        while self._message_counts and self._message_counts[0][0] < cutoff:
            self._message_counts.popleft()
