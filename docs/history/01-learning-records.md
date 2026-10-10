# 1. Learning records and versioned interpretation

Covers milestones 1–9, the v1.0 Entry ownership cleanup, FLH-004 timestamp
ordering and FLH-009 `.env` support. Milestone dates are **unknown**; their
order comes from the previous README and ARCHITECTURE text. Current behaviour
is described in [ARCHITECTURE §3–4](../ARCHITECTURE.md#3-source-records-and-interpretation).

## Initial implementation

**Milestone 1 — persistence.** A single Go HTTP service with SQLite stored a
learning entry (original input and context, timestamps) and exposed
create/get/list. The product goal was to keep questions that would otherwise
disappear inside individual chat conversations. Migration `001` created
`learning_entries` with nullable `category`, `explanation` and `confidence`
columns, before any interpretation model existed.

**Milestone 2 — versioned analyses.** Machine metadata moved to its own table,
`entry_analyses`. Each analysis is immutable and carries a per-entry version, so
re-analysing appends version 2, 3 and so on. A deterministic rule-based analyzer
made the workflow testable without an external provider. Output is validated
before storage and rejected with `422` otherwise.

**Milestone 3 — immutable feedback.** A person can accept, correct or reject an
analysis. Feedback rows are append-only and never modify the entry or the
analysis.

**Milestone 4 — pluggable analyzer.** `AI_PROVIDER` selects the rule-based
analyzer (default) or an OpenAI Responses API adapter behind the same
interface. Categories became a shared domain taxonomy, `fr_l2_taxonomy_v1`, so
the database never stores provider-specific category systems. Invalid
configuration stops startup; provider failures map to `502`/`504` and store
nothing; there is no retry or fallback.

**Milestone 5 — effective analysis.** The "current interpretation" became a
read-only projection: the analysis combined with its latest feedback, computed
on each request. Corrected categories were constrained to the taxonomy.

**Milestone 6 — explainable rule engine.** The local analyzer's original
four-branch `switch` (question mark, word count) was replaced by named,
weighted rules over input and context. It reports which rule matched, a
heuristic confidence score (explicitly not a calibrated probability) and an
advisory `NeedsAI` signal that never triggers a call. Provenance became
`rule-based:v2:fr_l2_taxonomy_v1` so older analyses stay distinguishable.

**Milestone 7 — learning inventory.** A cross-entry read model combines each
entry's latest analysis and that analysis's latest feedback into one row, with
filters, cursor pagination, a summary and JSONL export, computed in one SQL
projection.

**Milestone 8 — capture import.** `POST /captures` accepts a
`learning_capture_v1` document describing a discussion that already happened
elsewhere and stores it as an entry plus an optional version-1 analysis, in one
transaction. Imports are idempotent by `capture_id` and a content fingerprint;
changed content conflicts instead of overwriting. The design note is explicit
that this is not a chatbot: no model is called and no conversation is scraped.

**Milestone 9 — capture CLI.** `cmd/capture` posts a prepared document
unchanged to the public API, so the real client-to-storage path is exercised and
the server stays the only owner of capture rules.

## Later corrections

- **v1.0 Entry ownership cleanup (date unknown).** The active `Entry` model and
  API stopped exposing `category`/`explanation`/`confidence`. The migration-001
  columns remain physically present only so existing databases open without a
  rebuild; no values were migrated and the migration was not rewritten.
- **FLH-004 timestamp ordering (date unknown; no report in the repository).**
  "Latest" feedback, overrides and judgments were made chronological by parsing
  RFC3339 instants through a custom SQLite collation, instead of comparing text.
  Existing variable-width timestamps sort correctly without a data migration.
- **FLH-009 `.env` support (undated plan).** Configuration gained an optional
  working-directory `.env` file with process-environment precedence and
  value-free error messages ([plan](../plans/FLH-009-env.md)). FLH-011 later
  recorded eight focused configuration tests passing
  ([report](../validation/FLH-011-release-acceptance.md)).

## Current behaviour

Unchanged in substance from the milestones above, with the corrections applied:
the Entry is source truth only, every interpretation is a versioned or
append-only record, and current views are projections. See
[ARCHITECTURE §3](../ARCHITECTURE.md#3-source-records-and-interpretation) and
[§4](../ARCHITECTURE.md#4-capture-import-and-the-capture-cli).

## Evidence and gaps

- The milestone descriptions come from the previous README and ARCHITECTURE;
  there is no separate report or date for milestones 1–9.
- [FLH-001](../plans/FLH-001-sanity-check.md) (2026-10-07) exercised the real
  HTTP capture workflow with and without an imported analysis, identical and
  conflicting replay, and persistence after restart, and observed no P0
  data-integrity failure.
- The Simplified Chinese workflow
  [LOCAL_LEARNING_WORKFLOW.zh-CN.md](../LOCAL_LEARNING_WORKFLOW.zh-CN.md)
  describes the repeatable personal loop built on this capture path.
