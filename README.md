# SkyTrace ADS-B Console

This project is developed and deployed from `sky-tracker` (remote repository: `PiSugar/sky-console`).

SkyTrace receives 1090 MHz ADS-B signals on a Raspberry Pi and provides a live map, aircraft information, hardware controls, and optional voice and LLM questions. Docker Compose runs the receiver, API, hardware bridge, and TTS on the device. A Mac provides ASR and model inference. Device settings and map tiles persist locally.

## Features

- **Live map:** WebSocket updates show aircraft heard within the last 90 seconds and receiver status. Short-term positions are extrapolated from the latest ADS-B coordinates, ground speed, heading, and timestamps, then smoothly corrected when new messages arrive. Animation frequency adapts to zoom, and extrapolation stops after prolonged signal loss. Switch between English Esri and OpenStreetMap basemaps; both use ADS-B WGS-84 coordinates directly. Supports dragging empty map areas, mouse-wheel zoom, and mobile touch controls.
- **Aircraft information:** Background ADSBDB queries by ICAO address and callsign cache registration, manufacturer, type, registered owner, airline, and public route information in SQLite. Both passenger-facing IATA flight numbers and ADS-B ICAO callsigns are displayed. Airline and airport names follow the browser language, preferring Chinese names for Chinese browsers and falling back to source names when translations are unavailable. Map tooltips include both flight numbers, airline, and localized routes.
- **Mobile quick information:** Tapping an aircraft on a touch device or narrow screen opens a compact card at the bottom of the map. It emphasizes airline and aircraft type, with both flight numbers, altitude, speed, and heading. Tap **Flight details** to open the full drawer or an empty map area to dismiss the card.
- **Historical records:** Search previously received aircraft by ICAO address, callsign, registration, manufacturer, type, owner, or airline.
- **Aircraft details:** Inspect historical tracks, cumulative message counts, and individual Mode S / ADS-B messages, including bit fields, decoded values, Chinese explanations, CRC, and learning tips.
- **Reliable uploads:** The Pi uploads batches with idempotent IDs, preventing duplicate records on network retries.
- **Offline queue:** When the Synology server or network is unavailable, batches remain in a local SQLite queue and upload automatically after recovery.
- **Retention:** Raw messages and tracks are retained for 90 days by default, configurable in `.env`.
- **Automatic recovery:** Server and client containers use `restart: unless-stopped`.

## Feature settings

Open device settings with **Settings** at the top of the normal page or the persistent **⚙ Settings** button at the top right of the full-screen map. Settings remain accessible after selecting an aircraft.

- **Flight details:** The first switch controls airline, route, and aircraft photo lookups. Disabling it stops new external queries while preserving cached information and live ADS-B data. Requests already in progress may finish.
- **Voice responses:** Controls aircraft introductions and spoken answers. Disabling it stops current speech but preserves the aircraft selection beep and text answers.
- **Voice questions:** Controls questions triggered by holding the hardware button. Disabling it stops speech recognition and answer generation.
- **LLM responses:** Controls model-generated answers. When disabled or a model request fails, fixed response templates are used. This preference is retained when voice questions are disabled and applies again when they are enabled.

Settings save immediately to `feature-settings.json` alongside the history database (`/data` in Docker), require no restart, and synchronize to other pages over WebSocket. On first run, flight detail fetching, `RADIO_ENABLED`, and `DIALOGUE_LLM_ENABLED` use deployment defaults; voice questions default to disabled. Saved panel preferences take precedence afterward. Model, ASR, and audio services must be deployed separately; switches do not start or stop Docker services.

Before enabling voice questions, the application checks ASR health. Before enabling LLM responses, it also checks ASR, Ollama, and whether the configured model is installed. Unavailable switches remain disabled and explain why. Startup checks disable saved switches whose services are unavailable. After configuring services, click **Check services again**, then enable them. The ASR health URL defaults to `healthz` beside the recognition endpoint and can be overridden with `DIALOGUE_ASR_HEALTH_URL`. The backend enforces the same checks through the API. If a service disconnects during use, questions stop or fall back to fixed answers.

Access follows the hardware control policy: the device itself and Docker internal network can change settings; remote browsers are read-only. Remote management tools can use the existing ingest key with `PATCH /api/v1/settings`, the header `Authorization: Bearer <INGEST_API_KEY>`, and a JSON body containing only the boolean fields to update: `enrichment_enabled`, `radio_enabled`, `dialogue_enabled`, and `dialogue_llm_enabled`. If saving fails, the previous settings remain active and an error is shown.

## Data flow

```text
RTL2832U / R820T USB receiver
        ↓ 1090 MHz
Raspberry Pi readsb (validation, decoding, position calculation)
        ↓ Batch uploads every 5 seconds; local queue while offline
Raspberry Pi FastAPI service
        ├─→ ADSBDB (public aircraft/flight information, cached locally)
        ↓
data/adsb.sqlite3 (history database)
        ↓
Live map / aircraft records / raw message details
```

## Quick deployment

The current Pi deployment uses the root Docker Compose configuration for the UI, hardware, and ADS-B services. The Mac uses `docker-compose.asr.yml` for ASR and Ollama and connects to the Pi over Tailscale. See the [Docker deployment guide](DEPLOY_DOCKER.md). Fixed-template introductions and hold-to-ask questions remain available without an LLM.

