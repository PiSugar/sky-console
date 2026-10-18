from __future__ import annotations

import os
import sqlite3
import threading
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import IngestBatch


SCHEMA = """
CREATE TABLE IF NOT EXISTS receivers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    version TEXT,
    first_seen_ms INTEGER NOT NULL,
    last_seen_ms INTEGER NOT NULL,
    messages_received INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS aircraft (
    icao TEXT PRIMARY KEY,
    first_seen_ms INTEGER NOT NULL,
    last_seen_ms INTEGER NOT NULL,
    position_at_ms INTEGER,
    last_receiver_id TEXT,
    callsign TEXT,
    registration TEXT,
    aircraft_type TEXT,
    category TEXT,
    latitude REAL,
    longitude REAL,
    altitude_baro INTEGER,
    altitude_geom INTEGER,
    ground_speed REAL,
    track REAL,
    vertical_rate INTEGER,
    squawk TEXT,
    emergency TEXT,
    signal REAL,
    messages_received INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (last_receiver_id) REFERENCES receivers(id)
);

CREATE TABLE IF NOT EXISTS ingest_batches (
    batch_id TEXT PRIMARY KEY,
    receiver_id TEXT NOT NULL,
    emitted_at_ms INTEGER NOT NULL,
    received_at_ms INTEGER NOT NULL,
    message_count INTEGER NOT NULL,
    FOREIGN KEY (receiver_id) REFERENCES receivers(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    receiver_id TEXT NOT NULL,
    icao TEXT,
    received_at_ms INTEGER NOT NULL,
    raw TEXT NOT NULL,
    df INTEGER NOT NULL,
    type_code INTEGER,
    signal REAL,
    UNIQUE (batch_id, sequence),
    FOREIGN KEY (batch_id) REFERENCES ingest_batches(batch_id) ON DELETE CASCADE,
    FOREIGN KEY (receiver_id) REFERENCES receivers(id),
    FOREIGN KEY (icao) REFERENCES aircraft(icao)
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receiver_id TEXT NOT NULL,
    icao TEXT NOT NULL,
    observed_at_ms INTEGER NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    altitude_baro INTEGER,
    ground_speed REAL,
    track REAL,
    vertical_rate INTEGER,
    UNIQUE (receiver_id, icao, observed_at_ms),
    FOREIGN KEY (receiver_id) REFERENCES receivers(id),
    FOREIGN KEY (icao) REFERENCES aircraft(icao)
);

CREATE TABLE IF NOT EXISTS aircraft_metadata (
    icao TEXT PRIMARY KEY,
    registration TEXT,
    manufacturer TEXT,
    model TEXT,
    type_code TEXT,
    owner TEXT,
    owner_country TEXT,
    owner_flag_code TEXT,
    photo_url TEXT,
    photo_thumbnail_url TEXT,
    photo_link TEXT,
    photo_credit TEXT,
    photo_source TEXT,
    source TEXT NOT NULL,
    lookup_status TEXT NOT NULL,
    fetched_at_ms INTEGER NOT NULL,
    error TEXT,
    FOREIGN KEY (icao) REFERENCES aircraft(icao) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS flight_routes (
    callsign TEXT PRIMARY KEY,
    callsign_icao TEXT,
    callsign_iata TEXT,
    airline_name TEXT,
    airline_icao TEXT,
    airline_iata TEXT,
    airline_country TEXT,
    airline_callsign TEXT,
    origin_name TEXT,
    origin_iata TEXT,
    origin_icao TEXT,
    origin_city TEXT,
    origin_country TEXT,
    origin_latitude REAL,
    origin_longitude REAL,
    destination_name TEXT,
    destination_iata TEXT,
    destination_icao TEXT,
    destination_city TEXT,
    destination_country TEXT,
    destination_latitude REAL,
    destination_longitude REAL,
    source TEXT NOT NULL,
    lookup_status TEXT NOT NULL,
    fetched_at_ms INTEGER NOT NULL,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_aircraft_last_seen
ON aircraft(last_seen_ms DESC);

CREATE INDEX IF NOT EXISTS idx_messages_icao_time
ON messages(icao, received_at_ms DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_messages_received_at
ON messages(received_at_ms);

CREATE INDEX IF NOT EXISTS idx_positions_icao_time
ON positions(icao, observed_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_positions_observed_at
ON positions(observed_at_ms);

CREATE INDEX IF NOT EXISTS idx_batches_received_at
ON ingest_batches(received_at_ms);

CREATE INDEX IF NOT EXISTS idx_aircraft_metadata_fetched_at
ON aircraft_metadata(fetched_at_ms);

CREATE INDEX IF NOT EXISTS idx_flight_routes_fetched_at
ON flight_routes(fetched_at_ms);
"""


