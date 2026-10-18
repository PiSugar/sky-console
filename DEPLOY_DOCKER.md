# SkyTrace Docker deployment

The Raspberry Pi deployment is defined by the root `docker-compose.yml`. It runs the API/UI, RTL-SDR receiver, hardware bridge, Faster Whisper ASR, and Piper TTS as containers. Ollama is optional.

## Configure

```sh
cp .env.example .env
```

Set a random `INGEST_API_KEY`. The default mode uses deterministic pilot response templates and does not start Ollama:

```env
DIALOGUE_LLM_ENABLED=false
```

## Start fixed-template mode

```sh
sudo docker compose build
sudo docker compose up -d
```

## Enable Ollama pilot simulation

The ARM64 Ollama image plus Gemma 4 E2B requires roughly 10 GB of additional
storage. Keep at least 12 GB free before enabling it. Enable it explicitly:

```env
DIALOGUE_LLM_ENABLED=true
DIALOGUE_OLLAMA_MODEL=gemma4:e2b
```

```sh
sudo docker compose --profile llm up -d
```

The one-shot `ollama-model` service downloads the selected model into the persistent `ollama-data` volume. Until the model is ready, questions safely fall back to deterministic templates.

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
