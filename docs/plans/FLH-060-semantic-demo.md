# FLH-060 Isolated persistent semantic-search demo

Owner: local Claude Code. Branch label supplied: `feat/flh-060-semantic-demo`.
No Git/GitHub command or subagent was used. Evidence:
[validation](../validation/FLH-060-semantic-demo.md).

Not changed: production Go, the frontend, migrations, the Dockerfile,
`compose.yaml`, `tools/embedding/e5`, the FLH-034, FLH-040 and FLH-046 scripts
and historical reports. Only `scripts/validation/flh059/run-diagnostic.ps1`
changed outside the new directory.

## Files (exact edit set)

| File | Change |
| --- | --- |
| `scripts/demo/flh060/demo.py` (new) | setup/start/stop/status/index/search/offline/walkthrough/cleanup and compose-up/index/status/down |
| `scripts/demo/flh060/gateway.py` (new) | Loopback counting forwarder: query/document separation, persisted counters, real-mode budget charged before sending, offline switch |
| `scripts/demo/flh060/fake_e5.py` (new) | Fake upstream: the FLH-054 service with its fake encoder |
| `scripts/demo/flh060/catalog.py` (new) | 8 contrast Concepts and demonstration search inputs |
| `scripts/demo/flh060/compose.override.yaml` (new) | Own image tag, `restart: "no"`, ownership label |
| `scripts/demo/flh060/test_demo.py`, `README.md` (new) | Offline tests; operator guide |
| `scripts/validation/flh059/run-diagnostic.ps1` | Hashing fix and `-HashOnly` |
| `docs/DEMO.md`, `docs/SEMANTIC_SEARCH.md` | FLH-060 sections |
| This plan and the validation report | New |

## Reused, not re-implemented

| Need | Reused |
| --- | --- |
| Seeding | FLH-034 `demo.sh setup`, `seed.py` and the stub (unchanged), then `POST /concepts` |
| Process identity and listeners | FLH-034 `proc_guard.py` (`identity`, `listeners`, `is_loopback`, `commands`), loaded as a module |
| Index operations | `cmd/semantic-index` build/sync/rebuild/status, with `-json` for evidence |
| Search | `GET /knowledge-library/semantic-search` and `GET /knowledge-library/concepts` |
| Qdrant | The digest pinned in `compose.yaml`, via FLH-046's `pinned_image` |
| Fake embeddings | The FLH-054 `EmbeddingService` with `FakeEncoder` |
| Compose | `compose.yaml` semantic profile plus an override |

## Contracts

- **Isolation**
  - `WORK` must be absolute and outside the repository; `setup` needs it new or
    empty.
  - Child processes get an explicit environment and run with `WORK` as their
    working directory, so no `.env` is read and no provider variable is
    inherited.
  - Listeners bind 127.0.0.1, checked against the process's own sockets. The
    Qdrant container is published on loopback only.
- **Persistence:** the SQLite database, Qdrant storage, gateway counters and
  budget, logs and evidence stay in `WORK` across stop and start.
- **Embedding configuration**
  - Fake mode takes no embedding arguments and never contacts a model.
  - Real mode requires the base URL, exact deployment id and dimensions.
    `setup`, `start` and `status` only make read-only `readyz`/`manifest`
    checks, and an identity mismatch refuses to start.
- **Live budget (real mode)**
  - `WORK/gateway/budget.json` defaults to 64 POSTs and 256 positions. It is
    charged before forwarding, and exhaustion gives 429 with nothing sent.
  - One attempt per request, no retries.
  - `walkthrough --allow-live` plans 9 POSTs and 22 positions, checks the
    remaining budget, and runs once per directory (marker).
  - A Compose app that bypasses the gateway is charged its worst case before
    each operation.
- **Counting:** the gateway classifies each input by its declared
  representation and type: search query, Concept document, Unit query or other.
  Index POSTs and search POSTs are counted separately.
- **Ownership**
  - A process is signalled only if its PID, start time and command line, which
    names `WORK`, all match.
  - The container is removed only when its label names `WORK`.
  - Ports are checked free before each launch.
  - A failed setup or start stops what it started.
  - Repeated start, stop and cleanup are safe.
- **Explanations** (README and docs):
  - recorded history vs verified health;
  - keyword vs semantic search;
  - model identity as the index space;
  - offline recovery without fallback;
  - similarity is never a probability or SAME.

## Acceptance

| # | Criterion | How |
| --- | --- | --- |
| A1 | Fake mode end to end: setup, then the walkthrough's 18 mechanical checks, then stop/start, status, cleanup | Run here |
| A2 | Persistence across stop/start, and a repeated start | Run here |
| A3 | Occupied port refused before creating anything; forged record never signals an unrelated process; unrecorded demo process reported | Run here |
| A4 | Real mode: exact-identity preflight; one live walkthrough within budget; gateway and service counters agree; second attempt refused | Run here, against the supplied endpoint |
| A5 | Compose semantic profile in fake mode: build, repair from cache, search, down/up persistence | Run here (Docker Desktop) |
| A6 | `run-diagnostic.ps1` never hashes its own list; failures exit non-zero and keep evidence | PowerShell 7.4 Linux container, stubs |
| A7 | Offline unit tests | Run here |
| — | NAS native/Compose real mode, Windows PowerShell | Commands provided; NOT RUN |
