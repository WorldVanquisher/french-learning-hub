# 4. Release packaging and hardening

Covers the v1.0 release work and FLH-001, 008–013, 016, 017, 019, 021 and 026.
Dated reports fall on 2026-10-07 and 2026-10-08; the v1.0 verification and
packaging plans themselves are undated. Current behaviour:
[ARCHITECTURE §10–11](../ARCHITECTURE.md#10-runtime-configuration-and-the-http-boundary)
and [RELEASE.md](../RELEASE.md).

## Initial implementation

- **v1.0 release verification (date unknown).** `make verify` became the
  non-mutating release check (formatting, Go tests and vet, both builds,
  frontend typecheck, tests and production build), and
  [QUICKSTART.md](../QUICKSTART.md) became the maintained first-run path.
- **FLH-008 packaging (undated plan, "implemented, awaiting Codex review").**
  One Docker image with the Go server and the built workbench; Compose binds
  `127.0.0.1` only, fixes the container port and database path, and forwards
  only listed provider variables. `-web-dir` serves the workbench at `/`, the
  API under `/api`, and every root route unchanged. `/healthz` is liveness and
  `/readyz` bounded SQLite readiness
  ([plan](../plans/FLH-008-release.md)).
- **FLH-009 `.env` support** ([plan](../plans/FLH-009-env.md)); see
  [theme 1](01-learning-records.md).

## Checks and findings

- **FLH-001, 2026-10-07 (Codex, verification only).** Release verification
  passed in an isolated copy, and the real capture workflow passed. Findings: a
  P1 verification defect (a failed server build could be masked), a P1
  deployment/documentation gap, and a P2 install-documentation inconsistency
  ([report](../plans/FLH-001-sanity-check.md)).
- **FLH-011, 2026-10-07 (Codex).** On the supplied working tree the image
  built, the container became healthy, the workbench and API were served
  together, capture idempotency survived container replacement, and a stopped
  backup restored into a separate directory. It also confirmed the FLH-008,
  FLH-009 and FLH-010 changes were present. Branch ancestry was not inspected
  ([report](../validation/FLH-011-release-acceptance.md)).
- **FLH-012, 2026-10-07 (Claude Code).** 27/27 browser checks against the
  release workbench in headless Chrome; one pre-existing CSS usability defect
  and three low-severity observations
  ([report](../validation/FLH-012-workbench-acceptance.md)).
- **FLH-013, 2026-10-07 (Claude Code, self-audit of its own FLH-008 work).**
  Eight findings: restore only lasted until the next plain `up` (BR1); the
  daily-database migration copied other databases (BR2); cross-site
  `text/plain` POSTs wrote data (X1); any `Host` header was accepted, enabling
  DNS rebinding (X2); secret-like files under allowlisted directories could reach
  build stages (B1); the database was created world-readable (P2); startup
  failures restart-looped contrary to the docs (R1); and the backup steps' host
  tools were undocumented (D1)
  ([report](../validation/FLH-013-release-edge-cases.md)).

## Later corrections

- **FLH-016, 2026-10-08 (Codex).** Restore now swaps a validated staging
  directory in at the configured path, preserving the old one by rename; backup
  and daily migration copy only `app.db` and its WAL/SHM files; checksums and an
  exact `ok` integrity result are required; required tools, private
  directories, restart loops and rollback limits are documented; and
  `make verify` fails fast on either build failure. A repeatable harness
  exercised the documented shell blocks, including injected failures
  ([report](../validation/FLH-016-release-recovery.md)).
- **FLH-017 (undated, investigation only).** Reproduced and widened X1: eight
  cross-site POSTs wrote data, including a provider-calling extraction and a
  forged INVALID judgment. It showed that a content-type check alone is
  insufficient because some mutations are bodyless, and prototyped Go's standard
  `CrossOriginProtection`. X2 was confirmed as needing a separate Host decision
  ([report](../validation/FLH-017-browser-request-boundary.md)). The FLH-019 plan
  records that the human reported FLH-017 merged as PR #42.
- **FLH-019, 2026-10-08 (Codex).** Implemented the browser request boundary: a
  Host allowlist for every route, origin and Fetch Metadata checks plus a JSON
  content type for browser mutations, and explicit trusted origins for the Vite
  proxy and TLS reverse proxies. It is not authentication
  ([plan](../plans/FLH-019-browser-boundary.md)).
- **FLH-021 (undated, Claude Code).** Mutation components stopped settling
  under React StrictMode's development effect replay, because a "mounted" ref
  was cleared and never set again; a late analysis response could also refresh
  the wrong record. Both were fixed, with tests shown to fail before the fix
  ([plan](../plans/FLH-021-mutation-lifecycle.md)).
- **FLH-026, 2026-10-08 (Codex).** A repeatable daily-workflow regression
  harness, in native and container modes, that refuses to touch any target it
  did not create ([report](../validation/FLH-026-workflow-regression.md)).

## Current behaviour

The release and recovery procedures are those in [RELEASE.md](../RELEASE.md);
the boundary settings are documented there once.

## Open or unrecorded items

- No report records a fix for FLH-013 B1 (secret-like files inside allowlisted
  build directories). `.dockerignore` excludes `.env` files and databases by
  name.
- FLH-013 P2 (world-readable database files) is mitigated by the private
  directory modes documented in RELEASE.md; the file mode itself is unchanged.
- FLH-008's status line still says "awaiting Codex review"; FLH-011 and FLH-013
  are the later reviews, the second of them a self-audit.
