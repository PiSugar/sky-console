# 树莓派客户端部署

客户端在树莓派上直接访问 RTL2832U USB 接收器，运行带 RTL-SDR 支持的 `readsb`，再把飞机状态和原始报文批量上报群晖。

## 1. 准备目录和配置

群晖执行 `deploy-synology.sh` 后会在项目根目录生成：

```text
client.env
```

把群晖上的 `client.env` 复制到树莓派 `client` 目录内：

```text
client/
├── client.env
├── docker-compose.yml
├── Dockerfile
├── agent.py
├── entrypoint.sh
└── deploy-client.sh
```

建议补充接收站经纬度，这样网页能显示天线位置，也有利于某些本地 CPR 位置计算：

```text
RECEIVER_LAT=接收站纬度
RECEIVER_LON=接收站经度
```

经纬度可以只保留小数点后 3–4 位，无需填写精确门牌位置。

## 2. 一键启动

```sh
cd client
sh deploy-client.sh
```

首次构建会从源码编译 ARM64 `readsb`，时间取决于网络和树莓派性能。后续更新通常会使用 Docker 缓存。

## 3. 查看状态

```sh
docker ps --filter name=adsb-tracker-client
docker logs -f adsb-tracker-client
```

正常日志包含：

```text
using device #0: Generic RTL2832U
Found Rafael Micro R820T tuner
已连接 readsb 原始报文端口
累计已发=...
```

## 4. 关键配置

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `SERVER_URL` | `https://hive.hahapiggy.vip:8931` | 群晖 HTTPS 服务地址 |
| `API_KEY` | 自动生成 | 上报密钥，必须与群晖一致 |
| `RECEIVER_ID` | `devpn` | 接收站唯一 ID |
| `UPLOAD_INTERVAL` | `5` | 上报间隔，秒 |
| `RTL_GAIN` | `49.6` | 当前接收器实测有效增益，dB |
| `MAX_BATCH_MESSAGES` | `2000` | 单批最多原始报文 |
| `MAX_SPOOL_BATCHES` | `10000` | 最大离线批次数 |

客户端离线队列保存在：

```text
client/data/spool.sqlite3
```

群晖恢复后会自动补传，无需手工操作。

## 5. USB 注意事项

Compose 会映射 `/dev/bus/usb` 并允许 USB 字符设备。`readsb` 启动时会临时从 DVB 驱动分离接收器，容器正常停止时会重新绑定。

客户端使用宿主网络，以便通过树莓派的 IPv6 路由访问 `hive.hahapiggy.vip`；`readsb` 的原始报文端口仍只绑定在 `127.0.0.1:30002`，不会向局域网开放。

请使用以下命令正常停止：

```sh
docker compose stop
```

不要长期使用 `docker kill -s KILL` 强制结束。如果意外强制结束后设备未重新绑定，重启客户端容器仍可继续使用接收器；重启树莓派会完全恢复驱动状态。
