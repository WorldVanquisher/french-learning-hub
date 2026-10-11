# FLH-042 validation: semantic-index run consistency

Date: 2026-10-10 (local; some Qdrant timestamps read 2026-10-11 in UTC).
Working directory: `/Users/lowx/projects/FLH/french-learning-hub`. Owner: local
Claude Code. No Git/GitHub command or subagent was used. The contract is in the
[plan](../plans/FLH-042-index-run-consistency.md).

**Prerequisites**
- **Qdrant:** the official `qdrant-aarch64-apple-darwin` 1.19.1 release binary,
  run from a session scratch directory on `127.0.0.1` with scratch storage and
  telemetry disabled. It was downloaded for FLH-040; no host change was made.
- **Embeddings:** deterministic fakes only (the Go bag-of-words test provider
  and `scripts/demo/flh040/fake_embeddings.py`). **They prove mechanics, not
  semantic quality.**
- **Isolation:** fresh temporary SQLite databases and synthetic Concepts; no
  secret, `.env`, daily database or paid provider.
- **Not available:** the Docker daemon, so the Compose profile was not run.
- **Mocks:** in-memory fakes appear only in unit tests. Every acceptance claim
  about Qdrant below comes from the real instance.

## Automated checks

| Command | Result |
| --- | --- |
| `gofmt -l cmd internal scripts` | no output |
| `go vet ./...` | ok, including `scripts/validation/flh041/ownership_probe` (unchanged) |
| `FLH_QDRANT_URL=http://127.0.0.1:16333 go test ./... -count=1` | all packages ok |
| `go build` of `cmd/server`, `cmd/capture`, `cmd/semantic-index` and the FLH-041 probe | ok |
| `npm run typecheck` / `npm run test` / `npm run build` (scratch copy of `web/`) | ok / 17 files, 215 tests / ok |

### Real-Qdrant integration tests (`internal/vectorindex`)

| Test | Proves |
| --- | --- |
| `BuildSyncRebuildRestartAndCacheReuse` | build; `sync` on a healthy index is `verified_unchanged` with no new collection; restart then `rebuild` with 0 embeddings; the replaced collection is deleted; full inventory equals manifest, documents and cache |
| `SupersededRunCannotMutateNewerPublication` (gates `upsert`, `record-manifest`, `publish`) | Old run A paused after its gate; B takes over and publishes; A released. A fails with ownership lost and publishes nothing. B's publication, run record, manifest and every point and vector are unchanged, and A's private collection is gone |
| `FencedPublishAfterNoOpTakeover` | The narrowest window: A paused right before `Publish`, B is a no-op `sync`, so A's collection record is intact and only the lease fence can stop A. It does |
| `PointLossAndSameCountReplacementAreDetectedAndRepaired` | One point deleted gives `missing [2]`. Point 3's vector replaced with point 2's (count still 4) gives `vector_mismatch [3]`. Each is repaired by `sync` with 0 embeddings, and the full inventory is re-checked |
| `WholeCollectionLossAndIncompatibleShape` | Lost collection: `exists=false`, search 409, sync republishes. Same name recreated at 33 dims: `shape_ok=false`, search 409, sync republishes |
| `InterruptionKeepsPreviousPublication` | Cancel between upsert batches: `interrupted`; the run's collection is removed; search keeps the previous publication; resume needs 0 embeddings |
| `NoSQLiteWriteLockDuringNetworkCalls` | During 19 Qdrant HTTP requests and 3 provider calls, an independent connection took `BEGIN IMMEDIATE` within 50 ms every time. A **positive control** holding a write transaction makes the probe fail |
| `UnavailableQdrant` | build `failed`, nothing published, search 409, and status reports `vector index unavailable` |

### Mutation checks (each change restored byte-identical afterwards)

| Change | Caught by |
| --- | --- |
| Fence check ignored in `fenced()` | `TestSemanticIndexRepository_FencedWritesRejectSupersededRun` and the real-Qdrant `FencedPublishAfterNoOpTakeover`, where A actually published over the newer state |
| `verify` reports healthy whenever the collection exists | application `HealthDetectsDamageThatPointCountHides` and real-Qdrant `PointLossAndSameCount…` |
| Vector comparison disabled | the same two tests (same-count replacement no longer detected) |

