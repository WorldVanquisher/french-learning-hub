# FLH-060 persistent semantic-search demo

A self-contained Knowledge Library with semantic search, on **synthetic data
only**, in one directory you choose outside the repository. It reuses what
exists instead of re-implementing it:
- the FLH-034 seed (`demo.sh setup`, unchanged) and its process-identity
  checks (`proc_guard.py`);
- the production server, the `semantic-index` operator CLI and the existing
  HTTP search routes;
- the pinned Qdrant image from `compose.yaml`;
- the FLH-054 E5 service code (fake mode);
- the Compose semantic profile.

Nothing here changes production Go, the frontend, migrations or the Dockerfile.
Operator guide: [docs/SEMANTIC_SEARCH.md](../../../docs/SEMANTIC_SEARCH.md).
Contract: [plan](../../../docs/plans/FLH-060-semantic-demo.md).

## What runs

```text
browser / CLI ──> server (127.0.0.1)  ──┐
semantic-index ─────────────────────────┤──> gateway (127.0.0.1) ──> embedding service
                                        └──> Qdrant (127.0.0.1, storage in WORK/qdrant)
```

- **Server and CLI:** the production `cmd/server` and `cmd/semantic-index`,
  with an explicit environment. They run with `WORK` as the working directory,
  so no repository `.env` is read and no provider variable is inherited from
  your shell.
- **Gateway (`gateway.py`):**
  - forwards each embedding request unchanged, in one attempt with no retry;
  - counts **search-query** and **Concept-document** positions separately, and
    keeps the counts across restarts;
  - in real mode enforces a **budget charged before sending**: 64 POSTs and 256
    positions by default;
  - has an "offline" switch for showing recovery without touching the real
    service.
- **Embedding service:**
  - **fake mode** (the default) runs the real FLH-054 service code with its
    hash-vector fake encoder (`fake_e5.py`, deployment `fake-e5-plumbing-only`).
    It never contacts a model, and its rankings mean nothing;
  - **real mode** uses the endpoint and exact deployment you pass on the command
    line.
- **Qdrant:** a task-owned container from the image digest pinned in
  `compose.yaml` (`--qdrant docker`, the default), or a Qdrant binary you name.

**Catalog.** The 7 FLH-034 Concepts (subjunctive triggers, passé composé with
être, participle agreement, *tu me manques*) plus 8 Concept-only contrast pairs
from `catalog.py`, added through `POST /concepts`:
- imparfait / passé composé;
- depuis / pendant;
- ne … plus / ne … pas encore;
- y / en.

Titles are English and examples French. The search texts in `catalog.py` are
**demonstration inputs, not labels or expected answers**.

## Commands (Linux or macOS; Python 3, Go, Docker)

```sh
WORK="$HOME/flh-demos/flh060-semantic"          # new or empty, outside the repository
D="python3 -B scripts/demo/flh060/demo.py"

$D setup   "$WORK" --mode fake [--web-dist "$PWD/web/dist"]   # seed, build CLI, start; embeds nothing
$D status  "$WORK"            # processes, gateway counters, index status (published vs verified)
$D index   "$WORK" build      # embed every Concept document once, publish
$D search  "$WORK" "how do I tell a friend I miss them"           # semantic: 1 query embedding
$D search  "$WORK" depuis --keyword                               # keyword: no embedding call
$D stop    "$WORK"; $D start "$WORK"                              # same data, same publication
$D index   "$WORK" sync       # verifies; republishes only if unhealthy
$D index   "$WORK" rebuild    # republishes from the SQLite cache: 0 provider calls
$D offline "$WORK" on         # the service "goes away": semantic fails explicitly, keyword works
$D offline "$WORK" off        # back: no rebuild needed
$D walkthrough "$WORK"        # all of the above, with mechanical checks and evidence
$D cleanup "$WORK"            # stop, then delete WORK (demo directories only)
```

The workbench is served at `http://127.0.0.1:18960/` when `--web-dist` is
given (`npm --prefix web ci && npm --prefix web run build`).

**Ports** (`--port-base`, default 18960):

| Port | Service |
| --- | --- |
| +0 | server |
| +1 | gateway |
| +2 | fake service |
| +3 | Qdrant, and +4 for a Qdrant binary's gRPC |
| +5 | the seed stub during setup |
| +6, +7 | Compose app and Compose Qdrant |

Every port is checked free just before use.

**Pinned Qdrant image.** If it isn't present locally, setup stops and prints
the exact command, with no automatic pull:
`docker pull qdrant/qdrant:v1.19.1@sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10`.

## Real mode (the GPU service)

```sh
$D setup "$WORK" --mode real \
  --embedding-base-url http://100.118.109.6:8765/v1 \
  --embedding-model 'multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/flh_e5_role_prefix_v1/float16/singleton_v1/5a3e23f28a05baff' \
  --embedding-dimensions 768
$D walkthrough "$WORK" --allow-live      # one deliberate attempt per directory
```

