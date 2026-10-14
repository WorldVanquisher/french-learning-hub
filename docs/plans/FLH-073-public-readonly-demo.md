# FLH-073 Deployable read-only public demo of the Knowledge Library

Owner: local Claude Code. Branch label supplied: `feat/flh-073-public-readonly-demo`.
No Git/GitHub command or subagent was used. Evidence:
[validation](../validation/FLH-073-public-readonly-demo.md). Operator guide:
[PUBLIC_DEMO.md](../PUBLIC_DEMO.md).

**Authorized:** a narrow, explicit, opt-in demo mode with the backend and UI
changes it needs.

**Not authorized:**
- internet publication, DNS changes or cloud resources;
- live model calls;
- changes to existing acceptance reports/harnesses, AWS or Windows tools,
  migrations, or the personal website repository.

## Contract

### 1. Opt-in mode, isolated data, no providers

- **Opt-in:** `cmd/server -public-demo-artifact DIR` turns the mode on. Without
  the flag nothing changes: the same routes, defaults and wiring.
- **Isolated data:** in demo mode the server never opens `DB_PATH`. It opens
  only `DIR/demo.db`:
  - read-only and immutable (`mode=ro&immutable=1`);
  - after checking that the migration ledger equals the embedded migrations
    exactly;
  - nothing is migrated or written.
- **Startup is refused** unless:
  - `AI_PROVIDER=rule-based`, `EXTRACTOR_PROVIDER=disabled`,
    `EMBEDDING_PROVIDER=disabled` and `SEMANTIC_SEARCH=disabled`. No analyzer,
    extractor or provider client is constructed in demo mode;
  - the artifact validates (§4);
  - for an artifact whose vectors are mechanical test fixtures,
    `-public-demo-allow-mechanical` is also passed. This is for local smoke
    only.

### 2. Server-enforced allowlist (`NewPublicDemoBoundary`)

- **Position:** it wraps the whole handler *outside* the workbench prefix
  handling and *inside* the existing browser boundary (Host/Origin checks
  unchanged). It runs before any service.
- **Methods:** only `GET` and `HEAD`. Every other method, on any path, gets
  `405` with `Allow: GET, HEAD` and no service call.
- **Paths:** a request whose path is not in canonical form (`path.Clean`
  differs, or encoded slashes) gets `404`.
- **Allowed at the root and identically under `/api`:**
  - `/healthz`, `/readyz`;
  - `/knowledge-library/concepts`, `/knowledge-library/concepts/{id}`,
    `/knowledge-library/units/{id}/source` (ids: decimal digits only);
  - `/knowledge-library/demo`, `/knowledge-library/demo/semantic-search`,
    `/knowledge-library/demo/hybrid-search`.
- **Static, at the root only** (when `-web-dir` is given): `/` and `/assets/…`.
- **Everything else gets `404`** ("not available in the public demo"),
  including the free-text `/knowledge-library/semantic-search` and
  `/hybrid-search`, all entry/analysis/extraction/concept/annotation/
  evaluation routes, and unknown paths.

### 3. Query contract

- **Keyword:** free text stays available with its existing bounds (local SQL,
  no provider).
- **Semantic and hybrid** accept only `preset=<id>` from the artifact's
  bounded catalog (at most 12 presets), plus `state`, `limit` and (hybrid)
  `depth` under the existing rules.
  - Any other parameter, including `q`, gets `400`. An unknown preset gets
    `404`.
  - The handler substitutes the preset's exact text as `q` and then runs the
    **unchanged** semantic/hybrid handler, so the response schemas are the
    standard v2/v1 ones and `query` is the exact preset text.
- **Embedding provider = `PresetQueryVectors`:** it returns a cached vector
  only for the exact `concept_search_query_v2` envelope of a catalog preset.
  Any other text fails with `ErrEmbeddingProviderUnavailable`. It has no
  network code. Lookups and refusals are counted and shown on `/demo`.
- **`GET /knowledge-library/demo`** returns `knowledge_library_public_demo_v1`:
  - the artifact identity: version, manifest SHA-256, vector source,
    `real_model` and the notice;
  - the presets (`id`, `label`, exact `text`);
  - the limits and the read-only statement;
  - the counters.

### 4. Ranking mechanics and artifact binding

- **Reused unchanged:** `SemanticSearchService` (re-checks, state filter,
  publication), `HybridSearchService` (`concept_hybrid_rrf_v1`, k = 60) and
  `KnowledgeLibraryService`.
- **Vector index = `ArtifactIndex`:** read-only, in-process, exact cosine over
  the artifact's Concept-document vectors. It answers only for the one
  physical collection the artifact names, and every write method returns an
  error. There is no Qdrant in the demo.
