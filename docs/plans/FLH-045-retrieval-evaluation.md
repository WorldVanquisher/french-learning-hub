# FLH-045 — Reproducible retrieval evaluation preparation

## Scope and checkpoint

Owner: NAS Codex. Human-supplied branch label:
`test/flh-045-retrieval-evaluation-preparation` (not verified with Git).
Preparation completed on 2026-10-11. This package proposes an experiment; it
contains no measured retrieval results and no independently collected ground
truth. FLH-044 is parallel work and is neither a dependency nor assumed present.
The two known FLH-043 defects remain outside this task; its historical acceptance
report is unchanged. This preparation makes no index-consistency acceptance claim.

Owned files are this plan and `scripts/validation/flh045/{README.md,fixture.json,
validate.py,test_validate.py,experiment-record.template.json}`. Dependencies are
the implemented read-only application contracts below; no schema, migration,
provider, repository, shared document or production file changes are required.
Tests use standard-library Python and automatically removed task-owned temporary
files. No application, database, container or provider is started.

## Implemented contract map

Source paths below are repository-relative. These are observed contracts, not
proposed endpoint or policy changes.

| Layer | Existing contract and implication |
| --- | --- |
| Dataset | `internal/application/concept_annotation_dataset_service.go`: `concept_annotation_dataset_v1`, one current-extraction snapshot from M11-A, immutable Unit/source provenance, effective admission/annotation and human labels. CURRENT SAME comes from the membership projection, not historical link reconstruction. Automatic SAME supplies no human SAME label. Dominant INVALID suppresses pair labels. DISTINCT and relations are not positive SAME truth. |
| Quality | `concept_annotation_quality_service.go`: `concept_annotation_quality_report_v1`; valid means structurally consistent, not semantically correct gold data. Errors block evaluation; warnings do not. Source Entry/extraction and repeated target groupings expose leakage risk but do not automatically construct splits. |
| Evaluation | `concept_retrieval_evaluation_service.go`: `concept_retrieval_evaluation_v1`, policy `concept_retrieval_eval_policy_v1`, max K=5. Resolved CURRENT human SAME must agree with its projected Concept/event/resolver provenance. Only classified `human_same` or `human_same_correction`, with active admission and a present non-retired target, become samples. |
| Exclusions | Human SAME inventory counts sequential exclusion reasons: unclassified provenance, `seed_unit_same` (new-Concept temporal leakage), non-active admission, retired target, target missing from current catalog. Automatic/unresolved/INVALID records with no human SAME do not enter that inventory. Inconsistent projected human SAME fails explicitly. Seed receipts must not be rewritten as ordinary human SAME to obtain eligibility. |
| Universe | The complete current catalog minus retired Concepts, sorted by actual Concept ID; supported and orphaned normal Concepts both remain. This is not a reconstruction of the catalog available when a historical label was made. |
| Metrics | One target per eligible Unit. Recall@1/3/5 is the fraction with that target in the first K; reported MRR averages reciprocal ranks within returned top five, with misses contributing zero. Thus it is effectively MRR@5, not full-catalog MRR. Zero eligible samples produce null metrics. Invalid dataset produces `blocked_invalid_dataset`, null metrics and no samples, not a measured zero. |
| Detailed audit | Each sample contains Unit/Entry/extraction IDs, query, target document, human SAME event/reason, ranks/evidence and hits. Output validation enforces <=5, consecutive ranks, uniqueness and membership in the candidate universe. Scores across algorithms are not calibrated probabilities. |
| Comparison | `concept_retrieval_comparison_service.go`: `concept_retrieval_comparison_v1` calls exact, weighted lexical, BM25, embedding in that fixed order. Schema/policy/state/validity/universe/full eligibility and exclusion inventory/ordered queries/targets/provenance must agree. It does not create truth or compute ranking. Unregistered optional embedding is `unavailable` with null metrics; configured provider failure propagates. Freeze input snapshots across calls; the comparison guard does not create a transaction across services. |

Existing retrieval interface: `ConceptRetriever.Retrieve(ctx, query, documents,
limit)`. `ConceptRetrievalQuery` holds Unit ID, kind, canonical, statement,
nullable example and candidate identity. `ConceptRetrievalDocument` holds Concept
ID, identity/schema/signature and lifecycle/support/state metadata. Future harness
adapters must call these implementations, not recreate ranking in Python.

