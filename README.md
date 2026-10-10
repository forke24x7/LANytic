# LANytic

Ein aufgeräumter, selbst hostbarer Überblick über dein LAN. Geräte per ARP entdecken, als **Known** markieren und mit eigenen Namen und Beschreibungen versehen. Eigenständige Implementierung, kein WatchYourLAN-Fork.

## Funktionen

- Automatische und manuelle IPv4-ARP-Scans auf einem oder mehreren Interfaces.
- Persistente Geräteübersicht mit Online-/Offline-Status, MAC, IP und Hersteller.
- Known-Markierung, eigene Gerätenamen und Beschreibungen; bleiben bei IP-Wechsel erhalten.
- Suche, Known-/Status-Filter, Sortierung und CSV-Export der gefilterten Liste.
- Scan-Verlauf (letzte 100 Durchläufe), verständliche Fehleranzeige.
- Responsive deutsche Oberfläche; keine CDNs, Tracker oder externen Fonts.
- SQLite-Datenvolume, HTTP-Basic-Auth, Healthcheck und Docker Compose.

## Docker Compose auf deinem Linux-Server

Voraussetzung: Docker Engine mit Compose v2 und ein LAN-Interface auf dem Host.

```sh
cp .env.example .env
ip -br link
```

In `.env` mindestens `IFACES` und ein eigenes `AUTH_PASSWORD` eintragen. Mehrere Interfaces werden mit Leerzeichen getrennt, beispielsweise `IFACES=eth0 eth0.20`. Anschließend:

```sh
docker compose up -d --build
docker compose logs -f
```

Öffne `http://SERVER-IP:8840`. Der Browser fragt nach Benutzername (Standard: `admin`) und deinem Passwort. Der erste Scan startet automatisch, danach standardmäßig alle 120 Sekunden. Passwort und echte Netzwerkdaten gehören nicht ins Repository; `.env` und `data/` sind ausgeschlossen.

`network_mode: host` ist für den direkten ARP-Zugriff vorgesehen. Deshalb gibt es kein `ports:`-Mapping; `PORT` bestimmt den Port auf dem Host. Das Compose-Setup ist für **Linux** gedacht. Docker Desktop auf macOS/Windows besitzt keinen gleichwertigen direkten Zugriff auf das physische LAN; für die Oberfläche nutze dort den Demo-Modus.

Das Image läuft als root mit ausschließlich `NET_RAW` und `NET_ADMIN`, weil `arp-scan` Rohpakete und das Host-Interface benötigt. Es nutzt kein `privileged: true`. Das Root-Dateisystem ist schreibgeschützt; nur `/data` und `/tmp` sind beschreibbar. Installierte Programme und OUI-Herstellerdaten stammen aus Debian-Paketen.

HTTP-Basic-Auth über HTTP verschlüsselt das Passwort nicht. Für Zugriff außerhalb deines vertrauten LANs verwende einen HTTPS-Reverse-Proxy oder VPN und beschränke den direkten Host-Port per Firewall. Der Proxy muss den ursprünglichen `Host`-Header weiterreichen. Für ausschließlich lokalen Proxyzugriff lässt sich `HOST=127.0.0.1` setzen. LANytic ist ein LAN-Werkzeug, kein öffentlicher Internetdienst.

### Betrieb und Updates

```sh
git pull
docker compose up -d --build
docker compose ps
docker compose logs --tail=100
```

Alle Gerätedaten liegen im benannten Volume `lanytic-data` (Compose versieht es mit einem Projektpräfix). `docker compose down` erhält das Volume; `down -v` löscht es. Vor Backup den Dienst stoppen und das Datenvolume sichern, damit SQLite-Datei und WAL konsistent bleiben. Konfigurationsänderungen werden nach `docker compose up -d` übernommen.

## Demo ohne LAN-Zugriff

```sh
docker compose -f docker-compose.demo.yml up -d --build
```

