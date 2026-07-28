Inspect the current repository and implement milestone 2: validated,
versioned AI-generated metadata for learning entries.

Scope:
- Add an explicit migration for an entry_analyses table.
- Preserve entries.original_input and original_context unchanged.
- Allow one entry to have multiple analysis records.
- Add a small Analyzer interface in the application/domain boundary.
- Implement a deterministic fake or rule-based analyzer for local development.
- Validate category, explanation, confidence, and uncertainty before storage.
- Add POST /entries/{id}/analysis.
- Add GET /entries/{id}/analyses.
- Add repository, service, handler, and integration tests.
- Update README and architecture documentation.
- Do not call an external AI API yet.
- Do not implement review generation, embeddings, agents, or a frontend.

Before implementation, inspect the repository and report the exact files that
will be changed. After implementation, run formatting, tests, vet, and build,
then report commands and results.