- **No defaults:** all three `--embedding-*` arguments are required, and
  nothing comes from `.env` or the environment.
- **Read-only checks:** `setup`, `start` and `status` only make read-only
  `GET /readyz` and `/manifest` calls. They refuse a service that serves any
  other deployment id or dimension count.
- **What sends:** only `index build|sync|rebuild`, semantic searches and
  `walkthrough --allow-live` send embedding requests, all through the gateway
  and its budget.
- **Walkthrough plan:** it plans 9 POSTs and 22 positions for the 15-Concept
  catalog. It refuses a second live run in the same directory and refuses to
  start if the remaining budget is short.
- **If the GPU service is offline at `start`:** the demo still starts with a
  warning. Keyword search and `status` work, but semantic search and indexing
  fail explicitly: there is no fallback to keyword or to another model.

## Compose (the existing semantic profile)

```sh
$D compose-up "$WORK" --container-embedding-url URL --build   # project flh060-<id>, own image tag
$D compose-index "$WORK" status|sync|build|rebuild
$D search "$WORK" "I want two of them" --compose
$D compose-down "$WORK"
```

**What it does**
- Runs the repository's `compose.yaml` with `compose.override.yaml` and a
  generated `--env-file` inside `WORK`, so no repository `.env` is read.
- Uses its own project name (`flh060-<id>`) and image tag
  (`flh060-demo-app:local`), so `french-learning-hub:local` and the release
  project are never touched.
- Sets `restart: "no"` and a label naming `WORK`.
- Publishes on loopback ports only.
- The SQLite database is copied once from the native demo (SQLite backup API)
  into `WORK/compose/data`. Its Qdrant storage is `WORK/compose/qdrant`.

**Choosing `--container-embedding-url`**
- **Docker Desktop (macOS/Windows):**
  `http://host.docker.internal:<gateway port>/v1` reaches the gateway, so calls
  are counted and budgeted.
- **Linux, NAS:** the gateway listens on loopback only, so a container can't
  reach it. In real mode, pass the endpoint itself. Each Compose index
  operation or search is then charged to the same budget at its worst case
  before it runs.

**Fresh Compose Qdrant.** The first `status` shows the copied publication as
`UNHEALTHY — collection missing`. `compose-index sync` repairs it from the
cached embeddings without calling the provider.

## Reading the output

- **Published vs verified.**
  - "published", "last run" and the gateway counters are **recorded history**.
  - "verification: HEALTHY" is a **live check** of the Qdrant collection
    against SQLite.
  - Only the second says the index is usable now. The search response's
    `index.health_verified` is `false` for the same reason: it reports history,
    while every returned hit is re-checked against the database.
- **Keyword vs semantic.**
  - Keyword search matches words in the Concept identity (at most 8 terms) and
    never calls the embedding service.
  - Semantic search embeds the query once (`concept_search_query_v2`) and ranks
    the indexed Concept documents by cosine similarity.
- **Similarity is a cosine score.** It is not a probability, not a relevance
  judgment and never a SAME decision. Real-model scores here sit close together
  (around 0.8 to 0.87). Read the order, not the number.
- **Model identity.**
  - `EMBEDDING_MODEL_ID` is the exact deployment id. It names the index space
    (`flh_concepts_<hash>`) and the embedding cache.
  - A different deployment gets its own space and cache, so vectors are never
    mixed or relabelled. `status` lists other spaces in the same database.
- **Offline recovery.** With the service unreachable:
  - semantic search returns HTTP 502 `embedding provider unavailable`;
  - keyword search and `status` keep working;
  - published vectors stay valid.

  When the service is back, searches work again with no rebuild. If Qdrant data
  is lost, `sync` republishes from the SQLite cache with no provider calls.

## Safety

- `WORK` must be absolute, outside the repository, and new or empty for
  `setup`. Every other command needs its `.flh060-demo` marker.
- A process is signalled only if its PID, start time and command line, which
  names `WORK`, all match the record. Other processes are reported and never
  signalled.
- The Qdrant container is removed only when its `flh060.work` label equals
  `WORK`. A stopped container is removed on `stop`, while its storage stays.
- A failed `setup` or `start` stops what it started and keeps the data.
- `start`, `stop` and `cleanup` are safe to repeat. `cleanup` of a missing
  directory is a no-op.
- Raw evidence (preflight, index reports, searches, walkthrough logs) is in
  `WORK/evidence`, outside the repository.

## Tests

```sh
python3 -B -m unittest discover -s scripts/demo/flh060 -p 'test_*.py'
```

They use loopback stubs only: the gateway's counting, budget refusal before
sending, offline and model refusals and persistence, plus the harness's
refusals, explicit environment, role matching and catalog shape. Fake-mode
vectors and these tests say nothing about semantic quality.
