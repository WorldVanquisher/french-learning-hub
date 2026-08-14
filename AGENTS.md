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
* Do not commit, push, rewrite history, or create pull requests unless explicitly requested.
* Do not place credentials, tokens, account data, or local machine paths in Git.
* Do not read or expose `.env`, credential databases, SSH keys, or secret files.
* Use small, focused commits when commits are requested.
* Update this document when real project commands or architecture change.

## Documentation

Use:

* `README.md` for setup and user-facing project information
* `docs/ARCHITECTURE.md` for architectural decisions
* `docs/plans/` for temporary implementation plans when useful
* `AGENTS.md` for durable instructions to coding agents

Documentation should describe the implemented system, not an imaginary future
platform. Keep temporary, task-specific instructions out of this file.

## Definition of Done

Before declaring a task complete:

1. Relevant files are formatted.
2. Relevant automated tests pass.
3. Error paths are handled.
4. Documentation is updated when behavior changes.
5. No credentials or generated local files are included.
6. The final report names modified files and validation commands.

## Scope Discipline

Do not implement advanced agents, automatic schema rewriting, recommendation
systems, embeddings, review scheduling, speech processing, or a frontend unless
the user explicitly changes the scope. The OpenAI analyzer is the only external
AI provider integration in scope; do not add automatic fallback, retries,
streaming, batch analysis, additional providers, or usage/billing dashboards
without an explicit scope change.

## Git Workflow

For non-trivial milestone work:

1. Start from an up-to-date `main` and create or use a feature branch.
2. Do not implement non-trivial milestones directly on `main`.
3. Open a pull request targeting `main`.
4. Ensure CI passes and review the final diff before merge.
5. Prefer a squash merge, then delete the feature branch.
6. Coding agents must not merge their own pull requests unless explicitly instructed.
