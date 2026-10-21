# SkyTrace ADS-B 空情台

本项目统一在 `sky-tracker` 中开发和部署（远程仓库：`PiSugar/sky-console`）。旧 `personal-projects/adsb-tracker` 目录已废弃。

SkyTrace 在树莓派上接收 1090 MHz ADS-B 信号，提供实时地图、航空器资料、硬件控制和可选语音 / LLM 问答。当前设备通过 Docker Compose 运行接收器、API、硬件桥接和 TTS，Mac 提供 ASR 与模型推理。网页设置和地图缓存均持久化在设备本地。

## 已实现功能

- 实时地图：通过 WebSocket 推送最近 90 秒仍有信号的飞机与接收站状态；以最新 ADS-B 坐标、地速、航向、更新时间持续推算短时位置，并在新报文到达时平滑校正。动画刷新率随地图缩放调整，失联过久会停止外推。可在英文 Esri 与 OpenStreetMap 底图之间切换，两种底图均直接使用 ADS-B 的 WGS-84 坐标。支持空白区域直接拖动、普通滚轮缩放以及手机触摸操作。
- 飞机资料：后台按 ICAO 地址和呼号查询 ADSBDB，并在 SQLite 缓存注册号、制造商、机型、注册所有人、航司及公开航线资料。同时显示旅客使用的 IATA 航班号和 ADS-B 中的 ICAO 呼号；航司、出发地和目的地按浏览器语言显示，中文浏览器优先使用中文名称，未收录的本地化名称自动回退到资料源原名。地图图标的悬停信息同样包含双航班号、航司和本地化航线。
- 手机快速信息：在触摸设备或窄屏页面点击地图飞机图标，会在地图底部显示轻量卡片，优先突出航司和机型，并附带双航班号、高度、速度及航向；点击“详细资料”才打开完整抽屉，点击地图空白处可快速收起。
- 历史档案：按 ICAO、呼号、注册号、制造商、机型、所有人或航司搜索曾经接收到的飞机。
- 飞机详情：查看历史航迹、累计报文量，以及逐条 Mode S / ADS-B 报文的位字段、解析值、中文含义、CRC 和学习提示。
- 可靠上报：树莓派按批次上传；批次具备幂等 ID，网络重试不会重复入库。
- 离线缓存：群晖或公网不可用时，批次暂存在树莓派 SQLite 队列，恢复后自动补传。
- 数据保留：原始报文和轨迹默认保留 90 天，可在 `.env` 调整。
- 自动恢复：服务端和客户端容器均配置 `restart: unless-stopped`。

## 功能设置

普通页面顶部的 **Settings** 和全屏地图左下角的齿轮按钮可打开设备设置面板：

- **Voice responses**：开关飞机语音播报和问答语音；关闭时立即停止正在播放的语音，问答仍显示文字。
- **Voice questions**：开关硬件长按提问；关闭后不再进行语音识别或生成回答。
- **LLM responses**：开关模型应答；关闭或模型请求失败时使用固定模板回答。关闭语音提问时保留此选择，重新开启提问后继续生效。

设置即时保存到历史数据库同目录的 `feature-settings.json`（Docker 中位于持久化 `/data`），无需重启，并通过 WebSocket 同步到其他页面。首次运行沿用 `RADIO_ENABLED`、`DIALOGUE_LLM_ENABLED` 的部署默认值，语音提问默认开启；保存后以面板设置为准。模型、ASR 和音频服务仍需事先部署，开关不会启动或停止 Docker 服务。

沿用硬件控制的访问范围：设备本机和 Docker 内网可在面板修改，远程浏览器只读。远程管理程序可使用现有上报密钥调用 `PATCH /api/v1/settings`，请求头为 `Authorization: Bearer <INGEST_API_KEY>`，JSON 请求体仅包含要修改的布尔字段：`radio_enabled`、`dialogue_enabled`、`dialogue_llm_enabled`。设置文件写入失败时保留原设置并显示错误。

## 数据链路

```text
RTL2832U / R820T USB 接收器
        ↓ 1090 MHz
树莓派 readsb（校验、解码、位置计算）
        ↓ 每 5 秒批量上报；断网写入本地队列
树莓派 FastAPI 服务
        ├─→ ADSBDB（仅查询飞机/航班公开资料，结果写入本地缓存）
        ↓
data/adsb.sqlite3（历史数据库）
        ↓
实时地图 / 飞机档案 / 原始报文详情
```

