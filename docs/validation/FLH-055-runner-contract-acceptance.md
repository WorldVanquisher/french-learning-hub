# FLH-055 — independent acceptance of FLH-052 runner fixes

**ACCEPTED for the supplied runner contract.** Required behavior was checked
through actual CLI results, independent Go overlays, server-side counters,
raw-hit metric reconstruction and byte-preservation assertions. This conclusion
does not come from harness exit alone. No reproduced runner defect remains in
this bounded acceptance. The deadline is cooperative, not a hard process limit.

2026-10-12. Owner: NAS Codex. Actual `pwd`:
`/home/worldvanquisher/workspace/flh-nas-codex`. Read `AGENTS.md`; no Git/GitHub
commands or subagents. Supplied branch
`test/flh-055-runner-contract-acceptance` was not inspected. FLH-054 is outside
this baseline and was neither awaited nor reviewed. Only four files changed:
`scripts/validation/flh051/{accept.py,README.md,deadline_test.go.txt}` and this
report. Production, FLH-048, frozen FLH-045, dependencies/model service/shared
docs and the historical FLH-051 report remain unchanged. No Qdrant audit was run.

## Changed harness expectations

The historical [FLH-051 report](FLH-051-experiment-runner-acceptance.md) remains
NOT ACCEPTED for its historical baseline; this report records acceptance of the
subsequent fixes. The retargeted harness no longer asserts that defects survive.

| Scenario | Historical observation asserted by old harness | Corrected requirement / observed result |
| --- | --- | --- |
| Offline `-timeout 1ns` | Exit 0, completed baselines with metrics | **Exit 1**; all three failed, first query errors before Retrieve, remaining 55 not run, every metric slice null |
| Modified fixture + its own asserted hash | Exit 0, misleading frozen-match summary | **Exit 2**, no output; the caller assertion cannot replace the compiled reference |
| Schema / standalone explanation | v1 freeze fields; no structural explanation in generated summary | **v2** frozen-reference fields checked against literal frozen SHA; summary agrees and explains the exact-zero cause |
| Delayed retriever / invalid duration | Not independently tested | New owned overlay tests zero-work expiration, cancellation, late-result discard and completion check; CLI rejects zero/negative durations |

The existing production bridge, metadata perturbation, ordering, candidate
validation, metric oracle, fake endpoints and output checks were retained. The
new `.go.txt` file is injected through a temporary Go overlay; no virtual file
exists in production or FLH-048. Expected/actual command exits are now recorded
explicitly, along with named Go pass events and an `acceptance.json` artifact.

## Requirement adjudication

| Requirement | Independent evidence | Result |
| --- | --- | --- |
| 1. Already expired: no work, stop later queries, no partial metrics | Controlled context-ignoring retriever receives **0 calls**. Actual CLI at 1ns has three failed offline rows: Q001 error before Retrieve, duration 0, Q002–056 not run/no hits. With embedding enabled, all four fail and the counted server receives **0 requests/0 positions**. All overall/split/language/split-language/family metrics are null. | PASS |
| 2. Late context-ignoring result discarded | Independent retriever returns a valid first hit, then synchronously sleeps **200 ms** for call 2 under an **80 ms** context deadline. Actual elapsed **200.730 ms**, two calls, first hit retained, second hit discarded with explicit timeout error, remaining 54 queries not run. All metric slices null. Empty-work terminal completion check also fails an expired context rather than declaring success. | PASS, cooperative only |
| 3. Zero/negative configuration | Actual binary with `-timeout 0` and `-timeout -1s`: **exit 2**, no output directories. Existing tests additionally cover 0s and −1ns. | PASS |
| 4. Immutable freeze / v2 agreement | Modified copy SHA `4b806bba…8518` + own assertion: **exit 2**. Same copy + compiled assertion: **exit 3**. Same copy without assertion: **exit 3**. Frozen input + compiled assertion: **exit 0**. JSON schema v2 records the compiled frozen SHA, separate caller assertion and true frozen match; summary agrees. Legacy expected/match fields are absent. | PASS |
| 5. Structural exact-zero explanation | JSON reports 24/24 Concepts scoped/featured, 0/56 derived candidates scoped/featured, exact-match-possible=false. Generated summary contains the same note: scope/features are part of signature, so unscoped derived candidates cannot match this fixed catalog. No target identity copying or semantic-quality interpretation. Raw exact results are empty; N=48 metrics are measured zeros. | PASS |
| 6. Parity / separation / ordering / metrics | Independent virtual bridge calls actual unexported production converters: all 56 queries and 24 documents agree. Perturb targets/reasons/status/language/tags/free text and reverse arrays: all four rankings/provider text batches unchanged while evaluation changes. Stable IDs and equal-score ties verified; seven bad candidate/rank cases rejected. Python independently reconstructs all metric fields/slices from raw hits. | PASS |
| 7. Provider failures / caps / outputs / preservation | Counted loopback modes retain the successful first query when batch 2 fails, stop subsequent requests, and publish no failed embedding metrics. Timeout/malformed/count/dimension/index/nonfinite failures stop after one request. Under-cap configuration sends zero requests; direct runtime cap refuses before the second submission. Output collision/symlink/default modified-input checks refuse honestly. Hash checks preserve all source inputs and historical report. | PASS |

