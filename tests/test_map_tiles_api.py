from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from fastapi.testclient import TestClient
from server.app.tile_cache import TileCache
from test_tile_cache import PNG, TileResponse


class MapTilesAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {"INGEST_API_KEY": "map-tiles-test-api-key"}):
            cls.main = importlib.import_module("server.app.main")

    def setUp(self):
        self.client = TestClient(self.main.app)
        self.addCleanup(self.client.close)

    def test_esri_url_preserves_row_column_order(self):
        self.assertTrue(TileCache.tile_url("esri", 5, 7, 9).endswith("/tile/5/9/7"))
        self.assertTrue(TileCache.tile_url("international", 5, 7, 9).endswith("/5/7/9.png"))

    def test_routes_persist_and_reuse_tiles_for_both_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = TileCache(str(Path(folder) / "tiles.sqlite3"), 1024, "https://skytrace.example")
            with patch.object(self.main, "tile_cache", cache):
                client = self.client
                with patch("server.app.tile_cache.urlopen", side_effect=lambda *a, **kw: TileResponse()) as download:
                    for source in ("esri", "international"):
                        for _ in range(2):
                            response = client.get(f"/tiles/{source}/2/1/1.png")
                            self.assertEqual(response.status_code, 200)
                            self.assertEqual(response.content, PNG)
                            self.assertEqual(response.headers["content-type"], "image/png")
                            self.assertIn("public, max-age=", response.headers["cache-control"])
                    self.assertEqual(download.call_count, 2)
                with patch("server.app.tile_cache.urlopen", side_effect=URLError("offline")):
                    self.assertEqual(client.get("/tiles/esri/2/1/1.png").status_code, 200)
                    self.assertEqual(client.get("/tiles/esri/2/2/1.png").status_code, 502)

    def test_invalid_tile_is_rejected_before_download(self):
        with patch("server.app.tile_cache.urlopen") as download:
            client = self.client
            for path in ("unknown/2/1/1", "esri/2/4/1", "esri/19/0/0"):
                self.assertEqual(client.get(f"/tiles/{path}.png").status_code, 404)
            download.assert_not_called()
