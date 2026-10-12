# FLH-058 — One bounded real-E5 exploratory comparison

**COMPLETED: one authorized synthetic model-run attempt; no rerun.**
Every result/table below is an **exploratory comparison against author-proposed
unreviewed synthetic judgments; NOT production evaluation policy; NOT
independently collected human ground truth; small correlated author-visible
holdout, no tuning/generalization claim.** Measured embedding scores do not
prove SAME or useful free-text relevance. Labels remain
`author_proposed_synthetic_awaiting_human_review`; no proposal was rewritten or
human approval manufactured.

Owner: NAS Codex. Date: 2026-10-12. AGENTS.md read; actual `pwd`:
`/home/worldvanquisher/workspace/flh-nas-codex` (Linux amd64).
Supplied branch: `test/flh-058-real-e5-exploration`, not inspected through Git.
Only `scripts/validation/flh058/{explore.py,test_explore.py,README.md}` and this
report were created. FLH-057 was neither awaited nor used. No Git/GitHub commands,
model/dependency downloads, secrets, daily data, production index builds,
service/proxy changes or shutdown of the human's processes.

## Results and populations

All four actual existing Go implementations completed with zero query errors.
Raw hits independently reproduce these metrics; the denominator is **48**
single-target proposals against **all 24 Concepts**. All 56 queries were retrieved;
four ambiguous and four no-match cases are excluded from scoring.

| Existing retriever | Hits @1/3/5 | Recall @1/3/5 | MRR@5 |
| --- | --- | --- | --- |
| exact_signature_retriever_v1 | 0 / 0 / 0 | .000000 / .000000 / .000000 | .000000 |
| weighted_lexical_retriever_v1 | 14 / 26 / 30 | .291667 / .541667 / .625000 | .421528 |
| bm25_retriever_v1 | 15 / 30 / 32 | .312500 / .625000 / .666667 | .460764 |
| embedding_retriever_v1, supplied E5 | 24 / 40 / 44 | .500000 / .833333 / .916667 | .653125 |

Exact zeros are **structural**: all 24 fixture Concepts have scope/features,
while all 56 derived Unit candidate identities lack both. No signature can
match this catalog. These zeros are measured at N=48, not null, and say nothing
about semantic quality. Failed/unavailable runs would have null metrics; none
occurred in the live comparison. MRR@5 averages `1/rank` within returned ranks
1–5 and zero for absent targets; it is not full-catalog MRR.

E5 slices (all other retrievers' corresponding slices are independently checked
and retained in `analysis.json`):

| Slice | N | Hits @1/3/5 | MRR@5 |
| --- | ---: | --- | ---: |
| development | 32 | 16 / 25 / 29 | .635938 |
| held_out | 16 | 8 / 15 / 15 | .687500 |
| English | 24 | 13 / 21 / 23 | .685417 |
| French | 24 | 11 / 19 / 21 | .620833 |
| development/en | 16 | 8 / 13 / 15 | .642708 |
| development/fr | 16 | 8 / 12 / 14 | .629167 |
| held_out/en | 8 | 5 / 8 / 8 | .770833 |
| held_out/fr | 8 | 3 / 7 / 7 | .604167 |

For each retriever, split/language/split×language/family denominators sum to 48;
all hit counts and reciprocal-rank sums reconcile with overall values. Development
32 + held-out 16 and French 24 + English 24 agree with the frozen fixture.
No significance test, tuning or generalization inference was performed.

## Disagreements, not adjudicated relevance

“Fix/miss” below means agreement/disagreement with the existing **proposed target**,
not a new annotation. E5 adds **14** top-five proposed-target hits versus lexical
and **12** versus BM25, with no top-five regressions versus either in these 48
cases. At top one it adds 14 versus each, but loses four lexical matches and
five BM25 matches. Full ID lists are in `analysis.json`.

