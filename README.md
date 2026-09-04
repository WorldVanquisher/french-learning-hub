# French Learning App

[简体中文](README.zh-CN.md)

A small Go HTTP service that persistently stores French-learning questions and
their original context. The original user input is treated as the source of
truth; AI-generated metadata is stored separately as versioned analyses and
never overwrites the original record.

The active `Entry` model and `POST /entries`, `GET /entries`, and
`GET /entries/{id}` responses contain only learner-authored input/context,
identity, and timestamps. Category, explanation, and confidence belong only to
versioned `Analysis` records and the Effective Analysis / Inventory projections
that consume them. Migration 001's nullable columns with those names remain
physically present solely so historical databases keep their original schema;
active Entry reads and writes ignore them.

Milestone 1 delivered persistence: a single backend, SQLite storage, and the
workflow from question input to storage. Milestone 2 adds validated, versioned
AI-generated metadata: each entry can be analyzed repeatedly, and every analysis
is appended as an immutable versioned record. A deterministic rule-based
analyzer runs locally — no external AI API is called yet. Milestone 3 adds
immutable human feedback: a person can accept, correct, or reject an analysis,
and every feedback record is appended without ever modifying the entry or the
analysis it refers to. Milestone 4 makes the analyzer pluggable at runtime: the
rule-based analyzer remains the default and costs nothing, and an OpenAI-backed
analyzer can be enabled through configuration without changing any endpoint.
Milestone 5 adds effective analysis resolution: a read-only endpoint that
computes the current interpretation of an analysis by combining it with its
latest feedback, without storing anything new or mutating any record.
Milestone 6 replaces the local analyzer's simplistic `switch` with an
explainable, uncertainty-aware **named rule engine**: it reports which rules
matched, detects weak or conflicting evidence, produces a heuristic confidence
score, and computes an advisory `NeedsAI` signal — while remaining fully local,
deterministic, and free of API calls (no automatic AI escalation).
Milestone 7 adds a queryable **learning inventory**: read-only endpoints that
combine each entry's latest analysis and that analysis's latest feedback into
one current row per entry, with filtering, cursor pagination, an aggregate
summary, and a JSONL export. It is a derived projection — nothing new is stored,
no record is mutated, and no AI call is made.
Milestone 8 adds a **structured learning capture import**: a single stable
endpoint that accepts a `learning_capture_v1` JSON document — a French
discussion the user already had elsewhere (for example in ChatGPT) — and turns
it into a normal learning entry plus, optionally, a version-1 analysis, in one
atomic transaction. It is **not a chatbot** and makes **no AI call**: the
backend never talks to ChatGPT or any model, never scrapes a conversation, and
only ingests the structured fields the client sends. Imports are idempotent by a
client-supplied `capture_id`, and imported records flow through the existing
analysis, feedback, effective-resolution, and inventory features unchanged.
Milestone 9 makes that workflow usable day to day with a tiny **capture CLI**
(`cmd/capture`): it reads a prepared `learning_capture_v1` document from a file
or stdin and posts it to the backend's `POST /captures` endpoint over HTTP. It
is a thin transport client — **not a chatbot, not an analyzer, and not an
importer that rewrites data**: it never contacts a model and sends the payload
to the server unchanged, so the server stays the single source of truth for all
capture rules.
Milestone 10 adds **knowledge extraction** (immutable per-extraction
`KnowledgeUnit` candidates) and milestone 10.5 / 10.5.1 add the durable
**`KnowledgeConcept`** identity layer with a conservative deterministic resolver,
an append-only resolution event log, and a current-SAME-membership projection as
the single authority. Milestone 10.6 adds the first **human concept-review /
annotation UI** (`web/`) plus the backend operations needed to record
high-quality resolution labels. An **annotation-semantics correctness patch**
(migration `008`) sharpens two labels: a **unit-level INVALID** judgment
(`POST /knowledge-units/{id}/invalid`) records that a `KnowledgeUnit` is an invalid
candidate — recordable even for a freshly extracted unit that never had a SAME
membership, reversible via `.../invalid/restore`, and distinct from the
membership-level clear (`POST /knowledge-units/{id}/concept-membership/reject`); and
an explicit **DISTINCT** negative pair (`POST
/knowledge-units/{id}/concept-distinctions`) records that a unit is *not* the same
identity as a concept without touching membership. The review UI is an annotation /
data-collection instrument for future resolver experiments — **not** the Review
Engine, mastery, scheduling, or an ML resolver. Milestones 11-A/11-B add the
effective annotation projection and its read-only Inspector; milestone 11-C adds
the read-only, versioned Concept Annotation Dataset v1, and milestone 11-D adds a
deterministic validation and quality report over that dataset without training a
model. Milestone 12-A adds a read-only exact-signature retrieval evaluation
foundation, milestone 12-B adds a selectable weighted lexical cosine baseline,
milestone 12-C adds a corpus-aware BM25 lexical baseline, and milestone 12-D adds
an optional provider-independent semantic embedding baseline, without changing
Concept resolution or annotation authority. Milestone 13-A0 adds one compact,
read-only comparison over those four baselines while preserving the complete M12
experiment contract.
Milestone 13-A1 exposes the M11-D quality summary and M13-A0 retrieval comparison
in a third, read-only **Experiment Dashboard** view inside the existing workbench;
the browser presents backend-owned values and computes no experiment metrics.
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for design principles
and [web/README.md](web/README.md) for running the frontend.

