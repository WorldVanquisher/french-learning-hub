# FLH-042 Semantic-index run consistency and completeness reporting

Owner: local Claude Code, sole production writer. Branch label supplied:
`fix/flh-042-index-run-consistency`. No Git/GitHub command or subagent was
used. This fixes FLH-041 Phase B finding F1 and its three inspection findings
([FLH-041 report](../validation/FLH-041-vector-search-acceptance.md)). The
historical FLH-040/041 reports and the FLH-041 harness are unchanged. Evidence:
[validation](../validation/FLH-042-index-run-consistency.md). Operator guide and
Go walkthrough: [SEMANTIC_SEARCH.md](../SEMANTIC_SEARCH.md).

## Findings addressed

| Finding | Cause | Fix |
| --- | --- | --- |
| F1: superseded runs overwrote, cleared or removed newer bookkeeping, and could mutate the shared Qdrant collection | Only the final state write was fenced; one collection per space was mutated in place by every run | Each run writes a private collection, every bookkeeping write is lease-fenced, and publication is one fenced SQLite switch |
| `searchable_complete` was certified from point count and stored state | Only hashes in SQLite and a count were compared | Live verification of the full inventory: shape, ids, payload identity and hash, and vectors against the cache |
| An existing collection's lost or replaced point was never repaired | Sync skipped Concepts whose recorded hash was unchanged | Sync verifies the actual collection first; if anything is wrong it republishes from cache |
| Search presented stored run state (`index.complete`) as completeness | The flag was copied from the run record | Schema v2 reports publication and last-run history with `health_verified: false` |

## Serialization and publication contract

1. **Lease.** `AcquireLease` takes `semantic_index_spaces.lease_*` for the run.
   - It fails with `ErrSemanticIndexBusy` (CLI exit 4) while another run holds
     an unexpired lease.
   - An expired lease is taken normally. `-takeover` takes any lease and is for
     a holder known to be dead.
   - TTL is 120 s, renewed at every gate.
2. **Gates.** `checkpoint()` renews the lease and stops the run with
   `ErrSemanticIndexOwnershipLost` (CLI exit 3). It runs before:
   - each provider batch;
   - collection registration and creation;
   - each upsert and each manifest write;
   - each catch-up delete;
   - publication;
   - each cleanup deletion.
3. **Fenced bookkeeping.** Every store method that takes a run ID runs in one
   transaction whose first statement is `UPDATE … WHERE lease_run_id = ?`. That
   statement checks ownership and takes SQLite's write lock in the same step.
   Manifest writes also require the collection to be the run's own `writing`
   collection.
4. **Private collections.** A run writes only `<space>_r<run12>`, which is
   registered in SQLite before it is created in Qdrant. No run mutates another
   run's collection or the published one.
5. **Publication.** Before publishing, the run catches up with changed sources
   (at most two passes; otherwise `sources_changed` and no publication) and
   verifies its own collection completely. `Publish` then switches
   `published_collection`, marks the collection `published` and the previous one
   `retired`, all in one fenced transaction.
6. **Cleanup.** After publication the owning run deletes the replaced
   collection and leftovers (retired, abandoned, and writing collections of
   other runs). On `rebuild` it also deletes unrecorded collections of the
   space. A failed deletion stays recorded for the next run.
7. **No network-held transaction.** No transaction is held across a provider or
   Qdrant call.
8. **No cross-store atomicity is claimed.** The fenced switch is the single
   publication point, and search re-validates every hit and retries once if the
   collection it read was just replaced.

A check immediately before a network call cannot close the race on its own.
It doesn't need to: whatever a superseded run writes after its last check goes
only into its own unpublished collection, and its next bookkeeping write or
publish is refused by the fence.

## Health contract

`semantic-index status` reports these separately:
- the publication (collection, run, time);
- the last run (operation, outcome, error);
- the lease (active or expired);
- verification, computed now.

Verification checks:
- existence, vector size and distance;
- a full scroll of the collection, checking each point for missing or extra ids,
  invalid or foreign payloads, a stale content hash (against the current SQLite
  document) and a vector mismatch (against the cached embedding, both
  normalized);
- that the point count equals the number of Concepts.

`HEALTHY` only if all checks pass. Whole-collection loss is reported as
`exists: false`; a wrong shape as `shape_ok: false`.

`sync` runs this verification first. If the collection is healthy the outcome
is `verified_unchanged` and nothing is written; otherwise `sync` republishes
from cache, which repairs any of the cases above.

## Files

**New**
- `migrations/011_semantic_index_runs.sql`
- `internal/storage/sqlite/semantic_index_legacy.go`,
  `internal/application/semantic_index_legacy.go` (FLH-040 API kept only for the
  FLH-041 probe)
- this plan and the validation report

**Rewritten or changed**
- `internal/application/semantic_index.go`, `semantic_search.go`, and their
  tests and fakes
- `internal/storage/sqlite/semantic_index_repository.go` and its test
- `internal/vectorindex/qdrant.go` (Upsert takes the collection; adds Scroll and
  ListCollections), `qdrant_test.go`, `qdrant_integration_test.go`
- `internal/transport/http/semantic_search.go` and its test
- `cmd/semantic-index/main.go`, `main_test.go`
- `web/src/types/library.ts`, `web/src/pages/KnowledgeLibrary.tsx` and
  `KnowledgeLibrary.test.tsx` (semantic result header only)
- `docs/SEMANTIC_SEARCH.md`, `docs/ARCHITECTURE.md`, `README.md`,
  `README.zh-CN.md`, `AGENTS.md`

## Coordination note

`scripts/validation/flh041/ownership_probe` (owned by NAS Codex, not edited)
calls the FLH-040 repository methods. They are kept, unchanged, in
`semantic_index_legacy.go` on the now-unused migration-010 tables, so
`go vet ./...`, CI and `make verify` keep compiling. Run today, the probe still
reports `unfenced_mutations_observed: true`, but only for those dead tables.
The probe should be retargeted to the FLH-042 API, after which the legacy file
can be removed.
