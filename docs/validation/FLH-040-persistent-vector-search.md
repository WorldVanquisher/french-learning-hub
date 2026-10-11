# FLH-040 validation: persistent embeddings and rebuildable vector search

Date: 2026-10-10. Working directory: `/Users/lowx/projects/FLH/french-learning-hub`.
Implementation owner: local Claude Code. No Git/GitHub command or subagent was
used. The contract is in the [plan](../plans/FLH-040-persistent-vector-search.md).

**Scope of the evidence.** Every vector in these checks comes from a
deterministic fake: hashed bag-of-words vectors in the Go tests, and
`scripts/demo/flh040/fake_embeddings.py` in the live checks. The checks prove
caching, publication, re-validation, failure handling and UI wiring. **They say
nothing about semantic quality.** No real embedding model was called, and no
Recall@K or MRR change was measured; that belongs to a later evaluation task.

**Environment**
- macOS arm64; Go 1.26.5; Node v24.16.0; Python 3.13.5; headless Google
  Chrome 154 via `playwright-core` 1.49.1 installed only in scratch.
- Qdrant 1.19.1: the official `qdrant-aarch64-apple-darwin` release binary,
  downloaded into a session scratch directory and run there, bound to
  `127.0.0.1` with scratch storage and telemetry disabled. The Docker daemon was
  not running, so the Compose path was not executed.

**Isolation.** All data came from fresh temporary SQLite databases and the
synthetic FLH-034 fixture. No secret, `.env`, daily database, paid provider,
permanent dependency or host change was used. All task processes were stopped
and their directories removed at the end.

## Automated checks

| Command | Result |
| --- | --- |
| `gofmt -l cmd internal` | no output |
| `go vet ./...` | ok |
| `FLH_QDRANT_URL=http://127.0.0.1:16333 go test ./... -count=1` | all packages ok (includes the real-Qdrant integration tests) |
| `go build` of `./cmd/server`, `./cmd/capture`, `./cmd/semantic-index` | ok |
| `npm run typecheck` / `npm run test` / `npm run build` (scratch copy of `web/`) | ok / 17 files, 215 tests passed / ok |
| `docker compose config --quiet`; `docker compose --profile semantic config --services` | valid; default services `app` only, with the profile `app`, `qdrant` |

`make verify` itself was not run (it needs `web/node_modules` in the
repository); its steps were run equivalently above, including the new
`semantic-index` build it now performs.

### New focused tests

| Package | Tests | What they prove |
| --- | --- | --- |
| `internal/application` | 11 index + 4 search | See the list below |
| `internal/storage/sqlite` | 2 | Cache round trip, model-identity keying, no overwrite, blob-length constraint, run ownership (`FinishRun` by a superseded run is refused), point bookkeeping |
| `internal/vectorindex` | 3 unit (httptest) | Request shapes and `api-key`; 404 handling; categories for timeout, 500, garbage and cancellation, with no body leakage; foreign-payload hits |
| `internal/vectorindex` | 4 integration (**real Qdrant 1.19.1**) | Build, search and state filter; restart (reopened SQLite) then sync and rebuild with zero provider calls; stale and missing hits dropped, then `sync` repairs; interrupted build then recovery; Qdrant unreachable |
| `internal/transport/http` | 2 | Response schema on root and `/api`; 400s; POST 405; 503 when disabled; 409/502/504/500 mapping with no secret text and no results |
| `internal/config` | 3 | Default disabled; full load; 11 rejection cases |
| `cmd/semantic-index` | 1 | Usage errors, refusal when not configured, batch bound |
| `web` Knowledge Library | 2 new (8 total) | Semantic mode labels similarity and partial index state, issues only the semantic GET (no keyword fallback), opens current concept detail and returns with focus; explicit 503 message, and no request for an empty semantic query |

The `internal/application` tests cover:
- reuse across runs, restart and rebuild, proven with provider counters;
- a content change re-embeds one document only;
- a model change gets a separate space and makes no use of old vectors;
- dimension mismatch, NaN and zero vectors are rejected and never cached;
- after a partial provider failure, completed batches stay cached and are reused;
- an interrupted run is `partial` with "interrupted (canceled)", then resumes;
- a source change before publication is not reported complete;
- a superseded run does not claim completion;
- vector-store failure, and a lost collection that is republished without re-embedding;
- `build` refuses an existing index, and removed Concepts' points are deleted;
- an incompatible collection is refused and then repaired by `rebuild`;
- search orders by similarity, and the state filter does not fill shortages;
- missing, stale and foreign hits are dropped;
- a partial index stays visible, and failures are explicit (vector store,
  provider timeout, empty query, cancellation).

