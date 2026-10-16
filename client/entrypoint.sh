#!/usr/bin/env bash
set -euo pipefail

mkdir -p /run/readsb /data

readsb_args=(
  --quiet
  --net
  --device-type rtlsdr
  --device "${RTL_DEVICE:-0}"
  --gain "${RTL_GAIN:-49.6}"
  --net-bind-address 127.0.0.1
  --net-ro-port 30002
  --net-heartbeat 5
  --write-json /run/readsb
  --write-json-every 1
)

readsb "${readsb_args[@]}" &
readsb_pid=$!
sleep "${AGENT_START_DELAY:-5}"
python /app/agent.py &
agent_pid=$!

shutdown() {
  kill -TERM "$agent_pid" 2>/dev/null || true
  kill -INT "$readsb_pid" 2>/dev/null || true
  wait "$agent_pid" 2>/dev/null || true
  wait "$readsb_pid" 2>/dev/null || true
}
trap shutdown INT TERM EXIT

set +e
wait -n "$readsb_pid" "$agent_pid"
status=$?
set -e

if ! kill -0 "$readsb_pid" 2>/dev/null; then
  echo "readsb 已退出，容器将重启。" >&2
else
  echo "上报客户端已退出，容器将重启。" >&2
fi
exit "$status"
