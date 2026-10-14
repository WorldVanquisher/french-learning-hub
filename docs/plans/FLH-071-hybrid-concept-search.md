# FLH-071 Explicit, explainable hybrid Concept search

Owner: local Claude Code. Branch label supplied: `feat/flh-071-hybrid-concept-search`.
No Git/GitHub command or subagent was used. Evidence:
[validation](../validation/FLH-071-hybrid-concept-search.md).

**Authorization:** the human owner explicitly authorized this narrow hybrid
search feature, previously deferred. It is **not** a resolver, RAG, automatic
SAME, reranker or learned model.

**Not changed:**
- the keyword and semantic endpoints, their schemas and defaults;
- migrations, the semantic index CLI and the evaluation retrievers (§8);
- AWS tools, the Windows runtime, IAM and `AGENTS.md`.

## What exists (inspected before writing this contract)

**Keyword: `KnowledgeLibraryService.Search`** (`GET
/knowledge-library/concepts`, `knowledge_library_search_v1`).
- **Matching:** `concept_lexical_normalization_v1` tokens, AND semantics. Every
  query token must be a **prefix** of some token in the searched fields.
- **Tiers:**
  - `identity`: Concept target, intent, scope or identity features;
  - `unit_evidence`: the identity fields plus the canonical/statement/example
    wording of CURRENT SAME members.
- **Order:** tier (identity first), then state (active, orphaned, retired),
  then case-folded target, then id. This order is deterministic but **not a
  relevance score**: there is no numeric keyword score.
- **Bounds:** every match is ranked, then truncated to `limit` (≤ 50), with
  `total_matches` and `truncated`. Each request reads the Concept list with
  the requested state filter.
- It is **not** the §8 BM25 evaluation retriever. Hybrid does not use any §8
  retriever, dataset or label.

**Semantic: `SemanticSearchService.Search`** (`GET
/knowledge-library/semantic-search`, `knowledge_library_semantic_search_v2`).
- **One query, one collection:** one provider call embeds the
  `concept_search_query_v2` envelope. One published collection is queried with
  `k = min(4 × limit, 200)`. If that publication is replaced mid-search, it
  retries once on the new one (the existing contract); a second replacement
  gives `ErrSemanticPublicationChanged`.
- **Re-check:** hits are re-read against SQLite and dropped (and counted) when
  missing, stale by content hash, from an incompatible space or non-positive.
  The state filter applies to current facts. The page is cut at `limit`, and
  shortages are never filled.
- **Optional:** without `SEMANTIC_SEARCH=qdrant` the route is 503.

## Contract

**Route:** `GET /knowledge-library/hybrid-search?q=&state=&limit=&depth=`,
also under `/api`. GET only. It is registered only as a separate explicit mode;
the other two routes and their defaults are unchanged.

**Parameters:**

| Parameter | Rule |
| --- | --- |
| `q` | Required, non-empty, the same validation as keyword (≤ 200 bytes, ≤ 8 terms, at least one searchable term) |
| `state` | `all`/`active`/`orphaned`/`retired`, the same filter as both components |
| `limit` | Displayed results: default 20, 1..50 |
| `depth` | Candidate depth per component: default 50, `limit ≤ depth ≤ 50` (strict cap `HybridMaxDepth = 50`) |

An invalid parameter returns 400.

**Policy `concept_hybrid_rrf_v1`** (fixed, not tuned against any label):
1. Run **keyword** with `limit = depth`. Its 1-based positions are its ranks.
   This runs first and needs no provider, so an invalid query costs no
   embedding call.
2. Run **semantic** once with `limit = depth`. Its 1-based positions are its
   ranks; one publication, re-checked as above.
3. **Reciprocal rank fusion** by Concept ID with `k = 60` and equal weights
   `w_keyword = w_semantic = 1`: `fused(c) = Σ_i w_i / (k + rank_i(c))`, over
   the components where `c` appears. A duplicate Concept ID within one
   component keeps its best (first) rank and is counted, never added twice.