| Existing retriever | Query/document rendering and limits |
| --- | --- |
| `exact_signature_retriever_v1` | Exact complete identity-signature equality, score 1, Concept-ID tie order. `internal/domain/concept.go:DeriveCandidateIdentity` derives target from normalized Unit canonical, intent from kind, empty scope/features. Never copy a judgment's target identity into the query. The scoped fixture Concepts may naturally yield no exact hits; do not rewrite them to improve the baseline. |
| `weighted_lexical_retriever_v1` | `concept_lexical_normalization_v1`: lowercase, NFD, remove marks, punctuation boundaries, omit one-rune tokens. Unique tokens per field, weighted cosine; query canonical=4, statement=2, intent/scope/feature keys/values=1; document target=4, other fields=1. Example and candidate target are not extra lexical fields. Positive overlap only; no stemming, stop-word list or model call. |
| `bm25_retriever_v1` | Same normalization/fields/weights, raw term frequency and weighted document lengths, per-call corpus statistics, k1=1.2, b=0.75. Positive finite scores only; no learned tuning. |
| `embedding_retriever_v1` | `concept_embedding_text_v1` query JSON includes canonical, statement, example, derived candidate target/intent/scope and sorted feature pairs. Concept JSON includes target/intent/scope and sorted feature pairs. Neither sends IDs, signatures, lifecycle/support, annotation labels/reasons, expected ranks or metrics. One provider batch per nonempty query contains query then all documents. Cosine ranking validates finite equal-dimensional vectors; zero-norm/nonpositive similarity gives no result. Errors never fall back. The retriever itself has no persistent cache/index. |

All non-exact rankings sort score descending then actual Concept ID ascending.
Exact signature remains the default. Optional embedding availability does not
imply Knowledge Library index availability. The existing reports are descriptive
retrieval audits, not learned SAME classifiers, semantic-quality guarantees or
end-user search experiments.

## Frozen synthetic proposals

Fixture schema: `flh045_retrieval_preparation_v1`. Every judgment says
`awaiting_human_review`; root status says
`author_proposed_synthetic_awaiting_human_review`.

- 24 Concept identities: C001–C024.
- 56 independent authored query records: Q001–Q056, 28 French and 28 English.
- 56 proposed judgments: J001–J056, linked one-to-one to queries, with rationales.
- 48 single-target cases (two bilingual paraphrases per Concept); each names its
  contrasting Concept as a proposed hard negative with a rationale.
- Four ambiguous cases name possible alternatives, with **no asserted relevant
  target**. Four no-match cases assert no relevant Concept in this fixed catalog,
  including two in-domain objectives that are absent, not just unrelated topics.

These are constructed linguistic examples, not observed learner records.
Hard negatives propose distinct learning objectives; they do not claim that all
other Concepts are independently judged irrelevant or store DISTINCT authority.
Humans must review the entire catalog for overlooked relevant alternatives.

| Family | Concepts | Objective contrast | Query split |
| --- | --- | --- | --- |
| F01 | C001–C002 | Past background vs completed event | development |
| F02 | C003–C004 | Direct vs indirect object pronouns | development |
| F03 | C005–C006 | Place replacement y vs quantity en | development |
| F04 | C007–C008 | Adjective agreement vs manner adverb | development |
| F05 | C009–C010 | Simple denial vs no longer | development |
| F06 | C011–C012 | est-ce que vs subject/verb inversion | development |
| F07 | C013–C014 | Personal devoir vs impersonal falloir | development |
| F08 | C015–C016 | Relative subject qui vs object que | development |
| F09 | C017–C018 | Conditional request vs tu/vous register | held out |
| F10 | C019–C020 | ou/où spelling vs u/ou pronunciation | held out |
| F11 | C021–C022 | Continuing depuis vs bounded pendant | held out |
| F12 | C023–C024 | Affirmative partitive vs negated quantity | held out |
| F13 | none | Cooking/computer administration absent from catalog | held out |
| F14 | none | Subjunctive/future morphology absent from catalog | held out |

Development: 32 single-target + two ambiguous queries. Held out: 16 single-target
+ two ambiguous + four no-match queries. F09–F14 are reserved **before any tuning**.
All Concept candidates remain in the fixed catalog for both splits: these are
query-family splits, not removal of held-out targets from the search universe.
Paired close distinctions and their French/English paraphrases are indivisible.
The author has seen these proposals; this is a tuning holdout, not a blinded or
independent benchmark. Store future reviewer identity/date/disagreements in a
separate reviewed artifact with its own hash; do not rewrite this proposal as
collected human truth. Any family/split revision creates a new version and
requires review before examining model results.

