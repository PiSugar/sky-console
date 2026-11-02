# Synology deployment

## 1. Upload the directory

Upload the entire `adsb-tracker` directory to Synology, for example:

```text
/volume1/docker/adsb-tracker/
```

The configured mapping creates the database one level above the script directory:

```text
/volume1/docker/data/abs_d/adsb.sqlite3
```

Docker volume mapping:

```text
../data/abs_d:/data
```

Place SSL certificates in `../SSL` beside the script directory:

```text
/volume1/docker/SSL/privkey.pem
/volume1/docker/SSL/fullchain.pem
```

The container mounts them read-only:

```text
../SSL:/ssl:ro
```

## 2. Run the deployment script

Connect to Synology over SSH and run:

```sh
cd /volume1/docker/adsb-tracker
sudo sh deploy-synology.sh
```

The script:

1. Checks Docker and Compose.
2. Creates `.env`.
3. Generates a random ingest key with 64 hexadecimal characters.
4. Creates `../data/abs_d`.
5. Builds and starts the service.
6. Waits for the health check to pass.
7. Generates `client.env` for the Raspberry Pi.

Running the script again reuses the existing `.env` and database without resetting the key or history.

## 3. Open the port

The default HTTPS web UI and API URL is:

```text
https://hive.hahapiggy.vip:8931
```

Allow TCP `8931` in:

- DSM Control Panel → Security → Firewall.
- The router's IPv6 firewall.
- For IPv4, configure port forwarding to Synology as well.

Live updates use `wss://hive.hahapiggy.vip:8931/ws/v1/live` on the same port; no additional WebSocket port is needed.

To change the port before the first deployment:

```sh
PUBLIC_PORT=9443 sudo -E sh deploy-synology.sh
```

Alternatively, edit the generated `.env` and run the script again.

## 4. Renew HTTPS certificates

The server serves HTTPS directly with `../SSL/privkey.pem` and `../SSL/fullchain.pem`; DSM does not need to terminate TLS through a reverse proxy. After renewing or replacing certificates, restart the container so Uvicorn reloads them:

```sh
cd /volume1/docker/adsb-tracker
sudo docker compose restart
```

## 5. Management commands

```sh
cd /volume1/docker/adsb-tracker

# Check status
sudo docker compose ps

# Follow logs
sudo docker logs -f adsb-tracker-server

# Restart
sudo docker compose restart

# Stop while retaining the database
sudo docker compose down

# Rebuild after updating the source
sudo sh deploy-synology.sh
```

Health endpoint:

```text
https://hive.hahapiggy.vip:8931/healthz
```

Example healthy response:

```json
{"status":"ok","database":"ok","version":"1.3.4"}
```

## 6. Retention and backups

Set the retention period in `.env`:

```text
RETENTION_DAYS=90
```

The application removes expired raw messages and tracks every hour. Aircraft first/last seen timestamps and cumulative counts are retained.

The server fetches aircraft registration, type, airline, and public route information from ADSBDB in the background and caches it in the same SQLite database. Synology needs outbound access to `https://api.adsbdb.com`. Query failures do not affect reception, uploads, or historical storage.

Related `.env` settings:

```text
ENRICHMENT_ENABLED=true
ENRICHMENT_BASE_URL=https://api.adsbdb.com/v0
ENRICHMENT_SUCCESS_HOURS=168
ENRICHMENT_RETRY_HOURS=6
ENRICHMENT_TIMEOUT_SECONDS=8
```

To disable external enrichment, set `ENRICHMENT_ENABLED=false` and run the deployment script again.

For a safe backup:

```sh
cd /volume1/docker/adsb-tracker
sudo docker compose stop
# Copy ../data/abs_d to your backup location now
sudo docker compose start
```