4. **Authoritative re-check:** after both components, read the Concepts once
   more from SQLite.
   - A fused Concept is dropped and counted when it no longer exists
     (`missing`), or no longer passes the state filter (`filtered_by_state`).
   - It is also dropped when its identity fields or state differ from the
     snapshot a component ranked it with (`changed_during_search`), so
     evidence from an older version is never presented as current.
   - Dropped Concepts are never replaced by others.
5. **Order:** fused score descending, then Concept ID ascending (exact ties are
   possible). Truncate to `limit`, reporting `total_candidates` and
   `truncated`.
6. **Display counts:** member and supporting counts are read for the displayed
   results, as in both modes.

**Response `knowledge_library_hybrid_search_v1`:**
- **Request and policy:** `query`, `state`, `limit`, `depth`, and `policy`
  (`version`, `rrf_k: 60`, `weights {keyword: 1, semantic: 1}`, `tie_break:
  "concept_id_ascending"`).
- **`score_note`:** fused scores are rank-fusion sums, **not probabilities or
  relevance estimates**, and only comparable within this one response.
- **`components.keyword`:** `returned`, `total_matches`, `truncated_at_depth`,
  and `matching` (the semantics above, incl. that its rank is tier/state/target
  order, not a score).
- **`components.semantic`:** `returned`, `considered`, the `skipped` and
  `filtered_by_state` counts, `query_representation`, and the
  `index` publication object of the semantic response (one collection,
  `health_verified: false`).
- **`dropped_after_fusion`:** `missing`, `filtered_by_state`,
  `changed_during_search`, `duplicate_component_ids`.
- **`results[]`:**
  - `concept`, `fused_score`, `sources` (`["keyword"]`, `["semantic"]` or
    both, in that order);
  - `keyword` (`{rank, match_tier, matched_fields}` or null) — no keyword
    score is reported, because none exists;
  - `semantic` (`{rank, similarity}` or null);
  - `current_member_count`, `supporting_unit_count`.

**Failure contract:**
- **Both components are required.** Semantic disabled gives 503, and any
  semantic error maps exactly as the semantic route does (409 not built or
  incompatible, 502/504 provider or vector store, 500 otherwise, including a
  second publication replacement).
- **No keyword-only fallback,** no extra retry beyond semantic's existing one,
  no document embedding and no index build.
- An invalid query returns 400 before any provider call.

**Read-only:** hybrid holds only read interfaces (the two searchers, a Concept
lister and a summarizer). It writes no annotation, membership, support,
preferred unit, identity or index state.

**UI:** a third **Hybrid** radio in the existing Knowledge Library mode
selector, with the same query, state and Search button.
- **Per result:** the existing result card, plus a short evidence line giving
  each component's rank, the matched fields or similarity, and the fused
  score.
- **Summary:** a component and policy summary, plus explicit dropped counts.
- **Unchanged:** an empty query requests nothing, as semantic mode does. No
  redesign, router, state library or chart.

## Later human-reviewed comparison (documented, not built)

The three modes can be compared later on a **human-reviewed query set**:
1. Write each free-text query with the Concept IDs a person judges relevant,
   recorded as a separate evaluation file.
2. Run each mode on the same database, publication and depth, with fixed
   parameters.
3. Report Recall@k and MRR per mode, plus the per-query overlap.

The query set is evaluation data only. It never becomes annotation truth: no
CURRENT SAME, DISTINCT or relation is created from it, and M11-C human SAME
stays the only annotation-truth source. The existing synthetic labels and
fixtures are not human-reviewed ground truth and are not used to claim or tune
relevance.

## Files

- **New:**
  - `internal/application/hybrid_search.go`, `internal/application/hybrid_search_test.go`
  - `internal/transport/http/hybrid_search.go`, `internal/transport/http/hybrid_search_test.go`
- **Wiring:** `internal/transport/http/handler.go` (route and field) and
  `cmd/server/main.go`, wired only when semantic search is configured.
- **Web:**
  - `web/src/types/library.ts`, `web/src/api/client.ts`
  - `web/src/pages/KnowledgeLibrary.tsx`, `web/src/pages/KnowledgeLibrary.test.tsx`
  - `web/src/api/client.test.ts`, if needed
- **Docs:** `docs/ARCHITECTURE.md` §9 and A.13 (search sections only); this
  plan and the validation report.