Independent deadline evidence retains every query status/hit/error and expected
versus actual call counts in `deadline-evidence.json`. The delayed call was not
interrupted at 80 ms; it completed near 200 ms and its result was then discarded.
`RunRetriever` checks context before/after each synchronous call and before
completion (`rank.go:125–193`). A truly hung context-ignoring retriever can still
hang the runner. Setup/report I/O is not forcibly interrupted either. The
harness's separate 90-second subprocess timeout is not a runner guarantee.
This accepted limitation is also stated in the runner's v2 `timeout_limit`.

## Raw-hit reconstruction and counted fakes

The Python oracle derives ranks from raw retained hits joined to frozen proposed
targets, then checks the runner's ranks, counts and metric fields. It does not
trust reported aggregate values as its input. **40 completed retriever reports**
were checked across successful runs and baseline rows preceding provider
failures. Failed/unavailable rows were separately required to have all metric
slices null. Null is not converted into measured zero.

| Untuned existing retriever | N | Hits @1/3/5 | Recall @1/3/5 | MRR@5 |
| --- | --- | --- | --- | --- |
| exact_signature_retriever_v1 | 48 | 0 / 0 / 0 | 0 / 0 / 0 | 0 |
| weighted_lexical_retriever_v1 | 48 | 14 / 26 / 30 | .291667 / .541667 / .625000 | .421527777778 |
| bm25_retriever_v1 | 48 | 15 / 30 / 32 | .312500 / .625000 / .666667 | .460763888889 |

Development=32, held-out=16, fr=en=24; split-language Ns are 16/16/8/8.
All slice hit counts and reciprocal-rank sums reconcile. Four ambiguous and
four no-match cases remain unscored, with alternative ranks/returned counts
checked independently. Rank 6 contributes zero to MRR@5; an empty population
has null metrics. Author-proposed labels remain awaiting human review.

Repeated Linux ranking digests remain:

```text
exact    b5e926948ae4ba8ec46dabf8100cef6e781628fbbe57124e3297be939366f3b3
lexical  2daa58dab4c7b85477c2bb716b789037c5f772c693cc5988a0d61b08360ca0b3
BM25     c6e88774e27cb97b4b64e0b79e4f4553cccf310324560187b2e7c1979d2480d5
```

Fake success: 56 requests, 1,400 positions, 80 unique text hashes, dimensions [2].
Server-side text arrays/counts match the runner and independent Go capture.
Second-call HTTP 503: two requests/50 positions; first query raw hits retained,
second query error, remaining 54 not run and embedding metrics null.
Per-request 1s timeout and overall 200ms timeout: one request/25 positions each,
no further requests or embedding metrics. Wrong count, empty/unequal/wrong-size
vectors, duplicate index and NaN JSON: each one request and failed row.
Cap 1399 versus planned 1400: exit 2, zero requests/output. Runtime cap 26:
one 25-position batch, second batch refused, no retry/fallback/partial metrics.
Expired-all case is stronger: zero server requests and all four rows failed.

These are mechanics, not embedding quality. No real model, paid call, download,
secret or personal/daily data was used. There is no production-policy evaluation
or human approval claim. The small correlated, author-visible holdout and
FLH-049's human-review requirements remain relevant to future experiments.

## Commands and retained acceptance record

Linux amd64, Go `go1.27.1-X:nodwarf5`, standard-library Python 3.14.7. Used cached
dependencies only, with `GOPROXY=off GOSUMDB=off` and the writable temporary cache
retained by FLH-049. Full final command, executed with loopback permission:

```sh
GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off python3 -B scripts/validation/flh051/accept.py --output /tmp/flh055-acceptance-final
```

Harness exit 0; independently inspected **31 expected/actual command results**,
all matching. Existing tests: **28 top-level + 32 subtests pass**, no failures or
skips. Independent overlay: **3 top-level + 11 subtests pass**, no failures or
skips; the four deadline subtests are new. Exact child argv, exits, timing and
stdout/stderr are retained in `commands.json`. Key executed child commands:

