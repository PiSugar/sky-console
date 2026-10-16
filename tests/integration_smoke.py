from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from websockets.sync.client import connect


PROJECT_ROOT = Path(__file__).parents[1]
API_KEY = "integration-test-secret-key"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(url: str, method: str = "GET", payload: dict | None = None, authorized: bool = False):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if authorized:
        headers["Authorization"] = f"Bearer {API_KEY}"
    with urllib.request.urlopen(
        urllib.request.Request(url, data=data, method=method, headers=headers), timeout=5
    ) as response:
        body = response.read()
        return response.status, response.headers, body


def main() -> None:
    port = free_port()
    with tempfile.TemporaryDirectory() as tempdir:
        env = os.environ.copy()
        env.update(
            {
                "INGEST_API_KEY": API_KEY,
                "DATABASE_PATH": str(Path(tempdir) / "adsb.sqlite3"),
                "ACTIVE_SECONDS": "90",
                "RETENTION_DAYS": "90",
                "ENRICHMENT_ENABLED": "false",
            }
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--app-dir",
                "server",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=PROJECT_ROOT,
            env=env,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(50):
                try:
                    status, _, _ = request(f"{base}/healthz")
                    if status == 200:
                        break
                except (urllib.error.URLError, ConnectionError):
                    time.sleep(0.1)
            else:
                raise RuntimeError("server did not become healthy")

            now = int(time.time() * 1000)
            payload = {
                "batch_id": "devpn:integration-0001",
                "emitted_at_ms": now,
                "receiver": {"id": "devpn", "name": "DEVPN ADS-B"},
                "aircraft": [
                    {
                        "icao": "7823B7",
                        "observed_at_ms": now,
                        "position_at_ms": now - 250,
                        "callsign": "CSN3756",
                        "latitude": 22.598419,
                        "longitude": 112.499051,
                        "altitude_baro": 32100,
                    }
                ],
                "messages": [
                    {
                        "ts_ms": now,
                        "raw": "8D7823B79915C18E58045AA33D7E",
                        "icao": "7823B7",
                        "df": 17,
                        "type_code": 19,
                    }
                ],
            }
            with connect(f"ws://127.0.0.1:{port}/ws/v1/live", open_timeout=5) as live_socket:
                initial = json.loads(live_socket.recv(timeout=5))
                assert initial["type"] == "snapshot"
                assert initial["live"]["aircraft"] == []

                try:
                    request(f"{base}/api/v1/ingest", "POST", payload, authorized=False)
                    raise AssertionError("unauthorized ingest unexpectedly succeeded")
                except urllib.error.HTTPError as exc:
                    assert exc.code == 401

                status, _, body = request(
                    f"{base}/api/v1/ingest", "POST", payload, authorized=True
                )
                assert status == 200 and json.loads(body)["messages"] == 1

                deadline = time.monotonic() + 5
                while True:
                    pushed = json.loads(
                        live_socket.recv(timeout=max(0.1, deadline - time.monotonic()))
                    )
                    if any(
                        aircraft["icao"] == "7823B7"
                        for aircraft in pushed["live"]["aircraft"]
                    ):
                        break
                    if time.monotonic() >= deadline:
                        raise AssertionError("WebSocket did not push the ingested aircraft")
                assert pushed["type"] == "snapshot"
                assert pushed["stats"]["active_aircraft"] == 1

            status, _, body = request(f"{base}/api/v1/live")
            live = json.loads(body)
            assert status == 200 and live["aircraft"][0]["icao"] == "7823B7"

            status, _, body = request(f"{base}/api/v1/aircraft/7823B7/messages?limit=10")
            messages = json.loads(body)
            assert status == 200 and messages["items"][0]["decoded"]["type_code"] == 19
            assert messages["items"][0]["decoded"]["fields"]

            status, headers, body = request(f"{base}/")
            assert status == 200 and headers.get_content_type() == "text/html"
            assert b"SKYTRACE" in body
            print("integration smoke test: OK")
        finally:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


if __name__ == "__main__":
    main()