| Query / proposed Concept | Lexical rank | BM25 rank | E5 rank / observed top result | Observation |
| --- | --- | --- | --- | --- |
| Q001 / C001 imparfait description | absent | absent | 1 / C001 (.880040) | Childhood-weather wording reaches its proposed target |
| Q008 / C004 indirect-object pronouns | absent | absent | 1 / C004 (.878763) | English recipient wording reaches the proposed French Concept |
| Q016 / C008 adverb | 1 | 1 | 3 / C004 (.862219) | Both lexical methods win top one; E5 prefers an indirect-object Concept |
| Q017 / C009 ne…pas | 1 | 1 | 2 / C010 (.882280) | E5 prefers ne…plus; secondary quantity/article relevance remains unreviewed |
| Q020 / C010 ne…plus | 1 | 1 | 3 / C021 (.881418) | “No longer” loses top one to continuing-duration Concept |
| Q022 / C011 est-ce que | 1 | 1 | 2 / C004 (.883878) | Proposed question construction loses top one |
| Q027 / C014 falloir | 3 | 1 | 3 / C013 (.889376) | BM25 wins; E5 prefers personal obligation |
| Q043 / C022 pendant | absent | absent | 2 / C021 (.879812) | Gains top-five target, but still prefers depuis |
| Q045 / C023 partitive article | absent | absent | 3 / C006 (.893448) | Gains target; quantity-pronoun Concept still leads |

Additional top-one regression IDs: lexical **Q016/Q017/Q020/Q022**;
BM25 **Q016/Q017/Q020/Q022/Q027**. E5's four missing top-five targets are
**Q012→C006, Q013→C007, Q015→C008, Q047→C024**; both lexical methods also miss
those targets. E5 top results respectively are C009/C004/C003/C023.

FLH-049 already identified Q017 and Q045 cross-family useful-search alternatives,
Q047–048 negation/article overlap, and Q027's wording ambiguity. These observations
cannot settle Unit SAME identity or a separate useful free-text relevance policy.
Its correlated family/split findings also remain: French/English variants and
related quantity, negation and inversion objectives cross split boundaries.
No larger metric converts the holdout into independently collected human truth.

Unscored E5 ambiguous observations: Q049 C001@3/C002 absent; Q050 C003 absent/C004@1;
Q051 C021@2/C022@1; Q052 both C023/C024 absent. Each returns five Concepts.
Unscored no-match Q053–056 also each return five; their top scores are
.877527/.846017/.884984/.870378. Lexical and BM25 each return results for two of
these four, exact for none. For example, PostgreSQL-backup Q054 returns C001
(imparfait) at .846017. There is no approved false-positive definition here;
positive/high cosine is neither a probability nor proof of SAME/useful relevance.

## Numerical consistency finding retained without adjustment

All **1,400** response vectors are finite, nonzero, normalized and 768-D; norms
range **.9999999243149402–1.0000000839845846**. Independent cosine reconstruction
from all 56 retained response batches reproduces every ordered embedding top-five
list; maximum score difference from Go arithmetic is **3.33e-15** (comparison
threshold 1e-12). Response model and contiguous index order also agree.

**Medium reproducibility finding:** identical document text does not always meet
FLH-056's declared coordinate tolerance `1e-5 + 1e-4*max(abs(a),abs(b))` in these
larger mixed batches. Compared with the first occurrence, **112** repeated
vectors for **C001–C007** violate that tolerance. Maximum absolute difference is
**.00030038319528102875**, C005 in Q003 compared with Q001. The offline `repeats`
check deliberately exits **1** and retains all affected pairs/coordinate counts.
The runner itself has no repeated-vector consistency requirement, so its
completed rankings/metrics are retained honestly; this is an additional limit
on claiming numerical consistency across batch shapes, not a partial-run metric.

