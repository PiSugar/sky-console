# 群晖一键部署

## 1. 上传目录

把整个 `adsb-tracker` 目录上传到群晖，例如：

```text
/volume1/docker/adsb-tracker/
```

按照指定映射，数据库会自动创建在脚本目录的上一级：

```text
/volume1/docker/data/abs_d/adsb.sqlite3
```

对应的 Docker 映射为：

```text
../data/abs_d:/data
```

SSL 证书必须放在脚本目录旁的 `../SSL`：

```text
/volume1/docker/SSL/privkey.pem
/volume1/docker/SSL/fullchain.pem
```

容器中的只读映射为：

```text
../SSL:/ssl:ro
```

## 2. 执行一键脚本

通过 SSH 登录群晖后执行：

```sh
cd /volume1/docker/adsb-tracker
sudo sh deploy-synology.sh
```

脚本会自动：

1. 检查 Docker 和 Compose；
2. 创建 `.env`；
3. 生成 64 位十六进制随机上报密钥；
4. 创建 `../data/abs_d`；
5. 构建并启动服务；
6. 等待健康检查通过；
7. 生成供树莓派使用的 `client.env`。

重复运行脚本会沿用原有 `.env` 和数据库，不会重置密钥或历史。

## 3. 开放端口

默认 HTTPS 网页和 API 地址：

```text
https://hive.hahapiggy.vip:38391
```

请在以下位置放行 TCP `38391`：

- DSM 控制面板 → 安全性 → 防火墙；
- 路由器 IPv6 防火墙；
- 如果使用 IPv4，还需配置端口转发到群晖。

实时页面使用同一端口上的 `wss://hive.hahapiggy.vip:38391/ws/v1/live`，不需要额外开放 WebSocket 端口。

若端口需要修改，可在首次部署前执行：

```sh
PUBLIC_PORT=你的端口 sudo -E sh deploy-synology.sh
```

或者修改生成后的 `.env`，再重新执行脚本。

## 4. HTTPS 证书更新

服务端直接使用 `../SSL/privkey.pem` 和 `../SSL/fullchain.pem` 提供 HTTPS，不需要再由 DSM 反向代理终止 TLS。证书续期或替换后，重启容器使 Uvicorn 重新读取证书：

```sh
cd /volume1/docker/adsb-tracker
sudo docker compose restart
```

## 5. 常用管理命令

```sh
cd /volume1/docker/adsb-tracker

# 查看状态
sudo docker compose ps

# 查看日志
sudo docker logs -f adsb-tracker-server

# 重启
sudo docker compose restart

# 停止（数据库保留）
sudo docker compose down

# 更新代码后重建
sudo sh deploy-synology.sh
```

健康检查：

```text
https://hive.hahapiggy.vip:38391/healthz
```

正常返回：

```json
{"status":"ok","database":"ok","version":"1.3.4"}
```

## 6. 数据保留与备份

在 `.env` 中设置保留天数：

```text
RETENTION_DAYS=90
```

程序每小时自动清理超过保留期的原始报文和轨迹。飞机首次/最后出现时间及累计计数继续保留。

飞机注册、机型、航司和公开航线资料默认由服务端在后台查询 ADSBDB，并缓存在同一个 SQLite 数据库中。群晖需要能够出站访问 `https://api.adsbdb.com`。查询失败不会影响接收、上报或历史入库。

相关 `.env` 配置：

```text
ENRICHMENT_ENABLED=true
ENRICHMENT_BASE_URL=https://api.adsbdb.com/v0
ENRICHMENT_SUCCESS_HOURS=168
ENRICHMENT_RETRY_HOURS=6
ENRICHMENT_TIMEOUT_SECONDS=8
```

如不希望访问外部资料源，把 `ENRICHMENT_ENABLED` 改为 `false` 后重新运行部署脚本。

安全备份：

```sh
cd /volume1/docker/adsb-tracker
sudo docker compose stop
# 此时复制 ../data/abs_d 到备份位置
sudo docker compose start
```
