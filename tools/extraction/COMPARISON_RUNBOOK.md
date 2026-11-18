# Extractor comparison: owner runbook (2026-11-12)

Compares three extractors on one pinned slice: the **current extractor**
(the production OpenAI path), **untuned Qwen3.5-4B** and **tuned Qwen3.5-4B**
(LoRA on the v2 SFT data). Everything up to the real runs is prepared and
checked offline; **no real run has been performed**. Evidence:
`docs/validation/EXTRACTOR-COMPARISON-V1.md`.

## What is measured, what is a synthetic finding, what is pending

**Measured mechanics (offline, reproducible with `scripts/comparison_pipeline.sh`):**

- Datasets regenerate to the recorded hashes; the 96-record challenge slice
  regenerates byte for byte (`b004f6ed…`).
- The challenge references pass the production validator (96/96) and every
  leakage check (`challenge-check`).
- The comparison matrix pins slice, output schema, decoding and scoring version
  (`readiness/comparison-matrix.json`, `b3f66eda…`).
- Row accounting: a fixture with ten kinds of injected faults is counted
  exactly by `compare` through the real Go validator, with no row dropped.
- The SageMaker entry point refuses a stale stack and records `stack-check.json`.
  The local CPU image is stale (transformers 4.57.6, pinned 5.21.1).
- Six jobs are rendered with unique names and output prefixes. Inputs are bound
  to their digests, and no reference reaches any channel (`readiness-checks.json`).
- The decision report answers PENDING, NO_WINNER or a winner as its tests require.

**Findings from synthetic controls (they show the harness, not a model):**

- A category-only system (abstain iff the category is `other`) produces output
  byte-identical to the oracle on the frozen evaluation. On the production-style
  `rb` probe it makes 20/20 false extractions, and on the challenge slice its
  paired consistency is 0/32, while aggregate F1 still reads 0.662.
- A constant-empty system is perfectly consistent (32/32) but only 12/32
  accurate. Over-abstention gates and paired accuracy reject it.
- The production parser accepts a unit with an extra `evidence` key and drops it.
  Only the provider's strict schema forbids such keys; `compare` counts these
  rows as `valid_extra_keys`, which are not scorable.

**Requires a real model run or human review (not concluded anywhere here):**

- Whether any real model, untuned or tuned, takes the category shortcut.
- Every metric of the three systems. All three rows are NOT_PERFORMED.
- Token lengths and masking with the real tokenizer (the tokenizer files are
  missing locally).
- Inference rate and memory on `ml.g5.xlarge`, and whether 272 prompts fit in an hour.
- The challenge, increment and probe references. All are machine-authored and
  unreviewed; review packets v2 (25 items) and v3 (19 items) are open, and so is the
  reviewer sample of the held-out references (`review/REVIEW_SAMPLE_V1.md`, 35 items,
  8 disputed).
- Human-judged unit F1 and false-claim rates. The decision needs ≥ 100 judged
  examples per system.

## Owner steps

```sh
cd tools/extraction
B=OUT/bin/extraction-render   # built by the pipeline
# 0. Regenerate everything offline (no network).
bash scripts/comparison_pipeline.sh OUT
# 1. Tokenizer files, then token lengths and masking (commands in OUT/evidence/asset-check.json).
python3 -B scripts/check_model_assets.py --sums configs/qwen3.5-4b-851bf6e8.sha256 --dir "$D" --out OUT/assets.json
# 2. Fill review/review-packet-v2.jsonl and review/review-packet-v3.jsonl (verdict, and for v3 decision_ok and label),
#    and the reviewer sample through its sheet (review/REVIEW_SHEET_V1.md: intent, evidence and wording apart), then:
python3 -B -m flh_extraction review-sheet import --packet review/review-sample-v1.jsonl --sheet OUT/my-review.csv \
  --out OUT/review-sample-v1.filled.jsonl
python3 -B -m flh_extraction review-agreement --packet OUT/review-sample-v1.filled.jsonl --out OUT/review-agreement
# 3-8. AWS: deploy/aws/sagemaker-extractor/readiness/README.md (smoke, untuned shards, experiment, adapter shards).
# 9. Current extractor, one paid request per input (owner decision; the provider model is recorded at run time):
EXTRACTOR_PROVIDER=openai "$B" run -in OUT/slice/comparison-inputs.jsonl -out OUT/current-results.jsonl -max-requests 472 -confirm-paid-calls
# 10. Scoring: concatenate each model's shards a then b, then compare and decide.
cat base-a/predictions.jsonl base-b/predictions.jsonl > OUT/untuned.jsonl
cat eval-a/predictions.jsonl eval-b/predictions.jsonl > OUT/tuned.jsonl
python3 -B -m flh_extraction compare --matrix ../../deploy/aws/sagemaker-extractor/readiness/comparison-matrix.json \
  --slice OUT/slice/comparison-slice.jsonl --render "$B" --out OUT/compare --predictions \
  current_extractor=OUT/current-results.jsonl qwen3.5-4b-untuned=OUT/untuned.jsonl qwen3.5-4b-tuned=OUT/tuned.jsonl
python3 -B -m flh_extraction decision-report --comparison OUT/compare.json --human OUT/human.json \
  --review review/review-packet-v2.jsonl review/review-packet-v3.jsonl OUT/review-sample-v1.filled.jsonl --losses exp/losses.jsonl \
  --run-manifest exp/run_manifest.json --input-manifest ../../deploy/aws/sagemaker-extractor/readiness/input-manifest.json \
  --out OUT/decision
```

