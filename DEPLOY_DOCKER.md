# SkyTrace Docker deployment

The Raspberry Pi deployment is defined by the root `docker-compose.yml`. It runs the API/UI, RTL-SDR receiver, hardware bridge, and Piper TTS as containers. Faster Whisper ASR and Ollama run as separate Docker services on a Mac and are reached over Tailscale.

The active source and device directory is `sky-tracker`. The old local
`personal-projects/adsb-tracker` copy has been archived and must not be deployed.

## Upgraded device (2026-10-21)

The device uses `/home/pi/sky-tracker`. `/home/pi/adsb-tracker` is a compatibility
symlink for existing mounts and launchers, not a second checkout. The existing
device `.env` retains `COMPOSE_PROJECT_NAME=adsb-tracker` so its named volumes,
network and running receiver remain the same. New installations use
`COMPOSE_PROJECT_NAME=sky-tracker`. Do not change an existing Compose project name
without migrating its volumes.

Version 1.5.1 adds the device Settings panel, persistent Esri / OpenStreetMap tile
cache and `client/watch-aircraft.sh`. Settings are stored in
`data/feature-settings.json`; tiles in `data/map-tiles.sqlite3`. Both survive image
rebuilds. `MAP_TILE_CACHE_MAX_MB` defaults to 512. The settings panel is available
at the top of the normal page and via the gear button in kiosk mode.

Before this upgrade, the source/configuration and desktop launcher were backed
up to `/home/pi/skytrace-backups/20261021-1.5.1/`. The previous server image is
retained as `skytrace-server:rollback-20261021`. The existing receiver, hardware
and TTS containers do not need rebuilding for this upgrade.

## Configure

```sh
cp .env.example .env
```

Set a random `INGEST_API_KEY`. The default mode uses deterministic pilot response templates and does not start Ollama:

```env
DIALOGUE_LLM_ENABLED=false
FASTER_WHISPER_MODEL=small.en
```

On the Mac, set both `ASR_BIND_ADDRESS` and `LLM_BIND_ADDRESS` to its Tailscale
IPv4 address, then start the inference services:

```sh
docker compose -p skytrace-asr -f docker-compose.asr.yml up -d --build
```

On the Pi, set `DIALOGUE_ASR_URL=http://100.x.y.z:8903/recognize` and
`DIALOGUE_OLLAMA_URL=http://100.x.y.z:8904`. Both machines must be connected to
the same tailnet. Both inference ports are bound only to the selected Tailscale
address, not to all network interfaces.

`small.en` is the recommended English ASR model. The ASR service also uses beam
search, speech VAD, and aviation vocabulary hints. Use
`FASTER_WHISPER_BEAM_SIZE=3` only if lower recognition latency is more important
than maximum accuracy.

## Start fixed-template mode

```sh
sudo docker compose build
sudo docker compose up -d
```

## Enable Ollama pilot simulation

The Ollama image plus Gemma 4 E2B requires roughly 10 GB of additional Mac
storage. Keep at least 12 GB free before enabling it. Set the initial Pi defaults:

```env
DIALOGUE_LLM_ENABLED=true
DIALOGUE_OLLAMA_URL=http://100.x.y.z:8904
DIALOGUE_OLLAMA_MODEL=gemma4:e2b
```

After saving any preferences in **Settings**, the saved device preferences take
precedence over the initial boolean environment defaults. Use **LLM responses**
to toggle the model at runtime. **Voice responses** controls spoken output and
**Voice questions** controls hardware questions. These switches do not start or
stop the inference containers.

The one-shot Mac `ollama-model-download` service downloads the selected GGUF
with resumable 16 MiB range requests and verifies its size and SHA-256 digest.
The `ollama-model` service then imports it into the persistent `ollama-data`
volume. Until the model is ready, questions safely fall back to deterministic
templates.

The Mac inference Compose uses DaoCloud mirrors for Docker Hub, Tsinghua's PyPI
mirror, and ModelScope for both Faster Whisper and Gemma model files. The local
Ollama name remains `gemma4:e2b`, so the application model name is unchanged.
Ollama is pinned to the tested `0.40.6` image because older releases such as
`0.15.1` cannot load the Gemma 4 GGUF architecture.

## Controls

- Short Whisplay press: select the aircraft nearest the visible map center and play the normal fixed introduction.
- Hold Whisplay while speaking, then release: transcribe the question and answer as the selected pilot.
- With LLM disabled or unavailable, altitude, route, origin, speed, heading, vertical-rate, and callsign questions use fixed templates based on live ADS-B data.

## Status and rollback

```sh
sudo docker compose ps
sudo docker compose logs -f --tail=100
sudo docker compose down
```

Do not delete `data/` or Docker volumes during rollback. The previous systemd services can be restarted if needed.