`tools/embedding/e5/flh_e5/encoder.py:145` pads each microbatch to its longest
input and executes float16 model inference before float32 pooling/normalization
(lines 156–159). A batch/padding-dependent float16 effect is a plausible explanation,
not an established cause. No extra model call was made to investigate. Prior
FLH-056's smaller-batch repeats passed; that historical observation was not rewritten.
No tolerance was loosened. An owner should define/test acceptable reproducibility
across mixed batch shapes before making stronger vector-cache equivalence claims;
additional model testing requires a new assignment. No ranking difference caused
by this numerical drift has been established.

## Preflight, execution and accounting

Inspected actual CLI/configuration, FLH-052 deadline/freeze implementation,
FLH-055 accepted contract and FLH-056 live acceptance. Re-executed runner tests:
**28 top-level + 32 subtests pass, zero fail/skip**. A read-only independent
FLH-051 overlay rechecks all 56 actual production query converters and all 24
Concept converters; perturbing targets/reasons/status/language/tags/free text
leaves all ranking/provider inputs unchanged while evaluation changes.
Each actual POST's input array exactly matches that preflight Go-rendered capture.
No evaluator target, judgment, split, language label or reason was added to model
text. Concept identity targets and evidence-derived candidate targets are legitimate
ranking fields; labels do not supply them. Query/Concept JSON remained unchanged;
only the existing service applies query/passage roles and prefixes.

Exact live identity, verified against fresh before/after manifests:

```text
http://100.118.109.6:8765/v1
multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/flh_e5_role_prefix_v1/float16/dd0889c6f1869f7f
```

Full canonical manifest digest matches
`dd0889c6f1869f7fe3bcaf85e40713b99cd21812342155be9eac55222313bb56`;
LF-normalized local contract/encoder/manifest code identity matches
`96ab7c27ec6e18ec98cbafd3c8f3aac39c72f317110b98887d24d95d5e466bc0`.
Both fresh readiness reads are ready; manifests are byte-identical. This verifies
public identity/source consistency, not independent Windows hardware attestation.
The FLH-056 HTTP search response-field issue is outside this Unit-to-Concept task.

Exclusive `/tmp/flh058-budget-reservation.json` reserved the complete budget
before POSTs and persists. **56/56 POSTs and 1,400/1,400 positions consumed.**
Runner exit 0; observed provider dimensions [768], zero failures/cap refusals.
A local recording forwarder enforces both hard caps, compares each array to the
capture, forwards the original request/response bytes, and disables upstream
proxies/redirects/retries. Runner base is its loopback address; the separately
recorded upstream is the exact authorized endpoint. No prefix/text/target was
rewritten and no provider substituted.

| Fresh service counter | Before → after | Delta / client reconciliation |
| --- | --- | --- |
| total / successful requests | 8→64 / 6→62 | 56 / 56, client 56 attempts |
| accepted positions | 13→1413 | 1400, client 1400 submitted |
| query / passage roles | 5→61 / 8→1352 | 56 / 1344 |
| distinct input hashes | 7→87 | 80, client 80 unique strings |
| encoder computations | 6→230 | 224 = 56×(8+8+8+1 positions in four microbatches) |
| errors / truncations / overlength | unchanged / 0→0 / 0→0 | 0 / 0 / 0 |

80 unique texts are **56 Unit queries + 24 repeated Concepts**. Computations
are service-reported encoder microbatch calls, not 1,400 independent document
computations and not a cache-hit claim. The 224 include repeated Concept encoding.
Service encode-time delta is 2.014s; end-to-end runner process elapsed 13.628s,
embedding Retrieve total 13.599s, median 236.637ms. These include transport and
forwarding overhead and are not a GPU throughput benchmark.

Numeric configuration was fixed before POSTs: K=5, dimensions 768, overall 120s,
runner request 10s, upstream 8s, subprocess 150s, float16 deployment microbatch 8;
BM25 k1=1.2/b=.75; existing lexical/BM25 canonical/target weights4, statement2,
other identity-field weights1. No tuning. Runner timeout is cooperative before/
after Retrieve; the orchestrator's subprocess deadline is a separate bound.
The deadline was not reached. The forwarder stopped; the human service remained
ready. All **38** source/input/historical-file before/after hashes agree.

