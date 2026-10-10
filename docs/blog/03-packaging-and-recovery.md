# Shipping a small Go, React and SQLite service, then testing that it recovers

> Retrospective draft, prepared 2026-10-10. Not yet published. The validation
> reports cited here are dated 2026-10-07 and 2026-10-08; the packaging plan
> itself is undated.

A personal service is only useful if it starts the same way every time and its
data survives mistakes. This part of the project was less about features and
more about checking, from several angles, that the release did what its
documentation claimed.

## One process, one origin

The packaging choice was deliberately boring. The Go server can serve the built
React workbench itself when started with `-web-dir`:

- `/` and `/assets/` serve the workbench;
- `/api/...` serves the API with the prefix stripped, which is what the
  workbench calls;
- every existing root API route keeps working, so command-line clients and
  scripts are unaffected.

A multi-stage Dockerfile builds the frontend and a static Go binary from base
images pinned by digest, from an allowlisted build context. Compose publishes
the port on `127.0.0.1` only, fixes the container's port and database path, and
forwards only an explicit list of provider variables. `/healthz` answers
liveness without touching the database; `/readyz` pings SQLite with a two-second
bound and drives the container healthcheck. There is no authentication, and the
documentation says so plainly.

## Checking it from different directions

Several dated reviews looked at the same release with different methods, and
they are worth keeping apart because they prove different things:

- **A sanity check (FLH-001, 2026-10-07)** ran the release verification in an
  isolated copy and found that a failed server build could be masked by the
  verification recipe.
- **Release acceptance (FLH-011, 2026-10-07)** built the image, waited for it
  to become healthy, used the workbench and API together, replaced the container
  and checked that capture idempotency survived, and restored a backup into a
  separate project.
- **Browser acceptance (FLH-012, 2026-10-07)** drove the release workbench in
  headless Chrome: 27 of 27 checks passed, with one pre-existing CSS issue.
- **An edge-case audit (FLH-013, 2026-10-07)** was written by the same agent
  session that built the packaging, and says so: it is a self-audit, not an
  independent review. It still found eight problems.

## What the audit found

Some of the findings were about recovery, the part most likely to be trusted
without being tried:

- A documented restore only lasted until the next plain `docker compose up`,
  after which the service silently returned to the old database.
- The documented migration of the daily database copied the whole `data/`
  directory, including unrelated databases.
- Startup errors caused a restart loop, not the "unhealthy" state the
  documentation described.
- The backup steps used `sqlite3` and `sha256sum` without listing them as
  requirements.

Two were security boundaries that predated packaging:

- A web page on another site could send `text/plain` POSTs that wrote data.
- Any `Host` header was accepted, which allows DNS rebinding.

## The fixes

**Recovery (FLH-016, 2026-10-08).** Restore now works at the same configured
path:

1. copy the backup into a staging directory and verify its checksums;
2. require SQLite's integrity check to print exactly `ok`;
3. preserve the old directory by renaming it, then rename the staging directory
   into place.

Backups and the daily migration copy only the database file and its WAL/SHM
sidecars. The verification recipe now fails fast on either build failure. A
repeatable harness ran the documented shell blocks themselves, with injected
failures: missing source, corrupt database, a stub SQLite that exits zero with
the wrong output, and a tampered checksum.

**Browser boundary (FLH-017, then FLH-019, 2026-10-08).** An investigation first
reproduced the cross-site writes more widely. Eight probes wrote data,
including one extraction that called the provider and a forged human INVALID
judgment. It also showed that checking `Content-Type` alone would not work,
because some mutations have no body. The implemented boundary:

- validates `Host` against an allowlist (loopback by default) before serving
  anything;
- checks `Origin` and Fetch Metadata, using Go's standard cross-origin
  protection, and requires a JSON body type for browser mutations;
- allows explicit trusted origins for the Vite development proxy and for TLS
  reverse proxies.

The documentation is explicit that this is browser protection, not
authentication.

## A bug that only appeared in development

One failure was invisible in the production build. React's StrictMode replays
effects in development, and three workbench components cleared a "mounted"
flag on cleanup but never set it again. After the replay, their responses were
ignored and buttons stayed pending. The fix (FLH-021) was small; the evidence
was that new tests failed against the old code before passing against the fix.

## What remains open

No report records a fix for the audit finding that secret-like files inside
allowlisted directories could reach the build stages. The database file is
still created with mode `644`; the documentation mitigates this with private
directory permissions instead. Migrations are forward-only, and an older
binary does not refuse a newer database, so backing up before every upgrade is
an instruction, not something the software enforces.

## Sources in the repository

- `docs/RELEASE.md`, `docs/ARCHITECTURE.md` §10–11
- `docs/history/04-release-and-hardening.md`
- `docs/plans/FLH-001-sanity-check.md`, `docs/plans/FLH-008-release.md`,
  `docs/plans/FLH-019-browser-boundary.md`, `docs/plans/FLH-021-mutation-lifecycle.md`
- `docs/validation/FLH-011-release-acceptance.md`,
  `docs/validation/FLH-012-workbench-acceptance.md`,
  `docs/validation/FLH-013-release-edge-cases.md`,
  `docs/validation/FLH-016-release-recovery.md`,
  `docs/validation/FLH-017-browser-request-boundary.md`
