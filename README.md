# French Learning App

A small Go HTTP service that persistently stores French-learning questions and
their original context. The original user input is treated as the source of
truth; AI-generated metadata is stored separately as versioned analyses and
never overwrites the original record.

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
deterministic, and free of API calls (no automatic AI escalation). See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for design principles.

## Requirements

- Go 1.26+ (uses `net/http` method-based routing)
- No CGO required — SQLite is provided by the pure-Go `modernc.org/sqlite` driver.

## Layout

```
cmd/server            program entry point + graceful shutdown
internal/domain       Entry/Analysis/Feedback entities, repository + Analyzer interfaces, validation
internal/application  use cases (entry create/get/list; entry analysis; analysis feedback; effective analysis resolution)
internal/analyzer     local rule-based Analyzer + OpenAI Analyzer + named rule engine (assessment)
internal/storage/sqlite  SQLite repositories + migration runner
internal/transport/http  HTTP handlers and routing
internal/config       environment-based configuration
migrations            embedded .sql migrations
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
| `OPENAI_API_KEY`     | _(none)_                    | Required for `openai`; never logged           |
| `OPENAI_MODEL`       | _(none)_                    | Required for `openai`; the model to use       |
| `OPENAI_BASE_URL`    | `https://api.openai.com/v1` | API base URL (override for gateways/testing)  |
| `OPENAI_TIMEOUT`     | `8`                         | Per-request provider timeout (seconds)        |

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

## Development

```bash
make test    # run all tests
make vet     # go vet
make fmt     # gofmt -w .
make build   # compile to bin/server
```