- **Publication = `ArtifactPublication`:** a fixed space state from the
  manifest, with `last_run_operation: "artifact"`.
- **Artifact `DIR/`:** `manifest.json`, `demo.db`, `vectors.json`,
  `fixtures.json`. The manifest records:
  - each file's SHA-256 and the fixture SHA-256;
  - the vector identity: `source` (`mechanical-test` | `model`),
    `real_model`, `generator`, `model_id`, `dimensions`, the document
    representation `concept_embedding_text_v1`, and the query representation
    `concept_search_query_v2`;
  - `release_status` and a domain fingerprint.
- **Load is refused** (startup fails) when:
  - any file is missing or its hash differs;
  - the schema is unknown, or the vector identity differs between the
    manifest and `vectors.json`;
  - a vector has the wrong dimension, is non-finite or is zero;
  - a preset's recorded envelope is not exactly
    `ConceptSearchQueryEmbeddingText(text)`, or its SHA-256 differs;
  - a preset text fails the hybrid/keyword query rules;
  - presets are duplicated or exceed the bound;
  - any current Concept lacks a vector, or its document content hash differs
    from the recorded one;
  - a vector belongs to no Concept;
  - the database fingerprint differs.
- **Fake embeddings** are never substituted.

### 5. Artifact preparation (`scripts/demo/flh073/`)

- **Commands:** `go run ./scripts/demo/flh073/prepare` with `build -out DIR`
  and `validate -artifact DIR [-release]`.
- **Build:**
  1. Seed a fresh database through the real application services (entries,
     analyses, a scripted fixture extractor, Concepts, SAME memberships) from
     `fixtures/catalog.json`, which holds synthetic English questions about
     French.
  2. Compute **mechanical** vectors: signed feature hashing
     `flh073_mechanical_hash_v1`, 64 dimensions, labelled as such everywhere.
  3. Write the artifact, then validate it with the same loader the server
     uses.
- **No live model call exists in this tool.**
- **`validate -release`** exits 3 and prints `BLOCKED` unless the vectors come
  from a real model. Real vectors need a separately authorized run producing
  the documented `vectors.json` format with `source: "model"`.
- **Reproducibility:** `vectors.json` and the domain fingerprint are
  deterministic for a given fixture. The `demo.db` bytes are not (row
  timestamps), so its hash binds one artifact rather than reproducing it.

### 6. Presentation

- **Demo build:** `VITE_FLH_PUBLIC_DEMO=1 npm run build` produces a demo
  build. `main.tsx` then renders `PublicDemoApp`:
  - a short English intro (what to try, synthetic data, read-only, limits,
    the vector-source label);
  - the existing `KnowledgeLibrary` in demo mode;
  - no other workbench tab and no editing, import or review controls.
- **The normal build is unchanged.**
- **Demo mode in `KnowledgeLibrary`:**
  - keyword search is free text;
  - semantic and hybrid use a preset selector showing each preset's exact
    text, and a label saying free-text semantic search is disabled;
  - Concept detail, source/provenance and ranking evidence are unchanged.

### 7. Deployment preparation (`docs/PUBLIC_DEMO.md`)

- **Isolation:** a dedicated user and directory, the artifact read-only, and
  the server on loopback.
- **Reverse proxy:** TLS; pass only GET/HEAD; set `ALLOWED_HOSTS` to the
  public name; rate limits.
- **Operations:** startup, rollback (previous artifact directory) and
  shutdown; a local smoke script (`scripts/demo/flh073/smoke.sh`).
- **Qdrant** is not used, so nothing is exposed. A later NAS/Qdrant variant is
  documented as future work, not wired.

## File ownership

- **New:**
  - `internal/publicdemo/` (artifact, read-only DB, index, publication, preset
    provider, mechanical vectors, tests);
  - `internal/transport/http/public_demo.go`, `public_demo_test.go`;
  - `cmd/server/public_demo.go`;
  - `scripts/demo/flh073/` (`prepare/`, `fixtures/catalog.json`, `smoke.sh`,
    `README.md`);
  - `web/src/PublicDemoApp.tsx`, `web/src/PublicDemoApp.test.tsx`;
  - `docs/PUBLIC_DEMO.md`, this plan, the validation report.
- **Changed:**
  - `cmd/server/main.go` (flag and an early branch only);
  - `internal/transport/http/handler.go` (option and routes);
  - `web/src/main.tsx`, `web/src/api/client.ts`, `web/src/types/library.ts`;
  - `web/src/pages/KnowledgeLibrary.tsx` (optional demo prop);
  - `AGENTS.md` (a short FLH-073 contract entry).
