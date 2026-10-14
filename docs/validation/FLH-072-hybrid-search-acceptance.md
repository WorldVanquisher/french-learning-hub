# FLH-072 — Integrated hybrid Concept search acceptance

**PASS for production HTTP/CLI mechanics with real Qdrant and fake embeddings.**
**Browser interaction BLOCKED / NOT RUN:** no existing browser executable,
Playwright package or browser cache was available. HTTP and JSDOM are not DOM
acceptance. Fake-vector rankings prove nothing about relevance; no hybrid quality
improvement, real-model, Windows/GPU, AWS or paid-provider claim is made.

2026-10-14. Owner: NAS Codex. AGENTS.md and FLH-071 contract/validation read.
Actual `pwd`: `/home/worldvanquisher/workspace/flh-nas-codex`.
Supplied branch: `test/flh-072-hybrid-search-acceptance`, not Git-inspected.
Only this report and `scripts/validation/flh072/{accept.py,README.md}` changed.
No production/shared-doc edits, Git/GitHub commands or subagents.

## Acceptance by area

| Area | Verdict | Actual evidence |
| --- | --- | --- |
| Production wiring, web and CLI | PASS | Actual cmd/server with fresh built assets and SEMANTIC_SEARCH=qdrant; root, /api, JS/CSS assets and hybrid route work. Actual semantic-index CLI embeds/publishes 15 synthetic Concepts |
| Fusion, evidence and bounds | PASS | Independent oracle matches 23 same-depth keyword/semantic/hybrid comparisons, six ties, ID ascending order, union deduplication, exact component evidence, null absent components, limits/depth and filters |
| Read-only search | PASS for measured stable groups | Full logical SQLite dump and publication pointer unchanged across all 23 groups; keyword makes zero provider calls, each semantic/hybrid request embeds one query, never a document |
| Failure/staleness/publication | PASS | Provider-offline and Qdrant-down failures explicit; unbuilt/incompatible 409; stale and retired authority rechecks; one replacement succeeds on new publication, two replacements fail500 without keyword fallback |
| Restart/sync/cache | PASS | Persistent database/publication/gateway counters survive stop/start; unchanged sync verifies without publishing; repairs/rebuilds reuse all15 cache vectors with zero embedding calls |
| Actual browser Hybrid interaction | BLOCKED / NOT RUN | No Chromium/Chrome/Firefox executable, Playwright package or ms-playwright cache. Existing JSDOM interaction tests pass separately |

No production defect was reproduced. **126 adjudicated checks pass**; the
independent score/evidence oracle is additional to the existing test suites.

## Production fixture, arithmetic and authority

Isolated FLH-060 demo: `/tmp/flh072-demo`, fake deployment
`fake-e5-plumbing-only`, 768 dimensions, fifteen Concepts (seven reused FLH-034
plus eight contrast Concepts). The actual production Go server serves newly
built web assets at loopback 19720, gateway 19721, fake service 19722, Qdrant 19723.
Synthetic seeding intentionally writes initial records; measured searches do not.
No daily database or real provider configuration is read.

Real cached image:
`qdrant/qdrant:v1.19.1@sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10`.
Image ID:
`sha256:dd57172b0bbebb29b0a96a37c1f378a317449730c36cdfe68feabe36e740a92b`.
Demo uses `--pull never`, task-labelled container and task-local storage; no image
or dependency installation was needed.

For each stable comparison the harness requests keyword and semantic at **the
same depth**, then independently computes for the union of Concept IDs:
`score(c) = (keyword present ? 1/(60+rank) : 0) + (semantic present ? 1/(60+rank) : 0)`.
It sorts by score descending/Concept ID ascending and applies the separate display
limit. Score tolerance is 1e-14; evidence is checked exactly. It never calls the
production fusion function as its oracle.

