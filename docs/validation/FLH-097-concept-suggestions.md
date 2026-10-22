# FLH-097 — AI-assisted Concept suggestions: validation

Owner: NAS Claude Code. Same working tree as the uncommitted FLH-092 to FLH-095
work, which is kept.

**Status: implemented. Validated with authored synthetic content, isolated
temporary databases, a local fake provider, Go tests and jsdom tests only.**
- **No paid provider call** was made, so real-model suggestion quality is
  **not** evaluated.
- **No browser** was run for this task; browser behaviour is unverified.
- **Not acceptance:** this is not owner acceptance.

Contract: [plan](../plans/FLH-097-concept-suggestions.md),
[ARCHITECTURE §7.6](../ARCHITECTURE.md#76-ai-assisted-concept-suggestions-flh-097),
[API A.14](../ARCHITECTURE.md#a14-concept-suggestions-flh-097).

## 1. What the tests prove

| Requirement | Evidence |
| --- | --- |
| Generation changes no membership or human label | `TestConceptSuggestions_GenerateIsAdvisoryReplayableAndReopenable`: memberships, links, Concepts, judgments, distinctions, admission overrides, preferred units and annotation receipts are identical before and after generation |
| Bounded candidates | Same test: at most 5 candidates, the exact-signature match first; `TestConceptSuggestions_DistinctConceptsAreNotCandidates` |
| A unit without candidates is not sent | Same test: outcome `no_candidates`, and the provider request does not contain that unit's text |
| Request validation, nothing dropped | `TestConceptSuggestions_RequestValidation`: missing/invalid key `400`; empty, 11 units, duplicate, unknown, non-positive and already-resolved units `422` naming the unit; no provider call and no stored run |
| Oversized input rejected | `TestConceptSuggestions_OversizedTextIsRejected`: `422`, no provider call |
| Malformed, missing and foreign-ID output; provider failure | `TestConceptSuggestions_ProviderAndOutputFailuresStoreFailedRunOnly`, 10 cases: HTTP 500, malformed text, missing unit, foreign unit, duplicate unit, foreign Concept, Concept on `uncertain`, empty reason, body over 64 KiB, timeout. Each stores a failed run with the right code and no items, writes nothing semantic, never echoes the API key, and replays under its key without another provider call |
| Concurrent duplicate generation | `TestConceptSuggestions_InFlightKeyIsNotDuplicated`: `409` while in flight, one provider call |
| Persistence and reopening | The first test closes the database, reopens it with the suggester **disabled**, reads the run with reasons, replays the key, and gets `503` for a new key |
| Stale extraction, changed membership, changed target | `TestConceptSuggestions_StaleStateBlocksConfirmation`, 6 cases (new extraction, manual SAME elsewhere, INVALID, retired target, changed signature, DISTINCT recorded). Each shows `stale` on read; confirmation returns `409` with the reason and writes no event |
| Confirmation attribution and duplicates | `TestConceptSuggestions_ConfirmRecordsAttributedHumanSameOnce`: wrong Concept `422`; human SAME with evidence naming item, run and generator; CURRENT SAME updated; repeat is a replay of the same event; 4 concurrent confirmations of another item produce one event |
| Consumers do not treat suggestions as truth | `TestConceptSuggestions_EvaluationDoesNotTreatSuggestionsAsTruth`: before confirmation 0 human SAME; after it, the dataset stays valid, 1 human SAME, 0 evaluation samples, 1 `unclassified_human_same_provenance` |
| Guards are load-bearing | Mutation check: disabling the stale check or the confirmation replay makes the stale and confirmation tests fail (7 failures); restored code passes |
| Provider client | `internal/suggester/openai_test.go`: learner text only in the user role, strict schema, `store:false`, failure classification without leaking the key or learner text |
| Domain rules | `internal/domain/concept_suggestion_test.go`: proposal and unit-list validation, stale error is a conflict, character counting |
| Configuration | `internal/config/suggestion_config_test.go`: default disabled, independent of other providers, key and model required, key never in errors |
| Workbench | `web/src/ConceptSuggestions.test.tsx`, 8 tests: selecting sends nothing and is capped; Generate stores the key **before** one keyed request; disabled server; lost answer survives reload and is looked up, not resent; resend reuses the key; failed run shown and pending cleared; per-item confirm and **Leave unused** with no request; stale refusal re-reads and shows reasons with no confirm control; storage failure sends nothing; no bulk-accept control |

## 2. Commands and results (2026-10-22)

| Command | Result |
| --- | --- |
| `go test ./internal/transport/http/ -run ConceptSuggestions -v` | 9 tests pass (16 subtests) |
| `go test -race -count=1 ./internal/transport/http/ -run ConceptSuggestions` | pass |
| `go test ./internal/suggester/ ./internal/domain/ ./internal/config/` | pass |
| `go test -count=1 ./internal/...` | exit 0 |
| `cd web && NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/ConceptSuggestions.test.tsx` | 8 passed |
| `NODE_OPTIONS=--no-experimental-webstorage make verify` | exit 0: gofmt, Go tests, vet, builds; frontend typecheck, **310 tests in 24 files**, production build |
| `python3 -B -m unittest discover -s scripts/validation/flh079 -p 'test_*.py'` | OK |
| `python3 -B scripts/validation/flh079/run.py --work <scratchpad>/flh097/accept --port 18990` | exit 0, **210 checks passed, 0 failed**; artifact built from this tree including migration `013`; **browser: NOT RUN** (no Chrome or Chromium on this host) |
| `bash scripts/validation/flh094/test_wrapper.sh <scratchpad>/flh097/wrapper` | 26 PASS, 0 failures (docker shim; only `docker compose config` ran for real) |

## 3. Compatibility

- **Migration `013`** is additive (three new tables). Forward-only as always:
  back up before the first start of a binary with it.
- **Public demo:** the migration ledger must match exactly, so artifacts built
  before `013` are refused by a binary with it; rebuild from the same tree.
  Deployed self-contained packages are unaffected. Demo artifacts must hold no
  suggestion rows (`internal/publicdemo/database.go` empty-table list), and the
  demo boundary does not expose the new routes.
- **Existing behaviour:** no existing endpoint, schema column or semantic rule
  changed. Retrieval evaluation and the dataset need no code change; the new
  evidence reason is classified by their existing rules.
- **Compose and daily wrapper:** `SUGGESTION_PROVIDER` is forwarded with default
  `disabled`; the wrapper accepts only `openai` or `disabled` and then requires
  `OPENAI_API_KEY`/`OPENAI_MODEL` like the other providers.

## 4. Limits and remaining work

- **Real-model quality** is unmeasured: the first real runs need owner
  judgement. Candidate recall is limited by exact signature + BM25; a fitting
  Concept with no shared tokens is never offered, which the UI states.
- **Timeouts:** one request covers up to 10 units. `OPENAI_TIMEOUT` (shared)
  must leave headroom and stay below `HTTP_WRITE_TIMEOUT`; otherwise a stored
  run can arrive as an unknown outcome (recoverable by key).
- **In-flight protection** is per server process. A second process on the same
  database could make a second provider call for the same key; only one run is
  stored.
- **Not checked:** browser layout and keyboard flow; the wrapper's new
  `SUGGESTION_PROVIDER` refusal path (reviewed in code; the existing wrapper
  test passes); a real `docker compose up`.
- **Not provided by design:** bulk acceptance, automatic generation, retries,
  a persisted "leave unused" state, suggestions for already-resolved units, and
  a suggestion-quality report.
