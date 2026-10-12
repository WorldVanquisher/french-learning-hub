# FLH-051 — integrated experiment runner acceptance

**NOT ACCEPTED.** Two reproduced defects remain: the offline overall deadline
does not stop the run, and an expected-hash override permits a modified fixture
while the summary claims it matches frozen FLH-045. The ranking, converter,
metric, counted-provider and ordinary output-protection checks below passed.
Neither defect was patched by this review.

2026-10-12. Owner: NAS Codex. Actual `pwd`:
`/home/worldvanquisher/workspace/flh-nas-codex`. Read `AGENTS.md`. Branch name
`test/flh-051-experiment-runner-acceptance` is supplied, not independently
inspected. No Git/GitHub commands, subagents, dependency installs, downloads,
real providers, secrets, daily/personal data or browser acceptance. FLH-050 was
neither awaited nor included in this baseline review.

Owned files: this report and `scripts/validation/flh051/{README.md,accept.py,
production_bridge.go.txt,independent_test.go.txt}`. Production, FLH-045, FLH-048,
shared docs and CI remain read-only. No API/schema/dependency change. Acceptance
criteria are the requested converter/input/ranking/metric/failure/output/freeze
checks. Outputs, binaries and deliberately mutated **unreviewed copies** live
under `/tmp/flh051*`; there is no database or production annotation write.

## Reproduced findings

| ID / severity | Location and failure scenario | Impact / owner verification |
| --- | --- | --- |
| F1 — medium, acceptance blocker | `flh048/main.go:133,186–200`, `rank.go:125–145`: actual binary with `-timeout 1ns` exits 0, marks all three offline retrievers completed and publishes their full quality metrics. Context expires before retrieval; existing offline retrievers accept `_ context.Context`, and the runner never checks it. | The advertised overall timeout does not govern offline execution or the completed state. Validate the configured duration and check cancellation before/after Retrieve in the runner; canceled runs must fail explicitly and remain unscored. Verify with `offline-expired` and a controlled delayed offline retriever. No production retriever change is requested by this review. |
| F2 — medium, acceptance blocker | `flh048/main.go:125,165–172`, `inputs.go:Digests`, `report.go:150–151`: a copy with one rationale changed is rejected by default (exit 3), but supplying its own SHA-256 through `-expect-fixture-sha256` permits exit 0. Summary says **“matches frozen FLH-045: true”** for bytes whose hash is `4b806bba7ad294dc1b6f6196ade3e146d7ace11ca70137abbe16c9c816098518`, not the frozen `92726376…7043a`. | This contradicts the frozen-only contract in the README/plan. The JSON comparison is truthfully against the supplied expectation, but the summary misidentifies that expectation as the frozen fixture. Enforce the frozen constant for this runner, or introduce an explicitly versioned alternative-input mode with honest freeze status and reviewed contract. Verify `reject-modified` and `digest-override`; original fixture bytes were never changed. |
| R1 — concrete drift risk, currently passing | `flh048/inputs.go:168–193` mirrors `application/concept_retrieval_evaluation_service.go:279–301`. Existing runner tests do not invoke the unexported production converters. Source hashes identify changes but do not enforce parity. | Independent virtual bridge invoked the **actual production functions**: all 56 queries and 24 synthetic documents agree field-for-field today. Future field/derivation/normalization changes can leave the mirror stale while ordinary runner tests pass. Re-run the owned overlay parity test when either converter changes. Synthetic normal/supported/active document state is an explicit fixture assumption, not a production catalog snapshot. |
| R2 — low, standalone wording gap | Generated `summary.md` prints the exact baseline's measured zero but does not explain its structural cause. The FLH-048 plan/validation document does explain it. | Add a short structural-miss note to the standalone report/summary. All fixture Concepts have nonempty scope/features; `DeriveCandidateIdentity` supplies neither. Exact signatures cannot match in this fixed package. This is not evidence of semantic failure or a reason to copy target identities into queries. |

The test harness exits zero when both passing checks and these observed defects
reproduce. Its verdict remains NOT ACCEPTED. A future fix must change the defect
observations, not relax their intended acceptance requirements.

## Passing independent checks

