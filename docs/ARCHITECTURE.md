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

The `Analyzer` interface lives at the domain boundary. Milestone 2 ships one
implementation, a deterministic rule-based analyzer (`internal/analyzer`), so
the full workflow runs and is testable without any external AI provider. A real
provider can be added later as another `Analyzer` implementation without
changing the transport, application, or storage layers.

Validation before storage: `category` and `explanation` are required and length
bounded, `confidence` must be in `[0, 1]`, and `uncertainty` is bounded
free-form text. Metadata that fails validation is rejected with HTTP `422` and
never reaches the database.

Endpoints:

- `POST /entries/{id}/analysis` — analyze an entry, append a new version.
- `GET  /entries/{id}/analyses` — list an entry's analyses, oldest first.

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