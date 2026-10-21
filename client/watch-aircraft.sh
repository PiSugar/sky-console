#!/bin/sh
# Read the running receiver's state without rebuilding or restarting it.
set -eu

if ! command -v docker >/dev/null 2>&1; then
  echo "未找到 Docker。请在运行 ADS-B 接收器容器的树莓派上执行此脚本。" >&2
  exit 1
fi

# Resolve the running receiver by Compose service, independent of project name.
if [ -n "${ADSB_CONTAINER:-}" ]; then
  receiver_container=$ADSB_CONTAINER
else
  receiver_container=$(docker ps --filter label=com.docker.compose.service=adsb-client --format '{{.ID}}')
  receiver_count=$(printf '%s\n' "$receiver_container" | awk 'NF {n++} END {print n+0}')
  if [ "$receiver_count" -ne 1 ]; then
    echo "找到 $receiver_count 个接收器容器。请用 ADSB_CONTAINER 指定容器名称。" >&2
    exit 1
  fi
fi

exec docker exec -i "$receiver_container" python - "$@" <<'PY'
import argparse
import json
import math
import os
from pathlib import Path
import sys
import time


def positive_seconds(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("刷新间隔必须是大于 0 的有限秒数")
    return seconds


parser = argparse.ArgumentParser(description="打印接收器的 readsb 航空器状态；Ctrl+C 退出。")
parser.add_argument("--once", action="store_true", help="只打印一次后退出")
parser.add_argument("--json", action="store_true", help="每次输出一行完整 JSON，便于保存或管道处理")
parser.add_argument("--interval", type=positive_seconds, default=1.0, help="刷新间隔（秒，默认 1）")
parser.add_argument("--path", default=os.getenv("STATE_PATH", "/run/readsb/aircraft.json"), help="容器内的 readsb 状态文件路径")
args = parser.parse_args()


def field(value, width, decimals=None):
    if value is None:
        text = "-"
    elif decimals is not None and isinstance(value, (int, float)):
        text = f"{value:.{decimals}f}"
    else:
        text = str(value).strip()
    text = "".join(char if char.isprintable() else "?" for char in text)
    return f"{text[:width]:>{width}}"


def display(snapshot):
    aircraft = snapshot["aircraft"]
    now = snapshot.get("now")
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(now)) if now is not None else "未知"
    age = max(0, time.time() - now) if now is not None else None
    stale = f" [警告：状态文件已 {age:.0f} 秒未更新]" if age is not None and age > 10 else ""
    print(f"\n{timestamp} | 航空器 {len(aircraft)} 架{stale}")
    print("   ICAO     CALLSIGN   ALT(ft)   GS(kt)  TRK(deg)        LAT         LON  RSSI(dBFS)  SEEN(s)  POS(s)  MESSAGES")
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
        print("".join(columns))
    if not aircraft:
        print("当前状态文件中没有航空器，等待接收信号……")
    sys.stdout.flush()


try:
    while True:
        try:
            snapshot = json.loads(Path(args.path).read_text(encoding="utf-8"))
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("aircraft"), list):
                raise ValueError("状态文件缺少 aircraft 数组")
            if not all(isinstance(plane, dict) for plane in snapshot["aircraft"]):
                raise ValueError("aircraft 数组包含无效记录")
            if args.json:
                print(json.dumps(snapshot, ensure_ascii=False), flush=True)
            else:
                display(snapshot)
        except (OSError, ValueError, TypeError, OverflowError) as exc:
            print(f"无法读取接收器状态 {args.path}：{exc}", file=sys.stderr, flush=True)
            if args.once:
                sys.exit(1)
        if args.once:
            break
        time.sleep(args.interval)
except KeyboardInterrupt:
    pass
except BrokenPipeError:
    # A downstream command such as head has finished reading.
    os._exit(0)
PY