| Requirement | Observed evidence |
| --- | --- |
| Existing implementations | Actual CLI constructs `NewExactSignatureConceptRetriever`, `NewWeightedLexicalConceptRetriever`, `NewBM25ConceptRetriever` and optional `NewEmbeddingConceptRetriever`. It contains no independent scoring implementation. Independent tests invoke those same retrievers; production files are hashed in each report. |
| Live converter parity | Go `-overlay` adds only a virtual wrapper and independent tests. Wrapper calls the real unexported production converters. All 56 queries agree, including nullable examples and domain-derived identity; all 24 validated/normalized documents agree, including signature/schema/features and declared synthetic state. No overlay source was written into production or FLH-048. |
| Evaluator separation | Mutate proposed targets, rationales, review-status sentinels, language, tags and free text; reverse Concept/query/judgment arrays. Ranking structs remain identical; all four retriever ranking digests and every provider batch remain identical. Evaluation changes. The fake HTTP server's actual 56 received batches equal the independently retained Go batches byte-for-byte as text arrays. No judgment reaches query identity or provider text. |
| Stable mapping / ties | Mapping is C001–C024 → 1–24 and Q001–Q056 → 1–56, independent of array order. Every constant-vector query yields C001–C005 in that order. All retained actual results have consecutive ranks, ≤5 unique in-catalog IDs, finite descending scores and ascending IDs for exactly equal scores. |
| Invalid candidates | Independent injected retriever cases: foreign Concept ID, rank zero, gap, duplicate, NaN score, infinity score and six results. Each stops after one call; following queries are `not_run_after_error`. These are controlled validation tests, not new retrievers or production behavior. |
| MRR boundary / null versus zero | Independent arithmetic test uses ranks 1,3,5,6,miss: R@1=.2, R@3=.4, R@5=.6, MRR@5=`(1+1/3+1/5)/5`; rank six contributes zero. Empty population metrics remain null. Exact's 48 measured misses are numeric zeros; disabled/failed embedding metrics are null. |
| Frozen preservation / ordinary path safety | Five FLH-045 files and eight FLH-048 files hash identically before/after. CLI rejects modified copies by default, repository output, original fixture as output, symlink into the repository, nonempty output, rerun output, adjacent external fixture output and containing-fixture output, all exit 3. Sentinels and existing report files remain intact. Source uses exclusive file creation. F2 concerns the explicit hash override, not overwrite behavior. |

Ranking view has identity and Unit evidence only. Query candidate target is
normalized Unit canonical, intent is Unit kind, scope/features are empty.
Document identity is domain-validated and its signature uses the domain method.
The synthetic document state does not reconstruct lifecycle, support, CURRENT
SAME or admission. This is neither production-policy evaluation nor Knowledge
Library free-text evaluation; `free_text` is not used for these rankings.

## Independent metric reconstruction

The Python oracle joins frozen proposed targets to retained **raw hits**, not to
runner-reported target ranks or hit counts. It then checks those reported fields.
For N=48 single-target cases, Recall@K is targets present at ranks 1…K divided by
N; MRR@5 is the mean of reciprocal ranks within the returned five, else zero.
No ambiguous/no-match case is counted as a positive, miss or true negative.

| Existing offline retriever | N | Hits @1/3/5 | Recall @1/3/5 | Independently recomputed MRR@5 |
| --- | --- | --- | --- | --- |
| exact_signature_retriever_v1 | 48 | 0 / 0 / 0 | 0 / 0 / 0 | 0 |
| weighted_lexical_retriever_v1 | 48 | 14 / 26 / 30 | .291667 / .541667 / .625000 | .421527777778 |
| bm25_retriever_v1 | 48 | 15 / 30 / 32 | .312500 / .625000 / .666667 | .460763888889 |

Independent reconstruction matched all runner fields for **40 completed
retriever reports** across retained success/failure scenarios. Every split,
language, split×language and family slice reconciles to the overall denominator,
hit sums and reciprocal-rank sum. Development=32, held-out=16; French=24,
English=24; development/fr=en=16 each, held-out/fr=en=8 each. Families F01–F12
contribute four positives each; F13/F14 contribute no scored cases. Raw
ambiguous alternative ranks and four no-match returned counts were separately
checked against hits. For lexical/BM25, Q053/Q055 return five and Q054/Q056
return zero; this is descriptive output, not an approved false-positive metric.

Two unmodified Linux runs have identical ranking digests:

```text
exact    b5e926948ae4ba8ec46dabf8100cef6e781628fbbe57124e3297be939366f3b3
lexical  2daa58dab4c7b85477c2bb716b789037c5f772c693cc5988a0d61b08360ca0b3
BM25     c6e88774e27cb97b4b64e0b79e4f4553cccf310324560187b2e7c1979d2480d5
```

