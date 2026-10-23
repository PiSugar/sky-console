#!/bin/sh
# Read the running receiver's state without rebuilding or restarting it.
set -eu

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker was not found. Run this script on the Raspberry Pi hosting the ADS-B receiver." >&2
  exit 1
fi

# Resolve the running receiver by Compose service, independent of project name.
if [ -n "${ADSB_CONTAINER:-}" ]; then
  receiver_container=$ADSB_CONTAINER
else
  receiver_container=$(docker ps --filter label=com.docker.compose.service=adsb-client --format '{{.ID}}')
  receiver_count=$(printf '%s\n' "$receiver_container" | awk 'NF {n++} END {print n+0}')
  if [ "$receiver_count" -ne 1 ]; then
    echo "Found $receiver_count receiver containers. Set ADSB_CONTAINER to the container name." >&2
    exit 1
  fi
fi

# Pass the program as an argument so stdin remains available for keyboard input.
python_code=$(cat <<'PY'
import argparse
import json
import math
import os
from pathlib import Path
import select
import shutil
import signal
import sys
import termios
import time
import tty


def positive_seconds(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("refresh interval must be a finite number greater than zero")
    return seconds


parser = argparse.ArgumentParser(description="Monitor readsb aircraft data. Press q or Ctrl+C to quit.")
parser.add_argument("--once", action="store_true", help="print one snapshot and exit")
parser.add_argument("--json", action="store_true", help="print one complete JSON object per line for piping or saving")
parser.add_argument("--interval", type=positive_seconds, default=1.0, help="refresh interval in seconds (default: 1)")
parser.add_argument("--path", default=os.getenv("STATE_PATH", "/run/readsb/aircraft.json"), help="readsb state file path inside the container")
args = parser.parse_args()
interactive = sys.stdin.isatty() and sys.stdout.isatty() and not (args.once or args.json)
previous_aircraft = None


def field(value, width, decimals=None):
    if value is None:
        text = "-"
    elif decimals is not None and isinstance(value, (int, float)):
        text = f"{value:.{decimals}f}"
    else:
        text = str(value).strip()
    text = "".join(char if char.isprintable() else "?" for char in text)
    return f"{text[:width]:>{width}}"


def snapshot_lines(snapshot):
    global previous_aircraft
    aircraft = snapshot["aircraft"]
    current_aircraft = {}
    now = snapshot.get("now")
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(now)) if now is not None else "Unknown time"
    age = max(0, time.time() - now) if now is not None else None
    stale = f" [WARNING: state is {age:.0f}s old]" if age is not None and age > 10 else ""
    lines = [f"{timestamp} | Aircraft: {len(aircraft)}{stale}",
             "   ICAO     CALLSIGN   ALT(ft)   GS(kt)  TRK(deg)        LAT         LON  RSSI(dBFS)  SEEN(s)  POS(s)  MESSAGES"]
    for plane in sorted(aircraft, key=lambda item: str(item.get("hex", ""))):
        altitude = plane.get("alt_baro")
        if altitude is None:
            altitude = plane.get("alt_geom")
        columns = [
            field(str(plane.get("hex", "-")).upper(), 7),
            field(plane.get("flight"), 12),
            field(altitude, 9),
            field(plane.get("gs"), 8, 1),
            field(plane.get("track"), 9, 1),
            field(plane.get("lat"), 10, 5),
            field(plane.get("lon"), 11, 5),
            field(plane.get("rssi"), 11, 1),
            field(plane.get("seen"), 8, 1),
            field(plane.get("seen_pos"), 7, 1),
            field(plane.get("messages"), 10),
        ]
        identity = str(plane.get("hex", "")).upper()
        previous = previous_aircraft.get(identity) if previous_aircraft is not None else None
        lines.append([
            (value, interactive and previous_aircraft is not None
             and (previous is None or value != previous[index]))
            for index, value in enumerate(columns)
        ])
        current_aircraft[identity] = columns
    if not aircraft:
        lines.append("No aircraft in the current snapshot. Waiting for signals...")
    previous_aircraft = current_aircraft
    return lines


def render_line(line, width=None):
    segments = [(line, False)] if isinstance(line, str) else line
    rendered = []
    for text, changed in segments:
        text = "".join(c if c.isprintable() else "?" for c in text)
        if width is not None:
            text = text[:width]
            width -= len(text)
        if text:
            # Color only trusted, width-clipped text; always reset after each cell.
            rendered.append(f"\x1b[38;2;135;206;250m{text}\x1b[0m" if interactive and changed else text)
        if width == 0:
            break
    return "".join(rendered)


def display(lines):
    if not interactive:
        print("\n".join(render_line(line) for line in lines), flush=True)
        return
    columns, rows = shutil.get_terminal_size()
    capacity = max(0, rows - 1)
    hidden = max(0, len(lines) - capacity)
    footer = f"Refresh: {args.interval:g}s | q/Ctrl+C: quit | Light blue: updated"
    if hidden:
        footer += f" | {hidden} more rows (resize terminal to show)"
    visible = lines[:capacity] + [footer]
    # Clear each row in place; cap width/height to prevent wrapping and scrolling.
    frame = "\r\n".join(
        "\x1b[2K" + render_line(line, max(0, columns - 1))
        for line in visible
    )
    sys.stdout.write("\x1b[H" + frame + "\x1b[J")
    sys.stdout.flush()


def wait_for_refresh():
    if not interactive:
        time.sleep(args.interval)
        return True
    deadline = time.monotonic() + args.interval
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        if select.select([sys.stdin], [], [], remaining)[0]:
            key = os.read(sys.stdin.fileno(), 1)
            if not key or key.lower() == b"q":
                return False


def terminate(signum, frame):
    raise SystemExit(128 + signum)


terminal_settings = None
try:
    if interactive:
        signal.signal(signal.SIGTERM, terminate)
        signal.signal(signal.SIGHUP, terminate)
        terminal_settings = termios.tcgetattr(sys.stdin.fileno())
        tty.setcbreak(sys.stdin.fileno())
        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[2J")
        sys.stdout.flush()
    while True:
        try:
            snapshot = json.loads(Path(args.path).read_text(encoding="utf-8"))
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("aircraft"), list):
                raise ValueError("state file is missing the aircraft array")
            if not all(isinstance(plane, dict) for plane in snapshot["aircraft"]):
                raise ValueError("aircraft array contains invalid records")
            if args.json:
                print(json.dumps(snapshot, ensure_ascii=False), flush=True)
            else:
                display(snapshot_lines(snapshot))
        except (OSError, ValueError, TypeError, OverflowError) as exc:
            message = f"Cannot read receiver state {args.path}: {exc}"
            if interactive:
                display([message, "Waiting for receiver data..."])
            else:
                print(message, file=sys.stderr, flush=True)
            if args.once:
                sys.exit(1)
        if args.once:
            break
        if not wait_for_refresh():
            break
except KeyboardInterrupt:
    pass
except BrokenPipeError:
    # A downstream command such as head has finished reading.
    sys.stdout = open(os.devnull, "w")
finally:
    if terminal_settings is not None:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, terminal_settings)
        sys.stdout.write("\x1b[0m\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()
PY
)

docker_flags=-i
if [ -t 0 ] && [ -t 1 ]; then
  docker_flags=-it
fi
exec docker exec "$docker_flags" "$receiver_container" python -c "$python_code" "$@"