## 快速部署顺序

当前树莓派版本使用根目录的 Docker Compose 部署界面、硬件与 ADS-B 服务；Mac 使用 `docker-compose.asr.yml` 部署 ASR 和 Ollama，并通过 Tailscale 与树莓派连接。详见 [Docker 部署说明](DEPLOY_DOCKER.md)。不开启 LLM 时仍保留固定模板播报和长按问答。

1. 执行 `cp .env.example .env`，至少修改 `INGEST_API_KEY`。
2. 执行 `sudo docker compose build`。
3. 执行 `sudo docker compose up -d`，通过 `sudo docker compose ps` 检查状态。

群晖的独立服务端部署方式仍保留在 [群晖部署说明](DEPLOY_SYNOLOGY.md)。
4. 按 [树莓派部署说明](DEPLOY_RASPBERRY_PI.md) 执行 `sh deploy-client.sh`。
5. 打开 `https://hive.hahapiggy.vip:8931`。

服务端和树莓派客户端需要一起更新。本版客户端会读取 readsb 的 `seen_pos`，分别记录“最后信号时间”和“最后位置时间”；只更新群晖而不更新客户端时，服务端会兼容旧数据，但连续航迹推算的时间精度会较低。

## 地图缓存与坐标

浏览时请求的 Esri / OpenStreetMap 瓦片会保存到设备本地 `data/map-tiles.sqlite3`，主地图与详情地图共用；刷新网页和重启后仍可复用。默认限制图片总量为 512 MB，可通过 `MAP_TILE_CACHE_MAX_MB` 修改，SQLite 元数据另占空间。超限时淘汰最久未使用的瓦片。

缓存遵守地图源的 HTTP 有效期，缺省为 7 天，过期后按 ETag / Last-Modified 更新。只下载实际浏览的区域和缩放级别；未缓存或过期区域仍需联网，缓存不代表整个应用支持离线运行。底图来源和缩放级别分别存储，切换地图不会混用。

当前 Esri 和 OpenStreetMap 均按 WGS-84 显示，接收站经纬度应填写 GPS / ADS-B 的原始坐标。飞机图标包含短时位置外推，与其他应用比较时须对齐时间戳。

## 在命令行查看航空器

在设备项目目录执行：

```sh
sudo sh client/watch-aircraft.sh
sudo sh client/watch-aircraft.sh --once
sudo sh client/watch-aircraft.sh --json --once
```

脚本自动识别 Compose 的 `adsb-client` 服务，直接读取 readsb 状态，无需重建接收器。每秒输出 ICAO、呼号、高度、速度、航向、经纬度及信号强度；`--interval 5` 修改刷新间隔，`--json` 输出完整 JSON，`ADSB_CONTAINER` 可指定容器。没有航空器、数据过期或文件暂不可读时会显示相应提示。

## 目录

```text
sky-tracker/
├── deploy-synology.sh       群晖一键部署脚本
├── docker-compose.yml       群晖服务编排
├── server/                  API、SQLite 和网页
├── client/                  树莓派 readsb 与上报程序
├── tests/                   解码、数据库和接口测试
├── DEPLOY_SYNOLOGY.md
└── DEPLOY_RASPBERRY_PI.md
```

## 安全与容量

- 写入 API 必须使用部署时随机生成的上报密钥；网页和只读 API 默认不要求登录，适合放在自有局域网或由 DSM 反向代理负责访问控制。
- 默认端口为 TCP `8931`。
- HTTPS 直接使用脚本目录旁 `../SSL/privkey.pem` 和 `../SSL/fullchain.pem`，证书目录以只读方式映射进容器。
- 原始报文量取决于天线位置和空域繁忙程度。默认 90 天通常会积累数 GB 数据；存储较小时可把 `RETENTION_DAYS` 改成 `30`。
- SQLite 使用 WAL 模式。备份时在项目根目录执行 `sudo docker compose stop adsb-server`，再完整复制 `data/`；备份后执行 `sudo docker compose start adsb-server`。
- 飞机与航线资料补全默认访问 `https://api.adsbdb.com`。查询在后台单线程限速执行，失败不会阻塞 ADS-B 上报；航线按呼号匹配，可能是计划或常见航线，并不等于本次飞行的实时航路。