Model inputs are only `concept.identity`, `query.unit_evidence` and, for the
separate free-text protocol, `query.free_text`. Stable IDs, grouping, language,
tags, bucket, proposed relevance and rationales are evaluator metadata.
`unit_evidence` maps to existing kind/canonical/statement/example fields; it
contains no candidate identity. A future approved adapter must obtain it via
`domain.DeriveCandidateIdentity`, independent of the judgment file. Ambiguous
and no-match Unit evidence is a schema-compatible proposal only, not a claim of
valid admitted extraction or policy eligibility.

Do not add expected targets, membership history, admission state, human reasons,
held-out labels, or retrieved answers to prompts. Do not synthesize queries by
serializing the target Concept. Examples use naturally worded questions and
minimal grammatical contexts. Existing identity derivation is allowed to lose
fine distinctions; forcing it to reproduce the proposed target would leak truth.

## Protocol A — existing Unit-to-Concept evaluation

This package does **not** ingest records, fabricate current memberships or write
labels. Synthetic proposals alone cannot produce a valid policy evaluation.
Execute only after separate human review and authorization of an isolated data
setup or provision of an already-reviewed, synthetic-only application snapshot.

1. Freeze the source hashes, all fixture sections and reviewer-approved artifact.
   Inventory model inputs without judgments. Use task-owned output, a fresh
   isolated database, no daily records, and only separately approved provider
   configuration. Do not assume FLH-044 features. Record actual toolchains and
   deployed revision/configuration, not only a friendly model name.
2. If isolated data setup is authorized, construct Units through the actual
   domain/repository contracts with consistent Entry/analysis/extraction
   provenance. Have the human explicitly review target identity and record
   current human SAME for query Units against pre-existing Concepts. Catalog
   seed Units are separate from query Units; new-Concept seed memberships stay
   excluded. No proposal-to-label auto-write script is supplied. Freeze the
   fixture-ID to actual Unit/Entry/extraction/Concept/event mapping, derived
   identities and resulting current state. ID ordering matters for ties.
3. Read the existing Dataset v1 and quality report. Verify current extraction,
   active admission, CURRENT human SAME/event/resolver alignment and classified
   human_same/human_same_correction reasons. Preserve every exclusion and
   warning. Human review can reject a proposed SAME: record the changed eligible
   population rather than forcing all 48 proposals into the denominator.
4. Snapshot the full current non-retired catalog, including orphaned Concepts,
   with actual signatures/IDs; do not filter it by split. Freeze mutations for
   the run. Call the existing `BuildV1WithRetriever` for each exact identifier;
   optionally use the implemented read-only evaluation/comparison reports.
   Do not invent an endpoint or implement a replacement policy/normalizer.
5. Retain detailed reports, complete eligible/excluded inventory, ordered top-K
   actual IDs, scores and evidence. Check the comparison population guard. The
   compact comparison lacks per-query evidence, so it cannot alone substantiate
   the experiment. Capture errors/unavailable/blocked states distinctly.
6. Report the unchanged API policy aggregate and, separately, offline
   development/held-out slices of its **actually eligible** samples, using the
   frozen ID mapping. Keep K=1,3,5 and misses zero; name MRR as truncated at five.
   Slice denominators and source totals must reconcile with the original report.
   No-match/ambiguous cases never enter these positive-only metrics. Proposed
   JSON labels are not a substitute for Dataset v1 authority.
7. Check before/after source and annotation snapshots; read-only evaluation
   must change neither source, membership nor annotation state. Isolate any
   provider cache mutation in its own store. Retain cleanup evidence for all
   owned files/processes/ports/storage before handing off.

For a successful evaluation with Q nonempty eligible queries and C candidates,
current embedding retrieval submits Q batches of C+1 positions: Q query inputs
and Q*C document inputs, even when texts repeat. At hypothetical Q=48, C=24,
that is 48 requests / 1,200 input positions (48 + 1,152), **not observed counts**.
A provider may internally cache; separately count submitted positions, unique
hashes, actual backend computations, retries and billing. A comparison call plus
a detailed embedding evaluation repeats this work; do not mistake that for
cache reuse. Non-provider baselines should record zero provider deltas.

Without approved application truth, a future direct `ConceptRetriever` fixture
exercise may only be called an exploratory comparison against proposed synthetic
judgments. It is not `concept_retrieval_eval_policy_v1` and must not be presented
as the production report. This task runs neither kind of experiment.

## Protocol B — free-text Knowledge Library search

