# French Learning Hub

[简体中文](README.zh-CN.md)

A local-first Go, SQLite and React service that keeps French-learning questions
as traceable records. Each record can then be interpreted, corrected by a human,
broken into reviewable knowledge units, and organized into durable concepts that
you can search and trace back to the original question.

## The problem

Questions asked while learning a language — in class, in a journal, or in a chat
with an AI assistant — tend to disappear inside individual conversations. Even
when they are saved, a machine's explanation is easily mistaken for the
learner's own record, a later correction silently replaces an earlier answer,
and nobody can tell which piece of evidence supports which learned idea.

French Learning Hub treats the learner's original words as the source of truth
and stores everything said about them — analyses, human corrections, extracted
knowledge units and concept decisions — as separate, versioned or append-only
records. Current state is derived from that history instead of overwriting it.

## How it works

```text
learner question (typed, or imported from a prepared capture document)
  -> Entry                    the learner's original input and context, never rewritten
  -> Analysis (versioned)     local rule-based by default, OpenAI optional
  -> Feedback (append-only)   accept / correct / reject; the effective view is derived
  -> Knowledge extraction     explicit, provider-backed; produces immutable units
  -> Concept Review           a human files units under durable Concepts
  -> Knowledge Library        search Concepts and trace each one back to its source
  -> Dataset and retrieval reports (read-only research instruments)
```

Two distinctions run through the whole system:

- **Evidence versus identity.** An extracted unit is immutable evidence from one
  extraction; a Concept is the durable learning identity. Re-extracting a record
  creates new units without rewriting old ones.
- **Membership versus support.** A unit can be *filed under* a Concept (its
  current SAME membership) without *supporting* it: support also requires the
  unit to come from its record's current extraction and not to be hidden by the
  learner. Support is derived when read, never stored.

The full explanation is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Current capabilities

- Store learning **Entries** and append versioned **Analyses** from a local,
  deterministic rule-based analyzer (no API key) or an opt-in OpenAI analyzer.
- Record immutable human **Feedback** and read the derived effective
  interpretation and a cross-entry **learning inventory** with JSONL export.
- Import prepared `learning_capture_v1` documents idempotently, through the API,
  the workbench or the `cmd/capture` CLI. Capture never calls a model.
- Run explicit **knowledge extraction** (OpenAI adapter, disabled by default)
  with a fixed admission ruleset and append-only human overrides.
- Review units in the **Concept Review** workbench: SAME, NEW CONCEPT, BROADER,
  NARROWER, RELATED, DISTINCT and INVALID decisions, with append-only history,
  explicit corrections, and idempotent recovery for lost DISTINCT and relation
  responses.
- Search and browse curated Concepts in the read-only **Knowledge Library**,
  with plain-English status and links from each unit to the record and the exact
  interpretation it came from.
- Inspect effective annotations, export the versioned Concept Annotation
  Dataset v1, check its quality report, and compare exact, weighted lexical,
  BM25 and optional embedding retrieval baselines under one evaluation
  population.
- Package the server and built workbench as one Docker image with health and
  readiness checks and documented backup, restore and upgrade procedures.

## What it is not

