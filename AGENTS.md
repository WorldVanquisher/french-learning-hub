## Project Overview

This repository contains an AI-assisted French learning application.

The application stores the user's French-learning questions and their original
context, classifies learning records, generates explanations, and creates
personalized review activities.

The current priority is to build a small working end-to-end system. Prefer
simple, testable implementations over speculative platform architecture.

## Current Stage

The application is a single Go HTTP service backed by SQLite, built up in
incremental milestones. Implemented so far:

* Persistence of learning entries (original input + context), with validation,
  timestamps, and a create/get/list workflow.
* Validated, versioned AI-generated metadata (analyses) stored separately from
  the original entry, produced by a pluggable `Analyzer`. Two implementations
  exist: a local deterministic rule-based analyzer (the default, no cost) — an
  explainable, uncertainty-aware named rule engine that reports matched rules,
  a heuristic confidence score, and an advisory `NeedsAI` signal (which never
  triggers an API call) — and an opt-in OpenAI-backed analyzer selected by
  `AI_PROVIDER`. Provenance is stored in the existing `analyzer` field, versioned
  per implementation (e.g. `rule-based:v2:fr_l2_taxonomy_v1`,
  `openai:<model>:fr_l2_taxonomy_v1`). Persisted categories use the shared
  `fr_l2_taxonomy_v1` domain taxonomy; the database never stores
  provider-specific category systems.
* Immutable human feedback and corrections attached to analyses.
* Read-only projections derived on demand from the stored records: the effective
  interpretation of a single analysis, and a cross-entry **learning inventory**
  (latest analysis + latest feedback per entry) with filtering, cursor
  pagination, an aggregate summary, and a JSONL export. These add no table or
  migration, mutate nothing, and make no AI call.
* A **structured learning capture import** (`POST /captures`, `GET
  /captures/{capture_id}`) that ingests a versioned `learning_capture_v1`
  document — a French discussion the user already had elsewhere — as a normal
  entry plus an optional version-1 analysis, in one atomic transaction. It is
  **not a chatbot** and makes **no AI call**: no model is contacted, no
  conversation is scraped, and only the structured fields are ingested. Imports
  are idempotent by a client-supplied `capture_id` (decided by a content
  fingerprint over the receipt table `learning_captures`); a differing
  resubmission conflicts rather than overwriting. Imported analyses reuse the
  shared taxonomy, the existing analysis validation, and server-constructed
  `imported:<source>:learning_capture_v1` provenance, and flow through the
  feedback, effective-resolution, and inventory features unchanged.
* A thin **capture CLI** (`cmd/capture`, backed by `internal/captureclient`)
  that reads a prepared `learning_capture_v1` document from a file or stdin and
  posts it, unchanged, to the backend's `POST /captures` endpoint over HTTP. It
  is a transport client only — **not a chatbot, analyzer, or importer that
  rewrites data**: it contacts no model, duplicates no server-side domain
  validation, and never modifies the payload. The backend URL resolves as `-url`
  flag → `FRENCH_HUB_URL` → `http://localhost:8080`. It handles the existing
  server outcomes (201 new, 200 idempotent replay as success, 409 conflict,
  400/422 validation, 500) and never leaks learning content or credentials into
  errors.
* **Knowledge extraction** (`POST /entries/{id}/extractions`, `GET
  /entries/{id}/extractions`, `GET /extractions/{id}`, plus admission endpoints
  under `/knowledge-units/{id}`) that turns one interaction into zero or more
  durable, atomic **knowledge units**. The extraction source combines BOTH the
  immutable entry and its current effective interpretation (reusing the
  effective-analysis rules); zero units is a valid result. Extraction is
  **explicit only** — never automatic — and eligible only when the current
  analysis resolves to `unreviewed`, `accepted`, or `corrected` (`unanalyzed` and
  `rejected` are not eligible). Each run is an immutable, per-entry versioned
  `KnowledgeExtraction` recording the exact analysis/feedback provenance
  (rejected before persistence if that provenance is inconsistent — a source
  analysis from another entry or feedback from another analysis); later
  analyses/feedback never mutate it. There is no `stale` flag and no staleness
  feature yet — the provenance is merely sufficient to derive staleness later.
  Kinds use a dedicated `fr_l2_knowledge_v1` vocabulary, separate from the
  interaction taxonomy. The only extractor is an opt-in OpenAI one selected by
  `EXTRACTOR_PROVIDER` (default `disabled`; independent of `AI_PROVIDER`; no
  rule-based extractor, no silent fallback — disabled returns `503`); provenance
  is `openai:<model>:knowledge_extraction_v1`. A fixed, conservative
  `knowledge_admission_v1` ruleset recommends `active`/`suppressed`/`needs_review`
  per unit (exact duplicate = same kind + normalized canonical → suppressed, not
  deleted; low confidence → needs_review; no embeddings or semantic similarity).
  Humans append immutable admission overrides that win over the machine
  recommendation. Extraction, units, and recommendations persist atomically
  (migration 005); public errors never leak keys, headers, provider bodies, or
  original content.
