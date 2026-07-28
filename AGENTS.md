
## Project Overview

This repository contains an AI-assisted French learning application.

The application stores the user's French-learning questions and their original
context, classifies learning records, generates explanations, and creates
personalized review activities.

The current priority is to build a small working end-to-end system. Prefer
simple, testable implementations over speculative platform architecture.

## Current Stage

The repository is at the initial scaffolding stage.

Do not assume that planned directories, frameworks, services, or database
schemas already exist. Inspect the repository before proposing changes.

## Current Priorities

1. Establish the repository structure.
2. Define the smallest useful backend.
3. Store original learning questions without information loss.
4. Add structured AI-generated metadata separately from original user data.
5. Build one complete workflow from question input to persistent storage.
6. Add review generation only after persistence works reliably.

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
replace or silently rewrite the original record.

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
* `docs/architecture/` for architectural decisions
* `docs/plans/` for temporary implementation plans when useful
* `AGENTS.md` for durable instructions to coding agents

Documentation should describe the implemented system, not an imaginary future
platform.

## Definition of Done

Before declaring a task complete:

1. Relevant files are formatted.
2. Relevant automated tests pass.
3. Error paths are handled.
4. Documentation is updated when behavior changes.
5. No credentials or generated local files are included.
6. The final report names modified files and validation commands.

## Initial Task Boundary

The first implementation milestone should establish only:

* A clear repository structure
* One backend application
* One persistence mechanism
* One endpoint or command for saving a learning question
* Validation and automated tests
* Basic local development documentation

Do not implement advanced agents, automatic schema rewriting, recommendation
systems, speech processing, or a frontend during this milestone unless the user
explicitly changes the scope.