The Library keyword browse/search (`GET /knowledge-library/concepts`) and optional
free-text semantic search (`GET /knowledge-library/semantic-search`) serve user
text, not a `KnowledgeUnit` with a derived candidate identity. Their current
request/state-filter/response contract must be read at future execution time;
this preparation does not invent parameter names or a new endpoint.

1. Define a separately reviewed information-need benchmark: whether relevance
   means the same durable objective, a useful explanation, or a broader answer.
   Resolve multilingual wording, plausible alternative results and absent
   objectives explicitly. Proposed SAME relevance does not automatically prove
   useful free-text relevance. Approve the evaluation universe and state filter.
2. Freeze the catalog and any CURRENT SAME member wording searched by keyword
   Library search. Use separate catalog seed evidence; do **not** add evaluated
   query Units as searchable member wording. Otherwise the held-out query itself
   can become a document. Record support/lifecycle and membership snapshot hashes
   as well as identities. A Protocol A database is not automatically suitable
   for Protocol B. Persistent semantic documents and free-text query rendering
   are independent of the M12 per-call Unit evaluation; record their actual
   representation identifiers and bytes from the deployed implementation.
3. Obtain approved model/deployment settings and build the task-owned disposable
   index only if that protocol requires it. Record cache keys, cold/warm state,
   model/dimensions, vector inventory and verified health. Publication history is
   not verified health. FLH-043's known defects remain relevant limits; an index
   must be independently checked, not accepted from a success flag.
4. Send only frozen `free_text`, with no expected identity, labels or rewritten
   language-specific prompt. Retain ordered results, evidence, state filters,
   SQLite authority revalidation/drop behavior, errors and requested/returned K.
   Empty results and positive-score irrelevant hits are legitimate observations,
   not permission to add automatic labels, a tuned threshold or fallback.
5. If humans approve a separate single-target relevance definition, report
   separately named Recall@K and MRR@K on that subset, including denominator,
   truncation and empty-result handling. Do not label them with the Unit policy
   identifier. Ambiguous cases currently carry alternatives, not approved
   multi-relevant truth; record coverage/order and reviewer disagreement without
   scoring. No-match cases have undefined recall/MRR; separately record empty
   results and false-positive counts/rates under an approved definition. Never
   convert an empty relevance set to recall=1 or mix it into positive recall.
6. Record current database/annotation snapshots and provider counters before
   and after search. Keyword search should submit no embeddings; a semantic
   search's query embedding calls differ from indexing document calls. Verify
   observed behavior rather than inferring counters from response text. Do not
   reuse per-call M12 embedding counters to claim Library cache performance.

Exact/weighted/BM25 `ConceptRetriever` implementations accept Unit queries and
are not automatically free-text Library algorithms. Calling them with a newly
invented free-text adapter changes the experiment definition; review and version
that adapter separately. No such adapter is supplied here. No quality, ANN
speedup, Recall@K/MRR improvement or real-world relevance claim follows from
fake vectors, this synthetic corpus or the preparation checks.

## Experiment recording and latency boundaries

Copy `experiment-record.template.json` into task-owned temporary output for a
future approved run; it is an unexecuted template, not evidence or a config file.
Never put credentials, secret endpoint query strings or daily records in it.
Null fields mean unmeasured, not zero. Use a separate record per protocol,
retriever/configuration, split and cache condition.

Required records:

| Category | Required evidence |
| --- | --- |
| Identity | Provider implementation/name, explicit model/deployment identity, immutable model revision or weight digest, runtime/image version, tokenizer, truncation and observed truncations, vector dtype/normalization, configured **and observed** dimensions, hardware/resources, retries and batching/concurrency. An alias alone is insufficient. |
| Inputs | Raw fixture SHA-256, canonical Concept/query/group/judgment section hashes, reviewed-label hash, actual dataset/catalog/quality/current membership snapshots and actual-ID mapping. Hash ordered **actual rendered UTF-8 bytes** with length-prefixed records to avoid concatenation ambiguity. The validator's canonical JSON hash is not a hash of Go rendering. Record representation IDs, ordering and state filter. |
| Cache | Explicit cold/warm definition for each provider/index/application/OS layer, keys, hits/misses and before/after state. M12 retriever owns no persisted cache; Library index storage is a separate mechanism. Do not reset shared caches or daily storage. |
| Calls | Monotonic before/after counters for HTTP requests, query/document input positions, unique input hashes, retry positions, failures, actual computations if observable and billed tokens if paid. Retain each batch's input-role/hash inventory without labels. Unknown accounting stays unknown. |
| Timing | Raw per-query observations, clock, warmup policy/count, repetitions, concurrency, errors/timeouts/cancellations and sample count for summaries. Request end-to-end: before request to complete response decode (includes transport, authority reads, provider and serialization). Application Retrieve: entry to return (includes rendering/provider/scoring, excludes outer dataset/quality work). Provider Embed: call to validated batch completion (includes network/model/validation). Index build: separate start-to-publication/verified-health interval; never amortize it into search silently. Nested timings overlap and must not be added. |
| Output | Query/family/language/split/bucket, runtime IDs, state, requested/returned K, ordered Concept IDs, retriever-specific scores/evidence, elapsed time and error. Preserve full results and artifact hashes, exclusion counts and comparison population checks. Recall@1/3/5 and truncated MRR only where approved truth/protocol permits them. |