* **Knowledge concept resolution** (`/concepts`, `/concepts/{id}`,
  `/concepts/{id}/preferred-unit`, `/knowledge-units/{id}/concept-resolution`,
  `/knowledge-units/{id}/concept-links/same`,
  `/knowledge-units/{id}/concept-membership`,
  `/knowledge-units/{id}/concept-links/relation`, `/reviewable-units`,
  `/entries/{id}/current-extraction`) that introduces the durable learning
  identity. A **`KnowledgeUnit` is now immutable extraction evidence/candidate**
  (never deleted or rewritten); the **`KnowledgeConcept` is the durable identity**
  future review/mastery/scheduling attaches to (never a raw unit). Concept
  identity is an explicit versioned schema `fr_l2_concept_identity_v1` (`target`,
  `pedagogical_intent`, `scope`, extensible `identity_features`), compared by a
  deterministic canonical-JSON `signature`; canonical unit text is retrieval
  evidence, not identity. The v1 resolver is **conservative and deterministic**:
  automatic SAME only on an exact single signature match, `no_match` when none,
  `ambiguous` (reviewable, never force-merged) when many — **no embeddings,
  vectors, transformers, LLM fuzzy matching, semantic similarity, or learned
  P(SAME), and no automatic broader/narrower inference** (all deferred until real
  human resolution labels exist). Membership (`same`), relations
  (`broader`/`narrower`/`related`, which are **not** membership and carry no
  support), and preferred representation (explicit, must be a SAME member, never
  auto-set by accepting SAME) are independent decisions.
  **Milestone 10.5.1 (correctness patch, migration `007`)** sharpened the model:
  resolution history is a strictly **append-only event log** (a replacement is a
  *new* row with a `supersedes_link_id` back-pointer; no row is ever mutated to
  `superseded`). Each unit's single **current** SAME membership lives in a small
  mutable projection `unit_concept_memberships` (`unit_id` PK) — the current
  authority, separate from the immutable history. A human can **correct** a wrong
  SAME with `PUT /knowledge-units/{id}/concept-membership` (`ReassignSame`), moving
  the membership to another concept even when one already exists, superseding any
  prior automatic or human decision without deleting history and atomically
  clearing a now-invalid `preferred_unit_id`. **Concept support is derived at read
  time, never persisted**: computed live from current successful extraction +
  effective `active` admission + current SAME membership, so a newer extraction,
  an admission override, or a reassignment changes it immediately with no recompute
  call. Persisted `lifecycle_state` (`normal`/`retired`) is separate from derived
  support (`supported`/`orphaned`); the **effective** state is retired-wins, else
  supported→`active`, else `orphaned` (orphaned is never deleted and recovers if
  support returns). Concept **identity is not released by orphaning**: durable
  uniqueness is `(identity_schema_version, signature)` across non-retired concepts,
  so an unsupported concept still owns its signature. Create-concept + seed SAME is
  **atomic** in one repository transaction. Current extraction defaults to latest
  successful (a zero-unit success is still current; a failed run can't displace it)
  with an explicit human rollback row. Migration `006` adds `knowledge_concepts`,
  `unit_concept_links`, `entry_current_extractions`; migration `007` adds
  `unit_concept_memberships` + `supersedes_link_id`, replaces `state` with
  `lifecycle_state`, and switches the unique index to durable identity. No ML
  tables.

Inspect the repository before proposing changes; do not assume planned
directories, frameworks, services, or database schemas exist until confirmed.

M10.6:

- `web/` is a human annotation/data-collection UI, not a consumer product UI.
- `unit_concept_memberships` is the sole authority for CURRENT SAME.
- `unit_concept_links` is historical append-only resolution evidence, not current
  authority.
- Unit-level `INVALID` is stored in `unit_resolution_judgments`.
- `RejectSame` is a separate membership-level correction.
- `DISTINCT` is an explicit non-SAME identity pair stored in
  `unit_concept_distinctions`.
- `BROADER` / `NARROWER` / `RELATED` are non-membership relations.
- No ML resolver or dataset exporter exists yet.

M10.7:

- The annotation UI reads the existing `GET /concepts` catalog and performs
  deterministic client-side token search over durable Concept identity fields.
- Exact-signature resolver matches and generic catalog discovery are separate
  candidate sources. Showing, searching, selecting, or skipping a candidate has no
  annotation authority; only an explicit human action records a label.
- Discovery excludes retired concepts, keeps orphaned concepts discoverable, and
  deduplicates exact matches by Concept ID.
- Search normalization is retrieval-only and never changes Concept identity,
  signatures, stored data, SAME semantics, or current membership.
- No backend search endpoint, schema change, embedding, vector search, semantic
  similarity model, or automatic candidate label was added.

M11-A through M11-D:

- M11-A is the read-only effective annotation authority; M11-B exposes it through
  the Inspector API/UI, and neither creates annotation authority.
- M11-C exposes the versioned, current-extraction-only
  `concept_annotation_dataset_v1` JSON/NDJSON dataset. It consumes M11-A and does
  not reconstruct annotation semantics from history.
- M11-D exposes the read-only `concept_annotation_quality_report_v1` at
  `GET /annotation-dataset/v1/quality`. It consumes M11-C only, reports structural
  errors, human-supervision inventory, sorted provenance distributions, and
  grouping/leakage risk. Warnings do not invalidate the report.
- These milestones do not declare universal training eligibility, create splits,
  compute retrieval metrics, train models, or implement retrieval.

M12-A:

- `GET /retrieval-evaluation/v1` exposes the read-only
  `concept_retrieval_evaluation_v1` report under policy
  `concept_retrieval_eval_policy_v1`.
- M11-C CURRENT human SAME is the only positive retrieval truth; automatic SAME
  is excluded, and NEW CONCEPT `seed_unit_same` is excluded as temporal leakage.
- M11-D validity gates evaluation. Invalid Dataset v1 state produces a blocked
  HTTP `200` report with null metrics and no samples; warnings do not block.
- The current candidate universe excludes retired Concepts but includes normal
  supported and orphaned Concepts. Historical catalog reconstruction is deferred.
- `exact_signature_retriever_v1` is a deterministic retrieval-only baseline. It
  records no annotation and intentionally has no lexical/fuzzy/BM25/embedding/ML
  behavior. Metrics are Recall@1/3/5 and MRR; zero samples produce null metrics.

M12-B:

- `weighted_lexical_retriever_v1` is selectable through the same read-only
  evaluation endpoint; no query parameter still defaults to
  `exact_signature_retriever_v1`.
- Application-owned `ConceptRetrieverRegistry` selection keeps algorithm
  construction out of HTTP. Unknown retriever names return HTTP `400` rather
  than falling back.
- `concept_lexical_normalization_v1` lowercases Unicode, canonically decomposes
  text, removes combining marks, creates token boundaries at punctuation and
  separators, and discards one-rune tokens. It has no stop-word list, stemming,
  lemmatization, IDF, BM25, embeddings, fuzzy matching, ML, or provider call.
- The retriever deduplicates tokens within each weighted field, computes
  weighted cosine similarity, returns only positive-overlap Concepts, and sorts
  by score descending then Concept ID ascending. Stable JSON evidence lists
  unique sorted matched tokens and creates no annotation authority.
- Exact and lexical evaluations reuse `concept_retrieval_eval_policy_v1`; their
  validity, universe, eligibility, exclusions, sample Units, targets, and max K
  must remain identical. Only retrieval output, ranks, metrics, and retriever
  name may differ.

M12-C:

- `bm25_retriever_v1` is the deterministic corpus-aware lexical baseline. It is
  registered beside exact and weighted cosine through the existing
  `ConceptRetrieverRegistry`; the default remains `exact_signature_retriever_v1`.
- BM25 reuses `concept_lexical_normalization_v1` but preserves raw term frequency.
  Explicit field weights produce weighted query/document term frequencies and
  weighted document length; per-call in-memory corpus statistics provide document
  frequency, positive Robertson/Sparck Jones IDF, and average document length.
- Version 1 fixes `k1=1.2` and `b=0.75` without label-driven tuning. It applies
  term-frequency saturation and document-length normalization, returns positive
  finite scores only, sorts by score descending then Concept ID ascending, and
  emits stable JSON evidence with sorted matched tokens and term contributions.
- Exact, weighted cosine, and BM25 evaluations share the same M11-D gate, M11-C
  human-SAME truth, exclusions, current non-retired universe, samples, targets,
  max K, and metrics. BM25 ranking is retrieval evidence only and creates no
  annotation or resolution authority.
- M12-C adds no persistence, migration, index, SQLite FTS, cache, embedding,
  model inference, provider call, parameter learning, or frontend behavior.

## Design Priorities

1. Preserve original learning questions without information loss.
2. Keep AI-generated metadata separate from original user data.
3. Keep every workflow complete from input to persistent storage.
4. Preserve history: prefer append-only, versioned records over in-place edits.
5. Add higher-level features (review generation, scheduling) only after the
   layers they depend on work reliably.

## Core Data Principles

Every learning record should preserve:

* Original user input
* Original surrounding context
* Creation and update timestamps
* Detected learning category
* AI-generated explanation
* Confidence or uncertainty metadata
* Corrections and later review history

The original user input is the source of truth.

AI classifications and explanations are editable metadata. They must never
replace or silently rewrite the original record. Human corrections and feedback
are stored as additional immutable records, never by mutating the analysis they
refer to.

## Architecture Principles

* Keep HTTP transport, business logic, persistence, and AI integration separate.
* HTTP handlers must not contain direct database logic.
* AI output must be validated before storage.
* Database schema changes must use explicit migrations.
* Prefer stable core tables plus extensible metadata over uncontrolled
  AI-generated schema changes.
* Do not introduce distributed services, Kubernetes, event buses, or complex
  agent orchestration unless a demonstrated requirement justifies them.
* Prefer standard libraries and mature dependencies.
* Keep components replaceable through small interfaces.

## Development Workflow

For non-trivial tasks:

1. Inspect relevant files and current repository state.
2. Explain the existing behavior and constraints.
3. Propose a concise implementation plan.
4. Identify exact files that will be created or modified.
5. Implement only the requested scope.
6. Format changed files.
7. Run relevant tests.
8. Report changed files, commands executed, test results, and unresolved risks.

For small and obvious fixes, proceed after inspecting the affected files.

## Working Rules

* Never claim a command or test passed unless it was actually executed.
* Do not silently modify unrelated files.
* Do not delete user work merely because another structure seems cleaner.
* Do not place credentials, tokens, account data, or local machine paths in Git.
* Do not read or expose `.env`, credential databases, SSH keys, or secret files.
* Keep working-tree changes small and focused so the human owner can commit them
  cleanly.
* Update this document when real project commands or architecture change.
* Coding agents must not run Git or GitHub commands at all, including read-only
  inspection. The human owner exclusively controls branches, staging, commits,
  pushes, pull requests, merges, and rebases. Coding agents work only from the
  provided working tree: they inspect files, modify the requested scope, format,
  test, and report.

## Documentation

Use:

* `README.md` for setup and user-facing project information
* `docs/ARCHITECTURE.md` for architectural decisions
* `docs/plans/` for temporary implementation plans when useful
* `AGENTS.md` for durable instructions to coding agents

Documentation should describe the implemented system, not an imaginary future
platform. Keep temporary, task-specific instructions out of this file.

Every completed implementation task must ensure that `README.zh-CN.md` exists as
the maintained Simplified Chinese companion to `README.md`. When user-facing
behavior, setup, commands, API contracts, or architecture documented in the
English README changes, update the corresponding Chinese documentation in the
same task.

## Definition of Done

Before declaring a task complete:

1. Relevant files are formatted.
2. Relevant automated tests pass.
3. Error paths are handled.
4. Documentation is updated when behavior changes.
5. No credentials or generated local files are included.
6. The final report names modified files and validation commands.
7. The final report ends exactly with a suggested commit message for the human
   owner. The agent must only suggest it, never execute it.
8. The final report includes an executable `git add -- ...` command listing only
   the files modified for the task. The agent must display the command for the
   human owner and must never execute it.

```text
Suggested commit message:
<type>: <concise description>
```

## Scope Discipline

Do not expand the existing annotation frontend into a consumer/product UI,
authentication system, review engine, or unrelated frontend architecture
unless explicitly requested.

Unless explicitly requested, do not introduce:

* Advanced or general-purpose agents
* Automatic schema rewriting
* Recommendation systems
* Embeddings, vector search, semantic similarity systems, or ML resolver work
* Review scheduling or mastery systems
* Speech processing
* Authentication or consumer/product frontend expansion
* Additional AI providers or automatic provider fallback
* Automatic retry systems, streaming, or batch analysis
* Usage or billing dashboards
* Unrelated infrastructure or architecture expansion

## Human-Owned Git Workflow

The human owner exclusively manages branches, staging, commits, pushes, pull
requests, merges, and rebases. Coding agents do not inspect or operate on Git or
GitHub state; they modify, format, test, and report working-tree files only.
