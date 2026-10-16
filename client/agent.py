from __future__ import annotations

import json
import logging
import os
import re
import signal
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VERSION = "1.1.0"
FRAME_RE = re.compile(r"([0-9A-Fa-f]{28}|[0-9A-Fa-f]{14});?$")
MODE_S_POLYNOMIAL = 0x1FFF409


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("adsb-agent")


def env_float(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else None


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} 必须是整数") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} 必须在 {minimum} 到 {maximum} 之间")
    return value


@dataclass(frozen=True, slots=True)
class Config:
    server_url: str
    api_key: str
    receiver_id: str
    receiver_name: str
    receiver_lat: float | None
    receiver_lon: float | None
    upload_interval: int
    active_window: int
    max_batch_messages: int
    max_spool_batches: int
    send_raw_messages: bool
    status_interval: int
    state_path: str
    raw_host: str
    raw_port: int
    spool_path: str

    @classmethod
    def from_env(cls) -> "Config":
        server_url = os.getenv("SERVER_URL", "").rstrip("/")
        api_key = os.getenv("API_KEY", "")
        if not server_url.startswith(("http://", "https://")):
            raise RuntimeError("SERVER_URL 必须以 http:// 或 https:// 开头")
        if len(api_key) < 16:
            raise RuntimeError("API_KEY 长度不能少于 16 个字符")
        receiver_id = os.getenv("RECEIVER_ID", "devpn")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", receiver_id):
            raise RuntimeError("RECEIVER_ID 只能包含字母、数字、点、横线和下划线")
        return cls(
            server_url=server_url,
            api_key=api_key,
            receiver_id=receiver_id,
            receiver_name=os.getenv("RECEIVER_NAME", "DEVPN ADS-B").strip() or "DEVPN ADS-B",
            receiver_lat=env_float("RECEIVER_LAT"),
            receiver_lon=env_float("RECEIVER_LON"),
            upload_interval=env_int("UPLOAD_INTERVAL", 1, 1, 60),
            active_window=env_int("ACTIVE_WINDOW", 120, 10, 600),
            max_batch_messages=env_int("MAX_BATCH_MESSAGES", 2000, 100, 5000),
            max_spool_batches=env_int("MAX_SPOOL_BATCHES", 20, 1, 100000),
            send_raw_messages=os.getenv("SEND_RAW_MESSAGES", "false").strip().lower() in {"1", "true", "yes", "on"},
            status_interval=env_int("STATUS_INTERVAL", 60, 10, 600),
            state_path=os.getenv("STATE_PATH", "/run/readsb/aircraft.json"),
            raw_host=os.getenv("RAW_HOST", "127.0.0.1"),
            raw_port=env_int("RAW_PORT", 30002, 1, 65535),
            spool_path=os.getenv("SPOOL_PATH", "/data/spool.sqlite3"),
        )


def mode_s_syndrome(raw: str) -> int:
    value = int(raw, 16)
    total_bits = len(raw) * 4
    for bit in range(total_bits - 1, 23, -1):
        if value & (1 << bit):
            value ^= MODE_S_POLYNOMIAL << (bit - 24)
    return value & 0xFFFFFF


def extract_icao(raw: str, df: int) -> str | None:
    if df in (11, 17, 18):
        return raw[2:8].upper()
    if df in (0, 4, 5, 16, 20, 21, 24):
        address = mode_s_syndrome(raw)
        return f"{address:06X}" if address else None
    return None


def parse_frame(line: str, timestamp_ms: int | None = None) -> dict[str, Any] | None:
    match = FRAME_RE.search(line.strip())
    if not match:
        return None
    raw = match.group(1).upper()
    df = int(raw[:2], 16) >> 3
    type_code = (int(raw[8:10], 16) >> 3) if df in (17, 18) and len(raw) == 28 else None
    return {
        "ts_ms": timestamp_ms or int(time.time() * 1000),
        "raw": raw,
        "icao": extract_icao(raw, df),
        "df": df,
        "type_code": type_code,
        "signal": None,
    }