## Requirements

- Go 1.26+ (uses `net/http` method-based routing)
- No CGO required — SQLite is provided by the pure-Go `modernc.org/sqlite` driver.

## Layout

```
cmd/server            program entry point + graceful shutdown
cmd/capture           thin CLI that posts a learning_capture_v1 file/stdin to POST /captures
internal/domain       Entry/Analysis/Feedback entities, repository + Analyzer interfaces, validation
internal/application  use cases (entry create/get/list; entry analysis; analysis feedback; effective analysis resolution; learning inventory)
internal/analyzer     local rule-based Analyzer + OpenAI Analyzer + named rule engine (assessment)
internal/extractor    OpenAI knowledge Extractor (opt-in) selected by EXTRACTOR_PROVIDER
internal/embedding    optional HTTP text-to-vector provider for M12-D evaluation
internal/captureclient   thin HTTP client for POST /captures (used by cmd/capture)
internal/storage/sqlite  SQLite repositories + migration runner
internal/transport/http  HTTP handlers and routing
internal/config       environment-based configuration
migrations            embedded .sql migrations
examples/captures     example learning_capture_v1 documents
web                   internal annotation, inspection, and experiment dashboard workbench (React + Vite + TS)
```

Layers are kept separate: HTTP handlers hold no database logic, and the
application layer depends only on the domain repository and `Analyzer`
interfaces. The analyzer is pluggable — the rule-based one can later be replaced
by an external AI provider without touching the transport or storage layers.

Data is append-only where history matters: analyses are versioned per entry, and
feedback records are immutable. Original entries and analyses are never mutated.

## Configuration

Configuration comes from the environment (see [.env.example](.env.example)).
Defaults work out of the box:

| Variable             | Default                     | Description                                   |
| -------------------- | --------------------------- | --------------------------------------------- |
| `PORT`               | `8080`                      | HTTP listen port                              |
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
[Knowledge extraction](#knowledge-extraction-milestone-10) for details.

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

### Analyzer providers

The analyzer that produces metadata for `POST /entries/{id}/analysis` is
selected at startup by `AI_PROVIDER`:

- **`rule-based`** (default): a local, deterministic **named rule engine**. It
  calls no external service and costs nothing. It evaluates explicit linguistic
  cues (translation, pronunciation, orthography, morphology, grammar,
  vocabulary, pragmatics, whole-utterance comprehension) in the original input
  and context, falling back to weak token-count heuristics only when no explicit
  rule fires. It records which named rules matched and meaningful uncertainty
  reasons, and produces a **heuristic confidence score — not a calibrated
  probability**. It can also *advise* AI review (an internal `NeedsAI` signal),
  but **this milestone does not automatically call OpenAI**: `AI_PROVIDER=rule-based`
  uses only local logic. Provenance is stored as `rule-based:v2:fr_l2_taxonomy_v1`
  (`rule-based:<ruleset-version>:<taxonomy-version>`) so records produced by
  different rulesets stay distinguishable.
- **`openai`** (opt-in): calls the OpenAI Responses API and uses **only** the
  OpenAI analyzer. **API usage is billed by OpenAI and is separate from any
  ChatGPT subscription.** Provenance is stored as `openai:<model>:fr_l2_taxonomy_v1`
  so every analysis records which provider, model, and taxonomy/prompt version
  produced it.

The rule engine's `NeedsAI` recommendation is advisory only. Automatic hybrid
routing between the local engine and OpenAI (escalating low-confidence local
results to the AI provider) is future work and is not implemented here; there is
no automatic fallback in either direction.

Enable OpenAI through the environment — never place credentials in Git. Provide
them via your shell or an untracked `.env` file (see [.env.example](.env.example)):

```bash
# Rule-based (default): no configuration needed.
go run ./cmd/server

# OpenAI mode: set environment variables (placeholders shown; use your own).
export AI_PROVIDER=openai
export OPENAI_API_KEY=sk-your-key-here
export OPENAI_MODEL=gpt-4o-mini
go run ./cmd/server
```

Invalid configuration (unknown `AI_PROVIDER`, or `openai` without an API key or
model) stops startup with a clear error rather than silently falling back.

If an OpenAI request fails (network error, timeout, upstream 4xx/5xx, malformed
or refused output), **no analysis record is created**: a provider timeout
returns `504`, other provider failures return `502`, and the entry and its prior
analyses are left untouched. There is no automatic fallback to the rule-based
analyzer during an OpenAI request. `OPENAI_TIMEOUT` defaults below
`HTTP_WRITE_TIMEOUT` so a provider call cannot normally outlive the HTTP
response deadline.

## Running

```bash
make run          # or: go run ./cmd/server
```

The database file and its directory are created automatically on first run,
and migrations are applied at startup.

## API

### Health

```bash
curl localhost:8080/healthz
# {"status":"ok"}
```

### Create an entry

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

An Entry response deliberately does not include `category`, `explanation`, or
`confidence`. Use the Analysis endpoints below for versioned machine
interpretation, Effective Analysis for feedback-resolved interpretation, or the
learning inventory for the current cross-entry view. The similarly named nullable
columns created by migration 001 are legacy physical storage only and are not an
active API or domain authority.

### Get an entry

```bash
curl localhost:8080/entries/1
```

### List entries (newest first)

```bash
curl 'localhost:8080/entries?limit=20'
# {"entries":[ ... ]}
```

### Analyze an entry

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

Every stored `category` uses the shared `fr_l2_taxonomy_v1` taxonomy —
`vocabulary`, `grammar`, `morphology`, `orthography`, `pronunciation`,
`pragmatics`, `discourse`, `comprehension`, `translation`, `mixed`, `other` —
regardless of which analyzer produced it. The database never holds
provider-specific category systems. Output whose category falls outside the
taxonomy is rejected with `422` and never stored.

The `analyzer` field records provenance: `rule-based:v2:fr_l2_taxonomy_v1` for
the local rule engine (`rule-based:<ruleset-version>:<taxonomy-version>`), or
`openai:<model>:fr_l2_taxonomy_v1` when the OpenAI provider is enabled. The
ruleset version is bumped when the local rules change materially, so analyses
produced before and after such a change remain distinguishable; historical
records are never rewritten.

Analyzing the same entry again appends `version: 2`, and so on. A missing entry
returns `404`; metadata that fails validation returns `422`. When the OpenAI
provider is enabled, a provider timeout returns `504` and other provider
failures return `502`; in both cases no analysis is stored.

### List analyses for an entry (oldest version first)

```bash
curl localhost:8080/entries/1/analyses
# {"analyses":[ ... ]}
```

### Add feedback to an analysis

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

### List feedback for an analysis (oldest first)

```bash
curl localhost:8080/analyses/1/feedback
# {"feedback":[ ... ]}
```

### Get the effective analysis

Computes the *current interpretation* of an analysis by combining the immutable
analysis with its feedback history, and returns it. This is a read-only
projection: nothing is stored, and neither the analysis nor its feedback is
modified. The result is recalculated on every request, so it always reflects the
latest feedback.

```bash
curl localhost:8080/analyses/1/effective
```

Only the **latest** feedback (by `created_at`, then `id`) decides the outcome.
The response `resolution` is one of four states:

- **`unreviewed`** — no feedback exists. The effective values equal the original
  analysis and `feedback_id` is `null`.
- **`accepted`** — the latest feedback accepted the analysis. The effective
  values equal the original.
- **`corrected`** — the latest feedback corrected the analysis. Present
  corrected fields override the original; absent corrected fields retain the
  original value. Corrected categories use the shared `fr_l2_taxonomy_v1`
  taxonomy.
- **`rejected`** — the latest feedback rejected the analysis. There is no
  effective interpretation, so `effective` is `null` (the original is still
  returned for reference).

An earlier accepted or corrected record does not resurface after a later
rejection: resolution never falls back to older feedback.

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

### Learning inventory

The inventory is a **read-only, cross-entry view**. For each learning entry it
selects that entry's latest analysis (highest `version`, then highest `id`) and
that analysis's latest feedback (latest `created_at`, then highest `id`), then
derives a single current row. It stores nothing new, mutates no record, and
performs **no AI call**. It is a queryable inventory, not a chatbot, a learning
map, or a review scheduler.

Each record carries the original entry data, the latest-analysis metadata
(`null` for an unanalyzed entry), a `state`, the `original` analysis values, the
`effective` interpretation (which includes human corrections), and the resolving
`feedback_id`. The `state` is one of:

- **`unanalyzed`** — the entry has no analysis. Analysis fields, `original`, and
  `effective` are all `null`.
- **`unreviewed`** — the latest analysis has no feedback. `effective` equals
  `original`.
- **`accepted`** — the latest feedback accepted the analysis. `effective` equals
  `original`.
- **`corrected`** — the latest feedback corrected it. `effective` reflects the
  human corrections; `original` is preserved unchanged.
- **`rejected`** — the latest feedback rejected it. `effective` is `null` (the
  original is still shown for reference).

`effective` reflects the current interpretation *including human corrections*,
while `original` always shows the analysis exactly as the analyzer produced it.

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

### Structured learning capture import

`POST /captures` ingests one **`learning_capture_v1`** document: a structured
handoff of a French discussion the user already had elsewhere. It is the stable
public contract for getting an external discussion into the learning inventory
without the backend acting as a chatbot.

**This endpoint makes no AI call.** It does not contact ChatGPT or any model,
does not scrape or store a conversation transcript, and does not parse HTML or
Markdown. It only accepts the structured fields below and persists them.

The client supplies **only** learning content. Database ids, analysis version,
timestamps, analyzer provenance, feedback status, and effective resolution are
never accepted from the client — they are derived by the server. Unknown JSON
fields are rejected at every level (top level and inside `analysis`).

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

#### Idempotency and conflicts

Imports are idempotent by `capture_id`, decided by a deterministic fingerprint
over the **normalized** capture content (never over the raw JSON bytes, and
never including ids or timestamps):

- **New `capture_id`** → `201 Created`, `created: true`.
- **Same `capture_id`, same content** → `200 OK`, `created: false`, returning the
  existing ids. No new rows are written, so a retried or duplicated submission is
  safe.
- **Same `capture_id`, different content** → `409 Conflict`. The existing capture
  is never modified.

Concurrent submissions of the same `capture_id` resolve to exactly one stored
entry; the uniqueness constraint is the source of truth, so a race cannot create
duplicates.

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

#### How imported records behave in the rest of the system

An imported analysis is an ordinary version-1 analysis, distinguished only by its
provenance string. It participates in every existing feature with no special
casing:

- It appears in the learning inventory. With an analysis the state is
  `unreviewed` and `effective` equals `original`; without one it is
  `unanalyzed`.
- Human feedback works normally: accepting keeps it, correcting changes the
  effective category/explanation, rejecting removes the effective interpretation.
- The inventory `category` filter matches the **effective** category, so a
  corrected import is found under its new category and a rejected import matches
  none.
- Later analyses of the same entry continue as version 2, 3, and so on.

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

### Knowledge extraction (milestone 10)

Knowledge extraction turns one learning interaction into zero or more durable,
atomic **knowledge units**. A knowledge unit is *a learning objective that
actually arose from this interaction and can later be independently judged or
reviewed* — not every linguistic fact discoverable in the text. **Zero units is
a valid result**: the extractor answers "what did the learner actually learn,
ask about, correct, or reveal uncertainty about?", and is instructed never to
manufacture units just to avoid an empty answer.

**Extraction source.** Each extraction reads BOTH the immutable original entry
and its current *effective* interpretation (the latest analysis combined with its
latest feedback). It never extracts from the entry alone or the analysis alone.

**Eligibility is explicit** and never automatic. Extraction runs only when you
call the endpoint below — never as a side effect of creating an entry, an
analysis, feedback, or a capture. An entry is eligible only when its current
analysis resolves to `unreviewed`, `accepted`, or `corrected`. An `unanalyzed`
entry, or one whose current analysis is `rejected`, is **not eligible** (`409`).
For a `corrected` analysis the corrected effective values are used; for
`accepted`/`unreviewed` the current effective values are used.

**Versioning and provenance.** Each run is an immutable, per-entry versioned
`KnowledgeExtraction` recording the exact analysis (and feedback, if any) it was
derived from. A later analysis or feedback never mutates an existing extraction;
re-running appends a new version. There is no staleness feature in this
milestone and no mutable `stale` flag; the recorded provenance is **sufficient
to derive staleness later** by comparing it to the entry's current effective
interpretation, but nothing here computes or exposes such a signal yet.

**Knowledge kinds** use a dedicated v1 vocabulary (`fr_l2_knowledge_v1`),
distinct from the interaction taxonomy: `vocabulary`, `grammar`, `morphology`,
`orthography`, `pronunciation`, `usage`, `expression`.

**Extractor configuration.** Only one real, semantic extractor ships: the OpenAI
extractor. It is opt-in and off by default (`EXTRACTOR_PROVIDER=disabled`). When
disabled, the server runs normally and the extraction endpoint returns `503`
(no silent fallback). There is no rule-based extractor.

```bash
# Enable knowledge extraction (independent of AI_PROVIDER):
export EXTRACTOR_PROVIDER=openai
export OPENAI_API_KEY=sk-your-key-here
export OPENAI_MODEL=gpt-4o-mini
go run ./cmd/server
```

Provenance is stored as `openai:<model>:knowledge_extraction_v1`.

**Fixed admission ruleset (`knowledge_admission_v1`).** When units are persisted,
a fixed, conservative ruleset produces one machine recommendation per unit —
`active`, `suppressed`, or `needs_review`. It does not learn or rewrite itself.
A valid unit defaults to `active`. An **exact duplicate** (same kind + normalized
canonical, where normalization is trim + lowercase + collapse-whitespace, accents
preserved — no embeddings, stemming, or semantic similarity) of an earlier unit
in the same extraction is `suppressed` with reason `exact_duplicate`; the unit
still exists historically. A unit below the conservative confidence threshold is
routed to `needs_review` rather than suppressed. The threshold is a documented
heuristic, not a calibrated probability.

**Human authority over admission.** The ruleset only *recommends*. A human may
append an admission override (`active` or `suppressed`, with a suppression reason
of `mastered`, `ignored`, or `other`). Overrides are **append-only** and never
mutate or delete the machine recommendation; the full history is preserved. When
deriving the effective admission state, the latest human override wins.

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
| Invalid extractor output / invalid override     | `422`  |
| Extractor disabled                              | `503`  |
| Provider timeout                                | `504`  |
| Provider unavailable / invalid provider output  | `502`  |
| Unexpected storage failure                      | `500`  |

On any failure, no partial extraction is persisted (extraction, all units, and
their machine recommendations commit atomically or not at all). Errors use the
shared `{"error":"..."}` shape and never expose API keys, authorization headers,
full provider bodies, or original learning content.

### Concept Annotation Dataset v1 (milestone 11-C)

The backend exposes the collected Concept annotations as a stable, read-only
current snapshot:

```bash
# Versioned JSON envelope.
curl -sS http://localhost:8080/annotation-dataset/v1

# The same ordered records as newline-delimited JSON.
curl -sS http://localhost:8080/annotation-dataset/v1/export
```

Both endpoints use schema version `concept_annotation_dataset_v1` and consume the
M11-A effective annotation projection; they do not reconstruct authority from raw
history. Version 1 includes every unit from each entry's CURRENT extraction,
including suppressed and needs-review admission states, while excluding historical
extraction units. Each record preserves immutable unit evidence, entry/extraction
provenance, current admission state, effective annotation provenance, and snapshots
of every referenced durable Concept identity.

The `human_labels` section is deliberately narrower than effective system state.
A human CURRENT SAME, explicit human DISTINCT, human relation, or human INVALID
judgment is preserved as its own label; a `resolver:automatic` CURRENT SAME may be
effectively resolved but is not emitted as human SAME gold. DISTINCT remains
negative identity evidence, BROADER/NARROWER/RELATED remain relations, and INVALID
remains unit-level exclusion evidence.

Dataset v1 performs no mutation or AI call and does not decide final training
eligibility, create splits, compute metrics, train a model, or implement candidate
retrieval.

### Dataset Validation & Quality Report v1 (milestone 11-D)

The backend validates and describes the M11-C application representation through
one read-only endpoint:

```bash
curl -sS http://localhost:8080/annotation-dataset/v1/quality
```

The response schema is `concept_annotation_quality_report_v1`; its
`dataset_schema_version` is `concept_annotation_dataset_v1`. The report consumes
M11-C's `ListV1` boundary only. It does not read SQLite annotation history or
recompute CURRENT SAME, INVALID, DISTINCT, or relation authority.

The report checks record/source/extraction consistency, effective-state and
human-label projections, Concept snapshot identity fields, contradictions, and
active-unit Concept support. `valid` means there are no structural validation
errors. Conservative warnings—currently a human label on non-active admission and
a human CURRENT SAME to a retired Concept—do not make the report invalid and do
not discard or rewrite a label. A structurally invalid dataset is therefore still
reported with HTTP `200`; HTTP `500` is reserved for a report build failure.

Alongside stable, deterministically ordered issues, the report exposes effective
status/admission/authority counts, an explicit human-label inventory that keeps
human and automatic SAME separate, sorted extractor/Concept-schema/resolver
provenance distributions, and grouping statistics that quantify entry- and
Concept-level leakage risk. It deliberately does not declare universal training
eligibility, generate train/test splits, compute retrieval metrics, train a model,
or implement retrieval.

### Retrieval Evaluation Foundation v1 (milestone 12-A)

M12-A measures whether a retrieval-only baseline can place the current explicit
human SAME target in the top candidate ranks:

```bash
curl -sS http://localhost:8080/retrieval-evaluation/v1
```

The report uses schema `concept_retrieval_evaluation_v1`, policy
`concept_retrieval_eval_policy_v1`, and retriever
`exact_signature_retriever_v1`. Human ground truth comes only from M11-C's
effective CURRENT human SAME and matching `human_labels.same`; automatic SAME is
never evaluation gold. M11-D runs first, and a structurally invalid dataset
returns HTTP `200` with `state: "blocked_invalid_dataset"`, null metrics, and no
samples. Quality warnings do not block evaluation.

A human `seed_unit_same` created by NEW CONCEPT is excluded because that Concept
did not exist when retrieval for its seed Unit would have run. Ordinary
`human_same` and corrective `human_same_correction` decisions to an existing
Concept may be eligible. The remaining exclusion precedence is malformed or
unknown SAME provenance, seed creation, non-active admission, retired target,
then target missing from the current catalog; each human SAME record is counted
once.

Version 1 evaluates eligible Units against the CURRENT Concept catalog, sorted by
Concept ID. Retired Concepts are excluded; normal supported and normal orphaned
Concepts remain candidates. This intentionally does not reconstruct a historical
catalog, so Concepts created later can be additional current competitors.

The exact baseline returns only a complete candidate-identity signature match,
with score `1.0`; it has no fuzzy, token, or semantic behavior. A human SAME whose
Unit wording produces a different signature is therefore an expected baseline
miss, not an error. The report computes Recall@1, Recall@3, Recall@5, and MRR for
one positive target per eligible sample and exposes the query, target, ranked
candidates, target rank, reciprocal rank, and hit flags for audit. When there are
no eligible samples all metrics are `null`, distinguishing no data from measured
zero performance.

Retrieval output creates no annotation authority and is never persisted.

### Weighted Lexical Ranked Retriever v1 (milestone 12-B)

M12-B reuses the exact M12-A schema, policy, quality gate, eligibility rules,
current non-retired candidate universe, max K of five, and Recall/MRR definitions.
Only the selected retrieval algorithm and its ranked output change. The endpoint
keeps exact retrieval as its backward-compatible default and accepts each
registered retriever explicitly (the BM25 option is described under M12-C):

```bash
curl -sS http://localhost:8080/retrieval-evaluation/v1
curl -sS 'http://localhost:8080/retrieval-evaluation/v1?retriever=exact_signature_retriever_v1'
curl -sS 'http://localhost:8080/retrieval-evaluation/v1?retriever=weighted_lexical_retriever_v1'
curl -sS 'http://localhost:8080/retrieval-evaluation/v1?retriever=bm25_retriever_v1'
```

An unknown retriever returns HTTP `400` with `{"error":"unknown retriever"}`.
Selection is owned by an application-level registry; HTTP only reads and passes
the name.

`weighted_lexical_retriever_v1` is a deterministic weighted bag-of-words
baseline. Normalization version `concept_lexical_normalization_v1` performs
Unicode lowercase and canonical decomposition, removes combining diacritics,
uses punctuation and separators as token boundaries, and discards empty and
one-rune tokens. It deliberately has no French stop-word list and performs no
stemming or lemmatization. Tokens are deduplicated within each field; the same
token can accumulate weight across distinct fields.

| Representation | Field | Weight |
| --- | --- | ---: |
| Unit query | canonical | 4.0 |
| Unit query | statement | 2.0 |
| Unit query | candidate intent, scope, feature keys, feature values | 1.0 each |
| Concept document | target | 4.0 |
| Concept document | intent, scope, feature keys, feature values | 1.0 each |

Candidate-identity target is not separately added to a Unit query because it is
derived from canonical evidence. Concept lifecycle, support, and state are not
lexical content. The retriever scores every current non-retired Concept using
weighted cosine similarity, returns only positive-overlap results, sorts by score
descending then Concept ID ascending, and truncates to the requested limit. A
score is a length-normalized lexical similarity—not a calibrated probability and
not proof of SAME. Candidate evidence is stable JSON naming the reason,
normalization version, and unique lexicographically sorted matched tokens.

Cosine is used here because it is transparent, deterministic, requires no corpus
statistics or training, and prevents longer fields from winning merely because
they contain more words. Exact signatures receive no special boost in this
retriever, preserving a fair comparison with `exact_signature_retriever_v1`.
The M12-B algorithm itself still has no IDF, TF-IDF, or BM25 behavior. Across the
retrieval experiment there is still no inverted index, SQLite FTS, vector
database, fuzzy edit matching, reranking, automatic label, persistence,
migration, or frontend change. M12-D adds a separate embedding baseline below;
it does not change the M12-B algorithm.

### Corpus-aware BM25 Ranked Retriever v1 (milestone 12-C)

M12-C adds `bm25_retriever_v1` to the same application registry and shared
endpoint. The empty selector remains `exact_signature_retriever_v1`; an unknown
name still returns HTTP `400`. M12-A is therefore the exact-identity baseline,
M12-B is the corpus-independent weighted lexical cosine baseline, and M12-C is
the corpus-aware lexical baseline.

BM25 reuses `concept_lexical_normalization_v1` and the same lexical fields and
fixed field weights as M12-B, but it deliberately preserves raw token frequency
within fields. Candidate-identity target is still omitted from the query because
canonical is the primary Unit evidence. Concept lifecycle, support, effective
state, human labels, target rank, and evaluation outcome never enter scoring.

| Representation | Field | Weight |
| --- | --- | ---: |
| Unit query | canonical | 4.0 |
| Unit query | statement | 2.0 |
| Unit query | candidate intent, scope, feature keys, feature values | 1.0 each |
| Concept document | target | 4.0 |
| Concept document | intent, scope, feature keys, feature values | 1.0 each |

For every retrieval call, the retriever builds statistics only from the supplied
Concept documents. Let `q_w(t)` be raw query term frequency multiplied and summed
by query field weight, `tf_w(t,D)` the corresponding weighted document frequency,
and `|D|_w` the total weighted normalized-token count. With `N` supplied documents,
`df(t)` documents containing `t`, and `avgdl_w` the average `|D|_w`, v1 uses:

```text
IDF(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))

score(D,Q) = Σ[t in Q] q_w(t) * IDF(t) *
             tf_w(t,D) * (k1 + 1)
             -----------------------------------------------
             tf_w(t,D) + k1 * (1 - b + b * |D|_w / avgdl_w)
```

The fixed, untuned v1 parameters are `k1=1.2` (term-frequency saturation) and
`b=0.75` (document-length normalization). This is a simple field-weighted BM25
variant, not full per-field-normalized BM25F: fields are explicitly combined into
one weighted query/document representation before BM25 saturation and length
normalization. Corpus-derived IDF makes rare terms more discriminative than common
terms, repeated document terms help with diminishing returns, and the `b` term
prevents longer Concept text from winning solely by containing more tokens.

Only positive finite scores are returned. Results sort by score descending and
Concept ID ascending, receive one-based ranks, and respect the requested limit.
Stable JSON evidence records `reason: "bm25"`, normalization and parameters,
corpus/document lengths, sorted unique matched tokens, and sorted compact
per-token contributions. The score is lexical relevance, not a probability or
proof of SAME.

All corpus statistics are recalculated in memory from the evaluation service's
current non-retired Concept universe. Exact, cosine, and BM25 evaluations retain
the identical M11-D gate, M11-C CURRENT human-SAME truth, provenance and admission
exclusions, seed-unit leakage exclusion, candidate universe, eligible samples,
targets, ordering, maximum K, and Recall/MRR definitions. Only retriever-owned
ranking output and resulting metrics may differ. M12-C adds no persistence,
migration, index, cache, SQLite FTS, annotation authority, Concept resolution,
or frontend behavior. Its BM25 algorithm has no embedding/model/provider behavior;
M12-D adds that separate baseline below.

### Semantic Embedding Ranked Retriever v1 (milestone 12-D)

M12-D completes the current baseline sequence:

```text
M12-A = exact identity retrieval
M12-B = weighted lexical cosine retrieval
M12-C = corpus-aware BM25 lexical retrieval
M12-D = semantic embedding retrieval
```

`embedding_retriever_v1` implements the unchanged `ConceptRetriever` contract and
depends on one batch-oriented application interface:

```go
type EmbeddingProvider interface {
    Name() string
    Embed(ctx context.Context, texts []string) ([][]float64, error)
}
```

The retriever owns semantic text construction, vector validation, cosine ranking,
evidence, limits, and stable ordering. The provider owns only text-to-vector
inference plus provider/model provenance. It receives one combined batch in the
deterministic order `query, Concept documents...`; there is no per-Concept remote
call. The provider cannot read repositories, SQLite, annotation history,
lifecycle policy, human labels, targets, or metrics.

The versioned `concept_embedding_text_v1` representation is compact deterministic
JSON. Query text includes canonical, statement, nullable example, candidate-
identity target, pedagogical intent, scope, and identity-feature key/value pairs.
Concept text includes target, pedagogical intent, scope, and feature pairs.
Feature keys sort lexicographically before serialization. IDs, signatures,
identity-schema version, lifecycle/support/effective state, human SAME/DISTINCT,
annotation reason, target rank, hits, and metrics are excluded. Thus the query is
constructed only from Unit/query evidence and documents only from Concept
representation; evaluation truth is unavailable during embedding and ranking.

Cosine similarity is computed after requiring non-empty, equal-dimensional,
finite vectors. A zero-norm vector and non-positive similarity produce no
candidate; dimension mismatch, empty vectors, non-finite values, or a wrong batch
count fail the request rather than fabricating results. Positive results sort by
score descending then Concept ID ascending, receive one-based ranks, and respect
the requested limit. The score is semantic relevance—not a calibrated probability
or proof of SAME—and there is no automatic threshold, resolution, or fallback.
Stable JSON evidence contains `reason: "embedding_cosine"`, provider/model name,
representation version, similarity, and vector dimension; raw vectors and human
labels are never exposed.

Production embedding configuration is independent of `AI_PROVIDER` and
`EXTRACTOR_PROVIDER`. With the default `EMBEDDING_PROVIDER=disabled`, the server
requires no embedding infrastructure and does not register the semantic retriever;
explicit semantic selection therefore follows the registry's existing HTTP `400`
unknown-name behavior. With `EMBEDDING_PROVIDER=http`, the registry exposes all
four retrievers while exact signature remains the empty-selector default. The
HTTP provider sends an OpenAI-compatible batch request to
`<EMBEDDING_BASE_URL>/embeddings` using `EMBEDDING_MODEL`, an optional bearer
`EMBEDDING_API_KEY`, and `EMBEDDING_TIMEOUT`. It preserves response order by the
provider's explicit indexes and returns secret-safe `504` timeout or `502`
unavailable responses without lexical/exact fallback.

Exact, weighted lexical, BM25, and embedding evaluation still share the same
M11-D gate, M11-C CURRENT explicit human-SAME truth, provenance classification,
seed/admission/retired/missing-target exclusions, current non-retired universe,
eligible Units, targets, ordering, maximum K, and Recall@1/3/5 and MRR definitions.
Only retriever/provider-owned candidates, scores, evidence/provenance, target
ranks/hits, and resulting metrics may differ. Frozen-vector tests establish this
architecture and predictable ranking; they do not claim quality for any real
embedding model.

M12-D embeds the small evaluation corpus at request time and adds no migration,
vector persistence/cache/database, ANN/HNSW/FAISS index, hybrid fusion, reranking,
cross-encoder, LLM judge, learned SAME classifier, calibrated threshold, training,
local runtime, model weights, GPU detection, or NAS inference requirement. A
remote API, rented GPU, or a service on an RTX 4070 workstation can implement the
same boundary. Local-inference optimization is deferred.

### Retrieval Baseline Comparison v1 (milestone 13-A0)

M12 builds and audits one retrieval baseline at a time. M13-A0 adds the first
experiment-analysis layer: a compact comparison of their top-level metrics under
the unchanged M12 experiment contract.

```bash
curl -sS http://localhost:8080/retrieval-comparison/v1
```

`GET /retrieval-comparison/v1` returns schema
`concept_retrieval_comparison_v1`, the shared dataset validity, candidate-universe
size, eligible-sample count, and fixed-order rows for:

```text
exact_signature_retriever_v1
weighted_lexical_retriever_v1
bm25_retriever_v1
embedding_retriever_v1
```

Each evaluated row copies `state`, Recall@1, Recall@3, Recall@5, and MRR directly
from the existing `ConceptRetrievalEvaluationService`; the comparison layer does
not compute rankings or metrics. Detailed per-sample audit output remains at
`GET /retrieval-evaluation/v1?retriever=...` and is deliberately omitted from the
compact comparison response.

The optional embedding row is never silently omitted or replaced. When production
uses the default `EMBEDDING_PROVIDER=disabled`, it appears with
`state: "unavailable"` and null metrics. When configured, it is evaluated normally;
provider timeout/unavailability still returns the existing secret-safe HTTP
`504`/`502` failure rather than a fallback result.

Before presenting metrics, M13-A0 verifies that all evaluated reports agree on
the M12 schema/policy/state, dataset validity, complete exclusion inventory,
candidate universe, ordered eligible Units, queries, target Concepts, and human
SAME provenance. A mismatch fails explicitly with HTTP `500` rather than mixing
different populations. An M11-D-invalid dataset retains the existing successful
`blocked_invalid_dataset` interpretation with null metrics, and the underlying
M12 quality gate prevents any retriever call.

M13-A0 adds no retriever, ground truth, candidate-selection rule, persistence,
migration, cache, hybrid retrieval, score fusion, reranking, statistical analysis,
chart, dashboard, annotation write, or Concept-resolution behavior.

### Experiment Dashboard v1 (milestone 13-A1)

The existing `web/` workbench now has a third local view, **Experiment
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

**Knowledge-extraction work still out of scope** (not implemented): automatic extraction on
capture/analysis/feedback, a rule-based semantic extractor, local models, model
routing or cost optimization, ruleset evolution/proposal/replay, spaced
repetition or review scheduling, mastery probability or automatic mastery
detection, CEFR or difficulty scoring, embedding-based knowledge dedup/resolution,
knowledge or prerequisite graphs, and cross-interaction normalization.

## Capture CLI (`cmd/capture`)

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

### Usage

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

### Backend URL

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

### Exit status and error handling

The CLI exits `0` on success, including an **idempotent replay**: resubmitting
the same capture prints `capture already existed (idempotent replay)` with
`created: false` and still exits `0`. It exits non-zero and prints a concise
message to stderr for a conflict (`409`, same `capture_id` with different
content — the existing capture is left untouched), a validation error
(`400`/`422`, showing the server's safe public message), or an unexpected server
error (`500`). Errors carry only the status code and the server's own message —
never your learning content, credentials, or authorization headers. The client
uses a bounded request timeout, performs no retries, and makes no AI call.

## Development

```bash
make test          # run all tests
make vet           # go vet
make fmt           # gofmt -w .
make build         # compile the server to bin/server
make build-capture # compile the capture CLI to bin/capture
```