With the fence disabled, the three gated superseded-run cases still passed. In
those cases the per-gate lease check and the newer run's cleanup also stop the
old run. That is why the dedicated fence-only window test was added.

### Unit and other tests

- **Application** (in-memory index, real SQLite store):
  - reuse, and a verified no-op sync;
  - five kinds of damage detected and repaired;
  - whole-collection loss and wrong shape;
  - superseded-run gating at seven steps, including `embed` and `delete-collection`;
  - busy versus expired lease;
  - invalid vectors;
  - failure and interruption keep the previous publication;
  - catch-up versus continuously changing sources;
  - undeletable replaced collection stays visible as `retired`;
  - model change;
  - search: revalidation, no shortage filling, retry-once on a replaced
    publication, explicit failures.
- **SQLite:** the F1 sequence on two database handles. Every write by the
  superseded run (renew, record own or newer manifest, remove, publish, mark,
  forget, register, complete) is refused, and the newer records are unchanged.
  Publish retires the previous collection.
- **HTTP:** schema v2; no `complete` flag; `health_verified=false`.
- **CLI:** usage and configuration refusals; busy lease exits 4 and names the
  holder.
- **Frontend:** the v2 header shows history labelled "not re-verified", and
  there is no "index complete" text.

## Live checks with the real CLI processes

On `scripts/demo/flh040/semantic_demo.sh` (seeded FLH-034 library, real Qdrant
on 18941, fake embeddings, server with the production build):

| Step | Observed |
| --- | --- |
| Process A `build` (model v3, batch 1, slow provider) | holding the lease |
| Process B `sync` | exit 4: `busy: … build run 48af4fd1… until …Z (use -takeover only if that run is dead)` |
| Process B `-takeover build` | exit 0: 6 embedded, 1 reused from A's cache, published `…_r653a6a7d8c67` |
| Process A | exit 3: `ownership lost: a newer run took over; this run published nothing`; it never created a collection |
| Qdrant | Exactly two collections, one published per space. The v3 collection's 7 points match its manifest (hash, model, 64 dims) |
| SQLite | `published_run_id = last_run_id = B`, no lease, one `published` physical row per space, manifest 7 rows each |
| Delete point 2 in the published collection (Qdrant HTTP) | `status`: `UNHEALTHY — 1 missing (2)`. Search meanwhile: `last_run published`, `health_verified False`, results without 2. `sync`: 0 embedded, published, 1 leftover removed |
| Replace point 3's vector with point 1's (same id and payload, count 7) | `status`: `1 vector mismatch (3)`. `sync` repaired it, then `HEALTHY` |
| `sync` on the healthy index | `verified unchanged … nothing written`, outcome `verified_unchanged` |
| Browser (headless Chrome, production build) | Semantic results show "Index published …; last run: sync verified unchanged. This is recorded history, not re-verified for this search". Keyword walkthrough 10/10; all requests GET |
| FLH-041 probe (unchanged) | `unfenced_mutations_observed = True`, as expected on the **unused** migration-010 tables only |

Cleanup: the demo directory was removed, the test Qdrant was stopped and its
scratch storage deleted, and all task ports are free. Every integration test
deleted its own collections; the instance ended with none.

## Limits and remaining risks

- **Fake vectors only.** No real embedding model, and no Recall@K or MRR.
- **Docker Compose `semantic` profile:** NOT RUN (no daemon).
- **Linux:** the live scripts were run on macOS only. The Go integration tests
  are platform-neutral.
- **Lease liveness:** a run silent for more than 120 s can be taken over without
  `-takeover`. It then publishes nothing, but its work is wasted.
- **SIGKILLed runs:** these leave a lease until it expires and possibly a
  leftover collection, which is visible in `status` and removed by the next run.
- **Full republish:** every repairing `sync` or `rebuild` republishes all points
  from the cache and scans the collection. That is O(Concepts) and fine at
  personal scale.
- **Search** re-checks each hit but does not verify the whole index; `status`
  does.
- **FLH-041 harness:** it still targets the FLH-040 API. It needs updating by
  its owner, after which `semantic_index_legacy.go` can be removed.
