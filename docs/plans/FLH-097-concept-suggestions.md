# FLH-097 — AI-assisted batch Concept membership suggestions

Owner: NAS Claude Code (sole implementation owner). Working tree and branch
prepared by the owner; no Git commands were run.

The current design is described in [ARCHITECTURE §7.6](../ARCHITECTURE.md#76-ai-assisted-concept-suggestions-flh-097)
and the API in [Appendix A.14](../ARCHITECTURE.md#a14-concept-suggestions-flh-097).
This note records the contract decisions and their reasons.

## 1. Goal

Make accumulated units practical to organise:
1. the owner explicitly selects a bounded batch of reviewable units;
2. the model proposes existing Concepts they may belong to;
3. the stored suggestions can be left and reopened;
4. only an explicit per-item human confirmation changes CURRENT SAME.

## 2. Authority (unchanged)

- `unit_concept_memberships` remains the only CURRENT SAME authority;
  `unit_concept_links` remains the append-only event log.
- Suggestions live in their own tables and write nothing else. The single
  write path into membership is the confirmation, which reuses the existing
  `applySame` event path inside its own revalidating transaction.
- A suggestion by itself is never a label. A confirmed suggestion is a human
  SAME with AI-assisted provenance.

## 3. Decisions

| Topic | Decision | Reason |
| --- | --- | --- |
| Provider | `SUGGESTION_PROVIDER` (`disabled` default, `openai`), reusing `OPENAI_*`; Responses API, strict schema, `store:false`, no tools | Same integration pattern as the extractor; no new provider or fallback |
| Candidates | `concept_suggestion_candidates_v1`: exact signature, then `bm25_retriever_v1`, over non-retired Concepts minus DISTINCT ones, at most 5 per unit, plus at most 2 CURRENT SAME member wordings per Concept | Reuses existing deterministic retrievers; bounded; never the whole catalogue |
| Batch and text limits | 10 units; 1,200 characters of unit text; 800 per Concept; reply body 64 KiB; reason 500 characters | Small enough for one call inside a normal request timeout; oversize is refused, never truncated |
| Outcomes | `suggested`, `no_suitable_candidate`, `uncertain` (model); `no_candidates` (local, not sent) | Honest "no candidate" without a provider call; the UI states candidates were limited |
| Output validation | One answer per supplied unit, no foreign or duplicate unit, a suggested Concept must be one of that unit's candidates, non-empty bounded reason | Learner content is untrusted input; IDs must not be invented |
| Request identity | UUID `Idempotency-Key` required; the committed run (completed **or failed**) is the key's answer; same units replay, different units `409`; in-progress `409` | Reuses the FLH-029 committed-receipt pattern; a lost answer is looked up, not paid for twice |
| Failure | Failed run receipt with a code only (`provider_timeout`, `provider_unavailable`, `invalid_output`); no items; `502`/`504` return it | Distinguishes a known failure from an unknown outcome; nothing partial |
| Transactions | Source state read, provider called, then one write transaction for the run | No SQLite transaction is held across the provider call |
| Staleness | Derived on read and enforced at confirm: unit not in current extraction, unit has CURRENT SAME, unit INVALID, target retired, target signature changed, DISTINCT recorded since | The suggestion recorded the source extraction and candidate signatures, so changes are detectable |
| Confirmation | Body names the Concept; one transaction: write lock, replay existing confirmation, revalidate, human SAME, receipt `UNIQUE(item_id)` | Explicit, attributable, at most one semantic event per item; never reassigns |
| Evidence | `reason: human_same_ai_suggestion` with item, run and generator | Provenance without independent authority; M12 evaluation leaves it unclassified, so retrieval-chosen candidates never become retrieval truth |
| Leave unused | Client-side only; no request | Not DISTINCT, not INVALID, not any judgment |
| Bulk acceptance | Not provided | Each confirmation is a separate human decision |

## 4. Files owned

- Migration: `migrations/013_concept_suggestions.sql`.
- Backend: `internal/domain/concept_suggestion.go`, `internal/suggester/`,
  `internal/application/concept_suggestion_service.go`,
  `internal/storage/sqlite/concept_suggestion_repository.go`,
  `internal/transport/http/concept_suggestion.go`, plus small edits to
  `internal/transport/http/handler.go`, `cmd/server/main.go`,
  `internal/config/config.go` and `internal/publicdemo/database.go` (demo
  artifacts must hold no suggestion rows).
- Frontend: `web/src/pages/ConceptSuggestions.tsx`,
  `web/src/pages/suggestionRequest.ts`, `web/src/types/suggestion.ts`, plus
  edits to `web/src/api/client.ts`, `web/src/App.tsx`,
  `web/src/pages/annotationOperation.ts` (shared UUID helper), the i18n
  catalogues and `web/src/styles.css`.
- Configuration: `compose.yaml`, `.env.example`, `scripts/daily/`.
- Tests and documentation: see the validation report.

## 5. Not in scope

No automatic or background generation, no retries, no bulk acceptance, no
learned resolver or training, no new retrieval experiment, no embedding or
semantic candidate source, no change to entry, analysis, feedback, extraction,
identity, admission or retrieval semantics, and no change to the public demo.
