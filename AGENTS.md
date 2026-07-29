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
  exist: a local deterministic rule-based analyzer (the default, no cost) and an
  opt-in OpenAI-backed analyzer selected by `AI_PROVIDER`. Provenance is stored
  in the existing `analyzer` field (e.g. `openai:<model>:fr_l2_taxonomy_v1`).
  Persisted categories use the shared `fr_l2_taxonomy_v1` domain taxonomy; the
  database never stores provider-specific category systems.
* Immutable human feedback and corrections attached to analyses.

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
