# FLH-049 — independent evaluation and real-Qdrant CI review

2026-10-12. Owner: NAS Codex. Actual `pwd`:
`/home/worldvanquisher/workspace/flh-nas-codex`. Read `AGENTS.md`; no Git/GitHub
commands or subagents. Branch name `audit/flh-049-evaluation-and-ci` is supplied
by the human, not independently inspected. FLH-048 was neither awaited nor
audited. This review creates only this report and
`scripts/validation/flh049/{README.md,probe.py}`. No production contract,
dependency, migration, shared documentation, CI helper/workflow or frozen
fixture was changed. Test databases are Go `t.TempDir` databases; output and
copied sources are isolated under `/tmp/flh049*`.

Acceptance criteria: inspect all 24 Concepts and 56 query/judgment pairs against
the whole catalog; identify concrete linguistic/relevance/leakage issues; attack
validator boundaries; verify current policy/metrics; observe the eight expected
tests against the pinned image; independently enforce unavailable/skip/zero/fail/
timeout cases and check cleanup. Proposed labels remain **unreviewed**. This
automated review is not human approval or production annotation authority.

## Adjudication table

Severity: high blocks reviewed benchmark use; medium requires a targeted review
or correction; low is wording/coverage refinement. Findings are recommendations,
not applied changes.

| Finding | Location / concrete case | Severity and impact | Proposed revision / verification |
| --- | --- | --- | --- |
| Whole-catalog review cannot be represented by the current family restriction | `flh045/validate.py:182`; Q017/J017 → C009, with useful search alternative C024; Q045/J045 → C023, with contextual C006 | High for a reviewed free-text benchmark. The catalog is fixed at all 24 Concepts, but positive, possible and negative references must stay in the query family. Even adding a cross-family hard negative is rejected. | In a separately versioned reviewed artifact, allow whole-catalog judgments and record SAME versus useful-search relevance separately. Treat split grouping as a distinct check; do not silently move held-out families. Reproduce `cross_family_alternative` (exit 1). |
| SAME and useful search results are different | Q017 C009/C024; Q037–038 C019/C012; Q045 C023/C006; Q047–048 C024/C009 | High if labels are reused between protocols. Negation, inversion and quantity-pronoun explanations can help with the complete sentence while remaining different durable objectives. | Retain the focused proposed SAME targets pending human review. Review secondary free-text results under a separate relevance definition; do not turn these alternatives into SAME, DISTINCT or membership records. |
| Questions are being proposed as atomic Unit evidence | All Q001–056; e.g. Q049–052 have underspecified questions, not durable assertions | High before Protocol A execution. An information need does not establish an admitted Unit or a human SAME label. | Human-review objective, atomicity, kind and scope; separately authorize synthetic application setup. Do not auto-ingest the proposals or manufacture human memberships. |
| Answer-rich synthetic wording and partial identity copying escape the guard | All 48 single-target cases contain examples; Q021–024, Q028, Q037–040, Q048 especially disclose the construction or answer | Medium: easy, constructed retrieval inputs may overstate readiness for naturally authored questions. This is not evidence that authors copied serialized identity. | Preserve this frozen version; propose a second answer-free information-need set and independently authored Unit evidence. Do not remove examples from genuine Units solely to improve a score. Mutation copying C001 target + scope but omitting `background` passes. |
| Family holdout is structurally intact, semantically correlated | Development F03/F05/F06 versus held-out F12/F10/F09: Q011–012 ↔ Q045–046, Q017 ↔ Q047–048, Q023–024 ↔ Q037–038 | Medium: quantity, negation and inversion constructions cross split boundaries. These are distinct SAME objectives, but related retrieval cues; a family ID alone cannot prove semantic independence. | Explicitly declare this a related-objective query holdout, or regroup connected construction families in a new reviewed version before tuning. Do not claim a blinded/generalization benchmark. Mutation rewriting held-out Q041 to a past-background question passes. |
| Concept scopes need narrower linguistic boundaries | C006 “quantité avec de”; C014 “nécessité avec il impersonnel”; C024 “quantité niée sans contraste” | Medium. Numeric `J’en ai deux` has no overt `de`; `il` alone does not define the falloir construction; negation with être needs an explicit exception boundary. | C006: “reprise d’un nom associé à une quantité, y compris nombre conservé”; C014: explicitly name falloir + infinitive for this fixture; C024: explicitly exclude être and contrast. Human-check identity changes as new proposals, never rewrite durable production identity. |
| French/English prompts contain avoidable ambiguity | Q027/C014 does not constrain its free text to falloir; Q030/C015 and Q032/C016 ask an English gap; Q048/C024 uses the technical cue “no contrast or être” | Medium for relevance, low for wording. Other necessity expressions or English relatives can answer the literal request. Q048 preconditions heavily reveal the intended rule. | Q027: “Avec il impersonnel, comment exprimer qu’il est nécessaire de partir ?”; Q030/032: include the actual French gap; Q048: use an ordinary French negative sentence, record the exception boundary in reviewed metadata. |
| Small wording inconsistencies | Q023/C012: “où vous suit venez”; Q026/C013 canonical says “we”, statement/example say “I”; Q031/C016: “que remplace le mot manquant ?”; Q045/C023: “Quel petit mot” expects `de la` | Low; prompts remain interpretable but are less natural/consistent. | Quote « vous »/« venez »; align Q026 on I; Q031: “Quel pronom relatif complète le livre ___ je lis ?”; Q045: “Quelle forme de l’article…”. Keep the requested object-pronoun/relative distinctions explicit. |
| Endpoint cleanup can report PASS despite cleanup failure | `scripts/ci/flh046/qdrant_regression.py:402–403` | Medium, reproduced. After eight controlled Go passes, the final collection listing returns HTTP 503. `leftover_cleanup.error` is recorded, but exit remains 0 and stdout says PASS. Cleanup is then unverified. Container-mode CI is not affected by this specific endpoint branch. | Helper owner should make a cleanup error fail a previously successful run, retaining existing failure status otherwise. Add an orchestration regression that expects nonzero. Owned `cleanup_error` probe currently reproduces exit 0; no helper patch made. |

