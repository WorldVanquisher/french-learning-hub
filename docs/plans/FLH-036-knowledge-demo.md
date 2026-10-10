# FLH-036 Knowledge Library acceptance fixes and demo hardening

This task resolves FLH-035 Phase B findings B1–B5
([report](../validation/FLH-035-knowledge-library-acceptance.md)) without
changing the FLH-034 search policy, ranking, schema or migrations. The evidence
is in [FLH-036 validation](../validation/FLH-036-knowledge-demo.md).

## B1: search contract and labels

The implemented search behaviour is unchanged. It searches the wording of units
holding a Concept's **CURRENT SAME membership** (the `unit_concept_memberships`
projection):

- Membership is not current extraction and not support.
- A member from a historical extraction, or with suppressed admission, still
  matches.
- A former member (reassigned, rejected or INVALID) never matches under the
  Concept it left. A reassigned unit matches only its new Concept.

What changed is the wording:

- **Docs.** The FLH-034 plan, both READMEs and AGENTS.md now say this. The
  old sentence excluding "historical units" was wrong.
- **Results screen.** Match fields read "member unit wording/statement/example"
  rather than "current unit …". A `unit_evidence` result adds: "not in the
  concept identity. A CURRENT SAME member matched; membership is not support."
  Counts read "CURRENT SAME members".
- **Search hint.** It names members from an older extraction or with suppressed
  admission, and says former members are not searched.

## B2: loopback binding contract

The server had no bind-address option (`Addr` was always `":" + PORT`). The
smallest explicit option is added in `internal/config`:

| `LISTEN_HOST` | Listen address |
| --- | --- |
| unset or empty (default) | `":" + PORT`, all interfaces (unchanged) |
| an IP literal, e.g. `127.0.0.1`, `::1` | `LISTEN_HOST:PORT` (`net.JoinHostPort`) |
| a hostname or anything that is not an IP | configuration error; the server does not start |

- Hostnames are rejected, so the bound interface never depends on name
  resolution.
- Compose, the Dockerfile and `.env.example` are unchanged. Compose does not
  forward `LISTEN_HOST`, so the container keeps listening on all interfaces
  inside its network namespace, behind the `127.0.0.1` host port mapping.
- `demo.sh` starts the server with `LISTEN_HOST=127.0.0.1`. The stub already
  bound `127.0.0.1`.

## B3: relation identity

- On the Concept page each section lists a unit once, except Current relations.
- One unit may hold several distinct relations (e.g. RELATED and BROADER) to the
  same Concept, so relation rows are keyed by `link_id`, the relation event's
  own identity.
- Every relation is still rendered; nothing is deduplicated.

## B4: process ownership contract (`scripts/demo/flh034/proc_guard.py`)

Supported platforms are **Linux** (`/proc`) and **macOS** (`ps`, `lsof`). Any
other platform is refused rather than guessed.

**A demo process is identified by** three facts recorded when `demo.sh` starts
it:

- its PID (`server.pid`, `stub.pid`, which still hold just the PID);
- its kernel start time: Linux `/proc/PID/stat` field 22, macOS `ps -o lstart`;
- its command line: Linux `/proc/PID/cmdline`, macOS `ps -ww -o command`.

The start time and command line go in `server.id` and `stub.id`.

**The command line must name this demo directory:**

- server: the command is `WORK/server`, possibly with arguments;
- stub: the command contains `scripts/demo/flh034/stub_extractor.py` and ends with
  ` WORK`, because `demo.sh` passes `WORK` as an otherwise unused argument.

**Recording.** `record` waits, for up to 5 s, until the launched PID runs the
expected command (after the launcher's `exec`).

**`stop`** walks the records:

| Record state | Action |
| --- | --- |
| PID, start time and command all match | `SIGTERM`, then wait up to 10 s for exit |
| No live process (stale) | Record removed, reported |
| Live process with a different start time or command (reused or misattributed), or no `.id` record | **Never signalled**; the record is removed and the mismatch reported |

After stopping, every visible process is scanned for one that carries this
directory's identity. If any remains, for example because a record was
tampered with, `stop` exits 1 and `cleanup` refuses to delete the directory,
naming the PIDs. Nothing is ever signalled without a matching record.

## B5: setup and start failure contract

**Before anything is launched:**
- `DEMO_PORT` and `STUB_PORT` must be free: a TCP connect to `127.0.0.1` and
  `::1` must fail. Setup checks this before the build, and `start` checks it
  again right before launching.
- An occupied port is refused before any process starts or any request is sent.
  The only contact with the occupant is the TCP connect probe; no HTTP request
  is made.

**Readiness:**
- It counts only when the recorded child itself holds a LISTEN socket on its
  port: Linux socket inodes in `/proc/PID/fd` against `/proc/net/tcp*`, macOS
  `lsof -a -p PID`.
- Every address of that socket must be loopback. Only then is `/readyz`
  checked.
- Ownership is checked again immediately before seeding.

**Seed:**
- Seed output goes to `seed.partial.json`.
- It is renamed to `seed.json` only when `seed.py` exits 0, so there is no `tee`
  masking a failure.

**On any failure** (build, port, start, record, listener, readiness or seed):
- an `EXIT` trap runs `proc_guard.py stop`, which stops only verified owned
  children;
- the script prints `<cmd> FAILED` and exits non-zero, and never prints
  `setup complete`;
- `INT`/`TERM` take the same path.

**Limits:**
- `SIGKILL` of the script, or a power loss, skips the trap; use `cleanup`
  afterwards.
- A failed setup keeps its directory (logs, `seed.partial.json`), so a repeat
  `setup` there is refused until `cleanup`.

## Files

| File | Change |
| --- | --- |
| `internal/config/config.go`, `config_test.go` | `LISTEN_HOST` option and tests |
| `internal/transport/http/knowledge_library_integration_test.go` | B1 CURRENT SAME search regression |
| `web/src/pages/KnowledgeLibrary.tsx`, `.test.tsx` | B1 labels; B3 `link_id` keys and real-component regression |
| `scripts/demo/flh034/proc_guard.py` (new) | Ownership, listener and port checks |
| `scripts/demo/flh034/demo.sh` | Loopback bind, port refusal, owned readiness, failure propagation, verified stop |
| `scripts/demo/flh034/stub_extractor.py` | Documents the `WORK_DIR` identity argument |
| `scripts/demo/flh034/walkthrough.mjs` | New labels; optional `--multi-relation` W11 |
| `scripts/demo/flh034/README.md`, `docs/DEMO.md` | Binding, ownership, failure and timing documentation |
| `docs/plans/FLH-034-knowledge-library.md`, `README.md`, `README.zh-CN.md`, `AGENTS.md` | Corrected search contract; `LISTEN_HOST` |

Untouched: the FLH-035 report and harness, migrations, dependency manifests,
the search and ranking code, Compose and the Dockerfile.