1. Run `cp .env.example .env` and change at least `INGEST_API_KEY`.
2. Run `sudo docker compose build`.
3. Run `sudo docker compose up -d`, then check `sudo docker compose ps`.

The separate Synology server deployment is documented in the [Synology deployment guide](DEPLOY_SYNOLOGY.md). For that deployment, follow the [Raspberry Pi client guide](DEPLOY_RASPBERRY_PI.md) to run `sh deploy-client.sh`, then open `https://hive.hahapiggy.vip:8931`.

Update the server and Pi client together. The current client reads readsb's `seen_pos` and records the last signal time separately from the last position time. The server accepts older client data, but updating only Synology reduces timing accuracy for continuous track extrapolation.

## Display and touchscreen rotation

On a Pi using labwc and kanshi, configure both display orientation and the touch calibration matrix. Rotating only the display leaves touch input misaligned. Run from the project directory on the Pi:

```sh
chmod +x runtime/configure-display-rotation.sh
./runtime/configure-display-rotation.sh 270
sudo reboot
```

The first argument accepts `normal`, `0`, `90`, `180`, or `270`. The default output is `DSI-1`, and the default touch device is `Goodix Capacitive TouchScreen`. On the `.253` device, labwc's output mapping handles the Goodix touchscreen without extra rotation, so the fourth argument defaults to `0°`. Use the fourth argument only when other hardware has a touch sensor whose native orientation differs from the display panel. The second and third arguments override the output and touch device names:

```sh
./runtime/configure-display-rotation.sh 90 DSI-2 "10-005d Goodix Capacitive TouchScreen"
```

The script updates the SkyTrace-managed output profile in `~/.config/kanshi/config` and writes the touchscreen output mapping and calibration matrix to `~/.config/labwc/rc.xml`. Omitting the fourth argument uses the identity matrix so touch follows labwc's output mapping. Before editing, the script creates backups in the same directories with UTC timestamps. Reboot afterward because labwc does not reliably apply matrix changes to existing touch devices at runtime.

## Map cache and coordinates

Esri / OpenStreetMap tiles requested while browsing are cached locally in `data/map-tiles.sqlite3`, shared by the main and detail maps and retained across page reloads and restarts. Cached image data is limited to 512 MB by default; set `MAP_TILE_CACHE_MAX_MB` to change it. SQLite metadata uses additional space. Least recently used tiles are evicted when the limit is exceeded.

The cache respects each provider's HTTP expiration, defaulting to 7 days, and refreshes expired tiles using ETag / Last-Modified. Only viewed areas and zoom levels are downloaded. Uncached or expired areas still require internet access; tile caching does not make the entire application work offline. Providers and zoom levels are stored separately.

Both Esri and OpenStreetMap use WGS-84. Enter the receiver's original GPS / ADS-B coordinates. Aircraft icons include short-term position extrapolation, so align timestamps when comparing with other applications.

## View aircraft in the terminal

Run from the project directory on the device:

```sh
sudo sh client/watch-aircraft.sh
sudo sh client/watch-aircraft.sh --once
sudo sh client/watch-aircraft.sh --json --once
```

The script detects the Compose `adsb-client` service and reads readsb status directly without rebuilding the receiver. All prompts are in English. In an interactive terminal, it refreshes in place every second, like `top`; press `q` or `Ctrl+C` to exit and restore the terminal. It shows ICAO address, callsign, altitude, speed, heading, coordinates, and signal strength. Rows beyond the window are counted as hidden; enlarge the window to see more. Use `--interval 5` to change the refresh interval, `--once` for one snapshot, `--json` for complete JSON, or `ADSB_CONTAINER` to select a container. Pipes and redirection receive plain text without terminal control characters. Messages explain when no aircraft are present, data is stale, or the file is temporarily unreadable.

Changed cells appear in light blue for one refresh cycle without changing the background. Newly appearing aircraft have their entire row highlighted. The initial display has no highlights, and unchanged values use the default text color.

## Model files

Model files are available in the [PiSugar suit-cases repository](https://github.com/PiSugar/suit-cases/tree/main/pi5-whisplay-plus-skytracker).

## Directory layout

```text
sky-tracker/
├── deploy-synology.sh       Synology deployment script
├── docker-compose.yml      Service orchestration
├── runtime/                Kiosk startup and display/touch configuration
├── server/                 API, SQLite, and web UI
├── client/                 Raspberry Pi readsb and upload agent
├── tests/                  Decoder, database, and API tests
├── DEPLOY_SYNOLOGY.md
└── DEPLOY_RASPBERRY_PI.md
```

## Security and storage

- Write APIs require the randomly generated ingest key. The web UI and read-only APIs do not require login by default; use a trusted LAN or access controls provided by a DSM reverse proxy.
- The default port is TCP `8931`.
- HTTPS uses `../SSL/privkey.pem` and `../SSL/fullchain.pem` beside the script directory, mounted read-only into the container.
- Raw message volume depends on antenna placement and air traffic. The default 90-day retention can consume several GB; set `RETENTION_DAYS=30` for smaller storage.
- SQLite uses WAL mode. To back up the current Pi deployment, run `sudo docker compose stop adsb-server` from the project root, copy the entire `data/` directory, then run `sudo docker compose start adsb-server`.
- Aircraft and route enrichment uses `https://api.adsbdb.com` by default. Background queries run in a single rate-limited worker; failures do not block ADS-B uploads. Routes matched by callsign may be scheduled or typical routes rather than the actual route of the current flight.