Freeze existing baseline parameters; no parameter fitting is authorized. If any
future tuning is proposed, development families only, with the entire prompt,
model, representation, threshold and candidate-policy configuration frozen before
held-out results are inspected. A small correlated synthetic set cannot support
claims of generalization or statistically reliable performance gains; report
per-family and language breakdowns and disagreements alongside any future means.

## Human review and authorization gate

Review checklist:

- Check each Concept's scope and identity uniqueness, French examples and English
  paraphrases; correct language errors without making queries identity copies.
- Review every proposed target and paired negative against **all** Concepts;
  distinguish SAME identity from related/useful information.
- Decide whether each ambiguous case is intentionally underspecified and whether
  no-match objectives really are absent. Keep them outside the Unit denominator.
- Approve F09–F14 as untouched tuning holdout; group related Entry/extraction
  records together in any future application snapshot as well.
- Approve stable runtime mappings, seed exclusions, provider input separation,
  candidate universe, metrics/denominators and snapshot immutability checks.
- Record reviewer, date, revisions and unresolved disagreements in a separate
  reviewed artifact; synthetic author proposals remain identifiable.

Before any real-model download or paid call, the human must explicitly approve:
(1) reviewed dataset/protocol and whether isolated annotation setup is authorized;
(2) provider or local deployment and exact model/revision, license/weight source
if downloaded, dimensions and representation; (3) download/storage/network and
compute limits or paid-call budget/input/token/retry caps; (4) synthetic-only data
handling and credentials supplied outside the repository; (5) run scope,
timeouts, output location and owned-resource cleanup. No runtime/model has been
selected, installed, downloaded or contacted by this task. Approval for this
preparation is not approval for those later actions.

## Executed preparation evidence

Actual working directory was reported to the human from `pwd`; all commands were
run at the supplied repository root. `AGENTS.md` was read from disk. Existing
`README.zh-CN.md` was confirmed present; no user-facing shared README changed.
Observed toolchains: Linux `7.1.8-arch1-3`, GNU Bash `5.3.20(1)-release`, Python
`3.14.7`, ripgrep `15.2.0`. No Go/Node/model toolchain or application test was
needed or executed for this isolated Python/data task.

Baseline SHA-256 captured before fixture edits:

| File | SHA-256 |
| --- | --- |
| `AGENTS.md` | `3e29b4127ac46851fa878b522016949e3c8b8c9d2493668776b4b8136bbf7281` |
| `internal/application/concept_retrieval.go` | `0768fd4b77a2beca63900c09329e9472df8b8f078a48c16393c4894b0d6e2b77` |
| `internal/application/concept_retrieval_evaluation_service.go` | `18033961f2309fbb86fd922472b4f18afc40c385f8483e9a6aa788d757d40caf` |
| `internal/application/concept_retrieval_comparison_service.go` | `e31ad78f9c224e34ac2fc8a570c68cf839fc0d73dc3bbc53935a14b066694b9b` |
| `internal/application/concept_weighted_lexical_retrieval.go` | `177728ba5a39a52cfecaa9764796a8c2c24a4673d1f8f80ce099b7e98f01417e` |
| `internal/application/concept_bm25_retrieval.go` | `127f1d8af41961e9f633c1e9963a5f770d16eed8c640fd46f9cafb0f1451c8c0` |
| `internal/application/concept_embedding_retrieval.go` | `234d8ee5d17c05c0474a6f4102ceed7659cde9ff3cc024aa4a956f1cd17ff30d` |
| `internal/application/concept_annotation_dataset_service.go` | `57b2bae90018efb5e68e6ee20b3c21d9b588a558b23847c432cf3968b1c0a7b2` |
| `internal/application/concept_annotation_quality_service.go` | `5ebaec4ef34e8f6da5ec9d77c5ec599dac0e9fcef9b2de1b4c6515701dea073c` |
| `internal/domain/concept.go` | `128b299b6f15653c19a1125452c61e576840212f910ef37e1d3f575797c36feb` |
| `internal/domain/knowledge.go` | `17feb4d70fc0993e02f9ec40fda8a142010fecc5cc15488d7d506cdd1171a796` |

