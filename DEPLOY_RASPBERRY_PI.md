# Raspberry Pi client deployment

The client accesses the RTL2832U USB receiver directly on the Raspberry Pi, runs `readsb` with RTL-SDR support, and uploads aircraft states and raw messages to Synology in batches.

## 1. Prepare the directory and configuration

Running `deploy-synology.sh` on Synology generates `client.env` in the project root. Copy it into the Pi's `client` directory:

```text
client/
├── client.env
├── docker-compose.yml
├── Dockerfile
├── agent.py
├── entrypoint.sh
└── deploy-client.sh
```

Set the receiver coordinates to display the antenna on the map and support some local CPR position calculations:

```text
RECEIVER_LAT=<receiver latitude>
RECEIVER_LON=<receiver longitude>
```

Three or four decimal places are sufficient; an exact street address is unnecessary.

## 2. Start the client

```sh
cd client
sh deploy-client.sh
```

The first build compiles ARM64 `readsb` from source. Build time depends on the network and Pi performance. Subsequent updates normally reuse the Docker cache.

## 3. Check status

```sh
docker ps --filter name=adsb-tracker-client
docker logs -f adsb-tracker-client
```

Normal logs identify the receiver and tuner:

```text
using device #0: Generic RTL2832U
Found Rafael Micro R820T tuner
```

The upload agent also reports its connection to readsb's raw message port and cumulative upload counts. These agent messages may appear in Chinese.

## 4. Key settings

| Variable | Default | Description |
|---|---|---|
| `SERVER_URL` | `https://hive.hahapiggy.vip:8931` | Synology HTTPS service URL |
| `API_KEY` | Generated automatically | Ingest key; must match the server |
| `RECEIVER_ID` | `devpn` | Unique receiver ID |
| `UPLOAD_INTERVAL` | `5` | Upload interval in seconds |
| `RTL_GAIN` | `49.6` | Gain tested with the current receiver, in dB |
| `MAX_BATCH_MESSAGES` | `2000` | Maximum raw messages per batch |
| `MAX_SPOOL_BATCHES` | `10000` | Maximum queued offline batches |

The offline queue is stored in `client/data/spool.sqlite3`. Uploads resume automatically when Synology becomes available.

## 5. USB considerations

Compose maps `/dev/bus/usb` and permits USB character devices. At startup, `readsb` temporarily detaches the receiver from the DVB driver; a normal container shutdown reattaches it.

The client uses host networking to reach `hive.hahapiggy.vip` through the Pi's IPv6 route. The readsb raw message port binds only to `127.0.0.1:30002` and is not exposed to the LAN.

Stop the client normally:

```sh
docker compose stop
```

Avoid routinely forcing shutdown with `docker kill -s KILL`. If the device is not reattached after a forced shutdown, restarting the client container can still use the receiver. Rebooting the Pi fully restores driver state.
