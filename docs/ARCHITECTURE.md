# Architecture

This is the canonical description of how French Learning Hub works **today**.
Each topic is explained once here; other documents link to it instead of
repeating it. Where a section notes the milestone or task that introduced or
later corrected a behaviour, that label is for traceability only — the narrative
of how the design evolved, with dates and evidence, lives in
[docs/history/](history/README.md).

- Operations (Docker release, backup/restore, upgrades, browser boundary
  settings): [RELEASE.md](RELEASE.md).
- First run: [QUICKSTART.md](QUICKSTART.md). Synthetic demo: [DEMO.md](DEMO.md).
- Workbench behaviour in detail: [web/README.md](../web/README.md).
- HTTP endpoints, request/response examples and status codes:
  [Appendix A](#appendix-a-http-api-reference) at the end of this document.

## Contents

1. [Purpose and design principles](#1-purpose-and-design-principles)
2. [System overview](#2-system-overview)
3. [Source records and interpretation](#3-source-records-and-interpretation)
4. [Capture import and the capture CLI](#4-capture-import-and-the-capture-cli)
5. [Knowledge extraction and admission](#5-knowledge-extraction-and-admission)
6. [Concepts: identity, membership and support](#6-concepts-identity-membership-and-support)
7. [Human annotation](#7-human-annotation)
8. [Annotation dataset and retrieval research](#8-annotation-dataset-and-retrieval-research)
9. [Knowledge Library](#9-knowledge-library)
10. [Runtime, configuration and the HTTP boundary](#10-runtime-configuration-and-the-http-boundary)
11. [Persistence, migrations and recovery](#11-persistence-migrations-and-recovery)
12. [Deliberately not built](#12-deliberately-not-built)
- [Appendix A: HTTP API reference](#appendix-a-http-api-reference)

## 1. Purpose and design principles

Create a persistent personal knowledge system for French learning.

The application should preserve questions and learning context that would
otherwise disappear inside individual chat conversations.

The learner's original words are the source of truth. Everything a machine or a
person later says about them — an analysis, a correction, an extracted unit, a
Concept decision — is stored as separate, versioned or append-only metadata that
never rewrites the original.

Design principles:

1. Store raw learning records before attempting advanced classification.
2. Treat categories as changeable metadata.
3. Preserve database history through migrations.
4. Let AI propose structural changes, but never silently rewrite production data.
5. Prefer simple, replaceable components.
6. Build from real usage data rather than imagined future requirements.

The system is a single-user learning-data service and research instrument. It
is not a chatbot, a consumer course, a review scheduler, a mastery engine, or an
automatic ML resolver; see [§12](#12-deliberately-not-built).

## 2. System overview

The service is one Go HTTP process backed by one SQLite database, plus an
optional React/Vite/TypeScript workbench that can be served by the same process.

```text
HTTP request
    -> transport layer          (internal/transport/http: routing, DTOs, status mapping)
    -> application use case     (internal/application)
    -> domain rules/interfaces  (internal/domain)
    -> SQLite repository        (internal/storage/sqlite, embedded migrations)
```

HTTP handlers hold no database logic, and the application layer depends only on
small domain interfaces (repositories, `Analyzer`, `Extractor`,
`EmbeddingProvider`). Provider adapters live in their own packages and are
selected at startup.

```text
cmd/server            program entry point + graceful shutdown
cmd/capture           thin CLI that posts a learning_capture_v1 file/stdin to POST /captures
internal/domain       entities from Entry to Concept and annotation, small interfaces, validation
internal/application  use cases: entries, analysis, feedback, effective views, inventory, capture,
                      extraction, concepts and annotation, dataset/quality/retrieval, Knowledge Library
internal/analyzer     local rule-based Analyzer + OpenAI Analyzer + named rule engine (assessment)
internal/extractor    OpenAI knowledge Extractor (opt-in) selected by EXTRACTOR_PROVIDER
internal/embedding    optional HTTP text-to-vector provider for M12-D evaluation
internal/captureclient   thin HTTP client for POST /captures (used by cmd/capture)
internal/storage/sqlite  SQLite repositories + migration runner
internal/transport/http  HTTP handlers and routing
internal/config       environment-based configuration
migrations            embedded .sql migrations
examples/captures     example learning_capture_v1 documents
web                   internal workbench (React + Vite + TS): Learning Records, Knowledge Library,
                      Concept Review, Annotation Inspector, Experiment Dashboard
scripts/demo/flh034   synthetic Knowledge Library demo (isolated database, local stub extractor)
```

The end-to-end data flow, from the learner's question to the research reports:

```text
learner input
  -> Entry
  -> Analysis
  -> Feedback / Effective Analysis
  -> explicit Knowledge Extraction
  -> KnowledgeConcept / human annotation
  -> Knowledge Library (read-only search and provenance)
  -> Dataset v1 / Quality Report
  -> Retrieval Evaluation / Comparison
  -> Experiment Dashboard
```

The default configuration runs Entry, local Analysis, Capture and the read-only
inventory without any API key. Knowledge extraction is unavailable while
`EXTRACTOR_PROVIDER=disabled`; a fresh database needs extracted units and explicit
human annotations before the Concept dataset and retrieval reports become
meaningful.

The active ownership chain for one learning record:

```text
learner-authored source truth -> Entry
versioned machine interpretation -> Analysis
human correction/review -> Feedback
current interpreted view -> Effective Analysis / Inventory
```

## 3. Source records and interpretation

### 3.1 Entry: the learner-authored source record

`Entry` is exclusively the learner-authored source record: ID, original input,
original context, and timestamps. It has no category, explanation, or confidence
fields, and the normal Entry repository and HTTP responses neither select nor
expose such values.

Migration `001_create_learning_entries.sql` historically created nullable
`category`, `explanation`, and `confidence` columns before milestone 2 established
the versioned Analysis model. Those columns remain physically present so existing
databases created from the original migration continue to open without a table
rebuild or rewritten migration history. They are legacy compatibility storage
only: active Entry reads/writes ignore them, no values are migrated or synthesized,
and they carry no current domain or API authority.

### 3.2 Versioned analysis

AI-generated metadata is stored separately from the original entry as versioned
`entry_analyses` rows. One entry may have many analyses; each is immutable and
carries an incrementing per-entry `version`, giving an audit trail. The original
`learning_entries` row is never modified when an analysis is produced.

Analysis flow:

HTTP request (POST /entries/{id}/analysis)
    -> transport layer
    -> application AnalysisService
        -> domain repository (load entry)
        -> domain Analyzer (produce metadata)
        -> AnalysisResult.Validate (reject invalid metadata)
        -> domain AnalysisRepository (append versioned record)

The `Analyzer` interface lives at the domain boundary. Milestone 2 ships a
deterministic rule-based analyzer (`internal/analyzer`) so the full workflow
runs and is testable without any external AI provider; an
OpenAI-backed implementation (milestone 4) sits behind the same interface
([§3.3](#33-analyzer-providers)), chosen at
startup without touching the transport, application, or storage layers.

Validation before storage: `category` and `explanation` are required and length
bounded, `confidence` must be in `[0, 1]`, and `uncertainty` is bounded
free-form text. Metadata that fails validation is rejected with HTTP `422` and
never reaches the database.

Endpoints:

- `POST /entries/{id}/analysis` — analyze an entry, append a new version.
- `GET  /entries/{id}/analyses` — list an entry's analyses, oldest first.

### 3.3 Analyzer providers

The analyzer is selected at startup by `AI_PROVIDER`, with no change to the
`POST /entries/{id}/analysis` endpoint or its response shape. Provider selection
lives in a small factory (`analyzer.New`) rather than being spread through
`main.go`; the chosen `Analyzer` is passed to the existing `AnalysisService`, so
the flow is unchanged:

    HTTP handler -> AnalysisService -> domain.Analyzer -> AnalysisResult.Validate -> append entry_analyses

- **rule-based** (default): the local deterministic analyzer. No external calls,
  no cost. Provenance `rule-based` (unchanged).
- **openai** (opt-in): `analyzer.OpenAI` calls the OpenAI Responses API using
  the standard-library HTTP client (no SDK dependency). It sends `POST
  /responses` with `store: false` and no tools or conversation state. The
  request uses a two-message `input` array: a trusted `developer` message
  carrying the taxonomy instruction, and a `user` message carrying the entry as
  a serialized JSON payload (`entry_id`, `entry_content`, `original_context`,
  …), each as an `input_text` content part. Keeping the entry in its own user
  message — never merged into the developer instruction — is a deliberate
  separation of trusted instructions from untrusted entry data, not just a
  match of the documented example. It requests strict JSON-schema structured
  output with `additionalProperties: false` and a `category` `enum` derived from
  the domain taxonomy, mapping exactly onto `AnalysisResult`. The model is
  instructed not to rewrite or normalize the original entry. Provenance is
  `openai:<model>:fr_l2_taxonomy_v1`, where the prompt version is a code
  constant tracking the taxonomy version. No database columns or migrations were
  added — the existing `entry_analyses.analyzer` TEXT column carries provenance.

Categories are a shared domain concept, not a provider detail. The
`fr_l2_taxonomy_v1` taxonomy (vocabulary, grammar, morphology, orthography,
pronunciation, pragmatics, discourse, comprehension, translation, mixed, other)
lives in `domain` as the single source of truth. `AnalysisResult.Validate`
normalizes the category (trim + lowercase) and rejects any value outside the
taxonomy, so the database never stores provider-specific category systems. Both
analyzers map onto it: the rule-based analyzer emits taxonomy values directly
(e.g. `comprehension`/`grammar`/`vocabulary`/`other`), and the OpenAI analyzer
constrains output via the schema enum and is validated again before storage.

Configuration is validated at startup (`config.Load`): an unknown `AI_PROVIDER`,
or `openai` without `OPENAI_API_KEY`/`OPENAI_MODEL`, is a fatal startup error
rather than a silent fallback. The API key is never logged or placed in error
messages. `OPENAI_TIMEOUT` (default 8s) is kept below `HTTP_WRITE_TIMEOUT`
(default 10s) so a provider request cannot normally outlive the response
deadline.

Error model: provider failures never create an analysis and never fall back to
rule-based mid-request. A fired timeout (or deadline-exceeded context) wraps
`ErrProviderTimeout` → HTTP `504`; network failures, upstream HTTP errors
(401/403/429/5xx), and structurally unusable responses (malformed JSON,
missing/refused/incomplete output) wrap `ErrProviderUnavailable` → HTTP `502`.
Well-formed output that fails domain validation stays `ErrValidation` → `422`,
consistent with the rule-based path. Public error messages are generic; detail
is preserved through error wrapping for logs and tests but never leaks the API
key, Authorization header, full provider response, or original learning content.
Provider error bodies are read through a bounded reader. No retries are
performed.

Operational notes:

- `AI_PROVIDER=openai` calls the OpenAI Responses API; that usage is billed by
  OpenAI and is separate from any ChatGPT subscription.
- Enable providers only through the process environment or an untracked `.env`
  file ([§10.2](#102-configuration)); never place credentials in Git.
- Automatic hybrid routing between the local engine and OpenAI is not
  implemented; there is no fallback in either direction.

### 3.4 Local rule engine

The local analyzer (milestone 6 replaced an earlier four-branch `switch`) is a
deterministic, explainable rule engine.

It lives entirely in `internal/analyzer` (`assessment.go`). The engine is implementation
detail: the core domain still knows only `AnalysisResult`. It performs no I/O,
no network call, uses no clock and no randomness, so the same entry always
yields byte-identical output.

Read flow:

    Entry
      -> RuleBased.Assess
          -> feature extraction        (lowercased input/context, token count, letters, has-context)
          -> named rule evaluation     (explicit cue rules over input AND context; weak fallbacks only if none fire)
          -> category score aggregation (strongest match + bounded support; taxonomy-order tie-break)
          -> confidence and conflict calculation (heuristic score, top-vs-runner-up margin)
          -> NeedsAI recommendation     (advisory only)
      -> RuleBased.Analyze              (converts the assessment into AnalysisResult)
      -> shared AnalysisResult.Validate (same validation as every analyzer)
      -> immutable analysis storage     (append-only, unchanged)

`Analyze` delegates to `Assess`, so the classification algorithm exists in one
place and the two can never diverge. The structured `LocalAssessment`
(category, heuristic confidence, `NeedsAI`, matched rules in deterministic
order, specific uncertainty reasons) is internal; only the derived
`AnalysisResult` (category, explanation, confidence, uncertainty) is persisted.

Rules are named and weighted. Explicit cue rules (`explicit_translation_request`,
`explicit_pronunciation_request`, `explicit_orthography_request`,
`explicit_morphology_request`, `explicit_grammar_request`,
`explicit_vocabulary_request`, `explicit_pragmatics_request`,
`whole_utterance_comprehension`) match specific ASCII/French/CJK cues and are
strong. Weak fallbacks (`single_token_fallback` → vocabulary,
`multi_token_fallback` → grammar, `no_linguistic_content` → other) apply only
when no explicit rule fires, so token counts never dilute or override a specific
cue. A bare `?` no longer forces `comprehension`. Both input and context are
inspected (context can strengthen or introduce a match); neither is mutated.

Score aggregation is `strongest match + a bounded, capped contribution from
supporting matches`, so ten weak substring hits cannot outweigh one specific
rule. Confidence is a documented **heuristic decision score, not a calibrated
probability**, derived from strength, compatible support, the top-vs-runner-up
margin, presence of context, input length, and whether only fallbacks matched;
all weights and thresholds are named constants.

Key decisions, explicitly:

- `NeedsAI` is **advisory only** — it never triggers an API call in this
  milestone. It is set when confidence is low, only fallbacks matched, top
  categories conflict within a small margin, input is very short with no
  context, no meaningful rule matched, or the category needs semantic judgment
  (`pragmatics`/`discourse`/`mixed`).
- No API call occurs inside `RuleBased`.
- No automatic fallback occurs between providers in either direction.
- No rules are automatically rewritten, and human feedback does not yet update
  weights.
- Provenance is versioned to `rule-based:v2:fr_l2_taxonomy_v1`
  (`rule-based:<ruleset-version>:<taxonomy-version>`) so records from different
  rulesets are distinguishable. Historical analyses are not rewritten and no
  migration is added. The shared taxonomy is unchanged.

This structured assessment is deliberate groundwork for a future hybrid policy
and evaluation loop; the routing/escalation itself is out of scope here.

### 3.5 Human feedback

Human judgment about an analysis is stored as immutable `analysis_feedback`
rows. Each row references exactly one `entry_analyses` row. Feedback is
append-only, so the full history of decisions is preserved, and neither the
original `learning_entries` row nor the `entry_analyses` row is ever modified
when feedback is added. A correction proposes better metadata alongside the
analysis; it does not overwrite it.

Feedback flow:

HTTP request (POST /analyses/{id}/feedback)
    -> transport layer
    -> application FeedbackService
        -> NewFeedbackInput.Validate (reject invalid feedback)
        -> domain FeedbackRepository (verify analysis exists, append record)

Statuses: `accepted`, `corrected`, `rejected`. Validation before storage:
status must be one of the three; when status is `corrected`, at least one of
`corrected_category` or `corrected_explanation` must be present (either or both)
and any present field is length bounded; for `accepted`/`rejected` corrected
content must be absent; `user_note` is optional and bounded. Validation runs in
the application service and again in the SQLite repository (which calls the same
domain validation method before opening a transaction), so invalid input never
reaches the database even if the repository is used directly. Invalid feedback
is rejected with HTTP `422`. A reference to a non-existent analysis returns HTTP
`404`.

Endpoints:

- `POST /analyses/{id}/feedback` — append an immutable feedback record.
- `GET  /analyses/{id}/feedback` — list an analysis's feedback, oldest first.

### 3.6 Effective analysis

An analysis is immutable and its feedback is append-only, so the *current
interpretation* of an analysis is not a stored row — it is derived on demand by
combining the analysis with its latest feedback. It is exposed as a strictly
read-only projection (milestone 5). Nothing new is persisted; no
analysis or feedback record is mutated; no table or migration is added.

Resolution flow:

    HTTP request (GET /analyses/{id}/effective)
        -> transport layer
        -> application EffectiveAnalysisService
            -> domain AnalysisRepository.GetByID       (load the analysis)
            -> domain FeedbackRepository.GetLatestByAnalysis  (load latest feedback only)
            -> domain.ResolveEffective                 (pure function, no I/O)

`ResolveEffective` is a pure domain function over `(analysis, latestFeedback)`;
it holds the resolution rules and performs no I/O and no mutation. The
`EffectiveAnalysis` read-model (`internal/domain/effective.go`) is never stored.
It carries identity (`AnalysisID`, `EntryID`, `Version`), the original values,
the effective values (a pointer so it can be absent), a typed `Resolution`, and
the resolving `FeedbackID` (a pointer so it can be absent).

Only the **latest** feedback decides the outcome. "Latest" is defined
deterministically as the most recent by `created_at`, breaking ties by `id`
(`ORDER BY created_at DESC, id DESC LIMIT 1`), computed in the SQLite layer so no
full history is loaded. `GetLatestByAnalysis` returns `ErrNotFound` when the
analysis does not exist, and `(nil, nil)` when the analysis exists but has no
feedback — distinguishing "missing" from "unreviewed".

Resolution is one of four typed states (`domain.Resolution`):

- **`unreviewed`** — no feedback. Effective values equal the original;
  `FeedbackID` is absent.
- **`accepted`** — latest feedback accepted. Effective values equal the
  original; `FeedbackID` set.
- **`corrected`** — latest feedback corrected. Present corrected fields override
  the original; absent corrected fields retain the original value; `FeedbackID`
  set. Corrected categories are constrained to `fr_l2_taxonomy_v1` at feedback
  validation time.
- **`rejected`** — latest feedback rejected. There is no effective
  interpretation, so the effective values are absent (not copied from the
  original); the original is still reported for reference; `FeedbackID` set.

There is no fallback to older feedback or to a different version: an earlier
accepted or corrected record never resurfaces after a later rejection. Because
the projection is recomputed per request, it always reflects the current
feedback state.

Endpoint:

- `GET /analyses/{id}/effective` — resolve and return the effective analysis. A
  non-numeric id returns `400`; a missing analysis returns `404`; an unexpected
  failure returns `500` with a generic message (internal storage errors are not
  exposed). A `rejected` analysis serializes `"effective": null`.

Corrected-category validation (tightened in milestone 5): when
`corrected_category` is present it is trimmed, lowercased, and rejected unless it
is a `fr_l2_taxonomy_v1` value (reusing `domain.ValidCategory`, so the taxonomy
list is not duplicated). This keeps corrected categories consistent with the
categories analyses themselves must use.

### 3.7 Learning inventory

The read-only **learning inventory** (milestone 7) shows the whole collection at
once. It is a cross-entry projection
that, for each entry, combines its latest analysis and that analysis's latest
feedback into one current row. Like effective-analysis resolution, it is derived
on demand — no new table, no migration, no mutation, and no AI call. It reads *across*
entries rather than operating on one.

Read flow:

    HTTP request (GET /learning-records | /summary | /export)
        -> transport layer            (parse filters/pagination only)
        -> application InventoryService (validate + normalize query, bound limit)
        -> domain InventoryRepository   (single projection query)
            -> SQLite: latest-analysis + latest-feedback via window functions
        -> domain.ResolveEffective      (per row, reused unchanged)

The read model is `domain.LearningRecord`: the original entry fields, nilable
latest-analysis metadata, a `LearningRecordState`, the `original` analysis
values, the `effective` interpretation, and the resolving `feedback_id`. It is
never persisted. State is derived, not stored:

- **`unanalyzed`** — no analysis exists. Analysis metadata, `original`, and
  `effective` are all absent. This is an *inventory* concept and is deliberately
  **not** a `domain.Resolution` value; the other four states map one-to-one onto
  the existing resolutions via `StateFromResolution`.
- **`unreviewed` / `accepted` / `corrected` / `rejected`** — the state of the
  latest analysis under its latest feedback, exactly as
  `domain.ResolveEffective` already defines it. `effective` is absent for
  `rejected` (a rejected analysis has no current interpretation); `original` is
  always preserved.

#### Deterministic latest selection, in one query

All SQL lives in `internal/storage/sqlite`. A single projection built from CTEs
and window functions avoids an N+1 query per entry:

    WITH la AS (  -- latest analysis per entry
      ... ROW_NUMBER() OVER (PARTITION BY entry_id ORDER BY version DESC, id DESC) ...
      WHERE rn = 1
    ),
    lf AS (       -- latest feedback per (latest) analysis
      ... ROW_NUMBER() OVER (PARTITION BY analysis_id ORDER BY created_at DESC, id DESC) ...
      WHERE rn = 1
    ),
    proj AS ( learning_entries LEFT JOIN la LEFT JOIN lf, plus derived state/effective_category )

"Latest" is fully deterministic: analyses by `version DESC, id DESC`, feedback by
`created_at DESC, id DESC` — the same tie-break rule (`id` breaks equal
timestamps) that effective-analysis resolution uses, so an inventory row and the
`/analyses/{id}/effective` endpoint never disagree. Older analysis versions and
superseded feedback contribute nothing, and every entry yields exactly one row.

The projection computes `state` and `effective_category` in SQL so that
filtering and cursor pagination happen in the database — a `LIMIT`ed page is
therefore accurate rather than short after in-memory filtering. The actual
returned values are still resolved in Go through `domain.ResolveEffective`, so
the resolution rules live in exactly one place; the SQL expressions exist only
for correct server-side filtering and aggregation and mirror those rules.

#### Filtering, pagination, and the summary

`LearningRecordQuery` (state, effective category, analyzer, limit,
`before_entry_id`) is validated and normalized in the application service:
`state` and `category` are trimmed/lowercased and checked against the shared
vocabularies; `analyzer` is matched **exactly** (provenance strings are
case-sensitive), never as a substring; a non-positive `before_entry_id` is
rejected. Limit handling is *normalizing, not rejecting*: a non-positive limit
falls back to the default and an over-large one is clamped to the max (50/200 for
the list endpoint, 500/5000 for export). Category filtering uses the **effective**
category, so **rejected and unanalyzed records — which have no effective
category — never match a category filter**. Records are ordered by entry id
descending; `before_entry_id` is a descending cursor, and the list response
returns `next_before_entry_id` (null at the end) instead of a fabricated total.

The summary uses aggregate SQL over the same projection rather than loading every
row. State counts sum to the total and every state key is always present (zero
when none match); `analyzed + unanalyzed == total`; `by_effective_category`
excludes rejected/unanalyzed (NULL effective category); `by_analyzer` counts the
latest analysis's provenance per analyzed entry. Summary maps are assembled
without relying on Go map iteration order, so results are deterministic.

Export streams the same records as JSONL (`application/x-ndjson`), one object per
line with no enclosing array, written incrementally rather than buffered, and
stops on a write/encode failure. It never emits API keys, environment values, or
other internal data, and — like every inventory endpoint — performs no AI call.

### 3.8 Timestamp ordering in SQLite

Persisted timestamps retain their RFC3339Nano representation. SQLite queries that
order timestamps use `COLLATE flh_timestamp_v1`, registered once with the SQLite
Go driver for all subsequently opened connections. The collation parses each
value with Go's RFC3339Nano parser and compares instants without dropping
nanoseconds; equal instants fall through to the query's ID tie-break. This covers
latest feedback (including the inventory window), admission overrides and derived
support, unit judgments and reviewability, and chronological event histories.
Version-based analysis/extraction selection and CURRENT SAME membership authority
are unchanged.

The comparison supports existing variable-width fractions and timezone offsets
without migration, backfill, or mutation of immutable history. Clock rollback
retains chronological semantics rather than insertion-order semantics. Malformed
values sort above valid values so latest-record scanners report their parse errors;
two malformed values use deterministic text ordering. The collation cannot itself
return an error. External database tools must register the collation to execute
these application queries; ordinary database reads and stored schema are unchanged.
Timestamp parsing during sorting may cost more than binary text sorting, and
existing binary timestamp indexes cannot supply the custom ordering directly.

Introduced by FLH-004.

## 4. Capture import and the capture CLI

### 4.1 `learning_capture_v1` import

Capture import (milestone 8) brings learning from an external French discussion
(for example in ChatGPT) into the system: `POST /captures` accepts
 a versioned `learning_capture_v1` document and turns it
into a normal learning entry plus, optionally, a version-1 analysis. It is a
deliberate, narrow contract — **not** a chatbot. The backend makes **no AI
call**, never contacts ChatGPT or any model, never scrapes or stores a
conversation transcript, and parses no HTML or Markdown. It ingests only the
structured fields the client sends.

Import flow:

    HTTP request (POST /captures)
        -> transport layer            (strict JSON decode; reject unknown/trailing fields)
        -> application CaptureService
            -> NewLearningCaptureInput.Validate  (schema version, capture id, source,
                                                   entry data + analysis via REUSED validation)
            -> ImportedAnalysisProvenance(source) (server-constructed provenance, one place)
            -> CaptureFingerprint(prepared)       (deterministic content hash)
            -> domain CaptureRepository.Create
        -> SQLite: single transaction
             check capture_id -> insert entry -> (insert version-1 analysis) -> insert receipt -> commit

    HTTP request (GET /captures/{capture_id})
        -> transport layer            (router URL-decodes the id)
        -> application CaptureService.GetCapture (validate/normalize id)
            -> domain CaptureRepository.GetByCaptureID

#### What the client may and may not supply

The public contract is content-only. The client supplies `schema_version`,
`capture_id`, `source`, `original_input`, `original_context`, optional `analysis`
(category/explanation/confidence/uncertainty), and optional `discussion_summary`.
It never supplies database ids, analysis version, timestamps, analyzer
provenance, feedback status, or effective resolution — those are all derived by
the server. Strict decoding (`DisallowUnknownFields` plus a trailing-token check)
rejects unknown fields at the top level and inside `analysis`, and rejects a
second JSON object after the first.

`schema_version` must be exactly `learning_capture_v1` (a single domain constant,
not scattered string literals); any other value is a validation error. `source`
is a typed vocabulary (`chatgpt-web`, `manual`); an unknown source is rejected,
and there is no free-form source. Crucially, **source is descriptive metadata and
does not confer trust** — it never changes how the capture is validated or
stored.

#### Reuse, not a second taxonomy

The capture domain does not introduce a parallel validator or category system. An
imported `analysis` is carried as `ImportedAnalysisInput`, converted to the
existing `domain.AnalysisResult`, and validated by the **same**
`AnalysisResult.Validate` every analyzer already uses — so the `fr_l2_taxonomy_v1`
taxonomy and all bounds are enforced in exactly one place. Entry input and
context reuse the existing entry validation. If a present analysis is invalid,
the whole capture fails and nothing is stored.

Analyzer provenance for an imported analysis is server-constructed as
`imported:<source>:learning_capture_v1` (e.g.
`imported:chatgpt-web:learning_capture_v1`) by a single domain function, never
supplied by the client. The imported analysis is stored as an ordinary version-1
row through the existing `entry_analyses` shape, so it is not special-cased
anywhere downstream — later analyses of the same entry continue at version 2, 3,
… and list, feedback, effective-resolution, and inventory all treat it as any
other analysis.

#### Persistence: one receipt table, one transaction

Migration `004_create_learning_captures.sql` adds a `learning_captures` receipt
table: `capture_id` (UNIQUE — the idempotency key), `entry_id` (UNIQUE, FK to
`learning_entries` `ON DELETE RESTRICT`), nullable `analysis_id` (UNIQUE, FK to
`entry_analyses`), `source`, `schema_version`, `discussion_summary`,
`content_fingerprint`, and `created_at` (RFC3339 text, matching the existing
convention). It deliberately does **not** duplicate the original input, context,
category, or explanation — those live in their own tables and the receipt only
references them. The migration is additive and idempotent
(`CREATE TABLE IF NOT EXISTS`), so applying it to a milestone-7 database leaves
existing rows untouched (verified by `TestMigration_UpgradeFromPreM8`).

Creation is atomic in a single SQLite transaction: check whether the `capture_id`
already exists, insert the entry, insert the version-1 analysis if one is present
(with server provenance), insert the receipt, and commit. Any failure rolls the
whole transaction back, so a partial import can never persist (verified by
forcing failures at the analysis and receipt steps). All capture SQL lives in
`internal/storage/sqlite`; the domain exposes only a narrow
`CaptureRepository{Create, GetByCaptureID}` interface, and the SQLite-specific
uniqueness error is translated to a domain `ErrConflict` before leaving the
package.

#### Idempotency by content fingerprint

Idempotency is keyed on `capture_id` and decided by a deterministic SHA-256
**content fingerprint** computed over the *normalized* capture content — schema
version, capture id, source, normalized input/context/summary, whether an
analysis is present, and the normalized analysis fields. It is computed with
stdlib crypto only, uses length-prefixed field encoding so field boundaries can't
collide, and deliberately excludes ids, timestamps, and raw JSON bytes, so
whitespace or key ordering never affects the decision. The fingerprint never
leaves the storage layer except as an equality decision and is never logged or
returned to clients.

- New `capture_id` → insert, `Created=true` (HTTP `201`).
- Same `capture_id`, same fingerprint → return the existing result,
  `Created=false`, no new rows (HTTP `200`).
- Same `capture_id`, different fingerprint → `domain.ErrConflict`, existing
  capture untouched (HTTP `409`).

Concurrency does not rely on the read alone: the `capture_id` UNIQUE constraint
is the source of truth. If a concurrent writer wins the race between the
in-transaction existence check and the receipt insert, the insert fails on the
constraint; the repository rolls back and re-resolves against the now-committed
row, returning a replay or a conflict. Concurrent identical submissions therefore
yield exactly one entry, and concurrent conflicting ones yield one entry and one
conflict (both verified).

#### Result, lookup, and status mapping

`LearningCaptureResult{CaptureID, EntryID, AnalysisID *int64, Created bool}` is
the creation result; `analysis_id` serializes as explicit JSON `null` when the
capture carried no analysis. `GET /captures/{capture_id}` returns metadata and
references only (capture id, schema version, source, entry id, analysis id,
discussion summary, created-at) — never the fingerprint, and never a duplicate of
the full entry/analysis content, which is fetched through the existing endpoints.

The transport layer maps outcomes to status codes: `201` new, `200` exact replay,
`400` invalid/unknown-field/trailing JSON and malformed lookup id, `422`
unsupported schema and invalid content, `409` changed content, `404` missing
lookup, `500` unexpected storage failure. Errors use the shared `{"error":"..."}`
shape with concise messages that never expose SQL, the fingerprint, API keys,
environment variables, internal error chains, or authorization headers.

#### Guarantees

- No AI call, no external request, no conversation scraping, no transcript
  storage — the backend is not a chatbot and never becomes one here.
- Original learning input and context are preserved verbatim as a normal entry;
  imported analyses are separate, versioned metadata, exactly like every other
  analysis.
- Imports are idempotent and safe to retry; a differing resubmission conflicts
  rather than overwriting.
- Every write is atomic; a partial import never persists.
- The migration is additive and safe for existing databases.
- Validation, taxonomy, provenance format, and effective resolution each live in
  a single place and are reused, not reimplemented.

### 4.2 Capture CLI

The capture CLI (milestone 9) is a small external client for the
`POST /captures` contract. It is purely a transport adapter that turns a prepared
`learning_capture_v1` document into an HTTP request against the existing
endpoint:

    external learning_capture_v1 JSON (file or stdin)
        -> cmd/capture            (flags, input selection, exit code)
        -> internal/captureclient (POST {baseURL}/captures, decode result)
        -> existing server: HTTP transport -> application -> domain -> SQLite
        -> learning inventory

The client deliberately enters through the same public HTTP API an external tool
would use. It does **not** import the SQLite repository or the application
service, so milestone 9 genuinely exercises the real
`external client -> HTTP -> storage` path rather than shortcutting it.

#### Layering

`cmd/capture/main.go` is intentionally thin: it parses flags, chooses the input
source (file or stdin), resolves the backend URL, builds the client, invokes it,
prints a stable summary, and sets the process exit code. All testable behavior
lives in `internal/captureclient`, which is unit-tested against an
`httptest.Server` and integration-tested against the real handler and a real
temporary SQLite database. This keeps the CLI's own logic trivial and the HTTP
behavior fully covered, and it means the capture client is **not** a second
application layer — it is a client of the one that already exists.

#### The client does not duplicate domain rules

The server owns every capture rule: schema version, source vocabulary, entry
validation, `fr_l2_taxonomy_v1`, analysis validation, SHA-256 fingerprinting,
idempotency, and conflict detection. The client reimplements none of them. It
sends the caller's payload byte-for-byte — it never rewrites `original_input`,
normalizes content, generates an analysis, reclassifies a category, adjusts
confidence, rewrites `discussion_summary`, or computes a fingerprint. The only
checks it makes are transport-level: the payload is non-empty, the base URL is a
valid absolute HTTP(S) URL, and the response decodes into the expected shape. The
server decides whether a non-empty payload is actually valid.

#### Response mapping

The client mirrors the server's existing outcomes onto typed results and errors:

- `201` / `200` → a decoded `Result{CaptureID, EntryID, AnalysisID, Created}`.
  `Created` distinguishes a new capture from an idempotent replay; a replay is a
  success, not an error, so the CLI exits `0`.
- non-2xx → an `*APIError{StatusCode, Message}` carrying the server's safe public
  message from the shared `{"error":"..."}` body. `409` conflict is surfaced via
  `APIError.IsConflict()`; `400`/`422`/`500` propagate their status and message.

#### Safety properties

- **Standard library only.** `net/http`, `context`, `encoding/json`, `io` — no
  new dependency for a single POST client, and `go.mod` is unchanged.
- **No leakage.** Errors contain only the status code and the server's own
  message. The learning payload (`original_input`, `original_context`,
  `discussion_summary`), credentials, authorization headers, and environment
  values are never folded into an error, even on a network or decode failure.
- **Bounded reads.** The request payload is capped when read from file/stdin, and
  error/response bodies are read through a bounded `io.LimitReader`, so a large
  or hostile response cannot make the client buffer without limit. The error
  message is decoded from the leading JSON object, so a truncated or
  junk-suffixed body still yields the intended message.
- **No retries, no fallback, no AI.** A single request per invocation with a
  bounded timeout and request context (cancelled on SIGINT/SIGTERM); no automatic
  retry, no provider fallback, and no model call anywhere in the path.

#### Configuration

The backend URL is resolved with the precedence `-url` flag → `FRENCH_HUB_URL`
→ `http://localhost:8080`. This mirrors the server's environment-first
convention without adding a configuration framework or reading `.env` files, in
keeping with the project's dependency and configuration discipline.

## 5. Knowledge extraction and admission

Knowledge extraction (milestone 10) turns one interaction into durable,
reviewable learning material: zero or more atomic **knowledge units**.

    learning entry (immutable) + current effective analysis
        -> ExtractionSource        (both original data AND effective interpretation)
        -> Extractor               (one real implementation: OpenAI)
        -> validated ExtractionResult (zero or more units; empty is valid)
        -> knowledge_admission_v1  (one machine recommendation per unit)
        -> atomic persistence      (extraction + units + recommendations, versioned)
        -> human admission overrides (append-only, human wins)

A knowledge unit is *a learning objective that actually arose from this
interaction and can later be independently judged or reviewed* — deliberately not
every linguistic fact present in the text, and deliberately the smallest **useful
reviewable** objective rather than the smallest linguistic token (so
`vouloir — présent` is one unit, not one per person/number). Zero units is a
valid, expected outcome.

#### Extraction source: both original and effective

The source combines the immutable entry (original input/context) with its current
effective interpretation, reusing the milestone-5 `ResolveEffective` rules rather
than building a second projection. This is why extraction is gated on eligibility
(below): the effective interpretation must exist and be current.

#### Eligibility is explicit, never automatic

Extraction runs only on an explicit `POST /entries/{id}/extractions`. It is never
triggered as a side effect of entry creation, analysis, feedback, or capture
import. Eligibility maps directly onto the existing resolution states: an entry
is eligible when its current analysis resolves to `unreviewed`, `accepted`, or
`corrected`; an `unanalyzed` entry or a `rejected` current analysis is not
eligible and yields `domain.ErrNotEligible` (`409`). A `corrected` analysis
extracts from the corrected effective values; `accepted`/`unreviewed` use the
current effective values.

#### Immutable, versioned provenance — sufficient to derive staleness later

Each run is a `KnowledgeExtraction{EntryID, Version, SourceAnalysisID,
SourceFeedbackID, Extractor, CreatedAt}`, versioned per entry exactly like
analyses (`MAX(version)+1` inside the insert transaction). It records the precise
analysis and feedback it was derived from, and the repository rejects an
extraction whose provenance is inconsistent (a source analysis from another
entry, or source feedback from another analysis) so a recorded provenance is
always trustworthy. A later analysis or feedback never mutates an existing
extraction — a new run appends a new version.

The source is read before the provider call and no transaction or connection is
held while the provider runs, so the interpretation can move during the call.
The repository therefore also checks *currency* inside the write transaction,
after the ownership checks and before any insert: the source analysis must still
be the entry's latest analysis (by version) and the source feedback must still be
that analysis's latest feedback (by the shared `flh_timestamp_v1` latest-record
ordering; both absent is a match), and that feedback must not be `rejected`.
Otherwise `domain.ErrExtractionSourceChanged` (`409`) discards the result before
anything is written. SQLite serializes writers, so the check and the inserts see
one consistent state. There is deliberately no stored
`stale` boolean and no staleness feature; the recorded
provenance is *sufficient to derive staleness later* by comparing it against the
entry's current effective interpretation, but nothing here computes or exposes
that signal yet.

#### Knowledge kinds are a separate vocabulary

Kinds use a dedicated `fr_l2_knowledge_v1` vocabulary (`vocabulary`, `grammar`,
`morphology`, `orthography`, `pronunciation`, `usage`, `expression`), separate
from the interaction taxonomy `fr_l2_taxonomy_v1`. The two answer different
questions ("what objective arose" vs. "what kind of interaction was this"), so
they are modeled as distinct types with distinct validation.

#### One real extractor, decoupled configuration

Only a semantic OpenAI extractor ships; there is no rule-based extractor by
design. It closely mirrors the milestone-4 OpenAI analyzer: standard-library
HTTP, explicit timeout via context, no retries, `store:false`, no tools, no
conversation state, strict JSON-schema structured output, bounded error-body
reads, and validation of the parsed result before it is returned. Provenance is
`openai:<model>:knowledge_extraction_v1`.

Extractor selection is a separate `EXTRACTOR_PROVIDER` knob (`disabled` default,
or `openai`), independent of `AI_PROVIDER`, so a deployment may run the
rule-based analyzer and the OpenAI extractor together. When disabled, the factory
returns a nil extractor: the server runs normally and the extraction endpoint
returns `503` — never a silent fallback to another provider.

#### Fixed admission ruleset (`knowledge_admission_v1`)

Admission answers "should this unit currently enter the active learning pool?".
The v1 ruleset is fixed and conservative: it does not learn, generate rulesets,
or change its own thresholds. In output order it emits one recommendation per
unit — `active` (the default for a valid unit), `suppressed` (an **exact
duplicate**: same kind + normalized canonical of an earlier unit in the same
extraction, where normalization is trim + lowercase + collapse-whitespace with
accents preserved — no embeddings, stemming, or semantic similarity), or
`needs_review` (confidence below a single named, documented, non-calibrated
threshold — uncertain cases defer to a human rather than being suppressed). A
suppressed duplicate is still persisted; suppression is a recommendation, not a
deletion.

The extractor's own result validation is stricter still: it *rejects* a result
containing exact-duplicate units (same kind + canonical + statement + example)
rather than silently de-duplicating, so provider output is never quietly
rewritten before storage. The admission ruleset's looser kind+canonical rule then
operates across genuinely distinct units.

#### Human authority, append-only

The machine recommendation is immutable and non-authoritative. A human may append
an `AdmissionOverride` (`active` or `suppressed` with a reason of `mastered`,
`ignored`, or `other`). Overrides never mutate or delete the recommendation; the
full history is preserved (machine recommendation, every override, and the
derived effective state stay distinguishable). The effective state is computed on
read via `ResolveAdmission`, where the latest human override wins. This preserves
exactly the provenance a future milestone would need to analyze machine-vs-human
agreement — though ruleset evolution itself is out of scope here.

#### Persistence and atomicity

Migration `005` adds four tables: `knowledge_extractions`, `knowledge_units`
(`UNIQUE(extraction_id, ordinal)`, `canonical` intentionally **not** unique),
`knowledge_admission_recommendations` (one per unit), and
`knowledge_admission_overrides` (append-only). An extraction, all its units, and
all initial recommendations commit in a single transaction — any failure rolls
back the whole run, so there is never a partially-persisted extraction. Because
both boundary interfaces declare a `Create`, the storage layer splits them into
`KnowledgeRepository` (extraction/units/recommendations) and `AdmissionRepository`
(overrides), sharing the admission-resolution read path.

#### Out of scope (deliberately not built)

Automatic extraction on capture/analysis/feedback; a rule-based semantic
extractor; local models; model routing or cost optimization; ruleset
evolution/proposal/replay/activation; spaced repetition or review scheduling;
mastery probability or automatic mastery detection; CEFR or difficulty scoring;
embeddings, vector search, or semantic duplicate detection; a knowledge or
prerequisite graph; and cross-interaction normalization. The history and
provenance are preserved so these remain possible later. (The
`KnowledgeConcept` aggregation layer is described in
[§6](#6-concepts-identity-membership-and-support).)

## 6. Concepts: identity, membership and support

### 6.1 Membership versus support (canonical summary)

These two ideas are the ones most often confused, so they are stated once here:

- **Membership** — a unit's **CURRENT SAME** membership: at most one Concept per
  unit, held in the mutable `unit_concept_memberships` projection. It is a human
  (or exact-signature automatic) judgment that the unit expresses the same
  learning identity as the Concept. The Knowledge Library calls such a unit
  *filed under* the Concept.
- **Support** — derived at read time, never stored. A unit **supports** a Concept
  only when all three hold: it is a CURRENT SAME member, it belongs to its entry's
  *current* extraction, and its effective admission is `active`.

So a member can fail to support (it comes from an older extraction, or the
learner suppressed it), a Concept with members can be **orphaned**, and history
(`unit_concept_links`), relations (BROADER/NARROWER/RELATED), DISTINCT pairs and
INVALID judgments never confer either membership or support. The rest of this
section gives the detail.

### 6.2 Identity and resolution

A `KnowledgeUnit` is the output of one extraction, so it is
tied to a single extraction of a single entry: re-extract the same entry, or
learn the same objective from a different interaction, and you get a *new* unit
for the *same* underlying thing to learn. A unit is therefore the wrong place to
hang durable learning state (review history, mastery, scheduling).
The durable identity is the **`KnowledgeConcept`** (milestone 10.5, corrected in
10.5.1), kept separate from the evidence that supports it.

    KnowledgeUnit (immutable extraction evidence / candidate)
        -> DeriveCandidateIdentity     (unit -> normalized concept identity)
        -> conservative deterministic resolver (exact signature match only)
        -> KnowledgeConcept (durable learning identity)
             ^ accepted SAME membership links (append-only, superseding)
             ^ current-extraction selection decides which units count as support

#### Two roles, deliberately separated

- A **`KnowledgeUnit` is immutable evidence**: the candidate representation of
  one objective as it appeared in one `KnowledgeExtraction`. Historical units are
  never deleted or rewritten. Its canonical/normalized text is *retrieval
  evidence*, not identity.
- A **`KnowledgeConcept` is the durable learning identity** that future review,
  mastery, and scheduling attach to. Its identity is an explicit, versioned
  schema (`fr_l2_concept_identity_v1`): `target`, `pedagogical_intent`, `scope`,
  and an extensible `identity_features` map. Identity is intentionally **not** a
  large fixed linguistic schema, and it deliberately excludes taxonomy decisions
  (`fr_l2_taxonomy_v1` vs `fr_l2_knowledge_v1` are not reconciled here).

The future Review Engine must target `KnowledgeConcept`, never a raw
`KnowledgeUnit`.

#### Deterministic identity signature

`ConceptIdentity.Signature()` is a canonical JSON encoding of the *normalized*
identity: each field is trimmed, lowercased, and internal whitespace collapsed
(accents preserved), and feature keys are sorted so the signature is independent
of map insertion order. Two different surface wordings that normalize to the same
identity produce the same signature; any difference in `target`,
`pedagogical_intent`, `scope`, or an identity-bearing feature produces a
different one. The signature is the sole basis for automatic equality.

#### Conservative, deterministic resolver (v1)

`ResolveConcept(candidate, matches)` classifies a candidate against the active
concepts sharing its signature and never force-merges:

- **no active concept with that signature** → `no_match` (a human may create a
  concept).
- **exactly one** → `matched` (safe to link SAME automatically).
- **more than one** → `ambiguous` (stays reviewable; never auto-merged).

The resolver is purely deterministic and does **no** embeddings, vector search,
sentence transformers, neural networks, LLM fuzzy matching, semantic similarity,
learned probabilities, `P(SAME)`, or automatic BROADER/NARROWER inference. These
are deliberately deferred until real human resolution labels exist to train and
evaluate against. Ambiguous candidates are surfaced for human review rather than
guessed.

#### Membership vs. relations vs. preferred representation

Three decisions are kept independent:

- **Membership** is a `same` link. A unit has **at most one *current* SAME
  membership**, held in a small mutable projection (`unit_concept_memberships`,
  one row per unit — see milestone 10.5.1). Re-affirming the same membership is
  idempotent; claiming a second, different concept through the SAME endpoint is
  `ErrConceptConflict` (`409`). A human correction that *moves* the membership to
  a different concept is a separate, always-allowed operation (`ReassignSame`);
  see milestone 10.5.1. **`ReassignSame` is the only operation that may move an
  existing current membership.** In particular, `POST /concepts` with
  `link_seed_as_same` only *establishes* membership for an **unresolved** seed
  unit; if the seed unit already has a current SAME membership, creation is refused
  with `ErrConceptConflict` and nothing is persisted — concept creation never gains
  hidden reassignment authority and never implicitly calls `ReassignSame`.
- **Reading current membership** is done through the projection, never by scanning
  the event log. A UI must not infer "which concept this unit belongs to now" from
  the append-only resolution events: a superseded event legitimately keeps
  `status = accepted` (it was accepted at the time it was recorded). The
  authoritative current answer is `unit_concept_memberships`, exposed read-only at
  `GET /knowledge-units/{id}/concept-membership`.
- **Relations** (`broader`, `narrower`, `related`) are recorded for review but
  are **not membership** — they never make a unit a member of a concept and never
  contribute support. `INVALID` is deliberately not a relation. Attempting to
  record `same` through the relation endpoint is rejected (`422`); use the SAME
  endpoint, which carries the membership invariant.
- **Preferred representation** is separate from membership. Accepting SAME does
  **not** auto-set the concept's preferred unit. `SetPreferredUnit` is an explicit
  operation and validates that the chosen unit has an accepted SAME membership to
  that concept (`422` otherwise). Concept IDs are stable when the preferred
  representation changes.

Every resolution decision preserves unit id, concept id, relation, status,
decision source (`resolver:automatic` or `human`), resolver version, an optional
score, structured auditable evidence, and a timestamp. History is strictly
append-only: a decision that replaces an earlier one inserts a **new** event row
carrying a `supersedes_link_id` back-pointer to the row it replaces, and the
earlier row is left byte-for-byte intact (milestone 10.5.1 removed the old
`UPDATE ... SET status='superseded'` rewrite). Which SAME event is *current* is
read from the `unit_concept_memberships` projection, not inferred by scanning
statuses.

#### Current extraction and the active-support invariant

A concept receives **automatic current support** from a unit only when all three
hold: the unit belongs to the entry's *current* successful extraction, its
effective admission state is `active`, and it has an accepted SAME link to the
concept. Historical, superseded, or rejected units never silently enter the
active pool.

"Current extraction" is derived, not a new mutable flag: by default the latest
successful extraction (`MAX(version)`) is current. A **successful zero-unit
extraction is still current** and simply contributes zero units. Because a failed
run persists nothing (milestone 10), it can never displace the last successful
current extraction. An explicit override row (`entry_current_extractions`) lets a
human roll back to an earlier extraction.

**Support is derived at read time, never persisted** (milestone 10.5.1). There is
no stored support flag to keep in sync and no recompute-on-write step: whenever a
concept is read, its supporting units are computed live from the three conditions
above against the *current* state of extraction selection, admission overrides,
and SAME membership. A newer extraction, an admission override, or a SAME
reassignment therefore changes a concept's effective support immediately, with no
separate recompute call.

Concept **lifecycle** and **support** are two separate, deliberately distinct
axes:

- **Lifecycle** is persisted (`knowledge_concepts.lifecycle_state`): `normal` or
  `retired`. `retired` is a sticky human decision.
- **Support** is derived (`supported`/`orphaned`) as described above and is
  **never stored**.

The **effective state** a reader sees combines them: `retired` wins; otherwise a
supported concept reads `active` and an unsupported one reads `orphaned`. An
orphaned concept is never deleted and recovers to `active` automatically if
support returns.

#### Persistence

Migration `006` adds three tables, additively and idempotently:

- `knowledge_concepts` — identity columns, the canonical `signature`, a nullable
  `preferred_unit_id` (FK to `knowledge_units` `ON DELETE RESTRICT`).
- `unit_concept_links` — the append-only membership/relation event log.
- `entry_current_extractions` — the explicit human rollback override
  (`entry_id` PK, FK to `knowledge_extractions` `ON DELETE RESTRICT`).

Migration `007` (milestone 10.5.1) corrects the persistence model without editing
`006`:

- It drops the `one-accepted-SAME-per-unit` partial index on
  `unit_concept_links` (that table is now a pure append-only event log that must
  be free to accumulate superseded events) and adds a `supersedes_link_id`
  self-referential column recording provenance.
- It adds `unit_concept_memberships` (`unit_id` PK, `concept_id`, `link_id`,
  `updated_at`) — the small **mutable projection** holding each unit's single
  *current* SAME membership. This is the authoritative "what is current" table;
  the event log is the immutable "what was decided" history. The uniqueness of
  the current membership is now the `unit_id` primary key of this projection.
- It replaces the `state` column with a persisted `lifecycle_state`
  (`normal`/`retired`) and **removes the stale `state` truth entirely** — support
  is derived at read time, not stored.
- It replaces the `signature WHERE state='active'` partial unique index with a
  **durable-identity unique index on `(identity_schema_version, signature) WHERE
  lifecycle_state != 'retired'`**. Identity is thus owned for the concept's whole
  durable life and is **not released by orphaning** (a temporarily unsupported
  concept still blocks a duplicate), only by explicit retirement.

No embeddings or ML tables are introduced. The repository enforces the same
invariants inside transactions (not relying on indexes alone), and translates the
duplicate-identity case to `ErrConceptConflict`.

The concept, membership and extraction-selection endpoints are listed in
[Appendix A.10](#a10-concepts-membership-and-extraction-selection).

#### Out of scope (deliberately not built)

Any similarity/ML resolution (embeddings, vectors, transformers, learned SAME
probabilities); automatic BROADER/NARROWER inference; forced merging of ambiguous
candidates; review scheduling, mastery, or spaced repetition on top of concepts
(concepts are only the identity those will later attach to); and reconciliation
of the interaction taxonomy with the knowledge-kind vocabulary. These wait until
real human resolution labels exist.

#### Correctness model (milestone 10.5.1)

Milestone 10.5.1 is a correctness patch, not a feature expansion. It fixes six
ways the 10.5 model could drift from its own principles, and it keeps every 10.5
deferral (no embeddings, vectors, neural/LLM resolution, `P(SAME)`, automatic
BROADER/NARROWER inference, review/mastery/scheduling, frontend, or taxonomy
reconciliation). The v1 normalizer is intentionally left as-is; exact
deterministic signature match remains the only automatic SAME condition. The
model now rests on a few sharp distinctions:

- **`KnowledgeUnit` = immutable extraction evidence.** Never deleted or rewritten.
- **`KnowledgeConcept` = durable learning identity.** The thing a future Review
  Engine attaches to — never a raw unit. Its identity is stable for its whole
  durable life, even while it is temporarily unsupported.
- **Resolution history = immutable decision/event log.** `unit_concept_links` is
  append-only; a replacement is a *new* row with a `supersedes_link_id`
  back-pointer, and prior rows are never mutated. Historical evidence is not
  current derived authority.
- **Current SAME membership = derived/current authority.** At most one concept per
  unit, read from the mutable `unit_concept_memberships` projection, correctable
  by a human at any time.
- **Concept support = derived, never persisted.** Recomputed live from current
  extraction + effective admission + current SAME membership on every read, so it
  is never stale.
- **Human correction may supersede any prior machine or human resolution** —
  automatic SAME, a previous human SAME, anything — **without deleting history**.
  `ReassignSame` moves the current membership, appends the superseding event, and
  atomically clears a now-invalid `preferred_unit_id` if the moved unit was the
  old concept's preferred representation.

The six fixes, concretely:

1. **A human can correct a wrong SAME link.** `ReassignSame` moves the unit's
   current membership to another concept even though it already belongs to one.
   The old event stays queryable; the new one supersedes it; affected concepts get
   correct effective support immediately; a stale `preferred_unit_id` on the old
   concept is cleared in the same transaction.
2. **Resolution history is immutable.** No `UPDATE ... SET status='superseded'`
   anywhere; supersession is an append plus a provenance back-pointer.
3. **Support is never stale.** It is derived at read time (see above), not stored,
   so a newer extraction / admission override / reassignment changes it with no
   recompute call.
4. **Identity is not released by orphaning.** Durable-identity uniqueness holds
   across all non-retired concepts, so an orphaned concept still owns its
   signature and a would-be duplicate conflicts (or resolves to the existing one).
5. **Create-concept + seed SAME is atomic** — one repository transaction, all or
   nothing; no transaction logic in HTTP handlers.
6. **`AutoResolve` stays unused publicly** but remains compatible with the
   corrected current-membership model.

## 7. Human annotation

### 7.1 Concept Review workbench

Concept Review (milestone 10.6) is the **human-review workflow** for
`KnowledgeUnit → KnowledgeConcept` resolution. It is deliberately an **annotation /
data-collection instrument**: its purpose is to let a human record high-quality
resolution decisions that can later become ML training data. It is **not** the
Review Engine, mastery, scheduling, or an ML resolver — those remain separate and
deferred. It does not change the semantics above.

**Membership-level clear (`RejectSame`).** The model could express
`unresolved → SAME A` and `A → B` (`ReassignSame`), but not `A → no concept`.
`RejectSame` fills that gap. Given a unit whose current SAME is concept A, in one
transaction it:

- appends an immutable rejection **event** (`relation='same'`, `status='rejected'`,
  `decision_source='human'`, `concept_id = A`) whose `supersedes_link_id` points at
  the in-force SAME event — so the human judgment is preserved as queryable
  **negative evidence**, not represented merely by deleting the projection row;
- removes the unit from `unit_concept_memberships` (clears current membership);
- clears the old concept's `preferred_unit_id` if it pointed at this unit;
- leaves all historical events queryable; the concept's derived support drops on the
  next read.

INVALID is deliberately **not** a `ConceptRelation` (it is not SAME / BROADER /
NARROWER / RELATED). Rejecting a unit that already has no current SAME membership is
a deterministic idempotent no-op (no fabricated event). Exposed at
`POST /knowledge-units/{id}/concept-membership/reject`.

**The complete experimental loop the UI closes:**

    Entry
      -> Analysis / Feedback
      -> EffectiveAnalysis
      -> KnowledgeExtraction
      -> KnowledgeUnit candidate (immutable evidence)
      -> Human Concept Review  (the 10.6 UI)
      -> KnowledgeConcept (durable identity)
      -> resolution labels (append-only events = future training data)

**Frontend (`web/`).** React + Vite + TypeScript, native `fetch`, plain CSS — no
state-management or component framework, no authentication. In
development the browser talks to the Go backend through a `/api` prefix that the
Vite dev server proxies to `:8080`, so requests are same-origin and **no backend
CORS is weakened**; the proxy strips `/api` before forwarding, so Go routes are
untouched. Run the backend (`go run ./cmd/server`) and the frontend
(`npm run dev` in `web/`) in two terminals — see `web/README.md`.

The UI presents the six human decisions — **SAME, NEW CONCEPT, BROADER, NARROWER,
RELATED, INVALID** — one reviewable unit at a time. Two invariants matter most:

- **Current membership is read only from `GET
  /knowledge-units/{id}/concept-membership`**, never inferred from the append-only
  events (a superseded event may still read `accepted`). The UI shows *current
  membership* visually distinct from the collapsible *resolution history*.
- **SAME never becomes a hidden reassignment.** When a unit already has a current
  SAME membership and the reviewer picks a different concept, the UI uses the
  explicit `ReassignSame` (`PUT …/concept-membership`); create+seed is used only to
  *establish* membership for an unresolved unit. On a `409` the UI refreshes the
  unit's current membership before offering another action, because authority may
  have changed.

Every decision produces backend data sufficient to later construct training
examples (SAME = positive identity pair; new concept = the candidate didn't match;
BROADER/NARROWER/RELATED = structured non-SAME relations; INVALID = negative
resolution evidence). The UI ensures the provenance needed later is never discarded; the
read-only dataset export built on it is described in
[§8.1](#81-concept-annotation-dataset-v1).

### 7.2 Annotation labels: INVALID and DISTINCT

Two label kinds have **dedicated, append-only** tables (migration `008`, a
correction after the first Concept Review release showed the earlier labels did
not mean what a later ML pipeline needs). Neither reuses `unit_concept_links`: that
table carries a strict `CHECK` on `relation`/`status`, a self-referential FK, and an
inbound FK from `unit_concept_memberships`, and SQLite cannot `ALTER` a `CHECK` in
place — so a purpose-built table is both safer and more explicit than a rebuild. No
ML, embeddings, or dataset exporter is added; only human judgments are recorded.

**Problem 1 — INVALID meant the wrong thing.** `RejectSame` (above) is a
**membership-level** correction: it only does something when a *current* SAME
membership exists, and for a freshly extracted, never-resolved unit it is an
idempotent no-op. So a human could not label a garbage/invalid candidate that never
had a SAME. The patch adds a distinct **unit-level INVALID judgment**:

- `unit_resolution_judgments` (append-only): `unit_id`, `judgment IN
  ('invalid','restored')`, `decision_source`, optional `note`, structured
  `evidence`, `created_at`. It records "**this KnowledgeUnit is an invalid
  candidate**" without inventing a fake concept id and without being a
  `ConceptRelation`.
- **Effective invalid = the latest judgment** by `(created_at, id)`. INVALID is
  explicit positive evidence, never inferred from the *absence* of a membership
  (absence = unresolved / still reviewable; INVALID = explicitly reviewed and
  rejected — the two stay distinguishable).
- **Reversible**: `restored` withdraws a prior `invalid` and returns the unit to the
  queue; history is never destroyed, so a wrongly-invalidated unit recovers with its
  audit trail intact.
- **Review-queue semantics**: `GET /reviewable-units` now also excludes units whose
  latest judgment is `invalid`. Fresh unresolved → reviewable; INVALID → leaves the
  queue; restored → reviewable again.
- **Kept separate from `RejectSame`.** `RejectSame` remains the membership-level
  "clear the current SAME" action; unit-level `MarkUnitInvalid` is the
  candidate-level judgment. For a unit that *does* currently have a SAME membership,
  `MarkUnitInvalid` uses the **conservative atomic rule (option A)**: it clears the
  current SAME (reusing the reject-event logic, so the cleared membership survives as
  negative evidence) **and** appends the unit-level `invalid` judgment in one
  transaction, so a unit is never simultaneously SAME to a concept and INVALID.
- **API**: `POST /knowledge-units/{id}/invalid` (response carries the recorded
  judgment + effective invalid state + the now-null current membership),
  `POST /knowledge-units/{id}/invalid/restore`, and read model
  `GET /knowledge-units/{id}/invalid` (effective state + full history).

**Problem 2 — distinct negative pairs were lost.** When a reviewer was shown
candidate A and decided the unit was *not* A, nothing recorded that comparison; it
could only be (wrongly) inferred later from the absence of a SAME link. The patch
adds an explicit **DISTINCT** judgment:

- `unit_concept_distinctions` (append-only): `unit_id`, `concept_id`,
  `decision_source`, `resolver_version`, structured `evidence`, `created_at`.
  `DISTINCT(U, A)` = "the reviewer explicitly judged U is **not** the same learning
  identity as concept A" — a real negative pair for future training.
- DISTINCT is **not** a membership, **not** a relation (BROADER/NARROWER/RELATED),
  and **not** INVALID. It **never changes SAME membership**, so the unit stays
  reviewable. This supports the sequence *candidate A shown → DISTINCT A → NEW
  CONCEPT B → SAME U→B*, yielding both a negative `(U, A)` pair and a positive `(U,
  B)` membership. Clicking NEW does **not** implicitly reject the visible
  candidates; only explicit human decisions become labels.
- **API**: `POST /knowledge-units/{id}/concept-distinctions` and
  `GET /knowledge-units/{id}/concept-distinctions`.

**Frontend changes.** INVALID is no longer gated on `membership != null`; it is
always available and calls the unit-level endpoint (`markUnitInvalid`), then removes
the unit from the in-memory queue and advances with no refresh. A new **DISTINCT**
action is enabled when an existing candidate concept is selected; it records the
negative pair and **keeps** the unit in the queue so the reviewer can continue
(pick another concept, create a NEW one, or mark INVALID). The membership-level
`reject` endpoint remains available in the client as `rejectSameMembership`, kept
distinct from the primary INVALID action.

The full label vocabulary the annotation data now distinguishes: **SAME** (positive
identity pair), **DISTINCT** (explicit negative pair), **BROADER/NARROWER**
(structured non-SAME hierarchy), **RELATED** (associated non-SAME), and **INVALID**
(unit-level negative — the candidate should not participate in resolution at all).
The dataset export ([§8.1](#81-concept-annotation-dataset-v1)) consumes the
resulting effective projection without changing these semantics.

### 7.3 Effective annotation

M11-A adds a read-only, deterministic `EffectiveAnnotationSnapshot` for one
KnowledgeUnit. It composes persisted facts without rewriting them:

```text
append-only judgments, distinctions, and concept-link events
                              +
          current unit_concept_memberships authority
                              ↓
               effective annotation snapshot
```

The storage layer only retrieves the latest unit judgment, CURRENT SAME
membership, full unit-scoped concept-link history, and full DISTINCT history. The
application service composes those facts, and a pure domain resolver decides what
is effective. No migration or HTTP endpoint is needed.

- **Status:** the latest unit judgment by `(created_at, id)` determines INVALID.
  INVALID wins and suppresses all SAME, DISTINCT, and relation output. Otherwise a
  row in `unit_concept_memberships` means `resolved`; its absence means
  `unresolved`. A restored unit does not regain a SAME membership cleared during
  invalidation.
- **CURRENT SAME:** `unit_concept_memberships` remains the sole authority. Its
  `link_id` must resolve to an immutable matching `same`/`accepted` event; missing
  or incompatible provenance is reported as corruption instead of guessed or
  repaired. The snapshot retains the membership plus the complete event, including
  decision source, resolver version, evidence, score, and timestamp. Thus a current
  automatic SAME remains distinguishable from human SAME and is not automatically
  declared human-gold.
- **DISTINCT:** only explicit `unit_concept_distinctions` rows qualify. Repeated
  rows collapse to the newest per Concept. CURRENT SAME suppresses DISTINCT for
  that Concept, and any later accepted SAME permanently suppresses an older
  DISTINCT even if SAME later moves elsewhere. A new DISTINCT after that correction
  can become effective again. Equal cross-table timestamps conservatively favor
  SAME. `RejectSame`, candidate display, skipping, relations, and reassignment away
  never infer DISTINCT.
- **BROADER/NARROWER/RELATED:** only accepted, structurally un-superseded relation
  events qualify. Rejected, legacy-superseded, and structurally superseded events
  do not. CURRENT SAME and later affirmative SAME history suppress older relations
  to the same Concept without allowing them to resurrect after reassignment. A new
  explicit relation after the correction can become effective. Existing semantics
  supersede repetitions of the same relation kind only; if different non-SAME
  kinds remain active for one pair, M11-A preserves all of them rather than
  inventing cross-type precedence.
- **Determinism and provenance:** DISTINCT output is sorted by Concept ID then
  event ID; relations by Concept ID, relation kind, then event ID. All emitted
  records retain their persisted IDs, sources, evidence, resolver versions, and
  timestamps so later dataset decisions remain auditable.

This milestone does **not** export CSV/JSONL/Parquet, select human-gold training
labels, split datasets, compute statistics, train or evaluate models, add retrieval
or embeddings, or alter the annotation frontend. Those remain later milestones.

### 7.4 Effective Annotation Inspector

M11-B exposes the existing M11-A projection through two read-only endpoints:
`GET /knowledge-units/{id}/effective-annotation` and `GET
/effective-annotations`. The collection selects every KnowledgeUnit belonging to
each entry's CURRENT extraction, including resolved, unresolved, and invalid units,
while excluding stale historical extraction units. SQLite retrieves unit evidence
and persisted annotation facts; `EffectiveAnnotationService` calls the unchanged
M11-A resolver; transport maps the result to explicit DTOs.

The workbench's Annotation Inspector view loads the effective collection and Concept catalog once,
maps Concept IDs to readable targets with an ID-only fallback, and filters status
and CURRENT SAME source client-side. It performs GET requests only and does not
define, infer, or mutate annotation authority. It is a debugging view for collected
annotation data before dataset-export work; no ML dataset export is included.

### 7.5 Annotation request idempotency

Optional database-global UUID request identities cover DISTINCT and non-SAME
relation POSTs only. Migration 009 adds committed `annotation_operations`
receipts containing canonical semantic payload and the original domain result.
The application supplies the existing human evidence; SQLite transaction-local
annotation helpers preserve existing semantics. A writer lock precedes receipt
lookup; event and receipt commit together. Replay returns the historical result
without reevaluating current state. Conflicting payloads return 409. Receipt
lookup is transport-only wiring through existing browser protection and exposes
no new annotation authority. Unkeyed paths retain their existing contracts.

Concept Review saves only the versioned key/action/target IDs/relation before
sending. Reload restores unresolved operations without writing. **Retry saved
operation** sends that exact payload/key once; editing selection does not alter
it. Unknown keyed operations block new decisions for that unit until confirmed.
A subsequent deliberate decision gets a fresh key. A definite rejection removes
exactly its saved operation, even after leaving Concept Review. An unresolved
operation another tab saved for the same unit is kept unchanged and shown on that
unit only, with the same check/retry controls. Failed browser storage disables
the keyed decisions with an honest notice until an explicit **Recheck browser
storage** succeeds; nothing is resent, and an unreadable saved value must be
removed before the recheck can pass. Clearing storage or changing browser
origin loses recovery identity. After commit/receipt confirmation the browser
refreshes backend authority separately. Multi-tab locking and recovery controls
for units no longer in the review queue are not provided.

The exact contract is [FLH-029](plans/FLH-029-annotation-idempotency.md). The
lost-response analysis that motivated it is in
[FLH-028](validation/FLH-028-review-response-loss.md).

## 8. Annotation dataset and retrieval research

These read-only reports turn collected annotations into an auditable dataset and
compare retrieval baselines against human ground truth. None of them writes
annotations or resolves Concepts.

### 8.1 Concept Annotation Dataset v1

M11-C exposes a stable read-only current snapshot through `GET
/annotation-dataset/v1` and `GET /annotation-dataset/v1/export`. The former returns
a `concept_annotation_dataset_v1` JSON envelope; the latter returns the same
application records in the same order as NDJSON, with the schema version repeated
on every line. Neither endpoint mutates data, invokes AI, or makes an annotation
decision.

Dataset composition begins with `EffectiveAnnotationService.ListEffectiveAnnotations`.
Consequently, M11-A remains the only definition of CURRENT SAME, INVALID,
effective DISTINCT, and effective relations, and v1 includes only units from each
entry's CURRENT extraction. The dataset service does not scan link history. It
loads each referenced `KnowledgeExtraction` once per build for `entry_id`, version,
analysis/feedback/extractor provenance and current admission state, and loads each
referenced Concept once per build for its durable human-readable identity and
lifecycle/support snapshot. A missing extraction/unit/Concept reference fails the
whole build closed.

Each record preserves immutable unit evidence, extraction provenance, machine and
effective admission state, the Concept-decorated effective annotation, and a
separate conservative `human_labels` projection:

- Human CURRENT SAME becomes a human SAME label; `resolver:automatic` SAME can
  remain effectively resolved but is not human gold.
- Explicit effective human DISTINCT becomes negative identity evidence.
- Human BROADER/NARROWER/RELATED remain typed relations and are never collapsed
  into DISTINCT.
- Effective human INVALID becomes unit-level exclusion evidence and has no
  pair-level labels.

Records sort by entry ID, extraction version, unit ordinal, then unit ID. M11-C
does not assert `gold`/`training_ready`, create train/validation/test splits,
compute metrics, train a model, or implement candidate retrieval.

### 8.2 Dataset validation and quality report v1

M11-D adds `GET /annotation-dataset/v1/quality`, returning the explicit schema
`concept_annotation_quality_report_v1` for
`concept_annotation_dataset_v1`. `ConceptAnnotationDatasetQualityService` has one
narrow dependency—`AnnotationDatasetV1Reader.ListV1`—which the M11-C service
satisfies. It neither accesses SQLite nor scans append-only annotation history;
M11-A remains the authority and M11-C remains the dataset boundary.

One report build calls `ListV1` once and deterministically computes:

- record, entry, extraction, referenced-Concept, effective-status, admission, and
  resolved-authority counts;
- explicit human SAME, DISTINCT, typed relation, and INVALID inventory, keeping
  `resolver:automatic` SAME out of human supervision;
- sorted distributions for extractor provenance, referenced Concept identity
  schema versions, and resolver versions carried by explicit human pair labels;
- entry grouping and human-SAME Concept grouping statistics that expose leakage
  risk without generating a split.

Structural validation covers record/source/extraction/ordinal consistency,
unique units, resolved/current-SAME consistency, internal membership/decision
links, bidirectional human-label projections, INVALID pair-output suppression,
SAME contradictions, required Concept identity fields, and supported Concepts for
active units with CURRENT SAME. Issues are sorted by fixed severity (error before
warning), then code, entry ID, unit ID, and nullable Concept ID. Provenance buckets
sort by value. No wall-clock generation timestamp is included.

`valid` is true exactly when no error finding exists. Warnings are diagnostic and
do not reject data: v1 warns about an explicit human label on non-active admission
and a human CURRENT SAME pointing to a retired Concept. The endpoint returns HTTP
`200` even when validation produces `valid: false`; only failure to build the
underlying M11-C dataset/report returns a generic HTTP `500`.

This report is descriptive only. It creates no annotation authority, universal
training-eligibility decision, automatic correction, train/test split, retrieval
metric, model, or retrieval implementation.

### 8.3 Retrieval evaluation foundation v1

M12-A introduces a retrieval experiment boundary, not a resolution or annotation
boundary. `ConceptRetriever` accepts an immutable Unit query, a caller-composed
Concept document universe, and a limit, then returns ranked candidates. It has no
repository or mutation capability. The initial `exact_signature_retriever_v1`
returns only complete candidate-identity/Concept-signature equality with score
`1.0`, ranks from one, and breaks ties by Concept ID. It does not call
`AutoResolve` and does not record SAME.

`ConceptRetrievalEvaluationService` depends on four narrow readers/components:

```text
M11-D AnnotationDatasetQualityReader.BuildV1
                         ↓ valid only
M11-C AnnotationDatasetV1Reader.ListV1 ── human CURRENT SAME truth
RetrievalConceptCatalogReader.ListConcepts ── current candidate corpus
ConceptRetriever ── ranked retrieval output only
```

An invalid M11-D report blocks evaluation before the service reads the evaluation
dataset/catalog or calls the retriever. The resulting successful report has state
`blocked_invalid_dataset`, `dataset_valid: false`, null metrics, and an empty
sample array. Warnings do not block. Build failures from quality, Dataset v1,
catalog reading, or retrieval propagate to the HTTP adapter, which returns a
generic `500` without leaking internal errors.

Ground truth is exactly one effective CURRENT human SAME target with a matching
M11-C `human_labels.same`. Automatic SAME, missing SAME, displayed candidates, and
signature equality never create gold relevance. The service parses only
`reason` from the SAME decision's structured evidence:

- `human_same` and `human_same_correction` may be evaluated;
- `seed_unit_same` is excluded because NEW CONCEPT created the target from that
  Unit, so the target did not yet exist at the relevant retrieval moment;
- malformed, missing, or unknown reasons are excluded rather than guessed.

After provenance classification, the sample must have active effective admission,
a non-retired target, and a target present in the current candidate universe.
Exclusion precedence is unclassified provenance, seed creation, non-active
admission, retired target, missing current target, then eligible. Thus eligible
plus exclusions always equals the number of explicit human SAME records.

The candidate corpus is the current `ListConcepts(nil)` result filtered only by
persisted lifecycle: retired Concepts are removed, while normal supported and
normal orphaned Concepts remain. Documents sort by Concept ID before retrieval.
M12-A intentionally asks how each current labeled Unit performs against the
catalog available now; it does not reconstruct point-in-time catalogs, so later
Concepts can be additional competitors.

The `concept_retrieval_evaluation_v1` report, governed by
`concept_retrieval_eval_policy_v1`, requests top five candidates and computes
Recall@1, Recall@3, Recall@5, and mean reciprocal rank for the single human target.
A miss contributes zero; with zero eligible samples every aggregate metric is
`null`, not `0.0`. Samples sort by entry ID then Unit ID and preserve query
evidence, current target identity, human SAME event/reason, ranked retrieval
output, nullable target rank, reciprocal rank, and hit flags. No wall-clock value
is included.

`GET /retrieval-evaluation/v1` exposes that audit read-only. Rankings and scores
are never persisted and create no annotation authority.

Because the exact baseline has no fuzzy, token or semantic behaviour, a human
SAME whose unit wording produces a different signature is an expected baseline
miss, not an error.

### 8.4 Weighted lexical retriever v1

M12-B adds `weighted_lexical_retriever_v1` behind an application-owned
`ConceptRetrieverRegistry`. The empty selector and explicit
`exact_signature_retriever_v1` select the exact baseline; explicit
`weighted_lexical_retriever_v1` selects lexical ranking. The HTTP adapter only
passes the query value to the application service, returns `400` for an unknown
name, and never constructs an algorithm or gains storage capability.

Both retrievers execute the same `concept_retrieval_eval_policy_v1` path after
selection. They therefore share the M11-D validity gate, M11-C human-SAME truth,
seed/provenance/admission/target exclusions, current non-retired candidate
universe, sample ordering and targets, max K of five, and Recall@1/3/5 and MRR
definitions. Only retriever name, candidates, target ranks, and metrics may
differ. This is an experiment-control invariant, not merely a response-shape
convention.

The lexical representation uses normalization version
`concept_lexical_normalization_v1`:

1. Unicode lowercase, canonical decomposition, and combining-mark removal make
   accented and unaccented spellings comparable.
2. Non-letter/non-digit runes create token boundaries; empty and one-rune tokens
   are discarded.
3. There is no stop-word list, stemming, lemmatization, or fuzzy rewriting.
4. Tokens are deduplicated inside each field, then field weights accumulate when
   the same token occurs in distinct fields.

Query canonical and statement weights are `4.0` and `2.0`; candidate intent,
scope, feature keys, and feature values each weigh `1.0`. Candidate target is
omitted because v1 derives it from canonical and including both would double
count the primary evidence. Concept target weighs `4.0`; Concept intent, scope,
feature keys, and feature values each weigh `1.0`. Lifecycle, support, and state
remain metadata and never enter the vector.

The retriever scores the positive weighted vectors with cosine similarity. Empty
or disjoint vectors score zero and are omitted. Positive results sort by score
descending and Concept ID ascending, receive one-based ranks, and are truncated
to the caller's limit. Cosine supplies a transparent, length-normalized baseline
without corpus statistics or training; its score is neither a calibrated
probability nor evidence of SAME. Exact signatures receive no special lexical
boost. Evidence is stable JSON containing the reason
`weighted_lexical_cosine`, normalization version, and unique lexicographically
sorted matched tokens.

Each request scores the small current Concept corpus in memory. Nothing is
persisted, no annotation or membership is written, and no provider is called.
The M12-B algorithm has no IDF, TF-IDF, or BM25 behavior; M12-C adds the separate
BM25 baseline below. Inverted indexes, SQLite FTS, embeddings, vector search,
reranking, fuzzy edit distance, automatic labels, historical-corpus replay, and
frontend work remain outside M12-B. M12-D adds a separate embedding baseline
below without changing this algorithm.

### 8.5 Corpus-aware BM25 retriever v1

M12-C registers `bm25_retriever_v1` alongside the exact and weighted-cosine
retrievers. It implements the unchanged `ConceptRetriever` interface and receives
only one immutable query, the caller-supplied documents, and a limit. It does not
read a repository, SQLite, annotation history, resolver state, or an external
service. `ConceptRetrieverRegistry` remains the algorithm-selection owner;
production composition registers all three algorithms while retaining
`exact_signature_retriever_v1` as the empty-selector default. HTTP still only
passes `?retriever=` and maps an unknown name to `400`.

The retriever reuses `concept_lexical_normalization_v1` exactly. Unlike M12-B's
per-field token sets, M12-C keeps every normalized occurrence. Query fields and
weights are canonical `4.0`, statement `2.0`, and candidate intent, scope, feature
keys, and feature values `1.0` each. Candidate-identity target remains omitted
because canonical is the primary evidence and adding both would double count it.
Document fields are target `4.0` and intent, scope, feature keys, and feature
values `1.0` each. Example, Concept lifecycle/support/effective state, human SAME
target information, human reasons, rank, and evaluation outcomes never enter the
lexical representation.

Field weighting is explicit multiplication, never string or token duplication.
For token `t`, `q_w(t)` is raw query term frequency multiplied and summed over
query field weights, and `tf_w(t,D)` is the equivalent document value. Weighted
document length `|D|_w` is the sum of the relevant field weight for every
normalized token occurrence. For every retrieval call, the supplied corpus alone
defines document count `N`, per-token document frequency `df(t)`, and average
weighted document length `avgdl_w`. Version 1 uses positive Robertson/Sparck Jones
IDF and this score:

```text
IDF(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))

score(D,Q) = Σ[t in Q] q_w(t) * IDF(t) *
             tf_w(t,D) * (k1 + 1)
             -----------------------------------------------
             tf_w(t,D) + k1 * (1 - b + b * |D|_w / avgdl_w)
```

The versioned constants are `k1=1.2` and `b=0.75`; they are conventional defaults
and are not tuned against Dataset v1 labels. `k1` saturates repeated document-term
frequency, `b` normalizes for document length, and IDF reduces the influence of
tokens common throughout the supplied corpus. This is a deliberately small
field-weighted BM25 variant rather than full per-field-normalized BM25F: fields are
combined into one weighted representation before saturation and length
normalization. Empty or degenerate representations produce no result and never a
NaN or infinity.

Positive finite scores sort descending with Concept ID ascending as the stable
tie-break, are assigned one-based ranks, and are truncated to the requested
limit. Evidence is deterministic structured JSON with reason `bm25`, normalization
and parameter versions, corpus/document lengths, unique sorted matched tokens,
and sorted per-token query weight, document frequency, IDF, weighted document TF,
and contribution. This evidence remains retrieval relevance, not a probability,
SAME/DISTINCT label, or resolution decision.

The evaluation service is unchanged. Exact, weighted cosine, and BM25 therefore
share the M11-D validity gate, M11-C CURRENT explicit human-SAME truth, provenance
classification, seed creation exclusion, admission/retired/missing-target
exclusions, current non-retired Concept universe, eligible Units, targets, sample
ordering, maximum K of five, and Recall@1/3/5 and MRR definitions. Only retriever
name, candidates, scores, evidence, target rank/hits, and aggregate metrics can
differ. The quality gate still runs before dataset/catalog reads or BM25 scoring.

Corpus statistics are calculated in memory for each call. M12-C adds no migration,
table, persisted index/statistic/result, cache, SQLite FTS, annotation mutation,
Concept resolution, reranker, parameter learning, or frontend behavior. Its BM25
algorithm performs no embedding/model/provider work; M12-D adds that separate
baseline below.

### 8.6 Semantic embedding retriever v1

M12-D adds `embedding_retriever_v1` as the semantic baseline after exact identity
(M12-A), weighted lexical cosine (M12-B), and corpus-aware BM25 lexical retrieval
(M12-C). It implements the unchanged `ConceptRetriever` contract. Semantic
inference is isolated behind one small application-owned, batch-oriented boundary:

```go
type EmbeddingProvider interface {
    Name() string
    Embed(ctx context.Context, texts []string) ([][]float64, error)
}
```

The retriever owns semantic-text construction, vector validation, cosine scoring,
evidence, result limits, and stable ordering. The provider owns only text-to-vector
inference and its provider/model provenance name. One retrieval sends a single
combined batch in deterministic `query, Concept documents...` order, rather than
making one remote call per Concept. The provider has no repository, SQLite,
annotation-history, lifecycle-policy, human-label, target, or metric access.

#### Versioned semantic representation

`concept_embedding_text_v1` is deterministic compact JSON rather than prompt-like
prose. The query representation contains canonical, statement, nullable example,
candidate-identity target, pedagogical intent, scope, and identity-feature
key/value pairs. The document representation contains target, pedagogical intent,
scope, and feature pairs. Feature keys sort lexicographically before serialization.
IDs, signatures, identity-schema versions, lifecycle/support/effective state,
human SAME/DISTINCT labels, annotation reasons, target rank, hit flags, and metrics
are excluded. Consequently, query text derives only from Unit evidence, document
text only from Concept representation, and evaluation truth is inaccessible while
embedding and ranking.

#### Vector validation, ranking, and evidence

Cosine similarity is evaluated only for non-empty, equal-dimensional vectors with
finite components. A zero-norm vector and non-positive similarity yield no
candidate. An empty vector, dimension mismatch, non-finite component, or incorrect
provider batch count fails the retrieval request instead of creating a partial or
fabricated ranking. Positive candidates sort by score descending and Concept ID
ascending, receive one-based ranks, and are truncated to the requested limit.

The score is semantic relevance, not a calibrated probability or proof of SAME.
There is no automatic similarity threshold, annotation, resolution, or fallback.
Stable structured JSON evidence records `reason: "embedding_cosine"`, the
provider/model name, `concept_embedding_text_v1`, cosine similarity, and vector
dimension. It never contains raw vectors or human truth.

#### Composition and provider operation

Embedding configuration is independent of `AI_PROVIDER` and
`EXTRACTOR_PROVIDER`. `EMBEDDING_PROVIDER=disabled` is the default and requires no
model, credential, GPU, or embedding service. In that mode production composition
does not register `embedding_retriever_v1`; explicit semantic selection therefore
uses the registry's existing HTTP `400` unknown-retriever behavior. When
`EMBEDDING_PROVIDER=http`, production registers all four retrievers while the
empty selector still defaults to `exact_signature_retriever_v1`.

The HTTP adapter sends one OpenAI-compatible batch to
`<EMBEDDING_BASE_URL>/embeddings` using `EMBEDDING_MODEL`, optional bearer
`EMBEDDING_API_KEY`, and `EMBEDDING_TIMEOUT`. It reconstructs response order from
explicit provider indexes and validates exact count, uniqueness, dimensions, and
finite values. Provider timeouts map to a secret-safe HTTP `504`; other provider
unavailability maps to `502`. Neither case falls back to exact, lexical, or BM25.

#### Experiment control and operational scope

Exact, weighted lexical, BM25, and semantic evaluations use the same unchanged
evaluation service. They share the M11-D validity gate, M11-C CURRENT explicit
human-SAME truth, provenance classification, seed/admission/retired/missing-target
exclusions, current non-retired candidate universe, eligible Units, targets,
sample ordering, maximum K of five, and Recall@1/3/5 and MRR definitions. Only
retriever/provider-owned candidates, scores, evidence/provenance, target ranks and
hits, and resulting metrics may differ. Frozen-vector tests enforce this boundary
and deterministic ranking; they are architecture tests, not evidence about any
real embedding model's quality.

The small current evaluation corpus is embedded at request time. M12-D adds no
migration, vector persistence/cache/database, ANN/HNSW/FAISS index, hybrid fusion,
reranker, cross-encoder, LLM judge, learned SAME classifier, calibrated threshold,
training, local runtime, model weights, GPU detection, or NAS inference
requirement. A remote API, rented GPU, or a service hosted on an RTX 4070
workstation can implement the same boundary; local-inference optimization remains
deferred.

### 8.7 Retrieval baseline comparison v1

M13-A0 is the first experiment-analysis layer after M12's four individual
retrieval baselines. `ConceptRetrievalComparisonService` depends only on the
existing evaluation capability:

```text
ConceptRetrievalComparisonService.BuildV1
                    │ fixed v1 order
                    ▼
ConceptRetrievalEvaluationService.BuildV1WithRetriever
                    │
       exact → weighted lexical → BM25 → embedding
```

The comparison service neither receives repositories nor implements retrieval,
truth selection, exclusions, candidate-universe construction, Recall, or MRR. It
invokes the detailed M12 contract for each fixed name and copies only shared
population metadata plus each report's state and top-level metrics into schema
`concept_retrieval_comparison_v1`. `GET /retrieval-comparison/v1` exposes this
compact report; `GET /retrieval-evaluation/v1?retriever=...` remains the owner of
full per-sample audit output.

Rows have deterministic order: exact signature, weighted lexical cosine, BM25,
then embedding. The first three baselines are required. The embedding baseline is
optional in production: only `ErrUnknownConceptRetriever` for that fixed name is
converted to explicit state `unavailable` with null metrics. A configured
embedding provider is evaluated normally, and its timeout/unavailable errors
propagate to the existing secret-safe HTTP `504`/`502` mappings. No other
retriever is substituted and the embedding row is never omitted.

Before returning a comparison, every evaluated report must agree on evaluation
schema and policy, state, dataset validity, candidate universe, complete sample
inventory and exclusions, and the ordered sample identities: Unit, Entry,
Extraction, query, target Concept, human-SAME event, and provenance reason.
Retriever-owned candidates, ranks, hits, and metrics are intentionally excluded
from that equality check. Any population mismatch returns an internal consistency
error and the HTTP layer emits a generic `500`; the service never selects one
population or combines incompatible metrics.

An invalid M11-D dataset still produces the M12-owned successful
`blocked_invalid_dataset` reports. The comparison preserves that top-level and
per-row state with null metrics. Each underlying M12 call stops at its quality
gate before dataset/catalog reads or retriever execution; warnings remain
non-blocking.

M13-A0 is read-only and request-scoped. It adds no persistence, migration, result
history, cache, retriever, hybrid/fusion algorithm, reranker, significance test,
confidence interval, subgroup analysis, error taxonomy, chart, frontend,
annotation authority, or Concept-resolution behavior.

### 8.8 Interpreting comparisons

Retrieval uses the current non-retired Concept catalog rather than a historical
catalog reconstruction. Rankings and metrics are evidence only: they never
create SAME/DISTINCT labels or resolve Concepts. With embeddings disabled, the
comparison truthfully includes an `unavailable` semantic row while the local
baselines continue to work.

The retrievers share the same evaluation population, but the semantic
representation also includes the query example and candidate-identity target;
the lexical/BM25 query representation does not. The comparison is therefore not
a scorer-only ablation over perfectly matched evidence.

### 8.9 Experiment Dashboard

The workbench has a read-only view, **Experiment
Dashboard**, beside Concept Review and Annotation Inspector. It reads only:

- `GET /annotation-dataset/v1/quality` for M11-D structural validity, error and
  warning counts, dataset totals, human SAME/DISTINCT/INVALID inventory,
  unlabeled unresolved records, and human-versus-automatic SAME authority;
- `GET /retrieval-comparison/v1` for the fixed backend-ordered exact, weighted
  lexical, BM25, and embedding rows with state, Recall@1/3/5, and MRR.

Non-null retrieval metrics are formatted consistently as percentages. Null
metrics remain visibly distinct as `—`; an unavailable embedding row is retained,
and `blocked_invalid_dataset` is shown rather than reinterpreted. The two sections
load independently, so one successful report remains useful if the other request
fails.

This dashboard is a presentation-only view. It does not fetch detailed per-sample
evaluations, recompute validity, eligible samples, Recall, or MRR, select or run a
retriever independently, configure an embedding provider, write annotations, or
create Concept-resolution authority. M11-D and M13-A0 remain the sources of truth.

## 9. Knowledge Library

`KnowledgeLibraryService` is a read-only composition over existing authority. It
holds only read interfaces, so it cannot write:

- Concept storage: list, get, current membership, active support units, unit
  lookup, current-extraction selection;
- extraction, entry, analysis and feedback reads;
- the M11-A effective annotation snapshot.

It adds no table, migration, index or provider. Three GET routes expose it:

- `/knowledge-library/concepts` for search and browse;
- `/knowledge-library/concepts/{id}` for Concept detail;
- `/knowledge-library/units/{id}/source` for unit provenance.

They are available at the root and under `/api` through the existing workbench
prefix and browser boundary.

### 9.1 Search contract and limitations

Search is deterministic keyword matching, kept separate from the
[§8](#8-annotation-dataset-and-retrieval-research) experiment retrievers. It
reuses only the `concept_lexical_normalization_v1` tokenizer, and every query
token must be a prefix of some token in the searched fields (AND semantics).

- **Fields.** It searches Concept target, intent, scope and identity features,
  plus the wording of units that hold the Concept's CURRENT SAME membership.
  Membership is not support: a member from an older extraction or with
  suppressed admission still matches, and the result says it matched through
  member wording. Former members (reassigned, rejected or INVALID),
  relation-only units, source records and analyses are not searched.
- **Matching.** Accents and case are ignored, and each word must match the start
  of a word. It is deterministic keyword matching only, with no semantic
  retrieval.
- **Ordering.** Identity matches come before unit-wording matches. Then active
  comes before orphaned and retired, then target, then id.
- **Limits.** 20 results by default, at most 50. A query is at most 200 bytes
  and 8 terms.

Known limitations:

- Prefix matching only: no stemming, synonyms, typo tolerance or semantic
  retrieval. One-character words such as « à » or « y » cannot be searched.
- Entry text and analyses are not searched.
- Each request scans all Concepts and derives support per Concept; there is no
  index. This is adequate at personal scale, not for a large library.
- DISTINCT pairs are not listed on the Concept page.
- There is no URL state: a browser reload returns to the default view.

### 9.2 Concept detail and source view

**Concept detail** places each unit in one section, by priority:

1. supporting (from `ActiveSupportUnitIDs`);
2. current SAME member that does not provide support (projection-based, with the
   extraction and admission facts that explain why);
3. current effective relation (M11-A, current-extraction units that are not
   INVALID);
4. historical.

History is labelled as such and never shown as current authority.

**Source view** resolves the interpretation the extraction used: its
`source_analysis_id` with `source_feedback_id`, through `domain.ResolveEffective`.
It reports the entry's latest analysis separately, so later reinterpretation is
visible without rewriting provenance.

The workbench tab stays mounted while hidden, so the query and open screen
survive view switches. There is no router and no URL state. See
[FLH-034](plans/FLH-034-knowledge-library.md).

The workbench wording is plain English: a CURRENT SAME member is shown as a
unit *filed under* the Concept, and support as *currently supporting* it
([§6.1](#61-membership-versus-support-canonical-summary)). The synthetic demo
fixture and walkthrough are in [DEMO.md](DEMO.md).

## 10. Runtime, configuration and the HTTP boundary

### 10.1 Process and serving

`cmd/server` loads configuration, opens SQLite (creating the file and its
directory on first run), applies embedded migrations, wires repositories,
providers and services, and serves HTTP with graceful shutdown on SIGINT/SIGTERM.

To serve the built workbench from the same server, without the Vite dev server,
build it and pass `-web-dir`:

```bash
cd web && npm ci && npm run build && cd ..
go run ./cmd/server -web-dir web/dist
```

`/` then serves the workbench, `/assets/...` its built files, and `/api/...` the
API with the prefix stripped (what the workbench calls). Every existing API
route keeps its root path, so curl and the capture CLI are unchanged. Without
`-web-dir` the server is API-only.

`/healthz` is liveness only and does not touch the database. `/readyz` is
readiness: it pings SQLite with a 2-second bound and answers `200` or
`503 {"status":"not_ready"}` without error details.

### 10.2 Configuration

Configuration comes from the process environment and an optional `.env` file in
the server's working directory (see [.env.example](../.env.example)). A variable
already present in the process environment wins over `.env`, even when empty;
empty values behave as unset. Defaults work out of the box:

| Variable             | Default                     | Description                                   |
| -------------------- | --------------------------- | --------------------------------------------- |
| `PORT`               | `8080`                      | HTTP listen port                              |
| `LISTEN_HOST`        | _(empty: all interfaces)_   | Optional IP literal to bind, e.g. `127.0.0.1`; hostnames are rejected |
| `DB_PATH`            | `data/app.db`               | SQLite database file path                     |
| `HTTP_READ_TIMEOUT`  | `10`                        | Read timeout (seconds)                        |
| `HTTP_WRITE_TIMEOUT` | `10`                        | Write timeout (seconds)                       |
| `AI_PROVIDER`        | `rule-based`                | Analyzer provider: `rule-based` or `openai`   |
| `EXTRACTOR_PROVIDER` | `disabled`                  | Knowledge extractor: `disabled` or `openai`   |
| `OPENAI_API_KEY`     | _(none)_                    | Required for `openai`; never logged           |
| `OPENAI_MODEL`       | _(none)_                    | Required for `openai`; the model to use       |
| `OPENAI_BASE_URL`    | `https://api.openai.com/v1` | API base URL (override for gateways/testing)  |
| `OPENAI_TIMEOUT`     | `8`                         | Per-request provider timeout (seconds)        |
| `EMBEDDING_PROVIDER` | `disabled`                  | Semantic retrieval provider: `disabled` or `http` |
| `EMBEDDING_MODEL`    | _(none)_                    | Required when embedding provider is `http`    |
| `EMBEDDING_BASE_URL` | _(none)_                    | Required OpenAI-compatible API base for `http` |
| `EMBEDDING_API_KEY`  | _(none)_                    | Optional bearer token; never logged           |
| `EMBEDDING_TIMEOUT`  | `8`                         | Per-request embedding timeout (seconds)       |

`EXTRACTOR_PROVIDER` is independent of `AI_PROVIDER`: knowledge extraction is a
separate, opt-in capability, so `AI_PROVIDER=rule-based` together with
`EXTRACTOR_PROVIDER=openai` is a valid combination (and so is enabling the
analyzer but not the extractor). When `EXTRACTOR_PROVIDER=openai`, the extractor
reuses the same `OPENAI_*` settings above. See
[§5](#5-knowledge-extraction-and-admission) for details.

`EMBEDDING_PROVIDER` is a third, independent selection boundary used only by the
M12-D retrieval evaluation baseline. The default `disabled` mode requires no key,
model, GPU, or embedding service and leaves `embedding_retriever_v1` unregistered;
explicitly selecting that name then returns the existing HTTP `400` unknown-
retriever response. `http` requires `EMBEDDING_MODEL` and
`EMBEDDING_BASE_URL`, calls `POST <base-url>/embeddings` with one batch, and uses
`EMBEDDING_API_KEY` only when a bearer token is needed. This OpenAI-compatible
wire adapter can point at a remote API, rented compute, or a service hosted on
another machine; it is not coupled to the analyzer/extractor OpenAI settings.
Provider timeouts return `504`, other embedding failures return `502`, and there
is no fallback to another retriever.

`LISTEN_HOST` (FLH-036) is a plain bind option: empty keeps `":" + PORT` (all
interfaces), an IP literal binds `LISTEN_HOST:PORT`, and a hostname or malformed
value stops startup. It is not access control; the Docker release does not
forward it. It is not yet listed in `.env.example`.

The server reads `.env` from its working directory (the repository root for
`make run`); a missing file is fine, and a malformed one stops startup without
showing its values. A variable already present in the process environment wins
over `.env`, even when empty. Put values containing `$` or `#` in single quotes.
Invalid provider configuration (unknown provider, or `openai` without key or
model) stops startup with a clear error rather than silently falling back. The
container release never copies `.env` into the image
([RELEASE.md](RELEASE.md#configuration)).

### 10.3 Browser request boundary

The complete HTTP handler validates the request `Host` before serving either the
workbench or the API, and checks `Origin`/Fetch Metadata plus a JSON content
type for browser mutations before any application service runs (FLH-019, after
the FLH-013 and FLH-017 findings). It is browser-request protection, **not**
authentication: anyone with network access can still use the API or CLI. The
settings `HTTP_ALLOWED_HOSTS` and `HTTP_TRUSTED_ORIGINS`, their exact syntax and
the NAS guidance are documented once, in
[RELEASE.md](RELEASE.md#browser-request-boundary-and-nas-access).

### 10.4 Workbench

The workbench (`web/`) is an internal annotation and data-collection UI, not a
consumer product. It has five views — Learning Records, Knowledge Library,
Concept Review (write-capable), Annotation Inspector and Experiment Dashboard —
and keeps business rules and current authority in the backend: the browser
renders backend facts and never recomputes them. In development, Vite proxies
`/api` to the Go server (stripping the prefix); in production the Go server
serves the built files itself ([§10.1](#101-process-and-serving)). Mutation
components are written to survive React StrictMode effect replay (FLH-021). Its
behaviour per view is documented in [web/README.md](../web/README.md).

## 11. Persistence, migrations and recovery

SQLite is embedded through the pure-Go `modernc.org/sqlite` driver; no SQLite
server or CGO toolchain is needed. Migrations are embedded `.sql` files applied
at startup and recorded in `schema_migrations`. They are additive and
forward-only; there are no down migrations.

| Migration | Adds |
| --- | --- |
| `001_create_learning_entries` | `learning_entries` (including legacy nullable metadata columns; see [§3.1](#31-entry-the-learner-authored-source-record)) |
| `002_create_entry_analyses` | versioned `entry_analyses` |
| `003_create_analysis_feedback` | append-only `analysis_feedback` |
| `004_create_learning_captures` | `learning_captures` receipt table |
| `005_create_knowledge_extractions` | extractions, units, admission recommendations and overrides |
| `006_create_knowledge_concepts` | `knowledge_concepts`, `unit_concept_links`, `entry_current_extractions` |
| `007_fix_concept_resolution` | `unit_concept_memberships`, `supersedes_link_id`, `lifecycle_state`, durable-identity index |
| `008_unit_resolution_judgments` | `unit_resolution_judgments`, `unit_concept_distinctions` |
| `009_annotation_operations` | `annotation_operations` idempotency receipts |

Consequences that operators must respect, documented with exact procedures in
[RELEASE.md](RELEASE.md#upgrades-and-migration-rollback-limits):

- Back up before every upgrade; a newer binary may migrate the database as soon
  as it starts.
- An older binary does not refuse a newer database; never run one on it.
- Back up only while the service is stopped, copying the database and its
  WAL/SHM sidecars; restore into a staging directory and swap it in at the same
  configured path.
- Annotation idempotency receipts live in the database: restoring an older
  backup can lose newer receipts and events.

## 12. Deliberately not built

These are intentional boundaries of the current system, not hidden features or
committed roadmap items:

- No chatbot behaviour: capture imports structured fields only and never
  contacts a model or scrapes a conversation.
- No automatic extraction, no rule-based semantic extractor, no local model,
  and no provider routing, cost optimisation or automatic provider fallback.
- No automatic retry of provider or annotation writes.
- No learned or automatically applied Concept resolver, no automatic
  BROADER/NARROWER inference, and no forced merging of ambiguous candidates.
- No spaced repetition, review scheduling, mastery estimation, CEFR or
  difficulty scoring.
- No knowledge or prerequisite graph and no cross-interaction normalization.
- No training, dataset splits, vector database, persistent index, SQLite FTS,
  hybrid fusion or reranking; retrieval baselines are request-scoped
  experiments only.
- No authentication or multi-user support; the release binds to localhost.
- No staleness signal for extractions (the stored provenance is sufficient to
  derive one later).

The first milestone's design notes listed possible future directions
(AI-assisted classification, vocabulary and grammar extraction, review
scheduling, semantic search, listening and speaking records, Telegram
integration, adaptive database restructuring and bounded provider retries).
Some of these were later built in a narrower form, as described above; the rest
are not implemented.

## Appendix A: HTTP API reference

Conventions:

- Every route is available at the root path and, when the server runs with
  `-web-dir`, also under `/api/` with the prefix stripped.
- Errors use the shared `{"error":"..."}` shape. Messages never expose SQL,
  internal error chains, API keys, authorization headers or learning content.
- Common statuses: `400` bad id or JSON, `404` not found, `409` conflict, `422`
  validation failure, `500` storage failure; provider failures are `502`
  (unavailable) or `504` (timeout).
- The service is unauthenticated. Browser mutations must pass the request
  boundary ([§10.3](#103-browser-request-boundary)).

### A.1 Health

```bash
curl localhost:8080/healthz
# {"status":"ok"}
curl localhost:8080/readyz
# {"status":"ready"}
```

See [§10.1](#101-process-and-serving).

### A.2 Entries

```bash
curl -X POST localhost:8080/entries \
  -H 'Content-Type: application/json' \
  -d '{"original_input":"Je suis fatigué","original_context":"texting a friend"}'
```

Response `201 Created`:

```json
{
  "id": 1,
  "original_input": "Je suis fatigué",
  "original_context": "texting a friend",
  "created_at": "2026-07-27T12:00:00Z",
  "updated_at": "2026-07-27T12:00:00Z"
}
```

`original_input` is required. Requests with an empty input or unknown JSON
fields are rejected with `400`.

An Entry response deliberately has no `category`, `explanation` or `confidence`
([§3.1](#31-entry-the-learner-authored-source-record)).

#### Get an entry

```bash
curl localhost:8080/entries/1
```

#### List entries (newest first)

```bash
curl 'localhost:8080/entries?limit=20'
# {"entries":[ ... ]}
```

### A.3 Analyses

Runs the analyzer over the entry's original data, validates the output, and
appends a new versioned analysis. The original entry is never modified.

```bash
curl -X POST localhost:8080/entries/1/analysis
```

Response `201 Created`:

```json
{
  "id": 1,
  "entry_id": 1,
  "version": 1,
  "category": "translation",
  "explanation": "Local classification selected \"translation\" because rule \"explicit_translation_request\" matched \"how do i say\" in the input.",
  "confidence": 0.85,
  "uncertainty": "AI review not advised: local evidence is explicit and unambiguous.",
  "analyzer": "rule-based:v2:fr_l2_taxonomy_v1",
  "created_at": "2026-07-27T12:00:00Z"
}
```

The `explanation` names the selected category, the strongest matching rule, and
the observable cue; the `uncertainty` states whether AI review is advised and,
if so, the specific reasons (for example: `AI review advised: only weak fallback
rules matched; original context is empty.`). Confidence is a heuristic decision
score, not a calibrated probability.

Categories, provenance strings and validation are described in
[§3.2](#32-versioned-analysis) and [§3.3](#33-analyzer-providers).

Analyzing the same entry again appends `version: 2`, and so on. A missing entry
returns `404`; metadata that fails validation returns `422`. When the OpenAI
provider is enabled, a provider timeout returns `504` and other provider
failures return `502`; in both cases no analysis is stored.

#### List analyses for an entry (oldest version first)

```bash
curl localhost:8080/entries/1/analyses
# {"analyses":[ ... ]}
```

### A.4 Feedback

Records immutable human judgment about an analysis. `status` is one of
`accepted`, `corrected`, or `rejected`. When `status` is `corrected`, at least
one of `corrected_category` or `corrected_explanation` is required (either or
both); for the other statuses they must be omitted. `user_note` is optional.
Adding feedback never modifies the entry or the analysis.

```bash
# Accept
curl -X POST localhost:8080/analyses/1/feedback \
  -H 'Content-Type: application/json' \
  -d '{"status":"accepted","user_note":"looks right"}'

# Correct
curl -X POST localhost:8080/analyses/1/feedback \
  -H 'Content-Type: application/json' \
  -d '{"status":"corrected","corrected_category":"grammar","corrected_explanation":"present tense of manger"}'
```

Response `201 Created`:

```json
{
  "id": 1,
  "analysis_id": 1,
  "status": "corrected",
  "corrected_category": "grammar",
  "corrected_explanation": "present tense of manger",
  "user_note": "",
  "created_at": "2026-07-28T12:00:00Z"
}
```

A missing analysis returns `404`; input that fails validation (unknown status,
a `corrected` status with neither corrected field, a `corrected_category`
outside the `fr_l2_taxonomy_v1` taxonomy, over-length fields, or corrected
content on a non-corrected status) returns `422`. A `corrected_category` is
trimmed and lowercased before validation, so `" Grammar "` is accepted and
stored as `grammar`.

#### List feedback for an analysis (oldest first)

```bash
curl localhost:8080/analyses/1/feedback
# {"feedback":[ ... ]}
```

### A.5 Effective analysis

```bash
curl localhost:8080/analyses/1/effective
```

The resolution rules are in [§3.6](#36-effective-analysis).

Response `200 OK` for a `corrected` analysis (category corrected, explanation
retained):

```json
{
  "analysis_id": 1,
  "entry_id": 5,
  "version": 2,
  "original": { "category": "grammar", "explanation": "Original explanation" },
  "effective": { "category": "morphology", "explanation": "Original explanation" },
  "resolution": "corrected",
  "feedback_id": 19
}
```

Response `200 OK` for a `rejected` analysis (`effective` is `null`):

```json
{
  "analysis_id": 1,
  "entry_id": 5,
  "version": 2,
  "original": { "category": "grammar", "explanation": "Original explanation" },
  "effective": null,
  "resolution": "rejected",
  "feedback_id": 21
}
```

A non-numeric id returns `400`; a missing analysis returns `404`.

### A.6 Learning inventory

States and selection rules are in [§3.7](#37-learning-inventory).

#### List learning records

```bash
curl 'localhost:8080/learning-records?state=corrected&limit=50'
```

Filters (all optional): `state` (one of the five states above), `category`
(matches the **effective** category, so rejected and unanalyzed records — which
have no effective category — never match), `analyzer` (exact match on the latest
analysis's provenance, not a substring). Pagination: `limit` (default `50`, max
`200`; out-of-range values are clamped) and `before_entry_id` for descending
cursor pagination. Records are ordered by entry id descending.

Response `200 OK`:

```json
{
  "records": [
    {
      "entry_id": 42,
      "original_input": "Je mange une pomme",
      "original_context": "describing lunch",
      "entry_created_at": "2026-08-01T09:00:00Z",
      "state": "corrected",
      "analysis_id": 7,
      "analysis_version": 2,
      "analyzer": "rule-based:v2:fr_l2_taxonomy_v1",
      "confidence": 0.5,
      "uncertainty": "",
      "analysis_created_at": "2026-08-01T09:05:00Z",
      "original": { "category": "grammar", "explanation": "present tense" },
      "effective": { "category": "morphology", "explanation": "present tense" },
      "feedback_id": 11
    }
  ],
  "next_before_entry_id": 42
}
```

`next_before_entry_id` is the cursor for the next page (pass it back as
`before_entry_id`); it is `null` when there are no more records. This is a
paginated view, so no total count is included — use the summary for totals. An
invalid `state`, `category`, or `before_entry_id` returns `400`.

#### Summary

```bash
curl localhost:8080/learning-records/summary
```

Aggregate counts across all entries. State counts sum to `total_entries`;
`analyzed_entries + unanalyzed_entries == total_entries`. `by_effective_category`
excludes rejected and unanalyzed records (they have no effective category);
`by_analyzer` counts the latest analysis's provenance per analyzed entry.

```json
{
  "total_entries": 6,
  "analyzed_entries": 4,
  "unanalyzed_entries": 2,
  "by_state": {
    "unanalyzed": 2,
    "unreviewed": 1,
    "accepted": 1,
    "corrected": 1,
    "rejected": 1
  },
  "by_effective_category": { "grammar": 1, "vocabulary": 1, "morphology": 1 },
  "by_analyzer": { "rule-based:v2:fr_l2_taxonomy_v1": 4 }
}
```

#### Export (JSONL)

```bash
curl localhost:8080/learning-records/export?state=accepted
```

Streams the inventory as **JSONL / NDJSON**: `Content-Type:
application/x-ndjson; charset=utf-8`, one record object per line, no enclosing
array. Each line has the same shape as a list record. It accepts the same
filters as the list endpoint, uses a larger bound (default `500`, max `5000`),
and streams line by line rather than buffering the whole export. Records are
emitted in descending entry-id order. The export never includes API keys,
environment values, or other internal data, and performs no AI call.

```
{"entry_id":42,"original_input":"Je mange une pomme","state":"accepted", ...}
{"entry_id":41,"original_input":"Bonjour","state":"unreviewed", ...}
```

### A.7 Capture import

Semantics, persistence and idempotency are in
[§4.1](#41-learning_capture_v1-import). This endpoint makes no AI call.

Request fields:

| Field                | Required | Notes                                                                 |
| -------------------- | -------- | --------------------------------------------------------------------- |
| `schema_version`     | yes      | Must be exactly `learning_capture_v1`; any other value returns `422`. |
| `capture_id`         | yes      | Client-generated idempotency id. Trimmed; portable charset `[A-Za-z0-9][A-Za-z0-9._:-]*` (e.g. a UUID or `manual-2026-08-04-001`). |
| `source`             | yes      | Typed vocabulary: `chatgpt-web` or `manual`. Unknown sources return `422`. Metadata only — it does **not** confer trust. |
| `original_input`     | yes      | The learner's original question. Validated like a normal entry.       |
| `original_context`   | yes      | Surrounding context. Validated like a normal entry.                   |
| `analysis`           | no       | Optional imported classification (see below).                         |
| `discussion_summary` | no       | Optional short summary of the discussion. Trimmed, bounded.           |

The optional `analysis` object uses the shared `fr_l2_taxonomy_v1` taxonomy and
reuses the same validation as any other analysis: `category` (in the taxonomy),
`explanation` (required, bounded), `confidence` (in `[0, 1]`), and optional
`uncertainty` (bounded). If the analysis is present but invalid, the **whole
capture fails and nothing is stored**.

#### Import with an analysis

```bash
curl -X POST localhost:8080/captures \
  -H 'Content-Type: application/json' \
  -d '{
    "schema_version": "learning_capture_v1",
    "capture_id": "b1f0c3a2-1e8c-4b0a-9f0e-2a7d6c5b4a30",
    "source": "chatgpt-web",
    "original_input": "Je parle japonais ou je parle le japonais ?",
    "original_context": "Whether language names take an article after parler.",
    "analysis": {
      "category": "grammar",
      "explanation": "After parler a language name is normally used without an article.",
      "confidence": 0.9,
      "uncertainty": "Usage may vary when the language is the object."
    },
    "discussion_summary": "Compared parler japonais with apprendre le japonais."
  }'
```

Response `201 Created`:

```json
{
  "capture_id": "b1f0c3a2-1e8c-4b0a-9f0e-2a7d6c5b4a30",
  "entry_id": 42,
  "analysis_id": 7,
  "created": true
}
```

The server creates the entry, a **version-1** analysis with server-constructed
provenance `imported:chatgpt-web:learning_capture_v1`, and a capture receipt —
all atomically. The entry is then readable at `GET /entries/42`, the analysis at
`GET /entries/42/analyses`, and the record appears in the learning inventory.

#### Import without an analysis

```bash
curl -X POST localhost:8080/captures \
  -H 'Content-Type: application/json' \
  -d '{
    "schema_version": "learning_capture_v1",
    "capture_id": "manual-2026-08-04-001",
    "source": "manual",
    "original_input": "Comment dit-on \"apple\" ?",
    "original_context": "vocabulary lookup",
    "discussion_summary": "Asked for the French word for apple."
  }'
```

Response `201 Created` (note the explicit `null` analysis id):

```json
{
  "capture_id": "manual-2026-08-04-001",
  "entry_id": 43,
  "analysis_id": null,
  "created": true
}
```

The entry is created with no analysis, so it appears in the inventory as
`unanalyzed`. It can still be analyzed later through the ordinary
`POST /entries/{id}/analysis` endpoint, which appends version 1 as usual.

#### Idempotency summary

New `capture_id` → `201` with `created: true`; same id and same normalized
content → `200` with `created: false` and no new rows; same id with different
content → `409`, existing capture untouched.

#### Look up a capture

```bash
curl localhost:8080/captures/manual-2026-08-04-001
```

Response `200 OK`:

```json
{
  "capture_id": "manual-2026-08-04-001",
  "schema_version": "learning_capture_v1",
  "source": "manual",
  "entry_id": 43,
  "analysis_id": null,
  "discussion_summary": "Asked for the French word for apple.",
  "created_at": "2026-08-04T09:00:00Z"
}
```

The lookup returns metadata and references only. It never returns the content
fingerprint and never duplicates the full entry or analysis content — fetch those
through the existing entry, analysis, and inventory endpoints. A malformed
`capture_id` returns `400`; an unknown one returns `404`.

#### Status codes and error format

| Situation                                   | Status |
| ------------------------------------------- | ------ |
| New capture created                         | `201`  |
| Exact idempotent replay                     | `200`  |
| Invalid JSON / unknown field / trailing JSON | `400` |
| Unsupported `schema_version`                | `422`  |
| Invalid content (source, entry data, analysis) | `422` |
| Same `capture_id` with changed content      | `409`  |
| Lookup of a missing capture                 | `404`  |
| Malformed `capture_id` on lookup            | `400`  |
| Unexpected storage failure                  | `500`  |

Errors use the shared `{"error":"..."}` shape. Messages are concise and never
expose SQL, the content fingerprint, API keys, environment variables, internal
error chains, or authorization headers.

#### Security notes

`source` is descriptive metadata, not an authorization signal: a `chatgpt-web`
capture is not trusted more than a `manual` one, and the analyzer provenance is
always constructed on the server. The endpoint is unauthenticated, like the rest
of this service — do not expose it directly to untrusted networks without putting
authentication in front of it. It performs no outbound request and reads no
secret material.

### A.8 Knowledge extraction and admission

Semantics are in [§5](#5-knowledge-extraction-and-admission). Extraction is
disabled by default and returns `503` until an extractor is configured:

```bash
# Enable knowledge extraction (independent of AI_PROVIDER):
export EXTRACTOR_PROVIDER=openai
export OPENAI_API_KEY=sk-your-key-here
export OPENAI_MODEL=gpt-4o-mini
go run ./cmd/server
```

#### Run an extraction

```bash
curl -sS -X POST http://localhost:8080/entries/1/extractions
# 201 -> {"id":10,"entry_id":1,"version":1,"source_analysis_id":3,
#         "source_feedback_id":null,"extractor":"openai:...:knowledge_extraction_v1",
#         "created_at":"...","units":[{"id":100,"ordinal":1,"kind":"grammar",
#         "canonical":"vouloir + infinitif","statement":"...","example":null,
#         "confidence":0.9,"admission":{"ruleset":"knowledge_admission_v1",
#         "machine_state":"active","machine_reason":"default_active",
#         "effective_state":"active","latest_override":null}}]}
```

#### List an entry's extractions (newest version first)

```bash
curl -sS http://localhost:8080/entries/1/extractions
# {"extractions":[ ... ]}
```

#### Get one extraction

```bash
curl -sS http://localhost:8080/extractions/10
```

#### Admission: override, read state, and history

```bash
# Suppress a unit the learner has already mastered (append-only).
curl -sS -X POST http://localhost:8080/knowledge-units/100/admission-overrides \
  -H 'Content-Type: application/json' \
  -d '{"decision":"suppressed","reason":"mastered","note":"already know this"}'

# Effective admission state (machine recommendation + latest override).
curl -sS http://localhost:8080/knowledge-units/100/admission

# Full append-only override history (oldest first).
curl -sS http://localhost:8080/knowledge-units/100/admission-overrides
```

The `GET` endpoints never call the extractor. Only `POST
/entries/{id}/extractions` invokes AI.

| Situation                                       | Status |
| ----------------------------------------------- | ------ |
| Extraction created                              | `201`  |
| Override created / admission read               | `201` / `200` |
| Invalid path id / invalid JSON                  | `400`  |
| Entry / extraction / knowledge unit not found   | `404`  |
| Entry not eligible (unanalyzed / rejected)      | `409`  |
| Source changed while the provider ran           | `409`  |
| Invalid extractor output / invalid override     | `422`  |
| Extractor disabled                              | `503`  |
| Provider timeout                                | `504`  |
| Provider unavailable / invalid provider output  | `502`  |
| Unexpected storage failure                      | `500`  |

On any failure nothing partial is persisted, and a result whose source
interpretation changed while the provider ran is discarded with `409`
([§5](#5-knowledge-extraction-and-admission)).

### A.9 Capture CLI

The CLI's design is in [§4.2](#42-capture-cli).

`cmd/capture` is a thin command-line client for `POST /captures`. It reads a
prepared `learning_capture_v1` JSON document from a file or stdin and posts it,
**unchanged**, to a running backend. It is only a transport client:

```
capture CLI  ≠ chatbot
             ≠ analyzer
             ≠ importer that rewrites data
```

It contacts no AI model, does not scrape ChatGPT, and never rewrites, normalizes,
reclassifies, or fingerprints your payload. The server remains the single source
of truth for every capture rule (schema, source, entry, taxonomy, and analysis
validation, fingerprinting, idempotency, and conflict detection). The CLI only
performs transport-level sanity checks (non-empty payload, valid URL, decodable
response).

#### Usage

Start the server in one terminal:

```bash
make run
```

Then submit a capture in another terminal — by file:

```bash
go run ./cmd/capture -file examples/captures/manual-example.json
```

or from stdin (both forms work):

```bash
cat examples/captures/manual-example.json | go run ./cmd/capture
go run ./cmd/capture < examples/captures/manual-example.json
```

On success it prints a stable summary:

```
capture stored (new)
capture_id:  manual-example-001
entry_id:    1
analysis_id: null
created:     true
```

Verify the capture landed by listing the learning inventory:

```bash
curl 'localhost:8080/learning-records?limit=20'
```

The new entry appears as an `unanalyzed` record (or `unreviewed` when the capture
included an analysis). A capture with an analysis instead prints its
`analysis_id` and shows the imported analysis in the inventory.

#### Backend URL

The backend base URL is resolved with this precedence:

```
-url flag  ->  FRENCH_HUB_URL  ->  http://localhost:8080
```

```bash
# Explicit flag (highest precedence)
go run ./cmd/capture -url http://localhost:8080 -file examples/captures/manual-example.json

# Environment variable
export FRENCH_HUB_URL=http://localhost:8080
go run ./cmd/capture -file examples/captures/manual-example.json
```

#### Exit status and error handling

The CLI exits `0` on success, including an **idempotent replay**: resubmitting
the same capture prints `capture already existed (idempotent replay)` with
`created: false` and still exits `0`. It exits non-zero and prints a concise
message to stderr for a conflict (`409`, same `capture_id` with different
content — the existing capture is left untouched), a validation error
(`400`/`422`, showing the server's safe public message), or an unexpected server
error (`500`). Errors carry only the status code and the server's own message —
never your learning content, credentials, or authorization headers. The client
uses a bounded request timeout, performs no retries, and makes no AI call.

### A.10 Concepts, membership and extraction selection

Handlers contain no SQL; all decisions run through the application
`ConceptService`, following the existing error conventions (`400` bad id/JSON,
`404` not found, `409` conflict, `422` validation, `500` storage):

- `GET  /concepts` (optional `?state=`) — list concepts.
- `POST /concepts` — create a concept from an explicit identity (optionally
  seeding + linking a unit as SAME **atomically**, in one repository transaction:
  if the seed link fails, no concept persists either). The seed SAME only
  **establishes** membership for an **unresolved** unit; if the seed unit already
  has a current SAME membership the whole transaction rolls back with `409`
  (`ErrConceptConflict`) — nothing is created, no event is appended, the existing
  membership is untouched. Moving an existing membership is `ReassignSame`'s job
  alone.
- `GET  /concepts/{id}` — a concept with its links.
- `POST /concepts/{id}/preferred-unit` — explicitly select the preferred unit.
- `GET  /knowledge-units/{id}/concept-resolution` — read-only: what the
  deterministic resolver would decide for this unit (records nothing).
- `POST /knowledge-units/{id}/concept-links/same` — accept a SAME membership for
  a unit that has **no** current SAME (conflicts if it already has one).
- `GET  /knowledge-units/{id}/concept-membership` — read-only current-membership
  read model. Returns the unit's **current** SAME membership straight from the
  `unit_concept_memberships` projection (`{"unit_id":…,"current_membership":
  {"concept_id":…,"link_id":…,"updated_at":…}}`), or an explicit
  `"current_membership": null` when the unit is unresolved. It never scans the
  append-only event log, so a superseded-but-still-`accepted` event cannot be
  mistaken for the current answer. `404` if the unit does not exist.
- `PUT  /knowledge-units/{id}/concept-membership` — human correction that *moves*
  a unit's current SAME membership to a different concept even when one already
  exists (milestone 10.5.1). Returns `409` only for a genuinely invalid move,
  never merely because a prior SAME decision exists. This is the **only**
  operation permitted to move an existing current membership; concept creation
  with a seed SAME establishes membership only for an unresolved unit and never
  reassigns.
- `POST /knowledge-units/{id}/concept-membership/reject` — explicit human
  **INVALID** judgment (milestone 10.6): the candidate belongs to no concept.
  Clears the unit's current SAME membership and records the rejection as an
  immutable append-only event (`relation='same'`, `status='rejected'`) that
  supersedes the in-force SAME — negative evidence, not a deleted row. Also clears
  a now-invalid `preferred_unit_id`. Idempotent: rejecting a unit with no current
  SAME is a `200` no-op with a null `link`. `404` if the unit does not exist. The
  concept's derived support drops on the next read. INVALID is deliberately **not**
  a relation.
- `POST /knowledge-units/{id}/concept-links/relation` — record
  broader/narrower/related.
- `GET  /reviewable-units` (optional `?entry_id=`) — units with no accepted SAME
  membership, with their derived candidate identity for a reviewer. Each entry also
  carries the unit's `example` and extraction `confidence` (milestone 10.6) so the
  review UI needs no extra round-trip.
- `GET  /entries/{id}/current-extraction` — inspect selected extraction and mode.
- `PUT  /entries/{id}/current-extraction` — explicit persistent pin (including a
  pin to the latest version); request `{"extraction_id":34}`.
- `DELETE /entries/{id}/current-extraction` — remove the pin and resume automatic
  latest-successful selection. Bodyless, idempotent for an existing entry.

All three return `200` with `{"entry_id":12,"current_extraction_id":34,
"selection_mode":"pinned"}`. The existing ID fields are unchanged; the additive
`selection_mode` is exactly `automatic` or `pinned`. Pinning latest still reports
`pinned`. In automatic mode without a successful extraction, the ID is null.
GET is read-only. DELETE clears only the `entry_current_extractions` projection
row in a transaction and returns the resulting automatic snapshot. Unknown
entry is `404`; invalid/nonpositive path ID is `400`; storage failure is `500`.
PUT retains `400` for invalid JSON and `422` for an invalid or cross-entry target,
without changing the old pin. The browser boundary covers this DELETE on root
and workbench `/api/` routes before services execute.

No migration or annotation rewrite: extraction/unit/history, SAME memberships,
INVALID and DISTINCT records remain intact. Derived current-unit projections,
reviewability and support follow the selected extraction immediately. See
[FLH-023 frontend handoff](plans/FLH-023-extraction-selection-mode.md).

### A.11 Annotation labels, effective annotation and operations

- `POST /knowledge-units/{id}/invalid`, `POST /knowledge-units/{id}/invalid/restore`,
  `GET /knowledge-units/{id}/invalid` — unit-level INVALID judgment
  ([§7.2](#72-annotation-labels-invalid-and-distinct)).
- `POST /knowledge-units/{id}/concept-distinctions`,
  `GET /knowledge-units/{id}/concept-distinctions` — explicit DISTINCT pairs.
- `GET /knowledge-units/{id}/effective-annotation`, `GET /effective-annotations` —
  effective annotation read models ([§7.3](#73-effective-annotation),
  [§7.4](#74-effective-annotation-inspector)).
- `GET /annotation-operations/{uuid}` — committed idempotency receipt
  ([§7.5](#75-annotation-request-idempotency)). DISTINCT and
  BROADER/NARROWER/RELATED POSTs accept an optional `Idempotency-Key` UUID.

### A.12 Dataset, quality and retrieval reports

All are read-only GETs ([§8](#8-annotation-dataset-and-retrieval-research)):

```bash
curl -sS http://localhost:8080/annotation-dataset/v1          # JSON envelope
curl -sS http://localhost:8080/annotation-dataset/v1/export   # NDJSON
curl -sS http://localhost:8080/annotation-dataset/v1/quality
curl -sS http://localhost:8080/retrieval-evaluation/v1        # default: exact signature
curl -sS 'http://localhost:8080/retrieval-evaluation/v1?retriever=weighted_lexical_retriever_v1'
curl -sS 'http://localhost:8080/retrieval-evaluation/v1?retriever=bm25_retriever_v1'
curl -sS 'http://localhost:8080/retrieval-evaluation/v1?retriever=embedding_retriever_v1'  # only when EMBEDDING_PROVIDER=http
curl -sS http://localhost:8080/retrieval-comparison/v1
```

An unknown retriever returns `400` with `{"error":"unknown retriever"}`. An
invalid dataset returns `200` with `state: "blocked_invalid_dataset"` and null
metrics; `500` is reserved for a report build failure or, for the comparison, a
population mismatch.

### A.13 Knowledge Library

| Endpoint (GET, also under `/api`) | Returns |
| --- | --- |
| `/knowledge-library/concepts?q=&state=&limit=` | Search or browse; `knowledge_library_search_v1` |
| `/knowledge-library/concepts/{id}` | Identity, status, preferred unit, supporting units, non-supporting current members, current relations, historical units |
| `/knowledge-library/units/{id}/source` | Original entry, extraction, current-extraction selection, and the interpretation (analysis + feedback then) the extraction used |

Search parameters and limits are in [§9.1](#91-search-contract-and-limitations).
Invalid `q`, `state` or `limit` returns `400`; unknown ids return `404`; these
routes accept GET only.