Before it, the DRAFT `experimental-report` (`--comparison OUT/compare.json --human-evidence OUT/human-evidence.json
--review …`) gives an experimental preference at most, never a production GO. It needs per-system human
`false_claims`, `unsupported_units` and `bilingual_mismatch` counts beside unit F1; missing evidence is
PENDING (`docs/validation/FLH-154-part3-memo.md`). Since report v1 it also needs per-unit reviewer evidence
(`fixtures/one_record_v1/CONTRACT.md`): build the queue from the same matrix, slice and predictions as `compare`,
fill the template (source raised, claim true, Chinese the same) and pass both:

```sh
python3 -B -m flh_extraction reviewer-queue --matrix ../../deploy/aws/sagemaker-extractor/readiness/comparison-matrix.json \
  --slice OUT/slice/comparison-slice.jsonl --render "$B" --scope-packet review/review-sample-v1.jsonl --out OUT/reviewer-queue --predictions \
  current_extractor=OUT/current-results.jsonl qwen3.5-4b-untuned=OUT/untuned.jsonl qwen3.5-4b-tuned=OUT/tuned.jsonl
# fill a copy of OUT/reviewer-queue.evidence-template.jsonl (yes / no per question, reviewer, date), then:
python3 -B -m flh_extraction experimental-report --comparison OUT/compare.json --human-evidence OUT/human-evidence.json \
  --review OUT/review-sample-v1.filled.jsonl --reviewer-queue OUT/reviewer-queue.json --reviewer-evidence OUT/reviewer-evidence.jsonl --out OUT/experimental
```

A unit without a complete review keeps the report PENDING; an explicit `no` excludes that system whatever
its F1 or sample rates. The scope (here the review sample's ids in the slice) is an owner decision
(`docs/validation/FLH-154-part4-memo.md`). `decision-report` is unchanged and does not read this evidence.

`compare` refuses a slice or scoring code that differs from the matrix. If the
scoring code changes deliberately, rebuild the matrix (`comparison-matrix`) and
record why. `OUT/human.json` has the form
`{"<system>": {"unit_f1": 0.0, "judged_examples": 0, "unsupported_or_false_claim_rate": 0.0}}`,
built from human judgments on the frozen evaluation (`quality --judgments`,
section `semantic.human`).

## Decision rules (pre-registered: `flh_extractor_decision_v1`)

| Verdict | When |
|---|---|
| PENDING (exit 3) | a run is not performed or is incomplete (missing or duplicated predictions), a human criterion is missing, a review item has no verdict, or a disputed item has no stated position |
| NO_WINNER (exit 1) | no system passes every exact gate, review rejects > 10 %, or the leader's human F1 lead is < 0.05 |
| WINNER_FOR_OWNER_DECISION (exit 0) | exactly one eligible system leads on human unit F1 by ≥ 0.05 |
| REFUSED (exit 1) | the comparison was refused (slice or scoring version differs) |

Exact gates per system:

- strict validity ≥ 0.98 (scorable rows / 472);
- abstention ≥ 0.90 on the frozen evaluation and on `rb`;
- over-abstention ≤ 0.10 on both;
- challenge paired consistency ≥ 0.90;
- challenge abstain-group paired accuracy ≥ 0.80.

For the tuned model, the dev loss must also never rise twice in a row, and its
training hashes must equal the input manifest. Weak abstention or cue dependence
makes a system ineligible whatever its F1. A winner is only proposed for a
separate, owner-approved integration task; production routing is untouched.
