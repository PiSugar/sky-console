#!/bin/sh
set -eu

SKYTRACE_URL="${SKYTRACE_KIOSK_URL:-http://127.0.0.1:8931/#live-kiosk}"
SKYTRACE_HEALTH_URL="${SKYTRACE_HEALTH_URL:-http://127.0.0.1:8931/healthz}"
SKYTRACE_CLOSE_MARKER="${SKYTRACE_CLOSE_MARKER:-/home/pi/adsb-tracker/runtime/state/close-kiosk}"

while ! curl -fsS --max-time 2 "$SKYTRACE_HEALTH_URL" >/dev/null 2>&1; do
  sleep 2
done

mkdir -p "$(dirname "$SKYTRACE_CLOSE_MARKER")"
rm -f "$SKYTRACE_CLOSE_MARKER"

angelfish "$SKYTRACE_URL" &
kiosk_pid=$!

watch_for_close() {
  while kill -0 "$kiosk_pid" 2>/dev/null; do
    if [ -e "$SKYTRACE_CLOSE_MARKER" ]; then
      rm -f "$SKYTRACE_CLOSE_MARKER"
      kill "$kiosk_pid" 2>/dev/null || true
      return
    fi
    sleep 0.2
  done
}

watch_for_close &
watcher_pid=$!

cleanup() {
  kill "$watcher_pid" 2>/dev/null || true
  rm -f "$SKYTRACE_CLOSE_MARKER"
}
trap cleanup EXIT INT TERM

wait "$kiosk_pid" || true