Queries include subjunctive, depuis, past, quantity, question and an unmatched
synthetic token; depths1/15/50, display limits1/5/15/50 and all/active/orphaned/
retired filters. Six actual ties are resolved as the oracle predicts. The 23
saved cases verify total_candidates/truncated, deduplicated result IDs, component
positions, matched fields/tier, similarity, source order and current state.
Independent raw-response checks also reconcile component metadata, skipped counts
and publication evidence. Observed absent-component fields: **66 keyword nulls
and four semantic nulls** across displayed results, never manufactured rank0.

A deliberately cloned Qdrant point with a UUID differing from its Concept payload
is rejected as incompatible by the existing adapter before fusion. It contributes
no duplicate Concept or score; sync repairs it entirely from cache. Genuine
within-component duplicate-ID fusion is covered by existing Go tests: real Qdrant
uses one legitimate numeric point ID per Concept, so a distinct foreign point is
not a legitimate second copy. Actual cross-component overlap is merged by ID in
the independent union oracle.

Stable-group SQLite dumps cover annotations, memberships, preferred-unit fields,
embedding cache and index bookkeeping, not just Concepts. Every before/after hash
matches, and publication stays fixed. Twenty-three groups make46 query embedding
calls (one semantic and one hybrid per group); keyword makes none. Controlled
SQLite title/lifecycle changes and operator index repairs occur **between** these
groups, outside read-only assertions.

## Failure, stale-state and replacement results

| Probe | Expected / actual HTTP | Additional observation |
| --- | --- | --- |
| Before index build | hybrid409, semantic409, keyword200 | Zero provider calls |
| Gateway's existing offline switch | hybrid502, semantic502, keyword200 | Two offline refusals, no upstream forward or fallback |
| Owned Qdrant stopped | hybrid502, semantic502, keyword200 | Normal service remains running; own Qdrant storage retained/restarted |
| Invalid q/state/limit/depth | Seven400 responses | Zero provider calls; depth0/51, limit51 and depth<limit rejected |
| POST hybrid | 405 | GET-only contract preserved |
| Changed synthetic title after indexing | 200 | Stale vector counted/dropped; changed title remains keyword-discoverable |
| Synthetic Concept retired | 200 | Active/retired component and fused results honor current state |
| Published collection recreated with dimension4 | hybrid409, semantic409, keyword200 | Cache-only actual sync repairs it |
| One actual publication replacement | hybrid200 | Uses newly published collection, one query embedding, zero document embeddings |
| Two actual replacements | hybrid500 | No results/keyword fallback, one query embedding reused across retry; later semantic/hybrid recover |

All **17 captured non-200 responses** contain no results: seven400, four409,
four502, one405 and one500. Provider-offline is the demo's explicit503 gateway
simulation, not a claim that a real model service was stopped.

Publication tests use a task-owned loopback forwarding barrier (port19730).
Before forwarding an old collection's query, it runs the **actual CLI rebuild**
against real Qdrant; old-collection deletion makes real Qdrant return404. No
response or ranking is fabricated. Double-replacement evidence records two
old-collection query404s and hybrid500 after its existing single retry. Those
intentional concurrent operator rebuilds are test-control writes, not search
triggering index work. Every such rebuild reused15 cached vectors/embedded0.

## Counters, restart and existing suites

Final persistent gateway accounting:

| Counter | Actual |
| --- | ---: |
| Forwarded POSTs | 54 |
| Search POSTs / search-query positions | 52 / 52 |
| Index POSTs / Concept-document positions | 2 / 15 |
| Total forwarded positions | 67 |
| Unit-query / other positions | 0 / 0 |
| Offline refusals | 2 |
| Upstream non-200 / unreachable | 0 / 0 |

All fifteen document positions are the initial CLI build, batches8+7. Searches,
restart, subsequent syncs, repairs, rebuilds and replacement handling add **zero**
document embeddings. Gateway counters persist across process restarts; fake-service
metrics restart with that process and are retained separately, not conflated with
cumulative gateway totals. An offline refusal is not a forwarded POST.

