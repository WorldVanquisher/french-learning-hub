# FLH-044 validation: semantic-index recovery

Date: 2026-10-11. Working directory:
`/Users/lowx/projects/FLH/french-learning-hub` (macOS arm64). Owner: local
Claude Code. No Git/GitHub command or subagent was used. Contract:
[plan](../plans/FLH-044-semantic-recovery.md).

**Prerequisites**
- **Qdrant:** the official 1.19.1 release binary (commit `6ab21cac…`), already
  downloaded in the session scratch directory. It was run on `127.0.0.1:16344`
  with scratch storage and telemetry disabled, then stopped; it ended with no
  collections, its storage was deleted and the ports were free.
- **Embeddings:** deterministic bag-of-words fakes with exact call and text
  counters. No real model, paid provider, secret, `.env` or daily database.
  Each test uses fresh temporary SQLite.
- **Two kinds of evidence:** unit tests use the in-memory `memIndex` fake (marked
  *mock*). Everything marked *real* used the real Qdrant adapter against the
  instance above.

## Acceptance

| # | Criterion | Mock (`internal/application`) | Real Qdrant |
| --- | --- | --- | --- |
| 1 | Metadata-window and Query-window replacement recover | `ReplacementBeforeMetadataRecoversWithOneEmbedding`, `ReplacementBeforeQueryReusesTheQueryVector`: PASS | PASS. Metadata window: old collection really deleted; search used the new one; 3 results. Query window: new collection used |
| 2 | One total retry; repeated replacement ends honestly | `RepeatedReplacementEndsAfterOneRetry` (metadata→metadata, query→metadata): PASS; error is `ErrSemanticPublicationChanged`, not "not built"; next search works | PASS: two replacements observed, then `semantic index publication changed during the search: …_r824e… was replaced by …_rd5fb… after one retry; search again`; next search OK |
| 3 | Unchanged-pointer loss stays an explicit error | `MissingCollectionWithUnchangedPointerStaysAnError` (before metadata: 0 embeddings, 0 queries; before query: 1, 1, no retry): PASS | PASS: `semantic index has not been built: collection … does not exist` |
| 4 | Exact query-provider counters | provider calls/texts and vector queries per search: metadata window 1/1/1, query window 1/1/2, metadata→metadata 0/0/0, query→metadata 1/–/1 | Same counts: metadata 1 call/1 query; query window 1 call/2 queries; repeated 0/0 |
| 5 | Failed retired deletion, then only a healthy sync, removes the old collection and its bookkeeping without embeddings | `HealthySyncRemovesRecordedLeftovers`: PASS | PASS. An HTTP proxy answered `503` only to `DELETE /collections/<old>` during rebuild: `cleanup_pending=[old]`, `cleanup_error="vector index unavailable"`, `last_error="cleanup incomplete: 1 leftover collection(s) remain (vector index unavailable)"`, old real collection present and `retired`. Fault removed, plain `sync`: `verified_unchanged`, cleaned 1, **0 texts embedded**; real collections = only the current one; physical records = 1; old manifest rows = 0; full published inventory matches SQLite and cache; status HEALTHY, `last_error` empty |
| 6 | Cleanup failure observable; lease loss prevents unsafe cleanup | Persistent failure: sync stays `verified_unchanged`, `cleanup_pending=[old]`, status `last_error` "cleanup incomplete…" (PASS). `LeaseLossStopsHealthySyncCleanup`: lease taken at the first deletion gate, then `ownership_lost`, 1 gate only, the other leftover untouched, both records kept, publication/lease/run record belong to the newer owner (PASS). `HealthySyncLeavesOtherRunsWritingCollections`: a no-op sync keeps another run's `writing` collection and reports it pending; a later rebuild removes it (PASS) | PASS: lease lost after the gate: exit `ownership lost`, both records kept, publication and last run unchanged, published inventory matches SQLite |
| 7 | Existing publication, repair, cache reuse, interruption tests green | all `internal/application` tests PASS (also with `-race`) | all 8 `TestQdrantIntegration_*` PASS (build/sync/rebuild/restart/cache, superseded gates, fence-only window, point loss/same-count replacement, whole loss/shape, interruption, no SQLite write lock during network calls, unavailable Qdrant) |

**Where the real checks ran**
- The six real FLH-044 scenarios ran from a scratch-only test file
  (`flh044_scratch_test.go`) in a temporary copy of the module, reusing the
  repository's FLH-042 integration rig. That kept `qdrant_integration_test.go`,
  which this task doesn't own, unchanged.
- The copy and the scratch file were deleted after the run and are not
  retained. Their results are quoted above.
- The repository's own 8 integration tests also ran unmodified inside
  `make verify`.

## Mutation checks (each restored; SHA-256 re-checked equal to the edited originals)

| Mutation | Caught by |
| --- | --- |
| M1: no retry in the metadata window (old behaviour) | `ReplacementBeforeMetadata…`, `RepeatedReplacement…` |
| M2: unlimited retries | `RepeatedReplacement…` never terminates (test timeout 60 s) |
| M3: retry even if the pointer is unchanged | `MissingCollectionWithUnchangedPointer…`, existing `WholeCollectionLossAndIncompatibleShape` |
| M4: re-embed on every attempt | `ReplacementBeforeQueryReusesTheQueryVector` (2 embeddings) |
| M5: no cleanup on healthy sync (old behaviour) | `HealthySyncRemovesRecordedLeftovers`, `HealthySyncLeavesOther…`, `LeaseLoss…` |
| M6: healthy sync also deletes other runs' `writing` collections | `HealthySyncLeavesOtherRunsWritingCollections` |
| M7: cleanup ignores the lease checkpoint | `LeaseLossStopsHealthySyncCleanup` |

## Commands

| Command | Result |
| --- | --- |
| `go vet ./internal/application`, `gofmt -l` | ok, no output |
| `go test ./internal/application -count=1` and `-race` | ok |
| `FLH_QDRANT_URL=http://127.0.0.1:16344 go test ./internal/vectorindex -run 'FLH044\|QdrantIntegration' -v` (scratch copy) | 14/14 PASS |
| `FLH_QDRANT_URL=http://127.0.0.1:16344 make verify` | exit 0: gofmt clean; all Go packages ok (real Qdrant integration included); vet ok; server/capture/semantic-index build; frontend typecheck ok, 17 files / 215 tests, production build ok |

## Limits

- **No real embedding model**; fakes prove mechanics only.
- **Not run here:** Linux, the Compose profile and the browser. No frontend or
  HTTP behaviour changed.
- **Races are in-process.** Search races were driven by in-process hooks around
  the real adapter, not by two OS processes. The failed deletion was injected
  by a local HTTP proxy in front of real Qdrant.
- **Window after a gate:** a deletion already past its gate when the lease is
  lost still runs. That is accepted and documented: retired and abandoned
  collections are terminal, and the record is kept (fenced) until a later run.
- **Not edited here:** CLI text output of `cleanup_pending`, a dedicated HTTP
  status for `ErrSemanticPublicationChanged`, and the stale legacy note in
  `AGENTS.md`. These are reported as bounded dependencies in the plan.
