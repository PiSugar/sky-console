from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from fastapi import WebSocket


logger = logging.getLogger(__name__)


class LiveHub:
    """Broadcast coalesced live snapshots to connected browser clients."""

    def __init__(
        self,
        snapshot_factory: Callable[[], dict[str, Any]],
        heartbeat_seconds: float = 5.0,
    ) -> None:
        self.snapshot_factory = snapshot_factory
        self.heartbeat_seconds = heartbeat_seconds
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="adsb-live-hub")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        async with self._lock:
            clients = tuple(self._clients)
            self._clients.clear()
        await asyncio.gather(
            *(client.close(code=1001) for client in clients),
            return_exceptions=True,
        )

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)
        try:
            await websocket.send_json(await self._snapshot())
        except Exception:
            await self.disconnect(websocket)
            raise

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)

    def notify(self) -> None:
        """Wake the broadcaster after a newly ingested batch."""

        self._wake.set()

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send an out-of-band event to every connected browser."""

        async with self._lock:
            clients = tuple(self._clients)
        if not clients:
            return
        results = await asyncio.gather(
            *(client.send_json(message) for client in clients),
            return_exceptions=True,
        )
        failed = [
            client
            for client, result in zip(clients, results, strict=True)
            if isinstance(result, BaseException)
        ]
        if failed:
            async with self._lock:
                for client in failed:
                    self._clients.discard(client)

    async def _snapshot(self) -> dict[str, Any]:
        return await asyncio.to_thread(self.snapshot_factory)

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(
                    self._wake.wait(), timeout=self.heartbeat_seconds
                )
            except TimeoutError:
                pass
            self._wake.clear()

            async with self._lock:
                clients = tuple(self._clients)
            if not clients:
                continue

            try:
                snapshot = await self._snapshot()
            except Exception:
                logger.exception("failed to build ADS-B live snapshot")
                continue
            await self.broadcast(snapshot)