class Spool:
    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS batches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id TEXT NOT NULL UNIQUE,
                    payload BLOB NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_ms INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_batches_due ON batches(next_attempt_ms, id)"
            )

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
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

    def enqueue(self, batch_id: str, payload: bytes) -> None:
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO batches (batch_id, payload, created_at_ms) VALUES (?, ?, ?)",
                (batch_id, payload, int(time.time() * 1000)),
            )

    def oldest_due(self) -> sqlite3.Row | None:
        with self.connection() as connection:
            return connection.execute(
                "SELECT * FROM batches WHERE next_attempt_ms <= ? ORDER BY id LIMIT 1",
                (int(time.time() * 1000),),
            ).fetchone()

    def delete(self, row_id: int) -> None:
        with self.connection() as connection:
            connection.execute("DELETE FROM batches WHERE id = ?", (row_id,))

    def retry_later(self, row_id: int, attempts: int) -> None:
        delay_seconds = min(300, max(2, 2 ** min(attempts, 8)))
        with self.connection() as connection:
            connection.execute(
                "UPDATE batches SET attempts = ?, next_attempt_ms = ? WHERE id = ?",
                (attempts, int(time.time() * 1000) + delay_seconds * 1000, row_id),
            )

    def count(self) -> int:
        with self.connection() as connection:
            return connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0]

    def trim(self, maximum: int) -> int:
        count = self.count()
        excess = count - maximum
        if excess <= 0:
            return 0
        with self.connection() as connection:
            connection.execute(
                "DELETE FROM batches WHERE id IN (SELECT id FROM batches ORDER BY id LIMIT ?)",
                (excess,),
            )
        return excess


