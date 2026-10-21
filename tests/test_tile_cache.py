from __future__ import annotations

import io
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).parents[1] / "server"))
from app.tile_cache import MAX_TILE_BYTES, TileCache


PNG = b"\x89PNG\r\n\x1a\n" + b"tile-data"


def headers(**values):
    result = Message()
    for key, value in values.items():
        result[key.replace("_", "-")] = value
    return result


class TileResponse(io.BytesIO):
    status = 200

    def __init__(self, body=PNG, **values):
        super().__init__(body)
        self.headers = headers(Content_Type="image/png", **values)


class TileCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "tiles.sqlite3")
        self.cache = TileCache(self.path, 1024, "https://skytrace.example")

    def test_revisit_and_restart_do_not_download_again(self):
        with patch("app.tile_cache.urlopen", return_value=TileResponse()) as download:
            self.assertEqual(self.cache.get("esri", 2, 1, 1).body, PNG)
            restarted = TileCache(self.path, 1024, "https://skytrace.example")
            self.assertEqual(restarted.get("esri", 2, 1, 1).body, PNG)
            download.assert_called_once()

    def test_sources_and_zoom_levels_are_isolated(self):
        with patch("app.tile_cache.urlopen", side_effect=lambda *a, **kw: TileResponse()) as download:
            for args in [("esri", 2, 1, 1), ("international", 2, 1, 1), ("esri", 3, 1, 1)]:
                self.cache.get(*args)
                self.cache.get(*args)
            self.assertEqual(download.call_count, 3)

    def test_expired_tile_uses_conditional_request_and_304(self):
        with patch("app.tile_cache.urlopen", return_value=TileResponse(Cache_Control="max-age=0", ETag='"v1"', Last_Modified="Wed, 01 Jan 2025 00:00:00 GMT")):
            self.cache.get("international", 2, 1, 1)
        unchanged = HTTPError("https://tile.openstreetmap.org", 304, "unchanged", headers(Cache_Control="max-age=3600"), None)
        with patch("app.tile_cache.urlopen", side_effect=unchanged) as download:
            result = self.cache.get("international", 2, 1, 1, "https://skytrace.example/map")
            self.assertEqual(result.body, PNG)
            self.assertGreater(result.expires, time.time() + 3500)
            request = download.call_args.args[0]
            self.assertEqual(request.get_header("If-none-match"), '"v1"')
            self.assertIn("If-modified-since", request.headers)
            self.assertEqual(request.get_header("Referer"), "https://skytrace.example/map")
            self.assertIn("SkyTrace", request.get_header("User-agent"))
            self.cache.get("international", 2, 1, 1)
            download.assert_called_once()

    def test_changed_tile_replaces_expired_body(self):
        with patch("app.tile_cache.urlopen", side_effect=[TileResponse(Cache_Control="max-age=0"), TileResponse(PNG + b"new")]):
            self.cache.get("esri", 2, 1, 1)
            self.assertEqual(self.cache.get("esri", 2, 1, 1).body, PNG + b"new")

    def test_invalid_coordinates_never_reach_network(self):
        with patch("app.tile_cache.urlopen") as download:
            for args in [("unknown", 2, 1, 1), ("esri", -1, 0, 0), ("esri", 19, 0, 0), ("international", 20, 0, 0), ("esri", 2, -1, 0), ("esri", 2, 4, 0), ("esri", 2, 0, 4)]:
                with self.subTest(args=args), self.assertRaises(ValueError):
                    self.cache.get(*args)
            download.assert_not_called()

    def test_failed_or_invalid_download_is_not_cached(self):
        for failure in [URLError("offline"), TileResponse(b"<html>error</html>"), TileResponse(PNG + b"x" * MAX_TILE_BYTES)]:
            with self.subTest(failure=failure), patch("app.tile_cache.urlopen", side_effect=[failure, TileResponse()]) as download:
                # Use a fresh file for each case.
                Path(self.path).unlink(missing_ok=True)
                self.cache = TileCache(self.path, 1024, "https://skytrace.example")
                with self.assertRaises(OSError):
                    self.cache.get("esri", 2, 1, 1)
                self.assertEqual(self.cache.get("esri", 2, 1, 1).body, PNG)
                self.assertEqual(download.call_count, 2)

    def test_no_store_is_never_persisted(self):
        with patch("app.tile_cache.urlopen", side_effect=lambda *a, **kw: TileResponse(Cache_Control="no-store")) as download:
            for _ in range(2):
                tile = self.cache.get("esri", 2, 1, 1)
                self.assertEqual(tile.browser_cache_control(), "no-store")
            self.assertEqual(download.call_count, 2)
            self.assertIsNone(self.cache._read("v1/esri/2/1/1"))

    def test_capacity_evicts_least_recently_used_tile(self):
        self.cache.max_bytes = len(PNG) * 2
        with patch("app.tile_cache.urlopen", side_effect=lambda *a, **kw: TileResponse()) as download:
            for x in [0, 1, 0, 2, 0, 1]:
                self.cache.get("esri", 2, x, 1)
            self.assertEqual(download.call_count, 4)

    def test_concurrent_requests_share_download(self):
        def fetch(*args, **kwargs):
            time.sleep(0.02)
            return TileResponse()
        with patch("app.tile_cache.urlopen", side_effect=fetch) as download:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda _: self.cache.get("esri", 2, 1, 1), range(8)))
            self.assertTrue(all(tile.body == PNG for tile in results))
            download.assert_called_once()

    def test_unwritable_cache_still_displays_download(self):
        with patch.object(self.cache, "_connect", side_effect=OSError("disk full")), patch("app.tile_cache.urlopen", return_value=TileResponse()), self.assertLogs("app.tile_cache", level="WARNING"):
            self.assertEqual(self.cache.get("esri", 2, 1, 1).body, PNG)

    def test_cache_age_expires_and_no_cache(self):
        with patch("app.tile_cache.time.time", return_value=1000):
            self.assertEqual(self.cache._metadata(headers(Cache_Control="max-age=600", Age="200"))["expires"], 1400)
            self.assertEqual(self.cache._metadata(headers(Expires="Thu, 01 Jan 1970 00:20:00 GMT"))["expires"], 1200)
            self.assertEqual(self.cache._metadata(headers(Cache_Control="no-cache, max-age=600"))["expires"], 1000)


if __name__ == "__main__":
    unittest.main()