It is a single-user learning-data service and research instrument. It is not a
chatbot, a consumer course, a spaced-repetition scheduler or mastery tracker, or
an automatic ML resolver. There is no authentication: run it on localhost or a
trusted network only. Knowledge extraction and the semantic retriever need an
external provider that you configure; there is no rule-based extractor and no
silent fallback. Library search is keyword prefix matching, not semantic search.
See [what is deliberately not built](docs/ARCHITECTURE.md#12-deliberately-not-built).

## Prerequisites

- Go 1.26.5, as declared by `go.mod`. SQLite is embedded through the pure-Go
  `modernc.org/sqlite` driver, so no SQLite server or CGO toolchain is needed.
- Node.js and npm for the `web/` workbench. No minimum version is declared; CI
  uses Node 22.
- `curl` for the HTTP examples, and Python 3 for the synthetic demo.
- Docker with Compose only for the packaged release.

## Quick start

```bash
cd web && npm ci && cd ..   # install locked frontend dependencies once
make verify                 # formatting, Go tests and vet, builds, frontend checks
make run                    # API on http://localhost:8080, database data/app.db
```

In a second terminal:

```bash
curl -sS http://localhost:8080/healthz
curl -sS -X POST http://localhost:8080/entries \
  -H 'Content-Type: application/json' \
  -d '{"original_input":"Pourquoi dit-on je vais ?","original_context":"Étude du verbe aller."}'
curl -sS -X POST http://localhost:8080/entries/1/analysis
make capture ARGS="-file examples/captures/manual-example.json"
```

Start the workbench with `cd web && npm run dev` and open
`http://localhost:5173`. [docs/QUICKSTART.md](docs/QUICKSTART.md) walks through
the complete first run, including optional providers and why research reports
are empty on a fresh database.

## Two-minute synthetic demo

The Knowledge Library demo builds the server, starts it on loopback with a fresh
isolated database, and seeds four synthetic learning records and seven Concepts
through the public API. It uses the local analyzer and a local stub extractor:
no API key, paid provider or personal database is involved.

```bash
npm --prefix web ci && npm --prefix web run build
WORK=$(mktemp -d)/flh034-demo
sh scripts/demo/flh034/demo.sh setup "$WORK" "$PWD/web/dist"
# open http://127.0.0.1:18934/ and follow docs/DEMO.md
sh scripts/demo/flh034/demo.sh cleanup "$WORK"
```

The walkthrough, fixture contents, restart behaviour and supported platforms
(Linux and macOS) are in [docs/DEMO.md](docs/DEMO.md). Setup is preparation and
is not part of the two-minute presentation.

## Personal-use release

`Dockerfile` and `compose.yaml` package the API and the built workbench into
one image, published on `http://127.0.0.1:8080` only, with SQLite in
`./data/release`:

```bash
mkdir -p data/release
docker compose up -d --build   # wait for "(healthy)" in: docker compose ps
docker compose stop
```

Your existing `data/app.db` is not moved automatically. Back up only while the
service is stopped, restore through a staging directory, and back up before
every upgrade: migrations are forward-only and an older image must not run on a
newer database. The exact procedures are in [docs/RELEASE.md](docs/RELEASE.md).

## Configuration defaults

The server reads the process environment and an optional untracked `.env` file
in its working directory; the process environment wins. The defaults need no
credentials:

| Variable | Default | Meaning |
| --- | --- | --- |
| `PORT` | `8080` | HTTP port |
| `LISTEN_HOST` | empty (all interfaces) | Optional IP literal to bind, e.g. `127.0.0.1` |
| `DB_PATH` | `data/app.db` | SQLite database file |
| `AI_PROVIDER` | `rule-based` | Analyzer: `rule-based` or `openai` |
| `EXTRACTOR_PROVIDER` | `disabled` | Knowledge extractor: `disabled` or `openai` |
| `EMBEDDING_PROVIDER` | `disabled` | Semantic retriever: `disabled` or `http` |
| `HTTP_ALLOWED_HOSTS` | loopback names only | Extra exact Host names or IPs to accept |
| `HTTP_TRUSTED_ORIGINS` | Vite dev origins on port 5173 | Browser origins allowed to send mutations |

Provider settings (`OPENAI_*`, `EMBEDDING_*`) and timeouts are listed in
[`.env.example`](.env.example) and explained in
[ARCHITECTURE §10.2](docs/ARCHITECTURE.md#102-configuration). Invalid
configuration stops startup; nothing falls back silently. Never commit
credentials.

## Project status

The service, workbench and packaging described above are implemented in this
repository. Dated validation reports in [docs/validation/](docs/validation/)
record what was checked, by whom and with which limits — for example release
acceptance on Docker, browser acceptance of the workbench, a lost-response
investigation for annotation writes, and Knowledge Library acceptance on Linux
and in a real browser on macOS. Reports distinguish author verification from
independent review; a passing report is not a claim about every environment.
The development history, organized by theme and linked to that evidence, is in
[docs/history/](docs/history/README.md).

## Documentation

| Document | Use it for |
| --- | --- |
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | First run from a fresh checkout |
| [docs/DEMO.md](docs/DEMO.md) | The synthetic Knowledge Library demo |
| [docs/RELEASE.md](docs/RELEASE.md) | Docker release, backup, restore, upgrades, browser boundary settings |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the system works, with the HTTP API reference in Appendix A |
| [web/README.md](web/README.md) | Workbench views and annotation behaviour |
| [docs/LOCAL_LEARNING_WORKFLOW.zh-CN.md](docs/LOCAL_LEARNING_WORKFLOW.zh-CN.md) | Reusable local learning loop (Simplified Chinese), with the [capture prompt](docs/CAPTURE_PROMPT.zh-CN.md) |
| [docs/history/](docs/history/README.md) | How the design evolved, with dates and evidence |
| [docs/blog/](docs/blog/README.md) | Retrospective article drafts |
| [docs/plans/](docs/plans/), [docs/validation/](docs/validation/) | Original task contracts and validation reports |
| [AGENTS.md](AGENTS.md) | Instructions for coding agents working in this repository |

## Repository layout

```text
cmd/server, cmd/capture    server entry point; thin capture CLI
internal/                  domain, application, storage/sqlite, transport/http,
                           analyzer, extractor, embedding, config, captureclient
migrations/                embedded, forward-only SQL migrations
web/                       React + Vite + TypeScript workbench
examples/captures/         example learning_capture_v1 documents
captures/, seed_demo.py    16 synthetic captures and an importer that posts them
                           to a running backend you choose (it writes data)
scripts/demo/flh034/       synthetic Knowledge Library demo
scripts/validation/        isolated validation harnesses used by the reports
docs/                      documentation listed above
```

## Development

```bash
make test           # go test ./...
make vet            # go vet ./...
make fmt            # gofmt -w .
make build          # bin/server
make build-capture  # bin/capture
make verify         # non-mutating release check; needs web/node_modules (npm ci)
```

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 Sirui Liu. The
license covers this repository's own code and documentation; third-party
dependencies keep their own licenses.