Timing fields make raw report hashes differ. BM25's Linux digest differs from
the abbreviated macOS digest in FLH-048's historical report; the observed metrics
agree. This review proves repeatability on this Linux/toolchain, not cross-platform
bitwise score/evidence equality. No semantic-quality or comparative improvement
claim follows from these numbers.

## Counted fake embedding and failures

The actual compiled CLI uses the existing HTTPProvider against isolated loopback
servers. The success fake returns identical two-dimensional vectors for every
text: 56 requests, 1,400 positions, 80 unique text hashes, dimensions [2], zero
failures. Server-side counts and text hashes exactly equal runner counters.
Those vectors deliberately create ties; they encode no language semantics.

| Probe | CLI exit / actual requests | Report behavior |
| --- | --- | --- |
| Constant vectors, cap 1400 | 0 / 56 | Completed, measured metrics; every query returns IDs 1…5 |
| HTTP 503 on second batch | 1 / 2 (50 positions) | First query results retained; second query error; remaining 54 not run; **all embedding metric slices null** |
| 1.5-second response delay, per-request timeout 1s | 1 / 1 (25 positions) | Explicit provider timeout; no retry/fallback/embedding metrics |
| Same delay, overall timeout 200ms | 1 / 1 (25 positions) | Embedding respects context through HTTPProvider; this does not repair offline F1 |
| Wrong count, empty vector, unequal dimensions, configured dimension mismatch, duplicate index, NaN JSON | Each 1 / 1 (25 positions) | Explicit failure, one provider failure, later 55 queries not run, no embedding metrics |
| Preflight cap 1399 versus planned 1400 | 2 / 0 | Refused before output directory/provider call |
| Independent runtime cap 26 | One inner call / 25 positions | Next 25-position batch refused before submission; one cap refusal, failed retriever, null metrics, no retry |

Offline baselines remain separately completed when a later embedding run fails;
they are not fallback outputs substituted for embedding. Independent CLI probes
use no API key; existing self-tests use a synthetic dummy key only. No real
provider credential was used. Errors here contain provider-safe
categories rather than input text/body contents.

## Wording and remaining real-model requirements

FLH-049's warnings remain applicable. Current JSON and generated summary clearly
say exploratory author-proposed synthetic judgments, awaiting human review,
not independently collected human truth, not the production policy, small
correlated data and an author-visible holdout. No proposals were rewritten or
promoted. Standalone structural-zero explanation needs R2; freeze wording fails
F2. Human review of French/English wording, target scope, whole-catalog useful
alternatives and cross-family construction correlation is still outstanding.

Before a real-model experiment:

1. Owner resolves F1/F2 and reruns the acceptance probes; add the structural-zero
   explanation and retain current uncertainty/holdout caveats.
2. Human adjudicates the FLH-049 wording/relevance/scope issues and separately
   freezes reviewed labels, ranking evidence, catalog and grouping. Distinguish
   SAME identity from useful free-text relevance; do not claim production-policy
   eligibility from synthetic proposals or reuse these results as free-text search.
3. Explicitly authorize the chosen provider and bounded experiment. Freeze model/
   immutable revision, dimensions, normalization/tokenizer/truncation, batch and
   timeout limits, query/document representations and submitted-input budget.
4. Retain actual rendered-text/label/source/result hashes, provider call counts,
   model/configuration provenance and latency boundaries. No tuning on the
   correlated held-out families; no generalization claim from this tiny package.
5. Recheck converter parity and source fingerprints on the execution baseline.
   Source hashes alone do not automatically update mirrored construction.

These are unresolved requirements, not an authorization to run a real model.

## Commands, retained evidence and handoff

Linux amd64, Python 3.14.7, Go `go1.27.1-X:nodwarf5`. Used existing cached
dependencies with `GOPROXY=off GOSUMDB=off`; writable cache was the temporary
cache retained from FLH-049. Main acceptance command:

```sh
GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off python3 -B scripts/validation/flh051/accept.py --output /tmp/flh051-acceptance-final
```

Harness exit 0 with printed verdict NOT ACCEPTED; all checks reproduced. It
retains exact argv, exits, timings, stdout/stderr for every command in
`commands.json`. Important executed child commands (from actual pwd):

```sh
go build -o /tmp/flh051-acceptance-final/runner ./scripts/validation/flh048
go test -json -count=1 ./scripts/validation/flh048
go test -overlay /tmp/flh051-acceptance-final/overlay.json -json -count=1 -run '^TestFLH051' ./scripts/validation/flh048
/tmp/flh051-acceptance-final/runner -out /tmp/flh051-acceptance-final/offline-a
/tmp/flh051-acceptance-final/runner -out /tmp/flh051-acceptance-final/offline-b
/tmp/flh051-acceptance-final/runner -out /tmp/flh051-acceptance-final/offline-expired -timeout 1ns
/tmp/flh051-acceptance-final/runner -fixture /tmp/flh051-acceptance-final/external-fixture/fixture.json -expect-fixture-sha256 4b806bba7ad294dc1b6f6196ade3e146d7ace11ca70137abbe16c9c816098518 -out /tmp/flh051-acceptance-final/digest-override
```

