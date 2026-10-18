#!/bin/sh
set -eu

SKYTRACE_URL="${SKYTRACE_KIOSK_URL:-http://127.0.0.1:38391/#live-kiosk}"
SKYTRACE_HEALTH_URL="${SKYTRACE_HEALTH_URL:-http://127.0.0.1:38391/healthz}"

while ! curl -fsS --max-time 2 "$SKYTRACE_HEALTH_URL" >/dev/null 2>&1; do
  sleep 2
done

exec angelfish "$SKYTRACE_URL"
