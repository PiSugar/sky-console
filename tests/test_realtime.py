import asyncio
import threading
import unittest
from unittest.mock import AsyncMock

from server.app.realtime import LiveHub


class LiveHubTests(unittest.IsolatedAsyncioTestCase):
    async def test_audio_thread_delivers_ordered_events_on_server_loop(self):
        hub = LiveHub(lambda: {"type": "snapshot"})
        await hub.start()
        socket = AsyncMock()
        try:
            await hub.connect(socket)
            received = asyncio.Event()
            events = []
            loop = asyncio.get_running_loop()

            async def receive(message):
                self.assertIs(asyncio.get_running_loop(), loop)
                events.append(message)
                if len(events) == 2:
                    received.set()

            socket.send_json.side_effect = receive
            start = {"type": "radio_subtitle", "active": True, "text": "Flight report"}
            end = {"type": "radio_subtitle", "active": False}
            worker = threading.Thread(target=lambda: [hub.broadcast_from_thread(event) for event in (start, end)])
            worker.start()
            await asyncio.to_thread(worker.join)
            await asyncio.wait_for(received.wait(), timeout=2)
            self.assertEqual(events, [start, end])
        finally:
            await hub.stop()
        hub.broadcast_from_thread({"type": "ignored_after_shutdown"})