Existing tests: **17 top-level + 32 subtests pass**. Independent overlay:
**2 top-level + 7 invalid-candidate subtests pass**, including converter parity,
metadata perturbation, provider inputs, runtime cap and metric-boundary checks.
Offline CLI exits 0; all nine failing fake-provider scenarios exit 1; under-cap
configuration exits 2; output/default modified-input refusals exit 3. Exact
fake-server URLs and complete arguments are retained in commands, not guessed.

Initial existing-test run without sandbox escalation failed to open a loopback
socket (EPERM). Escalated local runs passed; this was an environment restriction,
not a runner regression. Earlier exploratory outputs remain in
`/tmp/flh051-deadline-initial` and `/tmp/flh051-acceptance`; final evidence is
`/tmp/flh051-acceptance-final`. No GitHub Actions execution claim.

Selected final artifact SHA-256 (full 100-artifact inventory is retained in
`artifact-sha256.json`):

| Artifact relative to final output | SHA-256 |
| --- | --- |
| offline-a/report.json | `852ba3ca0e4996af052cab05b62eedb63c1a78b89b40daf8dfa4e9f5dc186816` |
| offline-a/summary.md | `40cd395fc5c4d3891c91d2dcbdb53569540d40bf47b611081de3485233e144a4` |
| offline-b/report.json | `d4f9cc494373203a11dc9b9f1c4c56107dde3f518863ca2c21066384679b1d6c` |
| fake-constant/report.json | `cdc9f28265d1c42a88852f56b5a8b4fbd7a885fcbb90810f3a0f13e242d36f87` |
| fake-constant.provider.json | `c654c6087e82d5d140d2bd8e49ea75a560d1816ce9870623fbf9383872cae7b7` |
| go-evidence.json | `2e35474dfde61a167d599fcc156e0874e7f9eb7354c530526c378e3438b7cfba` |
| independent-metrics.json | `02a798462c36f02007830e019b308d3b0625f93dba9cd8846835dc2443e63e55` |
| observations.json | `59410409951316dc19e7cb5911bbaa27fc11045d8a29ee266fd23d7159cfab85` |
| artifact-sha256.json itself | `1359144f9a6c9a07cfcb48a13713a24fefb9698f331d6466f7354b98bb148153` |

Frozen fixture SHA-256 remains `92726376c7892ef5e7eb539648828eab3ccf9d026912a4a5509dc461c3b7043a`.
Ranking-input SHA-256 is `a2e995fe467644b3a8a806a645a0a4a6c348f55aeeb7925dcc4de6f0a2445a55`.
All 13 source hashes defining the runner's behavior are retained in each report;
all five FLH-045/eight FLH-048 before/after hashes are in preserved-sources.json.
Actual provider text arrays are retained and independently hashed; the runner's
ranking-input hash is not substituted for a provider-text-byte hash.

Fake listeners were shut down, server threads joined, timed-out handlers allowed
to finish, and the temporary repository symlink removed. Virtual Go files do not
exist in production/FLH-048. No bytecode or test output is included in the owned
source directory. Only owned Go probe text files were formatted. Raw artifacts,
binary and mutated unreviewed copies remain isolated for human inspection.
Final read-only verification passed: all 100 retained artifact hashes, all 13
preserved input hashes and all 13 report behavior-source hashes match current
bytes. Python `ast.parse`, five-owned-file whitespace/newline assertions and
`gofmt -l` on the two owned Go text files passed (gofmt printed nothing).
`README.zh-CN.md` exists; this isolated acceptance audit requires no README
behavior change. Earlier probe's repository symlink was also removed.

Handoff: five owned files only; no contract changes. Owner fixes findings and
reruns this acceptance before a real-model run. Stop editing at delivery.

```sh
git add -- docs/validation/FLH-051-experiment-runner-acceptance.md scripts/validation/flh051/README.md scripts/validation/flh051/accept.py scripts/validation/flh051/production_bridge.go.txt scripts/validation/flh051/independent_test.go.txt
```

Suggested commit message:

```text
test: audit integrated experiment runner acceptance
```
