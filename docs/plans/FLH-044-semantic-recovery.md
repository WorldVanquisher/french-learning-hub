# FLH-044 Semantic-index recovery: search replacement and no-op cleanup

Owner: local Claude Code. Branch label supplied: `fix/flh-044-semantic-recovery`
(baseline includes FLH-043, PR #69). No Git/GitHub command or subagent was used.
This plan fixes F1 and F2 from the
[FLH-043 acceptance report](../validation/FLH-043-index-consistency-acceptance.md)
without changing the FLH-042 design
([plan](FLH-042-index-run-consistency.md)). Evidence:
[validation](../validation/FLH-044-semantic-recovery.md).

## Defects

| | Cause | Fix |
| --- | --- | --- |
| F1: search reads the old pointer, a rebuild publishes and deletes that collection before `CollectionInfo`, and search reports "not built" | The replacement retry existed only after `Query` failed | One recovery rule for both windows: on a missing collection, re-read the pointer; retry once if it changed, otherwise report the real loss |
| F2: a healthy `sync` returned before cleanup, so a `retired` collection from a failed deletion stayed until the next publishing run | Cleanup ran only after publication | A healthy `sync` retries recorded `retired`/`abandoned` collections under its lease and reports what remains |

## Search contract (F1)

- **Attempt.** Read `published_collection`, check `CollectionInfo` (exists,
  size, Cosine), embed the query if no vector exists yet, then run `Query`.
- **Missing collection.** A missing collection in either window
  (`CollectionInfo` says absent, or `Query` returns not built) triggers one
  re-read of the pointer:
  - unchanged or empty: return the original `ErrSemanticIndexNotBuilt` (a real
    loss; HTTP 409, unchanged);
  - changed, first time: retry the attempt once on the new collection, reusing
    the query vector if one was computed;
  - changed again after the retry: return `ErrSemanticPublicationChanged`
    (new). HTTP maps it to the generic `500`; it is never reported as
    "not built".
- **Limits.** At most two attempts and one query embedding per search. No loop,
  no write, and no keyword fallback. Incompatible shape and provider or Qdrant
  failures are returned unchanged.

## Cleanup contract (F2)

`cleanup()` takes a scope:

| Scope | Used by | Deletes (never the published collection or the run's own) |
| --- | --- | --- |
| `cleanupLeftovers` | healthy `sync` (`verified_unchanged`) | recorded `retired`, `abandoned` |
| `cleanupRecorded` | any run after it published | also other runs' `writing` collections (unchanged FLH-042 behaviour) |
| `cleanupUnrecorded` | `rebuild` after it published | also unrecorded collections named for the space (unchanged) |

Why it is safe:
- **Retired and abandoned collections are terminal.** No run writes or
  publishes them again, so deleting them cannot affect the current
  publication or a live run.
- **Other runs' `writing` collections are left alone by a healthy `sync`.**
  Removing them stays with a run that has just published.
- **Every deletion is gated by the lease.** It is preceded by `checkpoint()`
  (lease renewal), and the record is forgotten only after the deletion
  succeeded, with a fenced write.
- **Lease loss stops cleanup.** Remaining collections are not touched, records
  stay, and the run ends with ownership lost (exit 3) and records nothing. A
  deletion already past its gate can still complete. That is harmless: the
  collection is terminal, and its record stays until a later run.
- **Failures are reported, never hidden.** `SemanticIndexReport` gains
  `cleanup_pending` (recorded leftovers still present after this run) and
  `cleanup_error`. A successful run with incomplete cleanup records
  `last_error = "cleanup incomplete: N leftover collection(s) remain (…)"`, so
  `status` shows it beside the leftovers. The outcome stays `published` or
  `verified_unchanged`.

## Files

- **Production:**
  - `internal/application/semantic_search.go`
  - `internal/application/semantic_index.go`
- **Tests:**
  - `internal/application/semantic_recovery_test.go` (new)
  - `internal/application/semantic_fakes_test.go` (CollectionInfo hook and
    query counter)
- **Docs:**
  - `docs/SEMANTIC_SEARCH.md`
  - this plan and the validation report

No migration, frontend, dependency, CI, HTTP, CLI or legacy change was made.

## Bounded dependencies reported, not edited

- **`cmd/semantic-index/main.go` text output.** It doesn't print
  `cleanup_pending` or `cleanup_error`, and a healthy `sync` still says
  "nothing written" even if it removed leftovers. `-json` and `status` (via
  `last_error` and the leftover list) show everything. Adding two lines to
  `printReport` would make the text output complete.
- **`internal/transport/http/semantic_search.go`.**
  `ErrSemanticPublicationChanged` falls to the generic `500 could not run
  semantic search`. A dedicated `503` "publication changed; retry" mapping would
  be clearer.
- **`AGENTS.md`.** Its FLH-042 note says the legacy methods are kept for the
  FLH-041 probe. FLH-043 retargeted the probe, so nothing calls them now. Both
  the note and the legacy files belong to a separate cleanup task.
