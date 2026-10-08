# FLH-026 isolated daily-workflow regression

From the repository root, run the native baseline:

```sh
python3 -B scripts/validation/flh026/run.py
```

This builds the server from a private source snapshot, uses a fresh SQLite
database and a counted local Responses-API fixture, exercises the workflow,
and removes its temporary data and processes on success or failure. Exit zero
means every assertion and cleanup passed; any failed assertion, prerequisite,
build or cleanup exits nonzero. No installed Python packages are needed.

Native prerequisites: Linux `/proc`, Python 3.10+ with SQLite, the installed Go
toolchain compatible with `go.mod`, and the project's modules already available
in its normal Go module cache. Builds use `GOTOOLCHAIN=local`, `GOENV=off`,
`GOPROXY=off`, `GOSUMDB=off`, `CGO_ENABLED=0`, and `-mod=readonly
-buildvcs=false`. The harness runs `go mod verify` and records the compiler and
binary build information. It does not install dependencies or download a Go
toolchain. Its Go build cache and HOME are temporary. Only the module-cache
location is queried using the user's HOME, with all Go environment-file loading
disabled; provider variables are never inherited.

Optional release-container mode:

```sh
python3 -B scripts/validation/flh026/run.py --mode container
```

This requires Docker at `/var/run/docker.sock`, the Compose plugin, and the
already-installed `python:3.12-slim` image for the local provider. The fixture
image is inspected and used with `pull_policy: never`; its actual image ID is
recorded. The release Dockerfile builds the application using its pinned base
images and project lockfiles. Its existing public dependency downloads may need
network access. No registry login, publication or paid provider is involved.
The temporary Docker configuration is empty. User Docker contexts, proxy
settings and authentication are not inherited. Missing prerequisites fail
preflight; they are not a passing application test.

Container mode uses the copied release `compose.yaml` plus a generated JSON
override, always `--env-file /dev/null` and a unique `flh026-*` project/image.
Provider choices are explicit: analyzer/extractor `openai`, both pointing only
to the isolated fake service with a public fixture key; embedding `disabled`.
There is no fallback. The app and fixture ports are chosen for this run and
published on `127.0.0.1` only. Each app replacement removes its own container,
then recreates it with the same configured private data directory. The fixture
is on that project's network and makes no outbound requests. Cleanup removes
only the project's containers/network and its unique application image tag;
shared base images and build cache remain installed.

For durable machine-readable evidence, choose a **new** path outside the
repository, in an existing directory:

```sh
python3 -B scripts/validation/flh026/run.py --report /tmp/flh026-native-example.json
python3 -B scripts/validation/flh026/run.py --mode container --report /tmp/flh026-container-example.json
```

Existing evidence is never overwritten. Reports include assertions reached,
failures, command results, source and harness SHA-256 inventories, service logs,
and cleanup status. Reports contain synthetic content and the non-secret fixture
key only. Temporary data, including the preserved pre-restore directory, is
removed after verification. If resource cleanup itself fails, the run fails and
retains its private directory for diagnosis; the printed project/run identifiers
identify its owned resources. SIGINT/SIGTERM and command timeouts also unwind
through cleanup. SIGKILL, power loss or daemon failure cannot guarantee cleanup.

Fast checks for the harness itself:

```sh
python3 -B scripts/validation/flh026/test_harness.py
```

These check environment isolation, refusal of an unowned native target, exact
SQLite integrity results, fail-fast copy/checksum errors, and process/provider/
directory cleanup after a controlled assertion failure. They also need local
socket permission. They use no application database or Docker.

## Assertions

The harness performs actual HTTP requests against only its own service:

- Capture create (201), lookup, replay (200), conflict (409), and no replay or
  conflict persistence/provider side effects.
- Empty automatic extraction selection and idempotent clear; unknown clear
  remains 404. Unanalyzed/rejected extraction returns 409 before the provider.
- Counted analysis, accepted/corrected/rejected effective interpretation and
  inventory; successful extraction carries exact analysis/feedback provenance.
- Two gated extraction races: append feedback or a newer analysis while the
  provider is blocked, release it, require 409 and no partial persistence. The
  intentionally appended source change remains; every table after the conflict
  must equal the snapshot taken immediately after that change.
- Explicit human SAME, INVALID, restore, fresh SAME, append-only judgment
  history, derived support/reviewability, Inspector and Dataset JSON/NDJSON
  agreement. Restore does not recreate the prior membership.
- Pin old, create newer, remain pinned through replacement, clear twice, choose
  newest and advance on another extraction. Pinning latest is still `pinned`.
  Clearing changes only `entry_current_extractions`, with no label rewrites or
  provider calls. Dataset/current support follow the selected extraction.
- Root and `/api` mutations reject cross-origin JSON and text/plain, `null`
  Origin, cross-site Fetch Metadata and unknown Host, including bodyless analysis,
  extraction, INVALID and DELETE. Unknown Host reads also fail; forwarded Host
  cannot grant access. Every table and both provider counters stay unchanged.
  Same-origin text/plain body fails 415. CLI-shaped requests without Origin,
  same-origin release, Vite-shaped trusted origins, and explicitly approved NAS
  name/IP requests pass using idempotent captures.
- Replacement preserves all table contents, selection and dataset. Backup
  copies only `app.db` and present WAL/SHM sidecars after the app writer stops,
  requires exactly `ok`, then hashes. Restore validates the complete manifest,
  stages privately, preserves the old directory, and swaps back onto the same
  configured path. A post-backup marker disappears after restoration while it
  remains in the preserved database. Ordinary restart and container down/up plus
  up `--build` keep that restoration selected.

## Safety and tested scope

There is no target URL, database path, port, project, image or provider option.
Unknown CLI options fail before launch. The harness never probes for a running
personal instance. Native requests require the listener's socket inode to
belong to the child PID under `/proc`. Container mode verifies its own project's
container labels, data mount and published port before HTTP requests. A port
collision fails startup. A new report path is the only user-supplied output.

Source copying is limited to known backend source trees and, for container
builds, frontend source/lockfiles plus release packaging. Symlinks, hidden files,
`.env*`, data, node_modules and generated dist are excluded; only listed source
extensions are opened. The source SHA inventory identifies the tested snapshot
without any Git operation. The server starts in a temporary directory with no
`.env`. Nothing reads, copies or modifies a daily database.

Native mode uses a minimal static index so the production `/api` prefix wiring
is exercised without frontend build prerequisites. Container mode packages the
frontend snapshot only. Neither mode tests DOM behavior or claims FLH-025 as
an integrated baseline. Vite compatibility is simulated HTTP headers, not a real
proxy/browser exercise. Cross-site probes confirm server behavior; an attack
from a browser was **NOT RUN**. SQLite snapshots establish zero persisted changes,
not tracing every SQL statement. Host policy rejects unapproved names and permits
the configured NAS/IP fixtures. It does not authenticate clients or pin DNS for
approved hostnames; that approved-name rebinding gap remains the FLH-019 boundary.

The recovery helpers implement the release procedure using Python's standard
SQLite and SHA-256 tools. They do not execute the release document's Bash blocks
or test arbitrary external writers, disk exhaustion, crash recovery or every
filesystem fault. No Compose/daily provider credentials are inherited. Report
application defects for their owner; do not modify production code to make this
harness pass.