**Mutation checks.** Each of three guarantees was disabled in turn in the
source; each time the named test failed, and the original was then restored
(byte-identical):

| Guarantee disabled | Test that failed |
| --- | --- |
| Search's content-hash re-check | `TestSemanticSearch_RevalidatesHitsAgainstSQLite` |
| Re-read before publication | `TestSemanticIndex_SourceChangeBeforePublicationIsNotReportedComplete` |
| `run_id` ownership in `FinishRun` | `TestSemanticIndex_SupersededRunDoesNotClaimCompletion` |

## Live checks (real Qdrant, fake embeddings, production build)

`scripts/demo/flh040/semantic_demo.sh up <scratch> <qdrant binary> <web/dist>`
ran in about 3 s. It seeded the FLH-034 fixture (7 Concepts) and ran
`semantic-index build`:

```
concepts: 7, embedded (provider): 7 texts, upserted: 7, state: complete
embedding calls so far: {"requests": 2, "texts": 7}      (batch size 4)
```

| Check | Observed |
| --- | --- |
| Search `subjunctive` (root) | `complete`, 4 results (concepts 3, 2, 4, 1; similarity 0.516 → 0.408); 3 non-positive hits dropped |
| Same with `state=orphaned` via `/api` | concepts 2 and 4 only |
| Provider counters across 3 searches | requests 2 → 5, texts 7 → 10: exactly one text per query, documents never re-embedded |
| `sync` then `rebuild`, each a fresh CLI process | `embedded (provider): 0 texts`, `reused from cache: 7`; counters unchanged |
| Keyword search `subjonctif` | unchanged schema and results (3, 1, 4, 2, identity tier) |
| `status` | complete; 7 up to date; Qdrant 7 points (64 dims, Cosine); 7 cached vectors |
| Qdrant stopped | semantic search `502 {"error":"vector index unavailable"}`; keyword search 200; `status` reports `vector index unavailable` |
| Qdrant restarted on the same storage, no sync | semantic search `complete`, 4 results |
| Provider returns NaN / wrong dimension / 503 | search `502 {"error":"embedding provider unavailable"}` in each case |
| New `EMBEDDING_MODEL_ID` (v2) `build` while the provider fails | exit 1; v2 space `partial`, `last error: embedding provider unavailable`, 7 missing; the v1 space is listed separately and untouched |
| v2 `sync` after recovery | 7 texts embedded (no reuse across models), `complete`; Qdrant now has two collections; the server still searches its own v1 space |
| v3 `build` (batch 1, slow provider) interrupted with SIGINT after 5 s | exit 1, "interrupted: the index is marked partial…"; `status`: `partial`, `last error: interrupted (canceled)`; resume `sync` embedded 5 texts and reused 2 |
| `semantic_demo.sh clean` | stopped the server, Qdrant and fake processes by verified command line; all task ports free |

## Real browser (headless Chrome)

| Run | Result |
| --- | --- |
| **PROD** (`-web-dir`, fresh build) | Semantic mode: 4 results with "Similarity 0.xx (cosine; not a probability or a SAME judgment)", summary "model fake/bag-of-words-64@flh040 · index complete". Opened "subjunctive forms of faire" (orphaned) and went back to "semantic results for “subjunctive”" with focus restored. Switching to Keyword gives "4 concepts matching “subjunctive”". 11 requests, all GET; one `semantic-search` call. |
| **DEV** (Vite on `127.0.0.1:5334`, StrictMode) | Same assertions passed; 48 requests, all GET; one `semantic-search` call. |
| Keyword regression: FLH-034/038 `walkthrough.mjs` against the semantic-enabled server | 10/10. The SQLite dump hash was identical before and after browsing. |

The only console error in every run is the pre-existing `/favicon.ico` 404.
Screenshots were inspected in scratch; one CSS fix followed: the mode radios
inherited a block label style. Screenshots are not committed.

## Not run, and limits

- **Docker Compose `semantic` profile and the image's `/app/semantic-index`:**
  NOT RUN against a daemon. Only `docker compose config` was validated. In
  particular, ownership of the Qdrant container's bind-mounted storage directory
  was not exercised.
- **Real embedding models:** not called, so semantic quality, multilingual
  behaviour and Recall@K/MRR were not measured.
- **Linux:** the live scripts were run on macOS only. The Go integration tests
  are platform-neutral.
- **Index content:** only Concept identity text is indexed. Unit wording and
  French examples are not, so semantic mode cannot find a Concept by an example
  sentence; keyword mode can.
- **Cache growth:** cached vectors for old model identities are never pruned
  automatically.
- **Killed runs:** a run killed with SIGKILL leaves the space `building` until
  the next `sync`. This is visible in `status` and safe, because search
  re-validates every hit.