## Complete catalog/query/judgment review ledger

Every listed pair was read against C001–C024, including its canonical, statement,
example, free text, rationale and hard negative. Jnnn corresponds to Qnnn.
“Plausible” below means an automated proposal assessment, **not approval**.
No overlooked second SAME target was established for the focused single-target
cases. Useful contextual alternatives are not exhaustive relevance judgments.

| Family / complete coverage | Assessment and whole-catalog alternatives |
| --- | --- |
| F01: C001–002; Q001–004, Q049 / J001–004, J049 | Background versus bounded event is plausible. C001 target says description while Q001 canonical includes habit; clarify whether habits are in scope. Q002/Q004 have English examples, unlike many French examples; record multilingual input differences. Q049 has no aspect information: retain ambiguous alternatives C001/C002. C021/C022 concern duration prepositions, not the same tense objective. |
| F02: C003–004; Q005–008, Q050 / matching J IDs | Direct le/la/les versus recipient lui/leur is plausible. C004 appropriately narrows to a recipient, not every à-complement. English Q008 “after I speak” is awkward: use “in Je parle à mes amis”. Q050 remains underspecified without the verb/object role. Relative C015/C016 is a separate construction, not another SAME target. |
| F03: C005–006; Q009–012 / J009–012 | Location y versus quantity en is plausible; C005's à-location scope fits both place examples, but is not all uses of y. Review C006's scope for retained numbers without overt de. C023/C024 are useful adjacent quantity/article topics for search, not pronoun identity targets. |
| F04: C007–008; Q013–016 / J013–016 | Adjective agreement versus manner-adverb invariance is plausible for the explicit examples. Do not generalize to every adjective/adverb exception. C020 pronunciation and C019 accent spelling do not address these endings. No second SAME objective identified. |
| F05: C009–010; Q017–020 / J017–020 | Pas versus plus is plausible. Q017 also demonstrates the article change in C024, a cross-family search alternative. C010 scope “cessation d’une habitude” is narrower than all ne…plus usage; keep this fixture explicitly on habits or broaden only in a new proposal. Past imparfait in Q019 is context, not C001 SAME. |
| F06: C011–012; Q021–024 / J021–024 | Est-ce que without inversion versus inversion is focused and plausible. Q021/022 disclose the exact contrasting strategy; Q023 needs quoted words. C018 can be relevant when selecting vous in a question, but question word order is not address-register identity. |
| F07: C013–014; Q025–028 / J025–028 | Personal obligation versus impersonal necessity is plausible when example and canonical are included. Fix Q026 I/we inconsistency. Q027 free text alone also admits other necessity expressions; explicitly constrain falloir construction. C017 polite conditional requests are a different intent despite shared modal verbs. |
| F08: C015–016; Q029–032 / J029–032 | Relative subject versus object is plausible; human referent does not determine role. English gaps need explicit French framing. Q031 is awkward/metalinguistic. C003's direct-object replacement can help explain object role in Q031/032, but is not relative-que SAME. |
| F09: C017–018; Q033–036 / J033–036 | Conditional softening versus address register is plausible. Q034 permits several softening forms; ask for a verb-form change consistently in both languages. Q035 includes formal setting while Q036 only says stranger: align social context and avoid universal rules about strangers. C011/C012 may help form a polite question, but remain separate SAME objectives. |
| F10: C019–020; Q037–040 / J037–040 | Written ou/où versus spoken u/ou is plausible. C019 is spelling disambiguation; C020 could explicitly name /y/ and /u/ to avoid broad “French vowels” scope. Q037/038 contain inversion C012 as useful sentence context. Tu in Q039/040 is a sound example, not C018 register relevance. |
| F11: C021–022; Q041–044, Q051 / matching J IDs | Continuing depuis versus bounded pendant is plausible. Keep C022 “bounded” rather than implying pendant only ever refers to finished time. Q044 lacks a French/preposition cue in free text: explicitly ask for the French time preposition. Q051 has no continuation/boundary information: retain ambiguous alternatives. Past tense C002 is contextual to Q043/044, not SAME. |
| F12: C023–024; Q045–048, Q052 / matching J IDs | Affirmative partitive versus negated quantity is plausible with the exception refinements above. Q045 explicitly mentions en: C006 is useful context; Q047/048 need C009 negation knowledge. Q052 remains ambiguous even beyond the two listed constructions (bread can be generic/definite in contexts absent from this catalog); do not force a SAME target. |
| F13: no Concepts; Q053–054 / J053–054 | Cooking temperature and PostgreSQL backup are outside all 24 learning objectives. Proposed no-match is plausible as an information need. Kind vocabulary is just schema-compatible here, not proof of valid extracted linguistic evidence. French tokens/SQL keywords do not establish search relevance. |
| F14: no Concepts; Q055–056 / J055–056 | Subjunctive after bien que and future stem of aller are absent. C016's que is not concessive bien que; C005's going-to-location evidence is not future morphology. Retain proposed no-match; these are stronger in-domain absence tests than F13. |

