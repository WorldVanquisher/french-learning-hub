# Architecture

## Product goal

Create a persistent personal knowledge system for French learning.

The application should preserve questions and learning context that would
otherwise disappear inside individual chat conversations.

## Initial architecture

The first version is a single Go HTTP service backed by SQLite.

HTTP request
    -> transport layer
    -> application use case
    -> domain repository interface
    -> SQLite repository

## Analysis metadata (milestone 2)

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
runs and is testable without any external AI provider; milestone 4 adds an
OpenAI-backed implementation behind the same interface (see below), chosen at
startup without touching the transport, application, or storage layers.

Validation before storage: `category` and `explanation` are required and length
bounded, `confidence` must be in `[0, 1]`, and `uncertainty` is bounded
free-form text. Metadata that fails validation is rejected with HTTP `422` and
never reaches the database.

Endpoints:

- `POST /entries/{id}/analysis` — analyze an entry, append a new version.
- `GET  /entries/{id}/analyses` — list an entry's analyses, oldest first.

## Human feedback (milestone 3)

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

## Pluggable analyzer provider (milestone 4)

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

## Effective analysis resolution (milestone 5)

An analysis is immutable and its feedback is append-only, so the *current
interpretation* of an analysis is not a stored row — it is derived on demand by
combining the analysis with its latest feedback. Milestone 5 exposes that
derivation as a strictly read-only projection. Nothing new is persisted; no
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

Corrected-category validation was tightened in this milestone: when
`corrected_category` is present it is trimmed, lowercased, and rejected unless it
is a `fr_l2_taxonomy_v1` value (reusing `domain.ValidCategory`, so the taxonomy
list is not duplicated). This keeps corrected categories consistent with the
categories analyses themselves must use.

## Explainable, uncertainty-aware rule engine (milestone 6)

The local rule-based analyzer's original four-branch `switch` (contains `?`,
word count) is replaced by a deterministic, explainable rule engine that lives
entirely in `internal/analyzer` (`assessment.go`). The engine is implementation
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

## Queryable learning inventory (milestone 7)

The individual records (entries, versioned analyses, append-only feedback) are
already stored; what was missing was a way to *see the whole collection at once*.
Milestone 7 adds a read-only **learning inventory**: a cross-entry projection
that, for each entry, combines its latest analysis and that analysis's latest
feedback into one current row. Like effective-analysis resolution, it is derived
on demand — no new table, no migration, no mutation, and no AI call. It is the
first feature that reads *across* entries rather than operating on one.

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

### Deterministic latest selection, in one query

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

### Filtering, pagination, and the summary

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

## Structured learning capture import (milestone 8)

The learning that happens in an external French discussion (for example in
ChatGPT) previously had no stable way into this system. Milestone 8 adds one:
`POST /captures` accepts a versioned `learning_capture_v1` document and turns it
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

### What the client may and may not supply

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

### Reuse, not a second taxonomy

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

### Persistence: one receipt table, one transaction

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

### Idempotency by content fingerprint

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

### Result, lookup, and status mapping

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

### Guarantees

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

## Capture workflow client (milestone 9)

Milestone 8 built the `POST /captures` server contract; milestone 9 makes it
usable in everyday learning by adding a small external client. Nothing on the
server changes. The new piece is purely a transport adapter that turns a prepared
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

### Layering

`cmd/capture/main.go` is intentionally thin: it parses flags, chooses the input
source (file or stdin), resolves the backend URL, builds the client, invokes it,
prints a stable summary, and sets the process exit code. All testable behavior
lives in `internal/captureclient`, which is unit-tested against an
`httptest.Server` and integration-tested against the real handler and a real
temporary SQLite database. This keeps the CLI's own logic trivial and the HTTP
behavior fully covered, and it means the capture client is **not** a second
application layer — it is a client of the one that already exists.

### The client does not duplicate domain rules

The server owns every capture rule: schema version, source vocabulary, entry
validation, `fr_l2_taxonomy_v1`, analysis validation, SHA-256 fingerprinting,
idempotency, and conflict detection. The client reimplements none of them. It
sends the caller's payload byte-for-byte — it never rewrites `original_input`,
normalizes content, generates an analysis, reclassifies a category, adjusts
confidence, rewrites `discussion_summary`, or computes a fingerprint. The only
checks it makes are transport-level: the payload is non-empty, the base URL is a
valid absolute HTTP(S) URL, and the response decodes into the expected shape. The
server decides whether a non-empty payload is actually valid.

### Response mapping

The client mirrors the server's existing outcomes onto typed results and errors:

- `201` / `200` → a decoded `Result{CaptureID, EntryID, AnalysisID, Created}`.
  `Created` distinguishes a new capture from an idempotent replay; a replay is a
  success, not an error, so the CLI exits `0`.
- non-2xx → an `*APIError{StatusCode, Message}` carrying the server's safe public
  message from the shared `{"error":"..."}` body. `409` conflict is surfaced via
  `APIError.IsConflict()`; `400`/`422`/`500` propagate their status and message.

### Safety properties

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

### Configuration

The backend URL is resolved with the precedence `-url` flag → `FRENCH_HUB_URL`
→ `http://localhost:8080`. This mirrors the server's environment-first
convention without adding a configuration framework or reading `.env` files, in
keeping with the project's dependency and configuration discipline.

## Design principles

1. Store raw learning records before attempting advanced classification.
2. Treat categories as changeable metadata.
3. Preserve database history through migrations.
4. Let AI propose structural changes, but never silently rewrite production data.
5. Prefer simple, replaceable components.
6. Build from real usage data rather than imagined future requirements.

## Future possibilities

These are not part of the first milestone:

- AI-assisted classification
- vocabulary and grammar extraction
- review scheduling
- semantic search
- listening and speaking records
- Telegram integration
- adaptive database restructuring
- automatic retries for transient provider failures (a bounded, validator-aware
  retry path, e.g. reclassifying when output fails schema/taxonomy validation).
  Deliberately not implemented in this milestone: a failed OpenAI request
  currently surfaces `502`/`504` and stores nothing, with no retry.