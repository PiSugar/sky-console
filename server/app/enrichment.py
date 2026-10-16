from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable

from .db import Database


LOGGER = logging.getLogger("skytrace.enrichment")
ICAO_PATTERN = re.compile(r"^[0-9A-F]{6}$")
CALLSIGN_PATTERN = re.compile(r"^[A-Z0-9]{2,16}$")


def _text(value: Any, maximum: int = 200) -> str | None:
    if not isinstance(value, (str, int, float)):
        return None
    cleaned = str(value).strip()
    return cleaned[:maximum] or None


def _coordinate(value: Any, minimum: float, maximum: float) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if minimum <= parsed <= maximum else None


def _https_url(value: Any) -> str | None:
    cleaned = _text(value, 1000)
    if not cleaned:
        return None
    parsed = urllib.parse.urlparse(cleaned)
    return cleaned if parsed.scheme == "https" and parsed.netloc else None


class EnrichmentService:
    def __init__(
        self,
        database: Database,
        *,
        enabled: bool,
        base_url: str,
        success_hours: int,
        retry_hours: int,
        timeout_seconds: int,
    ) -> None:
        self.database = database
        self.enabled = enabled
        self.base_url = base_url.rstrip("/")
        self.success_ttl_ms = success_hours * 3_600_000
        self.retry_ttl_ms = retry_hours * 3_600_000
        self.timeout_seconds = timeout_seconds
        self._queues: dict[str, queue.Queue[str | None]] = {
            "aircraft": queue.Queue(maxsize=500),
            "callsign": queue.Queue(maxsize=500),
        }
        self._pending: set[tuple[str, str]] = set()
        self._pending_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._last_request_at = 0.0
        self._request_lock = threading.Lock()

    def start(self, seed: Iterable[tuple[str, str | None]] = ()) -> None:
        if not self.enabled or self._threads:
            return
        for kind in ("callsign", "aircraft"):
            thread = threading.Thread(
                target=self._worker,
                args=(kind, self._queues[kind]),
                name=f"skytrace-enrichment-{kind}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)
        self.schedule_contacts(seed)

    def stop(self) -> None:
        if not self._threads:
            return
        self._stop_event.set()
        for work_queue in self._queues.values():
            try:
                work_queue.put_nowait(None)
            except queue.Full:
                pass
        for thread in self._threads:
            thread.join(timeout=2)
        self._threads = []

    def schedule_contacts(self, contacts: Iterable[tuple[str, str | None]]) -> None:
        if not self.enabled:
            return
        for raw_icao, raw_callsign in contacts:
            icao = (raw_icao or "").strip().upper()
            callsign = (raw_callsign or "").strip().upper()
            if CALLSIGN_PATTERN.fullmatch(callsign):
                self._schedule("callsign", callsign)
            if ICAO_PATTERN.fullmatch(icao):
                self._schedule("aircraft", icao)

    def _schedule(self, kind: str, key: str) -> None:
        due = (
            self.database.aircraft_metadata_due(
                key, self.success_ttl_ms, self.retry_ttl_ms
            )
            if kind == "aircraft"
            else self.database.flight_route_due(
                key, self.success_ttl_ms, self.retry_ttl_ms
            )
        )
        if not due:
            return
        item = (kind, key)
        with self._pending_lock:
            if item in self._pending:
                return
            self._pending.add(item)
        try:
            self._queues[kind].put_nowait(key)
        except queue.Full:
            with self._pending_lock:
                self._pending.discard(item)
            LOGGER.warning("enrichment queue is full; dropped %s %s", kind, key)

    def _worker(self, kind: str, work_queue: queue.Queue[str | None]) -> None:
        while not self._stop_event.is_set():
            try:
                key = work_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if key is None:
                work_queue.task_done()
                break
            try:
                if kind == "aircraft":
                    self._lookup_aircraft(key)
                else:
                    self._lookup_route(key)
            except Exception:
                LOGGER.exception("unexpected enrichment failure for %s %s", kind, key)
            finally:
                with self._pending_lock:
                    self._pending.discard((kind, key))
                work_queue.task_done()

    def _lookup_aircraft(self, icao: str) -> None:
        try:
            response = self._get_json(f"aircraft/{urllib.parse.quote(icao)}")
            aircraft = response.get("aircraft") if isinstance(response, dict) else None
            if not isinstance(aircraft, dict):
                raise LookupError("公开资料库暂未收录这架飞机")
            values = {
                "registration": _text(aircraft.get("registration"), 32),
                "manufacturer": _text(aircraft.get("manufacturer"), 100),
                "model": _text(aircraft.get("type"), 120),
                "type_code": _text(aircraft.get("icao_type"), 16),
                "owner": _text(aircraft.get("registered_owner"), 160),
                "owner_country": _text(
                    aircraft.get("registered_owner_country_name"), 100
                ),
                "owner_flag_code": _text(
                    aircraft.get("registered_owner_operator_flag_code"), 16
                ),
                "photo_url": _https_url(aircraft.get("url_photo")),
                "photo_thumbnail_url": _https_url(
                    aircraft.get("url_photo_thumbnail")
                ),
            }
            self.database.save_aircraft_metadata(icao, values, "ok")
        except LookupError as exc:
            self.database.save_aircraft_metadata(icao, {}, "not_found", str(exc))
        except Exception as exc:
            self.database.save_aircraft_metadata(
                icao, {}, "error", f"{type(exc).__name__}: {exc}"[:300]
            )

    def _lookup_route(self, callsign: str) -> None:
        try:
            response = self._get_json(f"callsign/{urllib.parse.quote(callsign)}")
            route = response.get("flightroute") if isinstance(response, dict) else None
            if not isinstance(route, dict):
                raise LookupError("公开资料库暂未收录这个呼号的航线")
            airline = route.get("airline") if isinstance(route.get("airline"), dict) else {}
            origin = route.get("origin") if isinstance(route.get("origin"), dict) else {}
            destination = (
                route.get("destination")
                if isinstance(route.get("destination"), dict)
                else {}
            )
            values = {
                "callsign_icao": _text(route.get("callsign_icao"), 20),
                "callsign_iata": _text(route.get("callsign_iata"), 20),
                "airline_name": _text(airline.get("name"), 160),
                "airline_icao": _text(airline.get("icao"), 16),
                "airline_iata": _text(airline.get("iata"), 16),
                "airline_country": _text(airline.get("country"), 100),
                "airline_callsign": _text(airline.get("callsign"), 80),
                **self._airport_values("origin", origin),
                **self._airport_values("destination", destination),
            }
            self.database.save_flight_route(callsign, values, "ok")
        except LookupError as exc:
            self.database.save_flight_route(callsign, {}, "not_found", str(exc))
        except Exception as exc:
            self.database.save_flight_route(
                callsign, {}, "error", f"{type(exc).__name__}: {exc}"[:300]
            )

    @staticmethod
    def _airport_values(prefix: str, airport: dict[str, Any]) -> dict[str, Any]:
        return {
            f"{prefix}_name": _text(airport.get("name"), 200),
            f"{prefix}_iata": _text(airport.get("iata_code"), 8),
            f"{prefix}_icao": _text(airport.get("icao_code"), 8),
            f"{prefix}_city": _text(airport.get("municipality"), 120),
            f"{prefix}_country": _text(airport.get("country_name"), 100),
            f"{prefix}_latitude": _coordinate(
                airport.get("latitude"), -90, 90
            ),
            f"{prefix}_longitude": _coordinate(
                airport.get("longitude"), -180, 180
            ),
        }

    def _get_json(self, endpoint: str) -> dict[str, Any]:
        with self._request_lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < 0.3:
                time.sleep(0.3 - elapsed)
            self._last_request_at = time.monotonic()
        request = urllib.request.Request(
            f"{self.base_url}/{endpoint}",
            headers={
                "Accept": "application/json",
                "User-Agent": "SkyTrace-ADSB/1.1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read(1_000_001)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise LookupError("公开资料库没有匹配记录") from exc
            raise
        if len(body) > 1_000_000:
            raise ValueError("enrichment response is too large")
        payload = json.loads(body)
        response_value = payload.get("response") if isinstance(payload, dict) else None
        if isinstance(response_value, str):
            raise LookupError(response_value[:200])
        if not isinstance(response_value, dict):
            raise ValueError("invalid enrichment response")
        return response_value