All 56 free-text strings equal their Unit statements. All 48 positives contain
an example; seven example strings recur within bilingual pairs. Those pairs
stay in the same split, so this is correlation/easy-cue risk, not a demonstrated
cross-split exact duplicate. There are 28 French and 28 English queries,
32 development positives + 2 ambiguous, and 16 held-out positives + 2 ambiguous
+ 4 no-match. The “independent authored” wording must not imply statistical
independence between these paired synthetic cases.

## Validator attacks and current application policy

Owned temporary copies, original left untouched:

| Probe | Actual validator exit | Interpretation |
| --- | --- | --- |
| Swap Q001–004 proposed targets and negatives between C001/C002 | 0 | Balanced bilingual inventories do not verify semantic truth. |
| Copy C001 target and scope into Q001, omit feature value `background` | 0 | Full-visible-identity guard at lines 140–145 does not prevent partial/semantic answer copying. |
| Rewrite held-out Q041 free text to development past-background objective | 0 | Group/split equality does not detect semantic-family leakage or Unit/free-text mismatch. |
| Add C024 as an explicit cross-family contrast for Q017 | 1 | Error: `judgment: cross-family reference would leak a split`; whole-catalog alternatives require a new reviewed artifact contract. |

The first three limits are substantially acknowledged by FLH-045's README;
passing validation is preparation evidence, not relevance approval.

Independently inspected `concept_retrieval_evaluation_service.go`,
`concept_annotation_dataset_service.go`, `effective_annotation_service.go`,
`concept_retrieval.go`, `concept_retrieval_comparison_service.go` and
`domain/concept.go:318–335`. The frozen plan agrees with current behavior:

- M11-A reads current extraction Units/current membership authority; M11-C
  consumes that projection, not raw history. INVALID dominates human-label
  projection. Only consistent resolved CURRENT human SAME is positive truth;
  automatic SAME, missing labels and ambiguous/no-match proposals are not
  eligible positives. Inconsistent asserted human SAME after a valid gate fails.
- Quality invalidity blocks before dataset/catalog/retriever calls and leaves
  null metrics/no samples. Warnings are non-blocking.
- Exclusion precedence counts a human SAME once: unclassified provenance,
  `seed_unit_same`, non-active admission, retired target, missing current target.
  Only `human_same`/`human_same_correction` survive the provenance filter.
- Candidate universe is all current non-retired Concepts, including orphaned
  ones; it is not a split-specific catalog. Samples sort Entry ID then Unit ID.
  Candidate identity comes from normalized canonical + kind with empty scope/
  features, never the proposed target. All 24 fixture identities have scope and
  features: an unchanged direct exact-signature fixture exercise would therefore
  have no exact matches, not evidence of a production bug.
- K is fixed at 5; excess results, wrong ranks, duplicates and foreign candidates
  fail validation. With one positive per eligible Unit,
  Recall@K = number of targets ranked ≤K / eligible Units. MRR is **MRR@5**:
  mean of 1/rank for hits within returned top five, otherwise 0. Rank 6 is
  unobserved and contributes 0, not 1/6. No samples ⇒ null metrics; an eligible
  population with all misses ⇒ numeric zero. Missing target rank stays null.
  Ambiguous/no-match queries have no recall/MRR denominator under this policy.
- Comparison checks complete evaluation populations before copying metrics;
  unavailable embedding is explicit with null metrics, not a measured zero.

Executed seven evaluation test functions (including subtests): eligibility,
exclusion precedence, quality/failure gates, identical retriever populations,
unknown selection, dependency failures, and ranks/misses/empty metrics. All pass.
Metric test observes ranks 1/3/5, miss=0, and aggregate MRR
`(1 + 1/3 + 1/5 + 0)/4`, with null empty metrics. No real retrieval experiment,
model call, label adjudication or policy-qualified synthetic evaluation was run.

## Real-Qdrant CI observation

Inspected actual `.github/workflows/ci.yml:53–99`, helper and expected list.
Dedicated Ubuntu job: 30-minute job limit, 22-minute real-suite step,
300-second pull, 90-second readiness, 600-second Go test timeout; helper tests
precede it, artifacts and label-filtered container safety cleanup use `always()`.
Default helper readiness=60 seconds; HTTP attempts=2 seconds, 0.5-second retry
sleep. A request may overrun the nominal readiness deadline slightly. Go's
watchdog allows test timeout +120 seconds for compilation/hangs and kills the
process group; final process-group cleanup is bounded by 10 seconds. Docker
operations have explicit command timeouts. These are separate bounds, not a
guaranteed single total runtime below the workflow step limit. SIGKILL/job
cancellation still needs workflow cleanup; not induced in this review.

Initially Docker access required sandbox escalation and the cache lacked Qdrant.
The human then supplied the exact image. Local inspection confirmed:

```text
qdrant/qdrant:v1.19.1@sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10
image ID sha256:dd57172b0bbebb29b0a96a37c1f378a317449730c36cdfe68feabe36e740a92b
architecture amd64
reported version 1.19.1; commit 6ab21cac18ebb6f4ae29102c7f8f5cc11affd5de
```

The unchanged helper ran through a temporary Docker wrapper replacing only its
redundant pull with inspection of this cached pin. All run/port/log/inspect/rm/ps
commands were delegated to real Docker. This proves local cached container
behavior, **not registry pulling or GitHub Actions execution**. No remote
workflow result was supplied or independently observed here.

