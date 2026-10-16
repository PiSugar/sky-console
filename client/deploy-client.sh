#!/bin/sh
set -eu

cd "$(dirname "$0")"

if [ ! -f client.env ]; then
  echo "缺少 client.env。请将群晖 deploy-synology.sh 生成的 client.env 复制到此目录。" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  echo "Docker 不可用，或当前用户无权访问 Docker。" >&2
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  compose() { docker compose "$@"; }
elif command -v docker-compose >/dev/null 2>&1; then
  compose() { docker-compose "$@"; }
else
  echo "未找到 docker compose。" >&2
  exit 1
fi

mkdir -p data
compose up -d --build --remove-orphans

echo "树莓派 ADS-B 客户端已启动。"
echo "查看日志：docker logs -f adsb-tracker-client"