```sh
go build -o /tmp/flh055-acceptance-final/runner ./scripts/validation/flh048
go test -json -count=1 ./scripts/validation/flh048
go test -overlay /tmp/flh055-acceptance-final/overlay.json -json -count=1 -run '^TestFLH05(1|5)' ./scripts/validation/flh048
/tmp/flh055-acceptance-final/runner -out /tmp/flh055-acceptance-final/offline-expired -timeout 1ns
/tmp/flh055-acceptance-final/runner -out /tmp/flh055-acceptance-final/timeout-invalid-0 -timeout 0
/tmp/flh055-acceptance-final/runner -out /tmp/flh055-acceptance-final/timeout-invalid-negative-1s -timeout -1s
/tmp/flh055-acceptance-final/runner -fixture /tmp/flh055-acceptance-final/external-fixture/fixture.json -expect-fixture-sha256 4b806bba7ad294dc1b6f6196ade3e146d7ace11ca70137abbe16c9c816098518 -out /tmp/flh055-acceptance-final/digest-override
```

Outputs are isolated in `/tmp/flh055-acceptance-final`: raw per-query reports,
provider request ledgers/counters, deadline evidence, independent metrics,
expected/actual observations, source hashes and a 115-artifact hash manifest.
The initial `/tmp/flh055-acceptance` run reached all runner checks but failed
while assembling the final harness record: package-level Go pass has no Test
name, producing `None` in a sorted set. Filtering those events fixed the owned
harness bug; the full final rerun passed. No acceptance artifact was issued for
that failed attempt, and its raw evidence is retained. A malformed patch attempt
also failed before editing files; it was corrected without touching implementation.

Selected final SHA-256:

| Artifact relative to final output | SHA-256 |
| --- | --- |
| acceptance.json | `d51f527d1fa317a137b125cad11e88fdd26876b552951dc6693cc795c4c35e03` |
| deadline-evidence.json | `f3ec2ea94a880bbcee25dc27791ffb789c961e3d87f3b64fa5a21d5b9360a4b3` |
| offline-a/report.json | `9470f292dfb769a0f456d74f95979d84b15a91441df1ef71471ca042cd32de76` |
| offline-expired/report.json | `e1315fe91ed448e48c7bfe34ddd8571c7d3346bff3c6094244cea8aaccebda4c` |
| fake-expired_all/report.json | `1838e3a5ce0a64e4d02296ed63af131115828bbef50756438dcc1b0648dc92d9` |
| commands.json | `97ee54a24ec154f34bab4e4d73fe4718f0a306ffb0d6c1a057aa5eea791b2a48` |
| independent-metrics.json | `98a0f8b58a6c8ba331b0592de4559790372a982b0df2f050d93ecaf2189ce293` |
| artifact-sha256.json itself | `2ab7cd6327bf1ed7c9c693cfe25e10d871c8b82177607d4e4ded3b0d4ead9e1d` |

Preservation inventory contains 18 files: five FLH-045 files, 12 FLH-048 files
including nested test data, and historical FLH-051 report. Before/after hashes
match. Historical report remains SHA
`d7f32c764c21821f2a731edf22d3e0823f87bcf973a676dc0c1e5b1f83a1af8d`;
frozen fixture remains
`92726376c7892ef5e7eb539648828eab3ccf9d026912a4a5509dc461c3b7043a`.
Thirteen behavior-source hashes remain in each report; input rendering hash
remains `a2e995fe467644b3a8a806a645a0a4a6c348f55aeeb7925dcc4de6f0a2445a55`.

Fake servers/threads shut down; timed-out handlers completed; repository symlink
removed; no virtual Go source was written to production/FLH-048. Raw artifacts,
binary and the deliberately modified unreviewed copy remain in isolated output.
No repository-wide formatting or unrelated checks were performed.
Final read-only verification passed: explicit acceptance/deadline assertions,
all 115 artifact hashes, all 18 preservation hashes and all 13 behavior-source
hashes match current bytes. Python AST and four-owned-file whitespace/newline
checks pass; `gofmt -l` on the three owned overlay source files prints nothing.
`README.zh-CN.md` exists and needs no shared-documentation change for this audit.

Handoff: runner fixes accepted within the cooperative-deadline scope; retain
the historical audit and rerun this harness after contract/converter changes.
Stop editing at delivery. The human owns all integration and Git operations.

```sh
git add -- scripts/validation/flh051/accept.py scripts/validation/flh051/README.md scripts/validation/flh051/deadline_test.go.txt docs/validation/FLH-055-runner-contract-acceptance.md
```

Suggested commit message:

```text
test: accept runner deadline and frozen-fixture contract fixes
```
