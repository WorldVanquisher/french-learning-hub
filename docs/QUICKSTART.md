# Quick start

This guide takes a fresh checkout from local startup to the current v1.0
workflows. The default configuration is useful without an API key: it runs the
Go service, SQLite persistence, the local rule-based analyzer, the capture CLI,
read-only inventory views, and the annotation/retrieval reports that can be
derived from data already in the database.

## Prerequisites

- Go 1.26.5, as declared by `go.mod`.
- Node.js and npm for the `web/` workbench. The project does not declare a
  minimum Node version; CI currently uses Node 22.
- `curl` for the HTTP examples.

SQLite is embedded through the pure-Go `modernc.org/sqlite` driver. No SQLite
server and no CGO toolchain are required.

Clone the repository with your normal Git workflow, or enter an existing
checkout:

```bash
git clone https://github.com/WorldVanquisher/french-learning-hub.git
cd french-learning-hub
```

Install the locked frontend dependencies once:

```bash
cd web
npm ci
cd ..
```

Run the same important checks used for release verification:

```bash
make verify
```

`make verify` checks Go formatting without rewriting files, runs all Go tests
and `go vet`, builds the server and capture CLI in a temporary directory, then
runs frontend typechecking, unit tests, and the production build. It does not
install dependencies; run `npm ci` first as shown above.

## Start the backend

From the repository root:

```bash
make run
```

The first run creates `data/app.db` and applies the embedded migrations. The
server listens on `http://localhost:8080` by default. In another terminal:

```bash
curl -sS http://localhost:8080/healthz
```

The response is:

```json
{"status":"ok"}
```

## Create and analyze an Entry

Create an Entry containing only learner-authored source data:

```bash
curl -sS -X POST http://localhost:8080/entries \
  -H 'Content-Type: application/json' \
  -d '{"original_input":"Pourquoi dit-on je vais ?","original_context":"Étude du verbe aller au présent."}'
```

Use the returned `id` in the next request. With the default
`AI_PROVIDER=rule-based`, analysis is deterministic, local, and makes no
external API call:

```bash
curl -sS -X POST http://localhost:8080/entries/1/analysis
curl -sS 'http://localhost:8080/learning-records?limit=20'
```

Analysis is versioned metadata; it never overwrites the Entry. The learning
inventory is a read-only projection over Entries, their latest Analysis, and
latest Feedback.

Alternatively, import the maintained example through the thin capture CLI:

```bash
make capture ARGS="-file examples/captures/manual-example.json"
```

The CLI sends the prepared `learning_capture_v1` document unchanged. Repeating
the same capture is an idempotent replay, not a duplicate import.

## Optional knowledge and research path

Knowledge extraction is intentionally provider-backed and disabled by default.
To continue an analyzed Entry into the Concept workflow, configure the existing
extractor adapter with placeholder values and restart the backend:

```bash
export EXTRACTOR_PROVIDER=openai
export OPENAI_API_KEY=replace-with-your-key
export OPENAI_MODEL=replace-with-your-model
make run
```

Then explicitly start an extraction, using the real Entry ID:

```bash
curl -sS -X POST http://localhost:8080/entries/1/extractions
```

There is no rule-based extractor and no manual extraction-import shortcut. A
human must review the resulting units and record Concept decisions before the
annotation dataset has human retrieval truth.

## Start the workbench

Keep the backend running and start the frontend in a second terminal:

```bash
cd web
npm run dev
```

Open `http://localhost:5173` (or the URL printed by Vite). The workbench has
three views with different ownership boundaries:

- **Concept Review** is write-capable: explicit human actions record Concept
  annotations and resolution decisions.
- **Annotation Inspector** is read-only and displays backend-owned effective
  annotation state.
- **Experiment Dashboard** is read-only and displays backend-owned dataset
  quality and retrieval-comparison results. It computes no metrics in the
  browser.

## Inspect quality and retrieval reports

The same reports used by the dashboard are available directly:

```bash
curl -sS http://localhost:8080/annotation-dataset/v1/quality
curl -sS http://localhost:8080/retrieval-comparison/v1
```

A fresh default database has no extracted KnowledgeUnits, human Concept
annotations, or retrieval ground truth. It therefore cannot jump directly from
one Entry to meaningful Concept/retrieval experiments: extraction must be
explicitly enabled and run, then Concept decisions must be recorded by a human.
Empty or null report metrics in that state are expected.

`EXTRACTOR_PROVIDER=disabled` is the default, so knowledge-extraction requests
are unavailable until an extractor is configured. Likewise,
`EMBEDDING_PROVIDER=disabled` leaves the optional semantic retriever
unregistered; the comparison report represents it as an explicit `unavailable`
row. That row is not a server failure. Exact-signature, weighted lexical, and
BM25 baselines remain available without an embedding provider.

Retrieval evaluation uses the **current non-retired Concept catalog**, not a
historically reconstructed catalog. All retrievers share the same evaluation
population and human-SAME truth, but the semantic baseline is not a perfectly
evidence-matched scorer-only ablation: `concept_embedding_text_v1` includes the
query example and candidate-identity target, while the lexical/BM25 query
representation does not. Interpret comparisons with that limitation in mind.

## Optional providers

Provider configuration is optional for the default workflow. Use
[`.env.example`](../.env.example) as the authoritative variable reference and
replace every placeholder with your own value. The service reads process
environment variables; it does not automatically load a `.env` file.

For example, the Analyzer can remain local while knowledge extraction uses the
OpenAI adapter:

```bash
export AI_PROVIDER=rule-based
export EXTRACTOR_PROVIDER=openai
export OPENAI_API_KEY=replace-with-your-key
export OPENAI_MODEL=replace-with-your-model
make run
```

Embedding configuration is independent of Analyzer and Extractor configuration.
There is no silent provider or retriever fallback. Never commit credentials or
paste them into learning payloads.

## Next references

- [README](../README.md) — capabilities, API examples, and milestone history
- [中文 README](../README.zh-CN.md) — maintained Simplified Chinese companion
- [Architecture](ARCHITECTURE.md) — ownership boundaries and workflow details
- [Workbench guide](../web/README.md) — frontend behavior and annotation semantics
