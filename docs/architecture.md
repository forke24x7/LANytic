# Technical background

LANytic invokes `arp-scan` per host interface and parses IP addresses, MAC addresses, and vendors from its output. Device information is stored in SQLite. The Docker image includes the scanner and uses host networking to access the LAN.

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
- The UI uses a warm neutral/orange palette and a charcoal dark palette. Light / Dark / System preferences are stored locally; a synchronous local theme script prevents an initial theme flash and follows system changes.

The scope is deliberately focused: discover, list, and identify devices. Unknown means unassigned; it is not an automatic threat assessment.