ENRICHMENT_COLUMNS = """
    am.registration AS metadata_registration,
    am.manufacturer AS aircraft_manufacturer,
    am.model AS aircraft_model,
    am.type_code AS metadata_type_code,
    am.owner AS registered_owner,
    am.owner_country AS registered_owner_country,
    am.owner_flag_code AS registered_owner_flag_code,
    am.photo_url AS aircraft_photo_url,
    am.photo_thumbnail_url AS aircraft_photo_thumbnail_url,
    am.photo_link AS aircraft_photo_link,
    am.photo_credit AS aircraft_photo_credit,
    am.photo_source AS aircraft_photo_source,
    am.source AS metadata_source,
    am.lookup_status AS metadata_status,
    am.fetched_at_ms AS metadata_fetched_at_ms,
    fr.callsign_icao AS route_callsign_icao,
    fr.callsign_iata AS route_callsign_iata,
    fr.airline_name,
    fr.airline_icao,
    fr.airline_iata,
    fr.airline_country,
    fr.airline_callsign,
    fr.origin_name,
    fr.origin_iata,
    fr.origin_icao,
    fr.origin_city,
    fr.origin_country,
    fr.origin_latitude,
    fr.origin_longitude,
    fr.destination_name,
    fr.destination_iata,
    fr.destination_icao,
    fr.destination_city,
    fr.destination_country,
    fr.destination_latitude,
    fr.destination_longitude,
    fr.source AS route_source,
    fr.lookup_status AS route_status,
    fr.fetched_at_ms AS route_fetched_at_ms
"""


ENRICHMENT_JOINS = """
    LEFT JOIN aircraft_metadata am ON am.icao = a.icao
    LEFT JOIN flight_routes fr ON fr.callsign = a.callsign
"""


