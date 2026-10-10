# LANytic

A clean, self-hosted view of your LAN. Discover devices with ARP, mark them as **Known**, and add your own names and descriptions.

## About this project

This tool is AI-generated. I work in IT infrastructure and created it to make
keeping track of devices on my local network easier. It is intended to run on a
trusted LAN or behind a reverse proxy with an authentication layer. It has not
been hardened for direct exposure to the public internet.

## Features

- Automatic and manual IPv4 ARP scans across one or more host interfaces.
- Persistent inventory with online/offline status, IP, MAC, vendor, and a Last seen timestamp in your configured timezone.
- Known status, custom names, and descriptions that survive IP changes.
- Search, Known/status filters, sorting, and filtered CSV export.
- Scan history with the latest 100 runs and explicit error details.
- English interface with Light / Dark / System appearance. Your theme choice is remembered locally; system mode follows OS changes.
- Responsive layout; no CDNs, trackers, or external fonts.
- SQLite volume, healthcheck, and Docker Compose.

## Docker Compose on Linux

Requirements: Docker Engine with Compose v2, a host LAN interface, and internet access for the build. Only the Compose file is required on the host; Docker fetches the source and Dockerfile from the public Git repository.

```sh
mkdir -p lanytic
cd lanytic
curl -fsSL https://raw.githubusercontent.com/forke24x7/LANytic/main/docker-compose.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/forke24x7/LANytic/main/.env.example -o .env.example
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

In this example, enter `enp3s0` under **Settings → LAN interfaces**. Interface names vary, e.g. `eth0`, `eno1`, or `br0` when the host uses a LAN bridge. Do not choose `lo` or `docker0` for scanning your physical LAN.

To see which interface the host uses for its default route:

```sh
ip -4 route show default
```

The name following `dev` is the interface. If the default route uses a VPN or a different network, choose the LAN interface from the address list instead.

### Sample `.env`

The optional `.env` next to `docker-compose.yml` only controls the HTTP listener:

```dotenv
PORT=8840
HOST=0.0.0.0
```

Configure LAN interfaces, scan interval, timeout, and timezone in the web interface under **Settings**. Multiple interfaces are space-separated, e.g. `enp3s0 enp3s0.20`. Host networking lets the container scan these host interfaces directly.

### Start LANytic

Compose builds LANytic from the `main` branch. `pull_policy: build` prevents a pull of an unpublished application image. No Docker registry login is required. If your deployment manager only pulls images, enable its build option or run the following command on the Docker host.

```sh
docker compose up -d --build
docker compose logs -f
```

Open `http://SERVER-IP:8840`. On first start, the interface loads without a configured LAN interface. Open **Settings**, enter your LAN interface, and save. The first scan then starts automatically, repeating every 600 seconds (10 minutes) by default. Leave interfaces empty to pause scans. `.env` and database files are excluded from Git.

The live setup uses **Linux host networking**, with no `ports:` mapping; `PORT` controls the port on the host. Docker Desktop on macOS/Windows does not provide equivalent ARP access to the physical LAN.

The image runs as root with only `NET_RAW` and `NET_ADMIN` capabilities for `arp-scan`. It does not use `privileged: true`. The root filesystem is read-only; `/data` and `/tmp` are writable. The scanner and its vendor database come from Debian packages.

LANytic has no built-in authentication. Run it on your trusted LAN or behind an HTTPS reverse proxy with its own authentication layer (e.g. MFA or OIDC), and restrict direct access to the host port. A reverse proxy must preserve the original `Host` header. Set `HOST=127.0.0.1` for a proxy on the same host when appropriate.

## Configuration

Scanner settings are saved in SQLite in the persistent data volume and take effect immediately. Wait for a running scan to finish before saving changes.

| Setting | Default | Purpose |
|---|---|---|
| LAN interfaces | empty | Space-separated Linux host interfaces; scanning stays paused until configured |
| Scan interval | `600` | Seconds after scan completion, minimum 10 |
| Scan timeout | `60` | Timeout per interface, 1–600 seconds |
| Timezone | `Europe/Berlin` | IANA timezone for displayed timestamps and application logs |

HTTP and storage environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8840` | HTTP port |
| `HOST` | `127.0.0.1` natively, `0.0.0.0` in Docker | Bind address |
| `DB_PATH` | `data/lan.sqlite3` natively, `/data/lan.sqlite3` in Docker | SQLite path |

Database/API timestamps remain UTC; the interface displays them in the saved timezone. After updating from an older version, remove `IFACES`, `SCAN_INTERVAL`, `SCAN_TIMEOUT`, and `TZ` from your `.env` and Compose environment, then configure them in Settings. Existing device data is preserved. Listener configuration changes require `docker compose up -d`.

## Operation

```sh
curl -fsSL https://raw.githubusercontent.com/forke24x7/LANytic/main/docker-compose.yml -o docker-compose.yml
docker compose up -d --build
docker compose ps
docker compose logs --tail=100
```

Device data lives in the `lanytic-data` named volume (prefixed by the Compose project name). `docker compose down` preserves it; `down -v` deletes it. Stop the service before backing up the entire volume so the SQLite database and WAL remain consistent.

## Discovery limits

Identity is `(MAC address, interface)`. IP changes do not overwrite your custom information. The same MAC on different interfaces is tracked separately; randomized MAC addresses can appear as new devices.

ARP discovers the local IPv4 broadcast segment, not routed subnets or IPv6 devices. VLANs need corresponding host interfaces. This version has no port scanning, DNS name lookup, or notifications. Vendors come from the OUI database bundled with `arp-scan` and may be unknown.

The Docker host is included using the IPv4 and MAC address of each configured interface. If an interface has multiple IPv4 addresses, its primary address is used; inventory identity remains MAC + interface. The host can be marked Known and given a name or description like any other device.

Online means a device responded during the last successful scan or is the local scanning host. No response means Offline, which may also reflect sleep mode or packet loss. If any interface fails or times out, the entire run is discarded and the previous device status is preserved. Removed interfaces keep their last observed status; the interface and last-seen time are visible in device details. Old devices are not automatically deleted.

## Development

For local source changes, build with `docker build -t lanytic:dev .`; the deployment Compose file always uses the Git repository as its build context.

```sh
python3 -m unittest discover -s tests -v
```

Tests cover parsing, IP changes, persistent metadata, failures/timeouts, concurrent scan requests, unauthenticated API access, input validation, and CSRF protection. GitHub Actions also builds the Docker image, starts the application container, and validates the Compose configuration.

API: `PATCH /api/settings` with `interfaces` (array), `interval`, `timeout`, and `timezone`; `GET /api/state`, `POST /api/scan` with `{}`, `PATCH /api/devices/<id>` with `known`, `name`, and/or `description`. Writes require `Content-Type: application/json`. `GET /healthz` checks the HTTP service; inspect scan history for scanner health.

See [docs/architecture.md](docs/architecture.md) for the technical background.

## License

Licensed under the [MIT License](LICENSE). Free to use, modify, and redistribute,
including commercially, provided the copyright and license notices are retained.
