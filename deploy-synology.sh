#!/bin/sh
set -eu

cd "$(dirname "$0")"
umask 077

DEFAULT_PORT=38391
DEFAULT_DOMAIN=hive.hahapiggy.vip
ENV_FILE=.env
SSL_DIR=../SSL

if [ ! -r "$SSL_DIR/privkey.pem" ] || [ ! -r "$SSL_DIR/fullchain.pem" ]; then
  echo "缺少 SSL 证书。请确认以下文件存在且可读：" >&2
  echo "  $SSL_DIR/privkey.pem" >&2
  echo "  $SSL_DIR/fullchain.pem" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "未找到 Docker。请先在群晖套件中心安装 Container Manager。" >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "当前用户无权访问 Docker。请改用：sudo sh deploy-synology.sh" >&2
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  compose() { docker compose "$@"; }
elif command -v docker-compose >/dev/null 2>&1; then
  compose() { docker-compose "$@"; }
else
  echo "未找到 docker compose。请更新 Container Manager。" >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  if command -v openssl >/dev/null 2>&1; then
    api_key=$(openssl rand -hex 32)
  else
    api_key=$(dd if=/dev/urandom bs=32 count=1 2>/dev/null | od -An -tx1 | tr -d ' \n')
  fi

  public_port=${PUBLIC_PORT:-$DEFAULT_PORT}
  public_domain=${PUBLIC_DOMAIN:-$DEFAULT_DOMAIN}
  cat >"$ENV_FILE" <<EOF
PUBLIC_PORT=$public_port
PUBLIC_BASE_URL=https://$public_domain:$public_port
INGEST_API_KEY=$api_key
RETENTION_DAYS=90
ACTIVE_SECONDS=90
DATABASE_PATH=/data/adsb.sqlite3
ENRICHMENT_ENABLED=true
ENRICHMENT_BASE_URL=https://api.adsbdb.com/v0
ENRICHMENT_SUCCESS_HOURS=168
ENRICHMENT_RETRY_HOURS=6
ENRICHMENT_TIMEOUT_SECONDS=8
EOF
  echo "已创建 .env 和随机上报密钥。"
else
  echo "沿用现有 .env 配置。"
fi

data_dir=../data/abs_d
mkdir -p "$data_dir"
chmod 700 "$data_dir"

compose up -d --build --remove-orphans

container=adsb-tracker-server
attempt=0
while [ "$attempt" -lt 30 ]; do
  status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container" 2>/dev/null || true)
  if [ "$status" = healthy ]; then
    break
  fi
  if [ "$status" = exited ] || [ "$status" = dead ]; then
    echo "服务启动失败，最近日志如下：" >&2
    docker logs --tail 100 "$container" >&2 || true
    exit 1
  fi
  attempt=$((attempt + 1))
  sleep 2
done

status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container" 2>/dev/null || true)
if [ "$status" != healthy ]; then
  echo "服务尚未通过健康检查（当前：$status）。请运行 docker logs adsb-tracker-server 查看。" >&2
  exit 1
fi

public_url=$(sed -n 's/^PUBLIC_BASE_URL=//p' "$ENV_FILE" | tail -n 1)
api_key=$(sed -n 's/^INGEST_API_KEY=//p' "$ENV_FILE" | tail -n 1)

cat >client.env <<EOF
SERVER_URL=$public_url
API_KEY=$api_key
RECEIVER_ID=devpn
RECEIVER_NAME=DEVPN ADS-B
RECEIVER_LAT=
RECEIVER_LON=
UPLOAD_INTERVAL=5
RTL_GAIN=49.6
EOF
chmod 600 client.env

echo
echo "部署完成：$public_url"
echo "树莓派配置已写入：$(pwd)/client.env"
echo "请在 DSM 防火墙和路由器 IPv6 防火墙放行 TCP $(sed -n 's/^PUBLIC_PORT=//p' "$ENV_FILE" | tail -n 1)。"
