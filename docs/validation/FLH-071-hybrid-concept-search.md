# FLH-071 validation: explicit, explainable hybrid Concept search

Date: 2026-10-14. Working directory:
`/Users/lowx/projects/FLH/french-learning-hub` (macOS arm64). Contract:
[plan](../plans/FLH-071-hybrid-concept-search.md); design:
[ARCHITECTURE §9.4](../ARCHITECTURE.md#94-explicit-hybrid-search-flh-071).

**Not used:** Git/GitHub, subagents, AWS, the Windows runtime, a GPU, Docker,
a paid provider or a real embedding model. No migration was written.

**Test data:** every test uses deterministic fakes and isolated temporary
SQLite databases.

**Not claimed:** relevance or ranking quality. The tests prove mechanics only.

## Implementation summary

- **`internal/application/hybrid_search.go`:**
  - `HybridSearchService` (read-only interfaces only), `ParseHybridSearchQuery`
    and `FuseReciprocalRank`;
  - policy `concept_hybrid_rrf_v1`: k = 60, equal weights 1/1, Concept-ID
    ascending tie-break;
  - depth: default 50 and cap 50 (`limit ≤ depth`).
- **`internal/transport/http/hybrid_search.go`:**
  - `GET /knowledge-library/hybrid-search` returning
    `knowledge_library_hybrid_search_v1`;
  - 503 when not wired;
  - semantic error mapping reused via `writeSemanticError`.
- **`semantic_search.go`:** the index/skipped response builders were extracted
  for reuse. Its response is unchanged, and its existing tests pass unchanged.
- **Wiring:** `handler.go` gains the route and field. `cmd/server/main.go`
  wires hybrid **only** together with semantic search (`SEMANTIC_SEARCH=qdrant`),
  sharing the same `SemanticSearchService` instance.
- **Web:**
  - a **Hybrid** radio in the existing mode selector;
  - `hybridSearchLibrary`;
  - `HybridResults`, which reuses the existing result card. It adds one
    evidence line per result (keyword rank and matched fields, semantic rank
    and similarity, combined score) plus a policy, component and dropped-count
    summary.
  - An empty query requests nothing.

## Automated results

| Command | Result |
| --- | --- |
| `go test ./internal/application/ -run Hybrid -count=1 -v` | 10 PASS |
| `go test ./internal/transport/http/ -run 'Hybrid\|Semantic' -count=1` | ok (4 new hybrid tests plus the existing semantic tests) |
| `npx vitest run src/pages/KnowledgeLibrary.test.tsx` | 10 passed (2 new) |
| `TMPDIR=/private/tmp/flh071-gotmp make verify` | **exit 0**. gofmt; `go test ./...` all ok; `go vet ./...`; server and capture builds; frontend typecheck, **17 files / 217 tests passed**, production build |
| `go test ./... -count=1` with the default macOS `TMPDIR` | everything ok **except** `scripts/validation/flh053` `TestCapsTimeoutAndOptIn` (exit/calls 2/1) |

**The `flh053` failure** is environmental and predates this work, and that
package imports no hybrid code:
- the probe's `outputDir` refuses output whose parent contains a symlink;
- macOS `TMPDIR` is `/var/folders/…`, and `/var → /private/var`;
- with `TMPDIR=/private/tmp/flh071-gotmp` it passes.

It is recorded here, not changed (it is not owned).

**Mutation check of the fusion tests.** Each change was made temporarily, then
restored:

| Mutation | Tests that fail |
| --- | --- |
| `HybridRRFK = 61` | hand-computed and tie tests |
| Descending ID tie-break | tie test |
| Disabling the change re-check | authority re-check test |

The restored code passes.

## What the tests cover

**Fusion arithmetic** (stub components, `hybrid_search_test.go`):
- **Hand-computed overlap.** Keyword returns [10, 20, 30] and semantic [20,
  40, 10].
  - Expected order: 20, 10, 40, 30.
  - Expected scores, within 1e-9:
    - 20 = 1/62 + 1/61 = 0.032522475;
    - 10 = 1/61 + 1/63 = 0.032266459;
    - 40 = 1/62 = 0.016129032;
    - 30 = 1/63 = 0.015873016.
  - Each result's evidence carries its component ranks, tier and fields, or its
    similarity, with null for an absent component.
- **Ties and disjoint lists:**
  - [5] / [3] → 3, 5;
  - swapped pairs [7, 8] / [8, 7] → 7, 8 (equal sums);
  - disjoint [1, 2] / [3, 4] → 1, 3, 2, 4;
  - identical lists keep their order;
  - symmetry `FuseReciprocalRank(1, 2) == (2, 1)`.
- **Empty results:** both empty → 0 results, not truncated. One-sided lists
  keep that component's order.
- **Limit, depth and duplicates:**
  - components are asked for `limit = depth`, and candidates beyond depth are
    ignored;
  - a duplicate semantic id is counted once (`duplicate_component_ids: 1`) and
    keeps its first rank;
  - `limit 2` of 6 candidates gives truncated, total 6; exactly `limit` is not
    truncated.

**Authority and filters:**
- **Re-check after fusion:** a deleted Concept is `missing`; a renamed Concept
  or a state change since ranking is `changed_during_search`. Each is dropped,
  not replaced.
- **State filter:** both components receive the same filter, and a Concept
  whose state changed out of the filter is `filtered_by_state`.

**Real components** (real SQLite keyword search plus the real
`SemanticSearchService` over the existing in-memory index and bag-of-words
fakes):
- the evidence ranks equal each component report's positions, and the fused
  score equals `FuseReciprocalRank`;
- keyword matches appear;
- the published run and collection are unchanged by the search.
- **Stale vector:** a Concept renamed after indexing is dropped by semantic
  (`skipped.stale = 1`) and appears with keyword evidence only.
- **Retired filter:** a retired Concept with `state=retired` yields retired
  results only.
- **One publication:** a rebuild that replaces the publication between the
  pointer read and the query makes semantic retry once, and hybrid reports
  the single new collection.

**Failures:**
- **No fallback:**
  - unbuilt index → `ErrSemanticIndexNotBuilt`;
  - provider timeout and vector store down → errors, with no partial or
    keyword-only result;
  - publication changed twice → error;
  - exactly one semantic call (no extra retry).
- **No provider call for invalid input:** a keyword-invalid query (`à`) or an
  empty `q` makes no embedding call.
- **Parsing:** defaults are limit 20 and depth 50. These are rejected: empty or
  whitespace `q`; a bad state; limit 0 or 51; depth 0 or 51; depth below limit.

**HTTP** (`internal/transport/http/hybrid_search_test.go`):
- **Exact response at the root and under `/api`:** byte-identical bodies, with
  JSON content type. The test checks:
  - the policy object `{version: concept_hybrid_rrf_v1, rrf_k: 60, weights:
    {keyword: 1, semantic: 1}, tie_break: concept_id_ascending}`;
  - the score note ("not a probability or a relevance estimate");
  - the keyword component (`matching` says "not a relevance score");
  - the semantic component (index collection, `health_verified: false`,
    skipped counts);
  - `dropped_after_fusion`;
  - the results: sources in order; a null component, not zero; keyword and
    semantic evidence; counts.
- **Validation:** 12 invalid query strings return 400 without calling the
  service (including over-long `q`, depth/limit bounds, depth < limit).
  Defaults are 20/50. POST returns 405.
- **Explicit failures:**
  - with only the keyword library configured, 503 "needs semantic search" at
    the root and under `/api`;
  - error mapping: 409 not built or incompatible; 504/502 for provider and
    vector-store timeouts or unavailability; 500 for a second publication
    replacement; 400 for an invalid query;
  - an unexpected error is 500, with no provider detail leaked.
- **Real keyword stack through HTTP,** using the FLH-034 SQLite library fixture
  and stub semantic ranks [C2, C3]:
  - keyword `subjonctif` gives C1 (active, 1), C2 (orphaned, 2);
  - hand-computed: C2 = 1/62 + 1/61, C1 = 1/61, C3 = 1/62, in exactly that
    order with those ranks;
  - `/api` equals the root;
  - the orphaned filter excludes active C1;
  - a semantic failure gives 502;
  - the Concept list is identical before and after (read-only).

**Frontend** (`KnowledgeLibrary.test.tsx`):
- **Hybrid run:** the radio, query and Search send only `GET
  /api/knowledge-library/hybrid-search?q=subjonctif`. The browser neither
  fuses nor falls back. The page shows the server order and the evidence lines:
  - "Keyword #1 (found in title) · Semantic #2 (similarity 0.51) · Combined
    score 0.0325";
  - "Not found by keyword · Semantic #1 …";
  - "… Not among the semantic candidates …".

  It also shows the policy and index summary, the dropped counts, and
  open/back with focus restored. GET only.
- **No query:** nothing is requested, and the page says "Type a query, then
  Search, to run a hybrid search."
- **Unavailable:** a 503 shows "Could not run the hybrid search: (503) …"
  with no keyword results region. The exact request carries
  `state=active`.
- **Existing behaviour:** the keyword and semantic tests are unchanged and
  pass.

## NOT RUN

- **Real-browser check:** no browser automation was used here.
- **Real-provider or real-Qdrant run:** this Mac has no Docker and no Qdrant
  binary, and no real embedding service was used. The production server path
  (`cmd/server` wiring) was built but not exercised against a live Qdrant.
- **Relevance comparison:** no relevance measurement of any mode. The
  existing synthetic evaluation labels are not human-reviewed ground truth.

## Demo steps (for a machine with Docker or a Qdrant binary)

These reuse the FLH-060 demo unchanged. Its production server sets
`SEMANTIC_SEARCH=qdrant`, so the hybrid route is wired automatically. Fake
mode embeds nothing real, and its rankings mean nothing.

```sh
npm --prefix web ci && npm --prefix web run build
WORK="$HOME/flh-demos/flh071-hybrid"; D="python3 -B scripts/demo/flh060/demo.py"
$D setup "$WORK" --mode fake --web-dist "$PWD/web/dist"   # add --qdrant /path/to/qdrant without Docker
$D index "$WORK" build
curl -s 'http://127.0.0.1:18960/knowledge-library/hybrid-search?q=subjunctive&limit=5&depth=20' | python3 -m json.tool
curl -s 'http://127.0.0.1:18960/api/knowledge-library/hybrid-search?q=depuis&state=active' | python3 -m json.tool
curl -s -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:18960/knowledge-library/hybrid-search?q='   # 400
$D offline "$WORK" on      # semantic unavailable: hybrid fails explicitly, keyword still works
curl -s -w '\n%{http_code}\n' 'http://127.0.0.1:18960/knowledge-library/hybrid-search?q=depuis'          # 502, no results
curl -s 'http://127.0.0.1:18960/knowledge-library/concepts?q=depuis' | python3 -m json.tool              # keyword unaffected
$D offline "$WORK" off
# Browser: http://127.0.0.1:18960/ → Knowledge Library → Hybrid → search → read each result's evidence line.
$D cleanup "$WORK"
```

**What to check:**
- `policy.version` is `concept_hybrid_rrf_v1`;
- each result's `keyword.rank` and `semantic.rank` equal its position in
  `/knowledge-library/concepts?q=…&limit=<depth>` and
  `/knowledge-library/semantic-search?q=…&limit=<depth>`, run immediately
  before or after on an unchanged database;
- `fused_score` = Σ 1/(60 + rank).

## Limitations

- **The keyword rank is not relevance.** It is the keyword order: identity
  tier before unit evidence, then active, orphaned, retired, then title, then
  id. Fusing it gives alphabetical position some influence within a tier.
  This is documented in the response (`components.keyword.matching`) and was
  deliberately not adjusted, since the first policy is fixed.
- **Candidate pools differ in breadth.** Keyword candidates are all prefix
  matches up to depth. Semantic candidates are the positive-similarity hits
  among `min(4 × depth, 200)` vector hits, after its re-checks. A Concept
  absent from one list gets no contribution from it, so `fused_score` is not
  calibrated across queries.
- **The re-check is not a single snapshot.** It is one SQLite read after both
  components, not a transaction across components, SQLite and Qdrant. A
  change between that read and the count reads is not detected, which is
  consistent with the two existing modes.
- **Cost:** each hybrid search costs one embedding call plus a full keyword
  scan, as running the two modes separately would.
- **Unchanged guidance:** `AGENTS.md` (FLH-040) still lists "hybrid ranking"
  as deferred. This task's explicit authorization covers it, but `AGENTS.md`
  is not owned here, so the human owner may want to update that line.
- **Later comparison:** a human-reviewed query set can compare the three
  modes later without touching annotation truth (ARCHITECTURE §9.4). None has
  been built or run.