def _aircraft_record(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["registration"] = item.get("registration") or item.get("metadata_registration")
    item["aircraft_type"] = (
        item.get("aircraft_type")
        or item.get("metadata_type_code")
        or item.get("aircraft_model")
    )
    return item


AIRCRAFT_UPSERT = """
INSERT INTO aircraft (
    icao, first_seen_ms, last_seen_ms, position_at_ms, last_receiver_id, callsign,
    registration, aircraft_type, category, latitude, longitude,
    altitude_baro, altitude_geom, ground_speed, track, vertical_rate,
    squawk, emergency, signal
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(icao) DO UPDATE SET
    first_seen_ms = MIN(aircraft.first_seen_ms, excluded.first_seen_ms),
    last_seen_ms = MAX(aircraft.last_seen_ms, excluded.last_seen_ms),
    position_at_ms = CASE
        WHEN excluded.latitude IS NOT NULL
         AND excluded.longitude IS NOT NULL
         AND excluded.position_at_ms >= COALESCE(aircraft.position_at_ms, -1)
        THEN excluded.position_at_ms ELSE aircraft.position_at_ms END,
    last_receiver_id = CASE WHEN excluded.last_seen_ms >= aircraft.last_seen_ms
        THEN excluded.last_receiver_id ELSE aircraft.last_receiver_id END,
    callsign = CASE WHEN excluded.last_seen_ms >= aircraft.last_seen_ms
        THEN COALESCE(excluded.callsign, aircraft.callsign) ELSE aircraft.callsign END,
    registration = COALESCE(excluded.registration, aircraft.registration),
    aircraft_type = COALESCE(excluded.aircraft_type, aircraft.aircraft_type),
    category = COALESCE(excluded.category, aircraft.category),
    latitude = CASE
        WHEN excluded.latitude IS NOT NULL
         AND excluded.longitude IS NOT NULL
         AND excluded.position_at_ms >= COALESCE(aircraft.position_at_ms, -1)
        THEN excluded.latitude ELSE aircraft.latitude END,
    longitude = CASE
        WHEN excluded.latitude IS NOT NULL
         AND excluded.longitude IS NOT NULL
         AND excluded.position_at_ms >= COALESCE(aircraft.position_at_ms, -1)
        THEN excluded.longitude ELSE aircraft.longitude END,
    altitude_baro = CASE WHEN excluded.last_seen_ms >= aircraft.last_seen_ms
        THEN COALESCE(excluded.altitude_baro, aircraft.altitude_baro) ELSE aircraft.altitude_baro END,
    altitude_geom = CASE WHEN excluded.last_seen_ms >= aircraft.last_seen_ms
        THEN COALESCE(excluded.altitude_geom, aircraft.altitude_geom) ELSE aircraft.altitude_geom END,
    ground_speed = CASE
        WHEN excluded.latitude IS NOT NULL
         AND excluded.longitude IS NOT NULL
         AND excluded.position_at_ms >= COALESCE(aircraft.position_at_ms, -1)
        THEN COALESCE(excluded.ground_speed, aircraft.ground_speed) ELSE aircraft.ground_speed END,
    track = CASE
        WHEN excluded.latitude IS NOT NULL
         AND excluded.longitude IS NOT NULL
         AND excluded.position_at_ms >= COALESCE(aircraft.position_at_ms, -1)
        THEN COALESCE(excluded.track, aircraft.track) ELSE aircraft.track END,
    vertical_rate = CASE
        WHEN excluded.latitude IS NOT NULL
         AND excluded.longitude IS NOT NULL
         AND excluded.position_at_ms >= COALESCE(aircraft.position_at_ms, -1)
        THEN COALESCE(excluded.vertical_rate, aircraft.vertical_rate) ELSE aircraft.vertical_rate END,
    squawk = CASE WHEN excluded.last_seen_ms >= aircraft.last_seen_ms
        THEN COALESCE(excluded.squawk, aircraft.squawk) ELSE aircraft.squawk END,
    emergency = CASE WHEN excluded.last_seen_ms >= aircraft.last_seen_ms
        THEN COALESCE(excluded.emergency, aircraft.emergency) ELSE aircraft.emergency END,
    signal = CASE WHEN excluded.last_seen_ms >= aircraft.last_seen_ms
        THEN COALESCE(excluded.signal, aircraft.signal) ELSE aircraft.signal END
"""


class Database:
    def __init__(
        self,
        path: str,
        retention_days: int | None = None,
        active_seconds: int = 90,
        retention_hours: int | None = None,
        store_raw_messages: bool = True,
        store_positions: bool = True,
        store_ingest_batches: bool = True,
    ) -> None:
        self.path = path
        if retention_hours is None:
            retention_hours = (retention_days or 90) * 24
        self.retention_hours = retention_hours
        self.retention_ms = retention_hours * 3_600_000
        self.active_seconds = active_seconds
        self.store_raw_messages = store_raw_messages
        self.store_positions = store_positions
        self.store_ingest_batches = store_ingest_batches
        self._cleanup_lock = threading.Lock()
        self._last_cleanup_ms = 0

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    @contextmanager
    def connection(self):
        connection = self.connect()
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(SCHEMA)
            aircraft_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(aircraft)")
            }
            if "position_at_ms" not in aircraft_columns:
                connection.execute("ALTER TABLE aircraft ADD COLUMN position_at_ms INTEGER")
            metadata_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(aircraft_metadata)")
            }
            for column in ("photo_link", "photo_credit", "photo_source"):
                if column not in metadata_columns:
                    connection.execute(
                        f"ALTER TABLE aircraft_metadata ADD COLUMN {column} TEXT"
                    )
            connection.execute("PRAGMA optimize")

    def health(self) -> dict[str, Any]:
        with self.connection() as connection:
            connection.execute("SELECT 1").fetchone()
        return {"status": "ok", "database": "ok"}

    def ingest(self, batch: IngestBatch) -> dict[str, Any]:
        received_at_ms = int(time.time() * 1000)
        receiver = batch.receiver
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO receivers (
                    id, name, latitude, longitude, version,
                    first_seen_ms, last_seen_ms, messages_received
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    latitude = COALESCE(excluded.latitude, receivers.latitude),
                    longitude = COALESCE(excluded.longitude, receivers.longitude),
                    version = COALESCE(excluded.version, receivers.version),
                    last_seen_ms = MAX(receivers.last_seen_ms, excluded.last_seen_ms)
                """,
                (
                    receiver.id,
                    receiver.name,
                    receiver.latitude,
                    receiver.longitude,
                    receiver.version,
                    received_at_ms,
                    received_at_ms,
                ),
            )
            if self.store_ingest_batches:
                try:
                    connection.execute(
                        """
                        INSERT INTO ingest_batches (
                            batch_id, receiver_id, emitted_at_ms,
                            received_at_ms, message_count
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            batch.batch_id,
                            receiver.id,
                            batch.emitted_at_ms,
                            received_at_ms,
                            len(batch.messages),
                        ),
                    )
                except sqlite3.IntegrityError:
                    connection.rollback()
                    return {"accepted": True, "duplicate": True, "messages": 0}

            for state in batch.aircraft:
                has_position = state.latitude is not None and state.longitude is not None
                position_at_ms = (
                    state.position_at_ms
                    if state.position_at_ms is not None
                    else state.observed_at_ms
                ) if has_position else None
                connection.execute(
                    AIRCRAFT_UPSERT,
                    (
                        state.icao,
                        state.observed_at_ms,
                        state.observed_at_ms,
                        position_at_ms,
                        receiver.id,
                        state.callsign,
                        state.registration,
                        state.aircraft_type,
                        state.category,
                        state.latitude,
                        state.longitude,
                        state.altitude_baro,
                        state.altitude_geom,
                        state.ground_speed,
                        state.track,
                        state.vertical_rate,
                        state.squawk,
                        state.emergency,
                        state.signal,
                    ),
                )
                if has_position and self.store_positions:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO positions (
                            receiver_id, icao, observed_at_ms, latitude, longitude,
                            altitude_baro, ground_speed, track, vertical_rate
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            receiver.id,
                            state.icao,
                            position_at_ms,
                            state.latitude,
                            state.longitude,
                            state.altitude_baro,
                            state.ground_speed,
                            state.track,
                            state.vertical_rate,
                        ),
                    )

            message_counts: Counter[str] = Counter()
            for sequence, message in enumerate(batch.messages):
                if message.icao:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO aircraft (
                            icao, first_seen_ms, last_seen_ms, last_receiver_id
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (message.icao, message.ts_ms, message.ts_ms, receiver.id),
                    )
                    connection.execute(
                        """
                        UPDATE aircraft
                        SET last_seen_ms = MAX(last_seen_ms, ?),
                            last_receiver_id = CASE WHEN ? >= last_seen_ms THEN ? ELSE last_receiver_id END
                        WHERE icao = ?
                        """,
                        (message.ts_ms, message.ts_ms, receiver.id, message.icao),
                    )
                    message_counts[message.icao] += 1
                if self.store_raw_messages and self.store_ingest_batches:
                    connection.execute(
                        """
                        INSERT INTO messages (
                            batch_id, sequence, receiver_id, icao,
                            received_at_ms, raw, df, type_code, signal
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            batch.batch_id,
                            sequence,
                            receiver.id,
                            message.icao,
                            message.ts_ms,
                            message.raw,
                            message.df,
                            message.type_code,
                            message.signal,
                        ),
                    )

            for icao, count in message_counts.items():
                connection.execute(
                    "UPDATE aircraft SET messages_received = messages_received + ? WHERE icao = ?",
                    (count, icao),
                )
            connection.execute(
                """
                UPDATE receivers
                SET messages_received = messages_received + ?
                WHERE id = ?
                """,
                (len(batch.messages), receiver.id),
            )
            connection.commit()

        self.cleanup_if_due(received_at_ms)
        return {
            "accepted": True,
            "duplicate": False,
            "messages": len(batch.messages),
            "aircraft": len(batch.aircraft),
        }

    def latest_state(self) -> dict[str, Any]:
        with self.connection() as connection:
            aircraft = connection.execute(
                """
                SELECT a.*, r.name AS receiver_name
                FROM aircraft a
                LEFT JOIN receivers r ON r.id = a.last_receiver_id
                ORDER BY a.last_seen_ms DESC
                """
            ).fetchall()
            receivers = connection.execute(
                """
                SELECT id, name, latitude, longitude, version, first_seen_ms,
                       last_seen_ms, messages_received
                FROM receivers
                ORDER BY last_seen_ms DESC
                """
            ).fetchall()
        return {
            "aircraft": [dict(row) for row in aircraft],
            "receivers": [dict(row) for row in receivers],
        }

    def cleanup_if_due(self, now_ms: int | None = None) -> None:
        now_ms = now_ms or int(time.time() * 1000)
        if now_ms - self._last_cleanup_ms < 3_600_000:
            return
        if not self._cleanup_lock.acquire(blocking=False):
            return
        try:
            if now_ms - self._last_cleanup_ms < 3_600_000:
                return
            cutoff = now_ms - self.retention_ms
            batch_cutoff = now_ms - self.retention_ms - 3_600_000
            with self.connection() as connection:
                connection.execute("DELETE FROM messages WHERE received_at_ms < ?", (cutoff,))
                connection.execute("DELETE FROM positions WHERE observed_at_ms < ?", (cutoff,))
                connection.execute(
                    "DELETE FROM ingest_batches WHERE received_at_ms < ?", (batch_cutoff,)
                )
                connection.execute("DELETE FROM aircraft WHERE last_seen_ms < ?", (cutoff,))
                connection.execute("PRAGMA optimize")
            self._last_cleanup_ms = now_ms
        finally:
            self._cleanup_lock.release()

    def stats(self) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        active_cutoff = now_ms - self.active_seconds * 1000
        day_cutoff = now_ms - 86_400_000
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM aircraft WHERE last_seen_ms >= ?) AS active_aircraft,
                    (SELECT COUNT(*) FROM aircraft) AS total_aircraft,
                    (SELECT COUNT(*) FROM messages WHERE received_at_ms >= ?) AS messages_24h,
                    (SELECT COUNT(*) FROM messages) AS stored_messages,
                    (SELECT COUNT(*) FROM receivers WHERE last_seen_ms >= ?) AS online_receivers,
                    (SELECT COUNT(*) FROM receivers) AS total_receivers
                """,
                (active_cutoff, day_cutoff, active_cutoff),
            ).fetchone()
        return {"server_now_ms": now_ms, **dict(row)}

    def live_aircraft(self) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        cutoff = now_ms - self.active_seconds * 1000
        with self.connection() as connection:
            aircraft = connection.execute(
                f"""
                SELECT a.*, r.name AS receiver_name,
                       {ENRICHMENT_COLUMNS}
                FROM aircraft a
                LEFT JOIN receivers r ON r.id = a.last_receiver_id
                {ENRICHMENT_JOINS}
                WHERE a.last_seen_ms >= ?
                ORDER BY a.last_seen_ms DESC
                """,
                (cutoff,),
            ).fetchall()
            receivers = connection.execute(
                """
                SELECT id, name, latitude, longitude, version, first_seen_ms,
                       last_seen_ms, messages_received
                FROM receivers
                ORDER BY last_seen_ms DESC
                """
            ).fetchall()
        return {
            "server_now_ms": now_ms,
            "active_seconds": self.active_seconds,
            "aircraft": [_aircraft_record(row) for row in aircraft],
            "receivers": [dict(row) for row in receivers],
        }

    def list_aircraft(self, search: str, page: int, page_size: int) -> dict[str, Any]:
        search_pattern = f"%{search.strip().upper()}%"
        where = "" if not search.strip() else """
            WHERE a.icao LIKE ?
               OR a.callsign LIKE ?
               OR COALESCE(a.registration, am.registration) LIKE ?
               OR am.manufacturer LIKE ?
               OR am.model LIKE ?
               OR am.owner LIKE ?
               OR fr.airline_name LIKE ?
        """
        params: list[Any] = []
        if where:
            params.extend([search_pattern] * 7)
        with self.connection() as connection:
            total = connection.execute(
                f"""
                SELECT COUNT(DISTINCT a.icao)
                FROM aircraft a
                {ENRICHMENT_JOINS}
                {where}
                """,
                params,
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT a.icao, a.callsign, a.registration, a.aircraft_type, a.category,
                       a.first_seen_ms, a.last_seen_ms, a.latitude, a.longitude,
                       a.altitude_baro, a.ground_speed, a.track, a.messages_received,
                       a.last_receiver_id,
                       {ENRICHMENT_COLUMNS}
                FROM aircraft a
                {ENRICHMENT_JOINS}
                {where}
                ORDER BY a.last_seen_ms DESC
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "items": [_aircraft_record(row) for row in rows],
        }

    def aircraft_detail(self, icao: str, hours: int, max_points: int = 2000) -> dict[str, Any] | None:
        cutoff = int(time.time() * 1000) - hours * 3_600_000
        with self.connection() as connection:
            aircraft = connection.execute(
                f"""
                SELECT a.*, r.name AS receiver_name,
                       (SELECT COUNT(*) FROM messages m WHERE m.icao = a.icao) AS stored_messages,
                       {ENRICHMENT_COLUMNS}
                FROM aircraft a
                LEFT JOIN receivers r ON r.id = a.last_receiver_id
                {ENRICHMENT_JOINS}
                WHERE a.icao = ?
                """,
                (icao,),
            ).fetchone()
            if aircraft is None:
                return None
            positions_desc = connection.execute(
                """
                SELECT observed_at_ms, latitude, longitude, altitude_baro,
                       ground_speed, track, vertical_rate, receiver_id
                FROM positions
                WHERE icao = ? AND observed_at_ms >= ?
                ORDER BY observed_at_ms DESC
                LIMIT ?
                """,
                (icao, cutoff, max_points),
            ).fetchall()
        return {
            "aircraft": _aircraft_record(aircraft),
            "hours": hours,
            "positions": [dict(row) for row in reversed(positions_desc)],
        }

    def aircraft_messages(self, icao: str, cursor: int | None, limit: int) -> dict[str, Any]:
        cursor_clause = "" if cursor is None else "AND id < ?"
        params: list[Any] = [icao]
        if cursor is not None:
            params.append(cursor)
        params.append(limit + 1)
        with self.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT id, receiver_id, received_at_ms, raw, df, type_code, signal
                FROM messages
                WHERE icao = ? {cursor_clause}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        return {
            "items": [dict(row) for row in rows],
            "next_cursor": rows[-1]["id"] if has_more and rows else None,
        }

    def aircraft_enrichment(self, icao: str, callsign: str | None) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                f"""
                WITH a(icao, callsign) AS (VALUES (?, ?))
                SELECT {ENRICHMENT_COLUMNS}
                FROM a
                {ENRICHMENT_JOINS}
                """,
                (icao, callsign),
            ).fetchone()
        if row is None:
            return {}
        item = dict(row)
        item["registration"] = item.get("metadata_registration")
        item["aircraft_type"] = item.get("metadata_type_code") or item.get("aircraft_model")
        return item

    def aircraft_enrichments(
        self, contacts: list[tuple[str, str | None]]
    ) -> dict[str, dict[str, Any]]:
        if not contacts:
            return {}
        limited_contacts = contacts[:1000]
        placeholders = ",".join(["(?, ?)"] * len(limited_contacts))
        params: list[Any] = []
        for icao, callsign in limited_contacts:
            params.extend([icao, callsign])
        with self.connection() as connection:
            rows = connection.execute(
                f"""
                WITH a(icao, callsign) AS (VALUES {placeholders})
                SELECT a.icao AS live_icao, {ENRICHMENT_COLUMNS}
                FROM a
                {ENRICHMENT_JOINS}
                """,
                params,
            ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            live_icao = item.pop("live_icao")
            item["registration"] = item.get("metadata_registration")
            item["aircraft_type"] = item.get("metadata_type_code") or item.get("aircraft_model")
            result[live_icao] = item
        return result

    def enrichment_candidates(self, limit: int = 200) -> list[tuple[str, str | None]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT icao, callsign
                FROM aircraft
                ORDER BY last_seen_ms DESC
                LIMIT ?
                """,
                (max(1, min(limit, 1000)),),
            ).fetchall()
        return [(row["icao"], row["callsign"]) for row in rows]

    def aircraft_metadata_due(
        self, icao: str, success_ttl_ms: int, retry_ttl_ms: int
    ) -> bool:
        with self.connection() as connection:
            photo_state = connection.execute(
                "SELECT photo_source FROM aircraft_metadata WHERE icao = ?",
                (icao,),
            ).fetchone()
        if photo_state is not None and photo_state["photo_source"] is None:
            return True
        return self._enrichment_due(
            "aircraft_metadata", "icao", icao, success_ttl_ms, retry_ttl_ms
        )

    def flight_route_due(
        self, callsign: str, success_ttl_ms: int, retry_ttl_ms: int
    ) -> bool:
        return self._enrichment_due(
            "flight_routes", "callsign", callsign, success_ttl_ms, retry_ttl_ms
        )

    def _enrichment_due(
        self,
        table: str,
        key_column: str,
        key: str,
        success_ttl_ms: int,
        retry_ttl_ms: int,
    ) -> bool:
        allowed = {
            ("aircraft_metadata", "icao"),
            ("flight_routes", "callsign"),
        }
        if (table, key_column) not in allowed:
            raise ValueError("unsupported enrichment cache")
        with self.connection() as connection:
            row = connection.execute(
                f"SELECT lookup_status, fetched_at_ms FROM {table} WHERE {key_column} = ?",
                (key,),
            ).fetchone()
        if row is None:
            return True
        ttl_ms = success_ttl_ms if row["lookup_status"] == "ok" else retry_ttl_ms
        return int(time.time() * 1000) - row["fetched_at_ms"] >= ttl_ms

    def save_aircraft_metadata(
        self,
        icao: str,
        values: dict[str, Any],
        status: str,
        error: str | None = None,
    ) -> None:
        payload = {
            "icao": icao,
            "registration": values.get("registration"),
            "manufacturer": values.get("manufacturer"),
            "model": values.get("model"),
            "type_code": values.get("type_code"),
            "owner": values.get("owner"),
            "owner_country": values.get("owner_country"),
            "owner_flag_code": values.get("owner_flag_code"),
            "photo_url": values.get("photo_url"),
            "photo_thumbnail_url": values.get("photo_thumbnail_url"),
            "photo_link": values.get("photo_link"),
            "photo_credit": values.get("photo_credit"),
            "photo_source": values.get("photo_source"),
            "source": "ADSBDB",
            "lookup_status": status,
            "fetched_at_ms": int(time.time() * 1000),
            "error": error,
        }
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO aircraft_metadata (
                    icao, registration, manufacturer, model, type_code, owner,
                    owner_country, owner_flag_code, photo_url, photo_thumbnail_url,
                    photo_link, photo_credit, photo_source,
                    source, lookup_status, fetched_at_ms, error
                ) VALUES (
                    :icao, :registration, :manufacturer, :model, :type_code, :owner,
                    :owner_country, :owner_flag_code, :photo_url, :photo_thumbnail_url,
                    :photo_link, :photo_credit, :photo_source,
                    :source, :lookup_status, :fetched_at_ms, :error
                )
                ON CONFLICT(icao) DO UPDATE SET
                    registration = excluded.registration,
                    manufacturer = excluded.manufacturer,
                    model = excluded.model,
                    type_code = excluded.type_code,
                    owner = excluded.owner,
                    owner_country = excluded.owner_country,
                    owner_flag_code = excluded.owner_flag_code,
                    photo_url = excluded.photo_url,
                    photo_thumbnail_url = excluded.photo_thumbnail_url,
                    photo_link = excluded.photo_link,
                    photo_credit = excluded.photo_credit,
                    photo_source = excluded.photo_source,
                    source = excluded.source,
                    lookup_status = excluded.lookup_status,
                    fetched_at_ms = excluded.fetched_at_ms,
                    error = excluded.error
                """,
                payload,
            )

    def save_flight_route(
        self,
        callsign: str,
        values: dict[str, Any],
        status: str,
        error: str | None = None,
    ) -> None:
        payload = {
            "callsign": callsign,
            "callsign_icao": values.get("callsign_icao"),
            "callsign_iata": values.get("callsign_iata"),
            "airline_name": values.get("airline_name"),
            "airline_icao": values.get("airline_icao"),
            "airline_iata": values.get("airline_iata"),
            "airline_country": values.get("airline_country"),
            "airline_callsign": values.get("airline_callsign"),
            "origin_name": values.get("origin_name"),
            "origin_iata": values.get("origin_iata"),
            "origin_icao": values.get("origin_icao"),
            "origin_city": values.get("origin_city"),
            "origin_country": values.get("origin_country"),
            "origin_latitude": values.get("origin_latitude"),
            "origin_longitude": values.get("origin_longitude"),
            "destination_name": values.get("destination_name"),
            "destination_iata": values.get("destination_iata"),
            "destination_icao": values.get("destination_icao"),
            "destination_city": values.get("destination_city"),
            "destination_country": values.get("destination_country"),
            "destination_latitude": values.get("destination_latitude"),
            "destination_longitude": values.get("destination_longitude"),
            "source": "ADSBDB",
            "lookup_status": status,
            "fetched_at_ms": int(time.time() * 1000),
            "error": error,
        }
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO flight_routes (
                    callsign, callsign_icao, callsign_iata,
                    airline_name, airline_icao, airline_iata,
                    airline_country, airline_callsign,
                    origin_name, origin_iata, origin_icao, origin_city,
                    origin_country, origin_latitude, origin_longitude,
                    destination_name, destination_iata, destination_icao,
                    destination_city, destination_country,
                    destination_latitude, destination_longitude,
                    source, lookup_status, fetched_at_ms, error
                ) VALUES (
                    :callsign, :callsign_icao, :callsign_iata,
                    :airline_name, :airline_icao, :airline_iata,
                    :airline_country, :airline_callsign,
                    :origin_name, :origin_iata, :origin_icao, :origin_city,
                    :origin_country, :origin_latitude, :origin_longitude,
                    :destination_name, :destination_iata, :destination_icao,
                    :destination_city, :destination_country,
                    :destination_latitude, :destination_longitude,
                    :source, :lookup_status, :fetched_at_ms, :error
                )
                ON CONFLICT(callsign) DO UPDATE SET
                    callsign_icao = excluded.callsign_icao,
                    callsign_iata = excluded.callsign_iata,
                    airline_name = excluded.airline_name,
                    airline_icao = excluded.airline_icao,
                    airline_iata = excluded.airline_iata,
                    airline_country = excluded.airline_country,
                    airline_callsign = excluded.airline_callsign,
                    origin_name = excluded.origin_name,
                    origin_iata = excluded.origin_iata,
                    origin_icao = excluded.origin_icao,
                    origin_city = excluded.origin_city,
                    origin_country = excluded.origin_country,
                    origin_latitude = excluded.origin_latitude,
                    origin_longitude = excluded.origin_longitude,
                    destination_name = excluded.destination_name,
                    destination_iata = excluded.destination_iata,
                    destination_icao = excluded.destination_icao,
                    destination_city = excluded.destination_city,
                    destination_country = excluded.destination_country,
                    destination_latitude = excluded.destination_latitude,
                    destination_longitude = excluded.destination_longitude,
                    source = excluded.source,
                    lookup_status = excluded.lookup_status,
                    fetched_at_ms = excluded.fetched_at_ms,
                    error = excluded.error
                """,
                payload,
            )

    def receivers(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT id, name, latitude, longitude, version, first_seen_ms,
                       last_seen_ms, messages_received
                FROM receivers
                ORDER BY last_seen_ms DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]
