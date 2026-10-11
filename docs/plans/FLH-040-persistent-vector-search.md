# FLH-040 Persistent embeddings and rebuildable vector search

Owner: local Claude Code, sole production writer. Branch label supplied:
`feat/flh-040-persistent-vector-search`. No Git/GitHub command or subagent was
used. The owner explicitly authorized persistent embeddings, a single-instance
Qdrant integration and user-facing semantic retrieval for this milestone only.
The canonical contract is
[ARCHITECTURE §9.3](../ARCHITECTURE.md#93-optional-semantic-search-flh-040). The
operator guide and Go walkthrough are in [SEMANTIC_SEARCH.md](../SEMANTIC_SEARCH.md).
Evidence is in the [validation report](../validation/FLH-040-persistent-vector-search.md).

## Decisions made before editing

| Topic | Decision |
| --- | --- |
| Migration | `010_semantic_index.sql`, additive: `semantic_embedding_cache`, `semantic_index_collections`, `semantic_index_points`. No existing table changes. |
| Index document | The existing `concept_embedding_text_v1` Concept document (identity fields only, sorted features), reused unchanged. Its content hash is SHA-256 of the text. No unit, history or source text is indexed. |
| Model identity | New required `EMBEDDING_MODEL_ID` (operator-declared model and deployment identity) and `EMBEDDING_DIMENSIONS`. The provider display name (`http:<model>`) is not used. |
| Cache key | (content_hash, representation, model_id, dimensions); float32 little-endian blob of exactly 4 × dimensions bytes (checked by a constraint). |
| Vector spaces | Collection = `<prefix>_<first 16 hex of sha256(representation, model_id, dimensions)>`; payload repeats the identity; search drops foreign hits. |
| Operator interface | `cmd/semantic-index` `build` / `sync` / `rebuild` / `status`, with `-json` and `-batch`. Exit codes 0 / 3 / 1 / 2. No worker, schedule or retry. |
| Consistency | SQLite stays authority. No network call inside a SQLite transaction. Run ownership by run ID. Re-read before each published batch. Points recorded after Qdrant acknowledgment. Final re-validation. `complete` only for the owning run with no stale document; otherwise `partial` with a sanitized error. No cross-store atomicity is claimed. |
| Search API | `GET /knowledge-library/semantic-search?q=&state=&limit=`, schema `knowledge_library_semantic_search_v1`. It reuses the keyword parameter rules, and `q` is required. Over-fetches ×4 (max 200), then re-reads every hit from SQLite. Missing, stale, foreign and non-positive hits are dropped and counted, never substituted. `503` / `409` / `502` / `504` are explicit; there is no keyword fallback. |
| Qdrant | REST over `net/http`, with no new Go dependency. Image `qdrant/qdrant:v1.19.1@sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10` in an opt-in Compose profile, published on `127.0.0.1` with a bind-mounted storage directory. |
| Defaults | `AI_PROVIDER=rule-based`, `EXTRACTOR_PROVIDER=disabled`, `EMBEDDING_PROVIDER=disabled`, `SEMANTIC_SEARCH=disabled`. Keyword search and the M12/M13 retrievers are unchanged. |

## Files

**New**
- `migrations/010_semantic_index.sql`
- `internal/application/semantic_index.go`, `semantic_search.go`; tests
  `semantic_index_test.go`, `semantic_search_test.go`, `semantic_fakes_test.go`
- `internal/storage/sqlite/semantic_index_repository.go` and its test
- `internal/vectorindex/qdrant.go`, `qdrant_test.go`, `qdrant_integration_test.go`
  (the last runs only with `FLH_QDRANT_URL`)
- `internal/transport/http/semantic_search.go` and its test
- `cmd/semantic-index/main.go` and `main_test.go`
- `scripts/demo/flh040/fake_embeddings.py`, `semantic_demo.sh`, `README.md`
- `docs/SEMANTIC_SEARCH.md`, this plan, and the validation report

**Modified**
- Backend:
  - `internal/config/config.go`, `config_test.go`
  - `internal/application/knowledge_library_service.go` (`ConceptCounts` helper)
  - `internal/transport/http/handler.go` (field and route)
  - `cmd/server/main.go` (opt-in wiring)
- Frontend:
  - `web/src/types/library.ts`, `web/src/api/client.ts`
  - `web/src/pages/KnowledgeLibrary.tsx`, `KnowledgeLibrary.test.tsx`
  - `web/src/styles.css`
- Packaging: `compose.yaml`, `Dockerfile`, `Makefile`, `.env.example`
- Docs:
  - `README.md`, `README.zh-CN.md`
  - `docs/ARCHITECTURE.md` (§2, §8.6, §9.1, §9.3, §10.2, §11, §12, A.13)
  - `docs/RELEASE.md`
  - `AGENTS.md`

## Out of scope (unchanged)

The following were not added:
- hybrid ranking, RAG, training or automatic SAME decisions;
- a background worker, automatic retry, authentication or cloud deployment;
- indexing of unit or source text;
- a Recall@K or MRR evaluation of a real model;
- dependency upgrades or CI changes.