Öffne `http://localhost:8841`. Die Demo enthält klar gekennzeichnete Beispieldaten mit synthetischen MAC-Adressen und ein eigenes Datenvolume. Bearbeiten, Filtern und Speichern funktionieren; Demo-Scans simulieren einen Durchlauf. Es werden keine echten ARP-Pakete gesendet.

Alternativ ohne Docker, mit Python 3.9+ und ohne Python-Abhängigkeiten:

```sh
DEMO=true PORT=8841 python3 app.py
```

## Konfiguration

| Variable | Standard | Bedeutung |
|---|---|---|
| `IFACES` | leer | Host-Interfaces, mit Leerzeichen getrennt; live erforderlich |
| `SCAN_INTERVAL` | `120` | Abstand nach abgeschlossenem Scan in Sekunden (mindestens 10) |
| `SCAN_TIMEOUT` | `60` | Zeitlimit je Interface in Sekunden (1–600) |
| `PORT` | `8840` | HTTP-Port |
| `HOST` | `127.0.0.1` nativ, `0.0.0.0` im Image/Compose | Bind-Adresse |
| `DB_PATH` | `data/lan.sqlite3` nativ, `/data/lan.sqlite3` im Container | Datenbankdatei |
| `AUTH_USER` | `admin` | HTTP-Basic-Benutzer |
| `AUTH_PASSWORD` | leer nativ, erforderlich in Live-Compose | HTTP-Basic-Passwort |
| `DEMO` | `false` | Beispieldaten und simulierte Scans |
| `TZ` | `Europe/Berlin` in Compose | Zeitzone für Container-Logs |

Zeitstempel in SQLite und der API sind UTC; die Oberfläche zeigt sie in der lokalen Browser-Zeitzone.

## Erkennung und Grenzen

Die Geräteidentität ist `(MAC-Adresse, Interface)`. Ein IP-Wechsel überschreibt nur die aktuelle IP, nicht deine eigenen Angaben. Dieselbe MAC auf mehreren Interfaces wird separat geführt. Private/zufällig wechselnde MAC-Adressen erscheinen als neue Geräte.

ARP erreicht das lokale IPv4-Broadcast-Segment, keine gerouteten Netze oder IPv6-Geräte. VLANs benötigen passende Host-Interfaces. Es gibt keine Port-Scans, DNS-Namensauflösung oder Benachrichtigungen in dieser ersten Version. Der Hersteller stammt aus der mit `arp-scan` gelieferten OUI-Datenbank und kann unbekannt sein.

Online bedeutet: Das Gerät hat beim letzten erfolgreichen Scan geantwortet. Eine fehlende Antwort bedeutet Offline, kann aber auch durch Schlafmodus oder Paketverlust entstehen. Bei einem Fehler oder Timeout auf einem Interface wird der gesamte Durchlauf verworfen und der letzte Gerätestatus bleibt bestehen. Entfernte Interfaces behalten ihren letzten Stand; das Interface und der letzte Sichtungszeitpunkt sind in den Details sichtbar. Alte Geräte werden bewusst nicht automatisch gelöscht.

## Entwicklung und Tests

```sh
python3 -m unittest discover -s tests -v
```

Die Tests prüfen Parser, IP-Wechsel, persistente Metadaten, Fehler/Timeouts, parallele Scan-Anforderungen, API-Validierung, Auth und CSRF-Schutz. GitHub Actions führt sie aus, baut das Docker-Image und startet einen Demo-Container als Smoke-Test.

API: `GET /api/state`, `POST /api/scan` mit `{}`, `PATCH /api/devices/<id>` mit `known`, `name` und/oder `description`. Schreibanfragen benötigen `Content-Type: application/json`. `GET /healthz` prüft den HTTP-Dienst, nicht die Scanner-Funktion; dafür den Scan-Verlauf ansehen.

Technischer Hintergrund und die Abgrenzung zu WatchYourLAN: [docs/architecture.md](docs/architecture.md).