Inspection used `pwd`, `cat AGENTS.md`, bounded `rg --files`/`rg -n`, `sed -n`
reads of the mapped files, `sha256sum`, `python3 --version`, `uname -sr`,
`bash --version`, and `rg --version`. Initial reads of guessed filenames
`concept_lexical_retrieval.go` and `knowledge_concept.go` returned missing-file
errors; discovery located `concept_weighted_lexical_retrieval.go` and `concept.go`.
These were inspection errors, not production or fixture test failures.

Reproduction commands (offline, from repository root):

```sh
python3 -B scripts/validation/flh045/validate.py
python3 -B -m unittest discover -s scripts/validation/flh045 -p 'test_*.py' -v
```

Expected/actual: validator exits 0 with 24 Concepts / 56 queries / 56 judgments /
14 groups and the split inventory above; observed exactly. All **32 self-tests
passed**, including unknown references, duplicate IDs/identities/query inputs,
missing judgments, cross-family/split violations, no-match/ambiguous target
misuse, contradictory negatives, self-approval, nested prohibited fields,
serialized truth/identity, visible complete identity copying, missing bilingual
coverage, invalid input types and nonzero CLI failure on missing/malformed/
duplicate-key/non-finite JSON. Hashes are repeatable and query edits change the
query section hash. These checks validate preparation mechanics only.

The reproduction commands were rerun after documentation/template creation and
again passed with the same inventory/hashes and 32 tests. A separate
`python3 -B` standard-library check parsed both Python files with `ast.parse`,
loaded the record template with `json.loads`, asserted `NOT_RUN` and null metric
fields, confirmed 28 French/28 English cases, checked the README plan link and
Markdown trailing whitespace, and verified no owned bytecode or temporary
self-test directories remained. All assertions passed. No formatter dependency
was installed; JSON uses two-space indentation and Python uses four-space blocks.
The final six-file formatting check initially rejected inline template arrays
under its strict canonical pretty-JSON expectation. Reformatting only the owned
template with standard-library JSON resolved it; the same check then passed.
This was a preparation formatting failure, not a production defect or experiment.

Frozen fixture hashes:

| Artifact | SHA-256 |
| --- | --- |
| `fixture.json` exact file bytes | `92726376c7892ef5e7eb539648828eab3ccf9d026912a4a5509dc461c3b7043a` |
| Canonical `concepts` section | `4f5325220adc1b0866364b152a50fe15fb1a63485379f26c374bc919128242ff` |
| Canonical `queries` section | `db7a8ef1f7d74934e51292fc805d5c22cf2286310bd88fca897dc8d3f64c196e` |
| Canonical `groups` section | `8b56468108c07de22a23df9a90b8c8ed844c44c051fdf6560a8c1ac49288549a` |
| Canonical `judgments` section | `91b5ac3a61a9a0dbe53690ac178402ee0e1a26a66f05e32e85488d9d717389cf` |

Cleanup: self-tests remove their `flh045-selftest-*` temporary directories via
context managers; Python runs use `-B`. No bytecode, database, generated results,
server, provider, container or permanent dependency is needed. The committed
JSON template remains `NOT_RUN`, with null measurement fields. Real-model and
retriever experiments, human label adjudication, frontend/browser interaction,
semantic relevance and performance measurement are **NOT RUN** by design.
The validator cannot prove semantic independence or relevance. No newly observed
production defect is claimed; the known FLH-043 findings are not re-investigated.

## Human handoff

Only the six owned files listed above are staged by this proposed command;
it is displayed for the human and was never executed:

```sh
git add -- docs/plans/FLH-045-retrieval-evaluation.md scripts/validation/flh045/README.md scripts/validation/flh045/fixture.json scripts/validation/flh045/validate.py scripts/validation/flh045/test_validate.py scripts/validation/flh045/experiment-record.template.json
```

Suggested commit message:

```text
test: prepare reproducible retrieval evaluation fixtures and protocols
```