## Reproducible commands and retained artifacts

All commands ran from actual pwd above. Go preparation uses cached dependencies:
`GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off`.
No Qdrant audit or Knowledge Library search was run.

```sh
python3 -B scripts/validation/flh058/explore.py prepare --out /tmp/flh058-real-e5-exploration
python3 -B -m unittest discover -s scripts/validation/flh058 -p 'test_*.py' -v
# Historical executed command; do not repeat: model budget is exhausted.
python3 -B scripts/validation/flh058/explore.py run --out /tmp/flh058-real-e5-exploration --allow-one-model-run
python3 -B scripts/validation/flh058/explore.py analyze --out /tmp/flh058-real-e5-exploration
python3 -B scripts/validation/flh058/explore.py repeats --out /tmp/flh058-real-e5-exploration
```

Exits: prepare0, helper tests0 (five tests), run0, analyze0, **repeats1** (preserved
consistency finding). Helper tests verify caps, unchanged bytes, one attempt on
upstream timeout, MRR truncation/null-zero and reservation refusal before network.
Final helper tests also pass; both helpers parse with Python3.11 grammar.
Child argv/exits/times/stdout/stderr are retained in per-command JSON/text files.
Actual runner invocation used `-embedding http -embedding-max-inputs 1400
-embedding-dimensions 768 -embedding-timeout 10s -timeout 120s`, exact deployment
and compiled frozen-hash assertion, through `http://127.0.0.1:45575/v1`.
The helper's retained `live-command.json` is the exact complete argv; the runner's
own `run.command` formats it as `go run` even though the built binary was executed.

Evidence outside repository: `/tmp/flh058-real-e5-exploration/` — raw per-query
hits/scores/evidence/errors/durations, all 56 original wire request/response pairs,
manifest/readiness/metrics snapshots, capture, numeric config, reservation,
independent metrics/slices/disagreements, consistency failures and helper snapshots.
**214 artifacts plus final hash manifest**, all hashes verified. Initial
`artifact-sha256.json` is preserved; `final-artifact-sha256.json` additionally
covers supplemental offline consistency checks/logs/helper snapshots.

| Artifact | SHA-256 |
| --- | --- |
| frozen fixture | `92726376c7892ef5e7eb539648828eab3ccf9d026912a4a5509dc461c3b7043a` |
| ranking inputs (runner encoding) | `a2e995fe467644b3a8a806a645a0a4a6c348f55aeeb7925dcc4de6f0a2445a55` |
| rendered-input stream (length-prefixed UTF-8, all positions) | `76e39e062bca7f1d7fc177ed0cda38f72309c5b9567ec62103165039140f466f` |
| configuration.json | `87a216c07707e1a84e32680bdeb0b60a13e5c1c0491e56a05e652497bf9431ec` |
| live/report.json | `22ff88a0200cd75245aeb5fdebfd61c12677fa2687fadf8932c625aa6bc379e3` |
| analysis.json | `b4e16bf43d84c392e8993b8971cb5288ef8dded7e252f4d07b41f7fb4c1606ff` |
| repeat-consistency.json | `44f51028fc1d43e80cc9ee7772c3a9089050752962e17147253a7abe52420b1e` |
| final-artifact-sha256.json | `3434dab827276243a2e375d3c154c184397ea3136abfbd7535dfcbf956b5c0ac` |

Offline baseline ranking digests match both preparation and FLH-055 Linux results;
embedding ranking digest is
`01f4dc63283ed8ff288674533ee918608d1a84e288b52b228fd22e44e0907544`.
No experiment was repeated. README.zh-CN.md exists; shared README setup was unchanged.
Remaining work requires separately authorized numerical-consistency investigation
and human adjudication of synthetic labels/relevance and correlated holdout design.
No production-quality or generalization acceptance follows. Editing stops at delivery.
