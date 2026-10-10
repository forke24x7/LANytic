# Technischer Hintergrund

WatchYourLAN ist eine Go-Anwendung. Sein [Scanner](https://github.com/aceberg/WatchYourLAN/blob/main/backend/internal/arp/arpscan.go) ruft `arp-scan` pro Interface auf und liest IP-Adresse, MAC-Adresse und Hersteller aus der Ausgabe. Laut [README](https://github.com/aceberg/WatchYourLAN#readme) werden Geräte und Historie in SQLite oder PostgreSQL gespeichert. Das [Dockerfile](https://github.com/aceberg/WatchYourLAN/blob/main/Dockerfile) installiert `arp-scan` und `tzdata`; der Docker-Start verwendet Host-Networking.

LANytic verwendet dasselbe etablierte Systemwerkzeug zur Erkennung, wurde aber vollständig neu implementiert. Es wurde kein Quellcode, UI, Asset oder Datenbankschema aus WatchYourLAN übernommen.

## LANytic

Browser → Python HTTP-API → SQLite

Manueller Scan oder Scheduler → begrenzter `arp-scan`-Subprozess je Interface → validierte Beobachtungen → eine SQLite-Transaktion

- Python-Standardbibliothek: kein pip, npm oder Build-Schritt erforderlich.
- SQLite/WAL: jeder Request benutzt eine eigene Verbindung. Namen und Beschreibungen werden bei Scan-Upserts nicht überschrieben.
- Scan-Mutex: höchstens ein Durchlauf zur gleichen Zeit; der nächste automatische Scan beginnt nach dem konfigurierten Intervall.
- Ein Durchlauf gilt nur dann als erfolgreich, wenn alle konfigurierten Interfaces erfolgreich gescannt wurden. Fehler setzen keine Geräte offline.
- MAC und Interface bilden eine stabile Identität. IP ist eine veränderliche Beobachtung.
- Parameter werden als Argumentliste ohne Shell ausgeführt; Interface-Namen sind validiert. Die API erlaubt keine freien Scan-Kommandos.
- Statische Dateien werden über eine feste Allowlist ausgeliefert. Die Oberfläche maskiert Geräteangaben vor der HTML-Ausgabe, CSP beschränkt Inhalte auf lokale Assets.
- HTTP-Basic-Auth ist in der Live-Compose-Konfiguration verpflichtend; JSON-Content-Type und Origin-Prüfung schützen Schreibanfragen gegen CSRF.
- Demo- und Live-Daten sind getrennt. Demo-MACs sind synthetisch und die UI zeigt den Modus sichtbar an.

Bewusst enger Funktionsumfang: Geräte entdecken, auflisten und zuordnen. Ein Unknown-Gerät ist eine nicht zugeordnete Beobachtung und keine automatische Bedrohungsbewertung.
