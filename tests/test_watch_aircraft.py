import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "client/watch-aircraft.sh"
PROGRAM = SCRIPT.read_text().split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]


class WatchAircraftTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name) / "aircraft.json"
        self.snapshot = {"now": time.time(), "aircraft": [{"hex": "abc123", "flight": "TEST123"}]}
        self.state.write_text(json.dumps(self.snapshot))

    def command(self, *args):
        return [sys.executable, "-c", PROGRAM, "--path", str(self.state), *args]

    def test_plain_text_json_and_errors(self):
        result = subprocess.run(self.command("--once"), capture_output=True, text=True, check=True)
        self.assertIn("Aircraft: 1", result.stdout)
        self.assertIn("TEST123", result.stdout)
        self.assertNotIn("\x1b", result.stdout)
        result = subprocess.run(self.command("--once", "--json"), capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), self.snapshot)
        self.state.write_text('{"aircraft": [null]}')
        result = subprocess.run(self.command("--once"), capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("aircraft array contains invalid records", result.stderr)

    def test_terminal_refresh_resize_and_cleanup(self):
        for exit_method in ("q", "interrupt", "terminate"):
            with self.subTest(exit_method=exit_method):
                self.snapshot["aircraft"] = [{"hex": "abc123", "flight": "TEST123"}]
                self.state.write_text(json.dumps(self.snapshot))
                master, slave = pty.openpty()
                original = termios.tcgetattr(slave)
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 8, 120, 0, 0))
                process = subprocess.Popen(self.command("--interval", "0.05"), stdin=slave, stdout=slave, stderr=slave)
                output = bytearray()

                def read_until(predicate):
                    deadline = time.monotonic() + 5
                    while not predicate() and time.monotonic() < deadline:
                        if select.select([master], [], [], 0.1)[0]:
                            try:
                                output.extend(os.read(master, 65536))
                            except OSError as exc:
                                if exc.errno != errno.EIO:
                                    raise
                                break
                    self.assertTrue(predicate(), bytes(output))

                try:
                    read_until(lambda: output.count(b"\x1b[H") >= 2)
                    self.assertIn(b"TEST123", output)
                    self.snapshot["aircraft"] = [{"hex": f"{i:06x}"} for i in range(12)]
                    self.state.write_text(json.dumps(self.snapshot))
                    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 6, 120, 0, 0))
                    read_until(lambda: b"9 more rows" in output)
                    self.assertIn(b"\x1b[38;2;135;206;250m", output)
                    if exit_method == "q":
                        os.write(master, b"q")
                    else:
                        process.send_signal(signal.SIGINT if exit_method == "interrupt" else signal.SIGTERM)
                    process.wait(timeout=3)
                    read_until(lambda: b"\x1b[?25h\x1b[?1049l" in output)
                    restored = termios.tcgetattr(slave)
                    # macOS may set PENDIN itself when canonical mode is restored.
                    restored[3] &= ~getattr(termios, "PENDIN", 0)
                    original[3] &= ~getattr(termios, "PENDIN", 0)
                    self.assertEqual(restored, original)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    os.close(master)
                    os.close(slave)

    def test_highlights_follow_aircraft_and_expire_on_next_snapshot(self):
        namespace = {}
        with patch.object(sys, "argv", ["watch-aircraft"]):
            exec(PROGRAM.split("terminal_settings = None", 1)[0], namespace)
        namespace["interactive"] = True
        lines = namespace["snapshot_lines"]
        render = namespace["render_line"]
        first = {"aircraft": [{"hex": "bbbbbb", "alt_baro": 1000}]}
        self.assertNotIn("\x1b", render(lines(first)[2]))
        updated = {"aircraft": [
            {"hex": "aaaaaa", "alt_baro": 2000},
            {"hex": "bbbbbb", "alt_baro": 1100},
        ]}
        rows = lines(updated)
        self.assertTrue(all(changed for _, changed in rows[2]))
        self.assertEqual([i for i, (_, changed) in enumerate(rows[3]) if changed], [2])
        self.assertIn("\x1b[38;2;135;206;250m     1100\x1b[0m", render(rows[3]))
        self.assertEqual(render(rows[2], 3), "\x1b[38;2;135;206;250m AA\x1b[0m")
        self.assertNotIn("\x1b", render(lines(updated)[3]))
        namespace["interactive"] = False
        self.assertNotIn("\x1b", render(rows[3]))


if __name__ == "__main__":
    unittest.main()