| Case / evidence type | Actual result | Cleanup |
| --- | --- | --- |
| Unchanged suite, real pinned Qdrant | Exit 0; all 8 named tests have actual JSON `run` and `pass` events; Go exit 0, no skips/failures | Container removed, no reported leftover collections |
| Force timeout after rig setup in temporary source copy, real pinned Qdrant | Exit 4; Go timeout panic, `timed_out: true`, no completed expected tests | Container removed |
| Insert one deliberate `t.Fatal` in copied first test, real pinned Qdrant | Exit 1; first test fails, other 7 pass | Container removed |
| Strip URL only in temporary Go wrapper, real pinned container running | Go exit 0; 7 top-level skips, 1 parent pass with 3 skipped subtests; helper exit 1 | Container removed |
| Select nonexistent regex only in temporary Go wrapper, real pinned container running | Go exit 0; zero test results; helper exit 1, all expected names missing | Container removed |
| Actual unavailable loopback endpoint, unchanged helper | Exit 3 after 2-second readiness deadline; connection refused | No container/test command started |
| Independent helper orchestration facade + actual Go tests | Skip/zero/fail exit 1 without injected leftovers, proving verdict enforcement independently of cleanup failures | Facade shut down; temporary wrappers removed |
| Controlled facade leftover after failed suite / synthetic Go timeout | Exits 1 / 4; new `flh042_it_flh049_leftover` deleted | Preexisting `flh042_it_preexisting` preserved |
| Controlled final cleanup listing HTTP 503 after 8 synthetic stdlib Go passes | **Exit 0 / PASS**, `leftover_cleanup.error` present | Cleanup not verified: reproduced endpoint defect above |

Real baseline expected names, independently checked against declarations and
JSON events:

```text
TestQdrantIntegration_BuildSyncRebuildRestartAndCacheReuse
TestQdrantIntegration_SupersededRunCannotMutateNewerPublication
TestQdrantIntegration_FencedPublishAfterNoOpTakeover
TestQdrantIntegration_PointLossAndSameCountReplacementAreDetectedAndRepaired
TestQdrantIntegration_WholeCollectionLossAndIncompatibleShape
TestQdrantIntegration_InterruptionKeepsPreviousPublication
TestQdrantIntegration_NoSQLiteWriteLockDuringNetworkCalls
TestQdrantIntegration_UnavailableQdrant
```

The normal no-URL baseline is more subtle than “only UnavailableQdrant runs” in
the older FLH-046 report: UnavailableQdrant itself skips, while the superseded-run
parent passes despite three skipped subtests. The helper correctly catches all
those subtest skips. Fake embeddings prove mechanics only, not semantic quality.

## Commands, artifacts and limitations

Commands below were executed from actual pwd. Network/Docker probes used the
approved sandbox escalation; it changed permissions, not test expectations.
Python 3.14.7; Go `go1.27.1-X:nodwarf5 linux/amd64`.

```sh
pwd
cat AGENTS.md
python3 -B scripts/validation/flh045/validate.py
python3 -B -m unittest discover -s scripts/validation/flh045 -p 'test_*.py'
python3 -B -m unittest discover -s scripts/ci/flh046 -p 'test_*.py'
mkdir -p /tmp/flh049-go-cache
cp -a /home/worldvanquisher/.cache/go-build/. /tmp/flh049-go-cache/
GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off go test ./internal/application -run 'TestConceptRetrievalEvaluationService_|TestCalculateConceptRetrievalMetrics_' -count=1 -v
python3 -B scripts/validation/flh049/probe.py fixture --output /tmp/flh049-fixture-probes
GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off python3 -B scripts/validation/flh049/probe.py helper --output /tmp/flh049-helper-complete
python3 -B scripts/ci/flh046/qdrant_regression.py --endpoint http://127.0.0.1:9 --ready-timeout 2 --artifacts /tmp/flh049-unavailable-network
docker image inspect qdrant/qdrant:v1.19.1@sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10 --format '{{.Id}} {{json .RepoDigests}} {{.Architecture}}'
GOCACHE=/tmp/flh049-go-cache GOPROXY=off GOSUMDB=off python3 -B scripts/validation/flh049/probe.py real --output /tmp/flh049-real-final
```

Results: fixture exit 0, 24/56/56/14 and frozen hash; 32 fixture self-tests OK;
16 helper self-tests OK; seven application evaluation test functions pass;
owned fixture/helper/real harnesses exit 0 because all **observed expectations**
were asserted, including the reproduced cleanup defect. Child helper exits are
in the table. The probe harness exit is not a real integration pass claim.

Source identity anchors (SHA-256):

