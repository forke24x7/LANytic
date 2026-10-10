# Technical background

WatchYourLAN is written in Go. Its [scanner](https://github.com/aceberg/WatchYourLAN/blob/main/backend/internal/arp/arpscan.go) invokes `arp-scan` per interface and parses IP, MAC, and vendor from its output. The [README](https://github.com/aceberg/WatchYourLAN#readme) documents SQLite/PostgreSQL storage and host networking. Its [Dockerfile](https://github.com/aceberg/WatchYourLAN/blob/main/Dockerfile) installs `arp-scan` and `tzdata`.

LANytic uses the same established scanner utility, with an independent application implementation. No WatchYourLAN application source, UI, assets, or database schema was copied.

## LANytic architecture

Browser → Python HTTP API → SQLite

Manual trigger or scheduler → bounded `arp-scan` subprocess per interface → validated observations → one SQLite transaction

- Python standard library: no pip, npm, or build step.
- SQLite/WAL: each request uses its own connection. Scan upserts never overwrite custom metadata.
- Scan mutex: at most one scan at a time. Scheduling restarts the interval after a run completes.
- Atomic results: all configured interfaces must succeed; failure leaves device states intact.
- Stable identity: MAC + interface; IP is a changing observation.
- No shell execution: scanner arguments are passed as a list and interface names are validated. API clients cannot submit arbitrary scan commands.
- Fixed static-file allowlist, escaped user/device data, and a same-origin Content Security Policy.
- HTTP Basic authentication is mandatory in live Compose. JSON Content-Type and Origin validation protect write requests against CSRF.
- The UI uses Simple SMTP Test's warm neutral/orange palette and charcoal dark palette. Light / Dark / System preferences are stored locally; a synchronous local theme script prevents an initial theme flash and follows system changes.

The scope is deliberately focused: discover, list, and identify devices. Unknown means unassigned; it is not an automatic threat assessment.
