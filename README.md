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
analyzer can be enabled through configuration without changing any endpoint. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for design principles.

## Requirements

- Go 1.26+ (uses `net/http` method-based routing)
- No CGO required — SQLite is provided by the pure-Go `modernc.org/sqlite` driver.

## Layout

```
cmd/server            program entry point + graceful shutdown
internal/domain       Entry/Analysis/Feedback entities, repository + Analyzer interfaces, validation
internal/application  use cases (entry create/get/list; entry analysis; analysis feedback)
internal/analyzer     local rule-based Analyzer implementation
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

- **`rule-based`** (default): a local, deterministic analyzer. It calls no
  external service and costs nothing. Provenance is stored as `rule-based`.
- **`openai`** (opt-in): calls the OpenAI Responses API. **API usage is billed
  by OpenAI and is separate from any ChatGPT subscription.** Provenance is
  stored as `openai:<model>:fr_l2_taxonomy_v1` so every analysis records which
  provider, model, and taxonomy/prompt version produced it.

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
  "category": "comprehension",
  "explanation": "Rule-based classification: ...",
  "confidence": 0.8,
  "uncertainty": "Generated by a deterministic rule-based analyzer, not a language model; treat as a placeholder.",
  "analyzer": "rule-based",
  "created_at": "2026-07-27T12:00:00Z"
}
```

Every stored `category` uses the shared `fr_l2_taxonomy_v1` taxonomy —
`vocabulary`, `grammar`, `morphology`, `orthography`, `pronunciation`,
`pragmatics`, `discourse`, `comprehension`, `translation`, `mixed`, `other` —
regardless of which analyzer produced it. The database never holds
provider-specific category systems. Output whose category falls outside the
taxonomy is rejected with `422` and never stored.

The `analyzer` field records provenance: `rule-based` for the default analyzer,
or `openai:<model>:fr_l2_taxonomy_v1` when the OpenAI provider is enabled.

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
a `corrected` status with neither corrected field, over-length fields, or
corrected content on a non-corrected status) returns `422`.

### List feedback for an analysis (oldest first)

```bash
curl localhost:8080/analyses/1/feedback
# {"feedback":[ ... ]}
```

## Development

```bash
make test    # run all tests
make vet     # go vet
make fmt     # gofmt -w .
make build   # compile to bin/server
```
