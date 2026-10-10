# FLH-034 Knowledge Library

A read-only workbench view for one workflow: search previously learned material,
open a curated Concept, see its current representation and support, and follow
its evidence back to the original learning record and the versioned
interpretation used to derive it.

- No migration, dependency, router or provider is added.
- Authority and search rules live in the backend; the UI renders backend facts.
- Demo: [docs/DEMO.md](../DEMO.md).

## Reused authority

| Fact | Source (unchanged) |
| --- | --- |
| Concept identity, lifecycle, derived support, effective state | `ConceptRepository.ListConcepts` / `GetConcept` (support derived at read time) |
| Units that support a Concept | `ActiveSupportUnitIDs`: current SAME member, in its entry's current extraction, effective admission `active` |
| CURRENT SAME membership | `unit_concept_memberships` projection via `GetCurrentMembership` (never the event log) |
| Current non-membership relations | M11-A `ResolveEffectiveAnnotation` snapshot relations |
| Current extraction | `GetCurrentExtractionSelection` |
| Admission | Extraction view's resolved admission |
| Interpretation used by an extraction | The extraction's `source_analysis_id` and `source_feedback_id`, resolved with `domain.ResolveEffective` |

The application service `KnowledgeLibraryService` depends only on read
interfaces, so it cannot write by construction. An HTTP test asserts that row
counts in every annotation, learning and extraction table are unchanged by
library reads.

## API (GET only; root and `/api/...`)

### `GET /knowledge-library/concepts?q=&state=&limit=`

Schema `knowledge_library_search_v1`.

**Searched fields**
- Concept `target`, `pedagogical_intent`, `scope`, and identity feature keys and values.
- The `canonical`, `statement` and `example` of units holding the Concept's CURRENT SAME membership (the `unit_concept_memberships` projection).
- Membership is not current extraction and not support. A CURRENT SAME member from a historical extraction, or with suppressed admission, still contributes its wording. Its result is labelled as a member-wording match, and the Concept page shows why it does not support.
- Not searched: former members (reassigned, rejected or INVALID) under the Concept they left, relation-only units, history-only units, source entry text and analyses. A reassigned unit's wording matches only its new Concept.
- Corrected in FLH-036: this section previously listed "historical units" as excluded, which wrongly suggested members from a historical extraction were not searched.

**Matching**
- Text is normalized with `concept_lexical_normalization_v1`: Unicode lowercase, accents removed, punctuation and separators split tokens, and one-character tokens are dropped.
- Every query token must be a prefix of some field token (AND).
- `matched_fields` lists the fields that matched.

**Ordering**
- `match_tier` comes first: `identity` (all tokens in identity fields) before `unit_evidence`.
- Then effective state: active, then orphaned, then retired.
- Then case-folded target, then id.
- An empty `q` browses all Concepts with tier `browse`.

**Limits and errors**
- `limit`: default 20, range 1–50. `total_matches` and `truncated` describe what was cut.
- `q`: at most 200 bytes and 8 unique terms.
- `state`: one of `all|active|orphaned|retired`.
- 400 for a bad limit, state or length, or for a non-empty `q` with no searchable term.

**Cost.** One request reads all Concepts with derived support, and the member units of Concepts whose identity does not match. That is fine at personal scale, but not indexed; see the risks below.

### `GET /knowledge-library/concepts/{id}`

Schema `knowledge_library_concept_v1`. 404 for an unknown Concept.

Each unit appears in exactly one section, in this priority:

1. `supporting_units`
2. `non_supporting_members`: CURRENT SAME members that are not support. Facts: `in_current_extraction`, `admission`.
3. `current_relations`: effective relation events, only from units in the current extraction that are not INVALID.
4. `historical_units`: any other unit with an event for this Concept. Includes its latest event, `effective_status` and `current_concept_id`.

Other fields:
- `preferred_unit` (always a current member).
- `history_event_count`.
- Every unit carries `entry_id`, `extraction_id`, `extraction_version`, `in_current_extraction` and `admission`.