CLI evidence includes initial build embedded15/reused0; duplicate/incompatible
repairs embedded0/reused15; unchanged sync verified_unchanged=true/embedded0;
ordinary and replacement rebuilds embedded0/reused15. Restart retains the same
publication until a deliberate repair/rebuild replaces it. Keyword and semantic
normal behavior continue before/after the fault phases.

Existing relevant tests ran **once**:
- Go application/HTTP Hybrid or Semantic selection: **41 top-level +21 subtests
  PASS, zero failures/skips**.
- KnowledgeLibrary and API client JSDOM tests: **46 PASS in two files**.
- Fresh isolated Vite production build: exit0. Static responses were fetched;
  execution of those assets in a real browser is **NOT RUN**.

## Exact commands, harness corrections and evidence

Executed from actual pwd (frontend commands from `web/`):

```sh
docker image inspect qdrant/qdrant:v1.19.1@sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10 --format '{{.Id}}'
(cd web && ./node_modules/.bin/vite build --outDir /tmp/flh072-evidence/web-dist)
GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off go test ./internal/application ./internal/transport/http -run 'Hybrid|Semantic' -count=1 -json
(cd web && ./node_modules/.bin/vitest run src/pages/KnowledgeLibrary.test.tsx src/api/client.test.ts)
python3 -B scripts/validation/flh072/accept.py --out /tmp/flh072-evidence --work /tmp/flh072-demo --port-base 19720
python3 -B scripts/validation/flh072/accept.py --out /tmp/flh072-followup --work /tmp/flh072-demo --port-base 19720 --resume
```

Image/build/tests exit0. Initial harness exit1: a path-joining bug occurred while
saving the successful one-replacement result, and its earlier “cloned UUID point
must reach fusion as a duplicate” expectation was incorrect. Both are owned
harness issues, not production defects. Initial raw evidence is preserved,
including that failed expectation. Corrected only the helper and ran the targeted
follow-up (exit0,18 checks/two oracle cases), without repeating setup/general
checks/tests. Final adjudication retains108 valid initial checks plus18 follow-up
checks; the incorrect duplicate expectation is excluded explicitly.

The helper imports the unchanged FLH-060 orchestration and adds only cached-Go
build environment plumbing to child launches. Actual demo setup/start/stop/offline
and index operations, CLI argv, reports and provider deltas are retained. The
production binaries and fresh web build remain under `/tmp`; source is unedited.

Evidence: `/tmp/flh072-evidence/`, `/tmp/flh072-followup/` and
`/tmp/flh072-demo/` (SQLite, Qdrant storage, process/log/CLI evidence retained).
**261 artifact hashes** cover HTTP bodies, oracle inputs/results, test/build logs,
provider totals, proxy trace, helper snapshots and cleanup (large binaries/Qdrant
storage excluded). A 113-file source snapshot taken before targeted follow-up
matches current source bytes. Helper parses with Python3.11 grammar and has clean
whitespace. README.zh-CN.md exists; no shared-doc changes were needed.

| Artifact under /tmp/flh072-followup | SHA-256 |
| --- | --- |
| adjudication.json | `fe2e770f44fe4b9a1c1c8f53392524fccdab9425191d6de62801f1076c4aea36` |
| final-provider-state.json | `0e6acb6333b1659581d73abb903abbb4392791211fb7e37e286a158422da7dd9` |
| publication-double.json | `3e8f61f96bfca0b06dd065e783ba9ce4d541ec77baa6a9f3bc383419258064b3` |
| artifact-sha256.json | `e85480ab093b32c47f65efec2a5209aeaed853d7d6e0e6437313cb361dc40172` |

Cleanup independently confirmed: demo stop exit0, no owned PIDs; Docker inspect
of **flh060-qdrant-069ba3630830** exits1 (container removed); ports19720/19721/
19722/19723/19730 all refuse connections. Only work-identified processes and the
work-labelled container were stopped; unrelated services were preserved. Demo
files and evidence remain. Browser interaction remains the sole unexecuted
acceptance area. Editing stops at delivery.
