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