### `GET /knowledge-library/units/{id}/source`

Schema `knowledge_library_source_v1`. 404 for an unknown unit.

Returns:
- The unit.
- The original entry.
- The extraction metadata.
- The entry's current extraction selection.
- `source_interpretation`: the analysis version, the feedback in force at extraction, and the resolved effective values.
- `latest_analysis` (to flag a newer analysis).
- The unit's current annotation status.

## UI

**Knowledge Library tab** (`web/src/pages/KnowledgeLibrary.tsx`).
- It is mounted on first open and then kept mounted while hidden. The query, results and open screen therefore survive switching views.
- Inside it, three screens: results, Concept and source.
- Back buttons name the query ("← Back to results for “subjonctif”"), and focus returns to the opened result.

**States**
- Loading, error with an explicit "Try again", empty library, no match, and truncated results.
- Results from a previous request are never shown under a new query.

**Labels**
- A `unit_evidence` result says it matched through "member unit wording/statement/example", not in the Concept identity, and that membership is not support. Counts read "CURRENT SAME members".
- Current sections and history are visually and textually distinct.
- A unit may hold several relations to one Concept; relation rows are keyed by `link_id`, so every relation is shown.
- Orphaned and retired status is explained.
- Non-support reasons are given from backend facts.

## Files

**Backend**
- `internal/application/knowledge_library_service.go`
- `internal/transport/http/knowledge_library.go` and `knowledge_library_integration_test.go`
- `internal/transport/http/handler.go` (field and routes)
- `cmd/server/main.go` (wiring)

**Frontend**
- `web/src/types/library.ts`
- `web/src/api/client.ts`
- `web/src/pages/KnowledgeLibrary.tsx` and `KnowledgeLibrary.test.tsx`
- `web/src/App.tsx`
- `web/src/styles.css`

**Demo:** `scripts/demo/flh034/` and `docs/DEMO.md`. FLH-036 hardened the demo's binding and process ownership: [FLH-036](FLH-036-knowledge-demo.md).

**Docs:** `README.md`, `README.zh-CN.md`, `docs/ARCHITECTURE.md`, and one durable AGENTS.md contract entry.

## Acceptance checks

| # | Check | Evidence |
| --- | --- | --- |
| 1 | Accessible view | "Knowledge Library" tab; walkthrough W1 |
| 2 | Search/browse states | Vitest (loading/error/retry/empty/no match/stale guard); Go test (tiers, ordering, bounds, 400s) |
| 3 | Identity, support, preferred unit, relations | Go detail test; W3, W7 |
| 4 | Concept → unit → source and back, preserving the query | Vitest; W4, W5, W9 |
| 5 | Current vs historical labelling | Go test (historical extraction, reassigned, INVALID); W3, W6, W7 |
| 6 | Orphaned Concepts inspectable | Go test (C2, C3); W6 |
| 7 | Read-only | Go row-count test; Vitest GET-only; walkthrough W10 (0 non-GET) |
| 8 | Restart and production build | Walkthrough after `demo.sh start` restarts on the same DB; PROD (`-web-dir`) and DEV (Vite StrictMode) |
| 9 | Repeatable demo, no paid or external service | `scripts/demo/flh034/`; local stub extractor and rule-based analyzer |

## Risks and limits

- **Scale.** Search is a full scan with per-Concept support derivation and no index. That is adequate for hundreds of Concepts; a larger library would need a storage-level query.
- **Matching.** Keyword prefix match only: no stemming, synonyms, typo tolerance or semantic retrieval. Single-letter words such as "à" or "y" are not searchable.
- **Source text not searched.** Entry text and analyses are not searched; only Concept identity and current-member unit wording are.
- **DISTINCT not shown.** DISTINCT negative pairs are not listed on the Concept page.
- **No deep links.** There is no URL state, so a browser reload returns to the default view.