class Agent:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.spool = Spool(config.spool_path)
        self.stop_event = threading.Event()
        self.messages: deque[dict[str, Any]] = deque()
        self.messages_lock = threading.Lock()
        self.raw_connected = False
        self.raw_lines = 0
        self.parsed_messages = 0
        self.sent_batches = 0
        self.sent_bytes = 0
        self.last_status_log = 0.0

    def stop(self, *_: Any) -> None:
        self.stop_event.set()

    def read_raw_messages(self) -> None:
        while not self.stop_event.is_set():
            try:
                with socket.create_connection(
                    (self.config.raw_host, self.config.raw_port), timeout=10
                ) as sock:
                    sock.settimeout(30)
                    self.raw_connected = True
                    logger.info("已连接 readsb 原始报文端口")
                    buffer = b""
                    while not self.stop_event.is_set():
                        chunk = sock.recv(65536)
                        if not chunk:
                            raise ConnectionError("readsb closed the raw output connection")
                        buffer += chunk
                        while b"\n" in buffer:
                            raw_line, buffer = buffer.split(b"\n", 1)
                            self.raw_lines += 1
                            message = parse_frame(raw_line.decode("ascii", errors="ignore"))
                            if message:
                                self.parsed_messages += 1
                                with self.messages_lock:
                                    self.messages.append(message)
                                    if len(self.messages) > self.config.max_batch_messages * 10:
                                        self.messages.popleft()
                                        logger.warning("内存报文队列已满，丢弃一条最旧报文")
                        if len(buffer) > 1_000_000:
                            logger.warning("readsb 输入缓冲区异常，已重置")
                            buffer = b""
            except (OSError, TimeoutError, ConnectionError) as exc:
                if self.raw_connected:
                    logger.warning("readsb 连接中断：%s", exc)
                self.raw_connected = False
                self.stop_event.wait(2)

    def drain_messages(self) -> list[dict[str, Any]]:
        drained: list[dict[str, Any]] = []
        with self.messages_lock:
            while self.messages and len(drained) < self.config.max_batch_messages:
                drained.append(self.messages.popleft())
        return drained

    def read_aircraft(self) -> list[dict[str, Any]]:
        try:
            with open(self.config.state_path, encoding="utf-8") as source:
                data = json.load(source)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []
        now_seconds = float(data.get("now", time.time()))
        result: list[dict[str, Any]] = []
        for item in data.get("aircraft", []):
            icao = str(item.get("hex", "")).upper().lstrip("~")
            seen = float(item.get("seen", 9999))
            if not re.fullmatch(r"[0-9A-F]{6}", icao) or seen > self.config.active_window:
                continue
            state = {
                "icao": icao,
                "observed_at_ms": max(0, int((now_seconds - seen) * 1000)),
                "callsign": str(item.get("flight", "")).strip() or None,
                "registration": item.get("r"),
                "aircraft_type": item.get("t") or item.get("desc"),
                "category": item.get("category"),
                "latitude": item.get("lat"),
                "longitude": item.get("lon"),
                "altitude_baro": item.get("alt_baro"),
                "altitude_geom": item.get("alt_geom"),
                "ground_speed": item.get("gs"),
                "track": item.get("track"),
                "vertical_rate": item.get("baro_rate", item.get("geom_rate")),
                "squawk": item.get("squawk"),
                "emergency": item.get("emergency"),
                "signal": item.get("rssi"),
                "messages": item.get("messages"),
            }
            if state["latitude"] is not None and state["longitude"] is not None:
                # `seen` is the age of any message from this aircraft. readsb's
                # `seen_pos` is the age of the latitude/longitude fix itself.
                # Keeping them separate prevents an old fix from looking new
                # when a non-position Mode S message arrives later.
                try:
                    seen_pos = float(item.get("seen_pos", seen))
                except (TypeError, ValueError):
                    seen_pos = seen
                state["position_at_ms"] = max(0, int((now_seconds - seen_pos) * 1000))
            result.append({key: value for key, value in state.items() if value is not None})
        return result

    def make_batch(self) -> tuple[str, bytes] | None:
        messages = self.drain_messages() if self.config.send_raw_messages else []
        aircraft = self.read_aircraft()
        if not messages and not aircraft:
            return None
        signal_by_icao = {item["icao"]: item.get("signal") for item in aircraft}
        for message in messages:
            if message["icao"] in signal_by_icao:
                message["signal"] = signal_by_icao[message["icao"]]
        batch_id = f"{self.config.receiver_id}:{uuid.uuid4().hex}"
        payload = {
            "batch_id": batch_id,
            "emitted_at_ms": int(time.time() * 1000),
            "receiver": {
                "id": self.config.receiver_id,
                "name": self.config.receiver_name,
                "latitude": self.config.receiver_lat,
                "longitude": self.config.receiver_lon,
                "version": VERSION,
            },
            "aircraft": aircraft,
            "messages": messages,
        }
        return batch_id, json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()

    def send(self, payload: bytes) -> None:
        request = urllib.request.Request(
            f"{self.config.server_url}/api/v1/ingest",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "User-Agent": f"SkyTrace-Agent/{VERSION}",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status != 200:
                raise RuntimeError(f"server returned HTTP {response.status}")

    def flush_spool(self) -> int:
        sent = 0
        for _ in range(10):
            row = self.spool.oldest_due()
            if row is None:
                break
            try:
                self.send(row["payload"])
            except (urllib.error.URLError, urllib.error.HTTPError, OSError, RuntimeError) as exc:
                attempts = int(row["attempts"]) + 1
                self.spool.retry_later(row["id"], attempts)
                logger.warning("上报失败，将自动重试：%s", exc)
                break
            self.spool.delete(row["id"])
            sent += 1
            self.sent_batches += 1
            self.sent_bytes += len(row["payload"])
        return sent

    def run(self) -> None:
        if self.config.send_raw_messages:
            reader = threading.Thread(target=self.read_raw_messages, name="raw-reader", daemon=True)
            reader.start()
        logger.info("SkyTrace 客户端 %s 已启动，接收站 %s", VERSION, self.config.receiver_id)
        while not self.stop_event.is_set():
            batch = self.make_batch()
            if batch:
                self.spool.enqueue(*batch)
            trimmed = self.spool.trim(self.config.max_spool_batches)
            if trimmed:
                logger.error("离线队列达到上限，已移除 %d 个最旧批次", trimmed)
            sent = self.flush_spool()
            Path("/tmp/adsb-agent-health").touch()
            now = time.monotonic()
            if now - self.last_status_log >= self.config.status_interval:
                logger.info(
                    "状态：readsb=%s，原始行=%d，已解析=%d，内存队列=%d，离线批次=%d，本轮已发送=%d，累计已发=%d/%dB",
                    "在线" if self.raw_connected else ("关闭原始报文" if not self.config.send_raw_messages else "等待连接"),
                    self.raw_lines,
                    self.parsed_messages,
                    len(self.messages),
                    self.spool.count(),
                    sent,
                    self.sent_batches,
                    self.sent_bytes,
                )
                self.last_status_log = now
            self.stop_event.wait(self.config.upload_interval)
        final_batch = self.make_batch()
        if final_batch:
            self.spool.enqueue(*final_batch)
        self.flush_spool()
        logger.info("客户端已安全停止")


def main() -> None:
    config = Config.from_env()
    agent = Agent(config)
    signal.signal(signal.SIGTERM, agent.stop)
    signal.signal(signal.SIGINT, agent.stop)
    agent.run()


if __name__ == "__main__":
    main()
