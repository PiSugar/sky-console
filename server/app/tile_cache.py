"""Bounded, persistent cache for tiles requested by the visible maps."""
from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)
DEFAULT_TTL = 7 * 86400
MAX_TILE_BYTES = 2 * 1024 * 1024


@dataclass
class Tile:
    body: bytes
    content_type: str
    expires: float
    etag: str = ""
    modified: str = ""
    cache_control: str = ""

    def browser_cache_control(self) -> str:
        if any(token in self.cache_control.lower() for token in ("no-store", "private")):
            return "no-store"
        return f"public, max-age={max(0, int(self.expires - time.time()))}, must-revalidate"


class TileCache:
    def __init__(self, path: str, max_bytes: int, public_base_url: str):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.public_base_url = public_base_url
        self._ready = False
        self._db_lock = threading.Lock()
        # Bounded locks coalesce concurrent requests without an ever-growing key map.
        self._tile_locks = [threading.Lock() for _ in range(64)]
        self._downloads = threading.BoundedSemaphore(8)

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        if not self._ready:
            connection.execute("""CREATE TABLE IF NOT EXISTS tiles (
                key TEXT PRIMARY KEY, body BLOB NOT NULL, content_type TEXT NOT NULL,
                expires REAL NOT NULL, etag TEXT NOT NULL, modified TEXT NOT NULL,
                cache_control TEXT NOT NULL, accessed REAL NOT NULL)""")
            connection.execute("CREATE INDEX IF NOT EXISTS tiles_accessed ON tiles(accessed)")
            connection.commit()
            self._ready = True
        return connection

    def _read(self, key: str) -> Tile | None:
        try:
            with self._db_lock, closing(self._connect()) as connection, connection:
                row = connection.execute("SELECT * FROM tiles WHERE key = ?", (key,)).fetchone()
                if row is None:
                    return None
                connection.execute("UPDATE tiles SET accessed = ? WHERE key = ?", (time.time(), key))
                return Tile(**{name: row[name] for name in Tile.__dataclass_fields__})
        except (OSError, sqlite3.Error):
            logger.warning("Map tile cache read unavailable", exc_info=True)
            return None

    def _write(self, key: str, tile: Tile) -> None:
        try:
            with self._db_lock, closing(self._connect()) as connection, connection:
                connection.execute("DELETE FROM tiles WHERE key = ?", (key,))
                if len(tile.body) > self.max_bytes or any(
                    token in tile.cache_control.lower() for token in ("no-store", "private")
                ):
                    return
                total = connection.execute("SELECT COALESCE(SUM(LENGTH(body)), 0) FROM tiles").fetchone()[0]
                while total + len(tile.body) > self.max_bytes:
                    oldest = connection.execute(
                        "SELECT key, LENGTH(body) FROM tiles ORDER BY accessed LIMIT 1"
                    ).fetchone()
                    connection.execute("DELETE FROM tiles WHERE key = ?", (oldest[0],))
                    total -= oldest[1]
                connection.execute(
                    "INSERT INTO tiles VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (key, tile.body, tile.content_type, tile.expires, tile.etag,
                     tile.modified, tile.cache_control, time.time()),
                )
        except (OSError, sqlite3.Error):
            # A full/unwritable disk must not prevent displaying a downloaded tile.
            logger.warning("Map tile cache write unavailable", exc_info=True)

    @staticmethod
    def tile_url(source: str, z: int, x: int, y: int) -> str:
        maximum = {"esri": 18, "international": 19}.get(source)
        if maximum is None or not 0 <= z <= maximum or not (0 <= x < 2**z and 0 <= y < 2**z):
            raise ValueError("invalid map tile")
        if source == "international":
            return f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        return ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map"
                f"/MapServer/tile/{z}/{y}/{x}")

    @staticmethod
    def _metadata(headers, previous: Tile | None = None) -> dict:
        now = time.time()
        control = headers.get("Cache-Control", previous.cache_control if previous else "")
        max_age = re.search(r'(?:^|,)\s*max-age\s*=\s*"?(\d+)', control, re.I)
        ttl = DEFAULT_TTL
        if max_age:
            ttl = int(max_age.group(1))
        elif headers.get("Expires"):
            try:
                ttl = max(0, parsedate_to_datetime(headers["Expires"]).timestamp() - now)
            except (ValueError, TypeError, OverflowError):
                pass
        try:
            age = max(0, int(headers.get("Age", "0")))
        except ValueError:
            age = 0
        if any(token in control.lower() for token in ("no-cache", "no-store", "private")):
            ttl = 0
        return dict(
            expires=now + max(0, ttl - age), cache_control=control,
            etag=headers.get("ETag", previous.etag if previous else ""),
            modified=headers.get("Last-Modified", previous.modified if previous else ""),
        )

    def get(self, source: str, z: int, x: int, y: int, referer: str = "") -> Tile:
        url = self.tile_url(source, z, x, y)
        key = f"v1/{source}/{z}/{x}/{y}"
        with self._tile_locks[hash(key) % len(self._tile_locks)]:
            cached = self._read(key)
            if cached and cached.expires > time.time():
                return cached
            headers = {
                "User-Agent": f"SkyTrace-ADS-B/1.5 (+{self.public_base_url})",
                "Referer": referer or self.public_base_url + "/",
                "Accept": "image/png,image/jpeg,image/webp",
            }
            if cached:
                if cached.etag:
                    headers["If-None-Match"] = cached.etag
                if cached.modified:
                    headers["If-Modified-Since"] = cached.modified
            with self._downloads:
                try:
                    with urlopen(Request(url, headers=headers), timeout=8) as response:
                        content_type = response.headers.get_content_type()
                        body = response.read(MAX_TILE_BYTES + 1)
                        valid_image = (
                            (content_type == "image/png" and body.startswith(b"\x89PNG\r\n\x1a\n"))
                            or (content_type == "image/jpeg" and body.startswith(b"\xff\xd8\xff"))
                            or (content_type == "image/webp" and body.startswith(b"RIFF") and body[8:12] == b"WEBP")
                        )
                        if response.status != 200 or not valid_image or len(body) > MAX_TILE_BYTES:
                            raise OSError("invalid map tile response")
                        tile = Tile(body, content_type, **self._metadata(response.headers))
                except HTTPError as error:
                    try:
                        if error.code != 304 or cached is None:
                            raise
                        tile = Tile(cached.body, cached.content_type, **self._metadata(error.headers, cached))
                    finally:
                        error.close()
            self._write(key, tile)
            return tile
