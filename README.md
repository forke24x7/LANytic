# LANytic

A clean, self-hosted view of your LAN. Discover devices with ARP, mark them as **Known**, and add your own names and descriptions.

## Features

- Automatic and manual IPv4 ARP scans across one or more host interfaces.
- Persistent inventory with online/offline status, IP, MAC, and vendor.
- Known status, custom names, and descriptions that survive IP changes.
- Search, Known/status filters, sorting, and filtered CSV export.
- Scan history with the latest 100 runs and explicit error details.
- English interface with Light / Dark / System appearance, matching Simple SMTP Test. Your theme choice is remembered locally; system mode follows OS changes.
- Responsive layout; no CDNs, trackers, or external fonts.
- SQLite volume, HTTP Basic authentication, healthcheck, and Docker Compose.

## Docker Compose on Linux

Requirements: Docker Engine with Compose v2 and a host LAN interface.

```sh
git clone https://github.com/forke24x7/LANytic.git
cd LANytic
cp .env.example .env
```

### Find your LAN interface

Run this on the **Linux Docker host**, not inside the container:

```sh
ip -br -4 addr
```

Choose the interface with the IPv4 address of the LAN you want to scan. For example:

```text
enp3s0           UP             192.168.178.10/24
```

In this example, set `IFACES=enp3s0`. Interface names vary, e.g. `eth0`, `eno1`, or `br0` when the host uses a LAN bridge. Do not choose `lo` or `docker0` for scanning your physical LAN.

To see which interface the host uses for its default route:

```sh
ip -4 route show default
```

The name following `dev` is the interface. If the default route uses a VPN or a different network, choose the LAN interface from the address list instead.

### Sample `.env`

Save this as `.env` next to `docker-compose.yml`. Replace `enp3s0` with your interface and set your own password before starting:

```dotenv
IFACES=enp3s0
PORT=8840
HOST=0.0.0.0
SCAN_INTERVAL=120
SCAN_TIMEOUT=60
TZ=Europe/Berlin
AUTH_USER=admin
AUTH_PASSWORD='replace-with-a-long-unique-password'
```

Multiple interfaces are space-separated, e.g. `IFACES=enp3s0 enp3s0.20`. Host networking lets the container scan these host interfaces directly.

### Start LANytic

```sh
docker compose up -d --build
docker compose logs -f
```

Open `http://SERVER-IP:8840`. Sign in with `admin` (or your configured user) and your password. The first scan starts automatically, then repeats every 120 seconds by default. `.env` and database files are excluded from Git.

The live setup uses **Linux host networking**, with no `ports:` mapping; `PORT` controls the port on the host. Docker Desktop on macOS/Windows does not provide equivalent ARP access to the physical LAN.

The image runs as root with only `NET_RAW` and `NET_ADMIN` capabilities for `arp-scan`. It does not use `privileged: true`. The root filesystem is read-only; `/data` and `/tmp` are writable. The scanner and its vendor database come from Debian packages.

HTTP Basic authentication over plain HTTP does not encrypt credentials. Use an HTTPS reverse proxy or VPN for access outside your trusted LAN and restrict direct access to the host port. A reverse proxy must preserve the original `Host` header. Set `HOST=127.0.0.1` for a proxy on the same host when appropriate.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `IFACES` | empty | Space-separated host interfaces; required for live scans |
| `SCAN_INTERVAL` | `120` | Seconds after scan completion, minimum 10 |
| `SCAN_TIMEOUT` | `60` | Timeout per interface, 1–600 seconds |
| `PORT` | `8840` | HTTP port |
| `HOST` | `127.0.0.1` natively, `0.0.0.0` in Docker | Bind address |
| `DB_PATH` | `data/lan.sqlite3` natively, `/data/lan.sqlite3` in Docker | SQLite path |
| `AUTH_USER` | `admin` | HTTP Basic username |
| `AUTH_PASSWORD` | empty natively, required in live Compose | HTTP Basic password |
| `TZ` | `Europe/Berlin` in Compose | Container log timezone |

Database/API timestamps use UTC. The English UI formats timestamps in your browser's local timezone. Container configuration changes take effect after `docker compose up -d`.

## Operation

```sh
git pull
docker compose up -d --build
docker compose ps
docker compose logs --tail=100
```

Device data lives in the `lanytic-data` named volume (prefixed by the Compose project name). `docker compose down` preserves it; `down -v` deletes it. Stop the service before backing up the entire volume so the SQLite database and WAL remain consistent.

## Discovery limits

Identity is `(MAC address, interface)`. IP changes do not overwrite your custom information. The same MAC on different interfaces is tracked separately; randomized MAC addresses can appear as new devices.

ARP discovers the local IPv4 broadcast segment, not routed subnets or IPv6 devices. VLANs need corresponding host interfaces. This version has no port scanning, DNS name lookup, or notifications. Vendors come from the OUI database bundled with `arp-scan` and may be unknown.

Online means a device responded during the last successful scan. No response means Offline, which may also reflect sleep mode or packet loss. If any interface fails or times out, the entire run is discarded and the previous device status is preserved. Removed interfaces keep their last observed status; the interface and last-seen time are visible in device details. Old devices are not automatically deleted.

## Development

```sh
python3 -m unittest discover -s tests -v
```

Tests cover parsing, IP changes, persistent metadata, failures/timeouts, concurrent scan requests, API validation, authentication, and CSRF protection. GitHub Actions also builds the Docker image, starts the application container, and validates the Compose configuration.

API: `GET /api/state`, `POST /api/scan` with `{}`, `PATCH /api/devices/<id>` with `known`, `name`, and/or `description`. Writes require `Content-Type: application/json`. `GET /healthz` checks the HTTP service; inspect scan history for scanner health.

See [docs/architecture.md](docs/architecture.md) for the technical background.