| Read-only input | Hash |
| --- | --- |
| FLH-045 fixture exact bytes | `92726376c7892ef5e7eb539648828eab3ccf9d026912a4a5509dc461c3b7043a` |
| FLH-045 validator | `24d133d9e07bab7206d43a7ee12f1caf6c24744014e94daf99bd131dc04f323e` |
| FLH-046 helper | `8320f04b898aa81a4f5d8902b2c9ce25d4f3d1e443c5df44822cce4a96aa9241` |
| Expected tests | `9034d2946a98c07aa4dd7a8816d929f19ea6e99fe619e99f58e01833506f0b72` |
| Actual workflow | `582c2da713387bb9cb8c5f602b1300125d456f43e32efe4a5d567f9f1ac74d1d` |
| Integration test source | `643a61bb817b9b3e715a43401d034ade995ea9ddf4a6272f5e5188be62d2245b` |
| Evaluation service | `18033961f2309fbb86fd922472b4f18afc40c385f8483e9a6aa788d757d40caf` |

Intermediate attempts are retained honestly: initial Go test failed because the
default cache was read-only; using a copied temporary cache resolved it. Initial
unavailable-endpoint run without escalation reported sandbox EPERM, not a
connection-refused observation; the escalated rerun proved connection refusal.
Initial `/tmp/flh049-real` timeout challenge finished all tests in under one
second and correctly passed; the harness's timeout expectation failed. A first
copied-source retry (`/tmp/flh049-real-complete`) lacked the embedded migrations
package and honestly failed as a build regression. Including existing migrations
in the temporary copy and injecting a deliberate delay produced the final
validated timeout. No CI helper or production source was patched to pass.

Final evidence resides in `/tmp/flh049-real-final` (five summaries, JSON/readable
Go logs, Qdrant logs, Docker inspections, image verification and Docker command
ledger), `/tmp/flh049-helper-complete` (facade orchestrations),
`/tmp/flh049-fixture-probes`, and `/tmp/flh049-unavailable-network`.
No outputs are committed. Temporary mutated fixtures, wrappers, source copies
and synthetic modules were removed by context managers. Owned loopback facade
threads were joined. Real containers used loopback random ports and tmpfs
storage, no daily-data mounts. The cached image supplied by the human remains.
The copied temporary Go cache and evidence logs remain available for review.
Final `docker ps -a --filter label=org.flh.task=flh046 --format '{{.Names}}'`
returned no task containers. A directory inventory found no surviving
`flh049-wrapper-*`, `flh049-docker-wrapper-*` or mutated-fixture temporary
directories. Read-only `ast.parse`, Markdown/Python trailing-whitespace and
terminal-newline assertions passed for all three owned files; no owned bytecode
was generated. `README.zh-CN.md` exists and needs no change for this audit.
Read-only SHA-256 rechecks matched every anchor above at delivery.
No permanent dependency install, model download, provider/secrets/personal data,
production annotation write or browser acceptance was involved.

## Separate conclusions and handoff

**Evaluation preparation:** structurally reproducible and consistent with the
current application policy. Not ready as human-reviewed ground truth or a
claimed retrieval-quality benchmark. Human review must resolve the table's
wording/scope issues, judge the whole catalog separately for SAME and useful
search relevance, adjudicate ambiguous/no-match cases, and freeze reviewed
labels/grouping/input representations with new hashes before any execution or
tuning. All supplied labels remain awaiting human review.

**CI helper:** local real pinned-container baseline accepted: actual eight-test
execution, skip/zero/failure/timeout enforcement and container removal observed.
Endpoint cleanup acceptance remains incomplete because a final cleanup-listing
error falsely preserves PASS. Owner should fix and rerun that isolated case.
Registry pulling, remote GitHub Actions behavior, signal/cancellation scenarios
and real endpoint-mode leftover sweeps were not independently executed here;
facade cleanup evidence does not substitute for real endpoint cleanup evidence.

Only three files changed. No API/schema/shared-file changes. Ownership transfers
at delivery; stop editing. The human owns integration and all Git operations.

```sh
git add -- docs/validation/FLH-049-evaluation-and-ci.md scripts/validation/flh049/README.md scripts/validation/flh049/probe.py
```

Suggested commit message:

```text
test: independently audit evaluation readiness and Qdrant CI enforcement
```
