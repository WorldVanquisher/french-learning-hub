# Extractor training: AWS readiness package (prepared 2026-11-12, nothing submitted)

No AWS command, upload or job has been run. Every file here was produced
offline from deterministically regenerated data with placeholder account values
(`values.example.json`). The owner runs every step below. The whole comparison
(what is measured, what is pending) is in `tools/extraction/COMPARISON_RUNBOOK.md`.

| File | What it is |
|---|---|
| `input-manifest.json` | every file a job reads: SHA-256, bytes, records, S3 key; base model and revision; what is never uploaded |
| `output-manifest.json` | what each job must leave behind (including `stack-check.json`) and the offline checks before the next step |
| `rendered/*.json` | six jobs rendered and bound-checked by `render_job.py` (1 × ml.g5.xlarge, runtime caps, network isolation, image by digest, no `eval` channel); **placeholder** registry, digest, role and bucket |
| `readiness-checks.json` | offline checks of the rendered jobs: input digests, held-out reference isolation, unique job names and output prefixes |
| `comparison-matrix.json` / `.md` | the pinned three-system comparison (slice, output schema, decoding, scoring version); every run NOT_PERFORMED |
| `experiment-manifest.json` | hashes of every dataset, slice, prompt shard, generator and config, plus the matrix, scoring and input-manifest hashes |
| `values.example.json` | the placeholders; real values stay outside the repository |

## Inputs (from `input-manifest.json`)

| File | Records | SHA-256 |
|---|---|---|
| `sft-train.jsonl` (base 1,076 + increment v2 169) | 1,245 | `4dab4e7bd8e2d14f174328ea221f43dc452f8954ec49ec348c6fa091d45eb1dd` |
| `sft-dev.jsonl` (base 124 + increment v2 13) | 137 | `31285fe884c8990f7f04bf13f6fb1aab1505bf9df2110bd8d5d8515c9de736fc` |
| `predict-a/eval-prompts.jsonl` (frozen evaluation 200 + challenge_test 72) | 272 | `f75494750995c242a3414a716ff0fe4d6f447fbeceeb7f1686eb314a60e44678` |
| `predict-b/eval-prompts.jsonl` (`rb` probe 200) | 200 | `52b00b781bf1eea3631e8e25a33e6d5ce3e6dde87406d75c88109def760c390f` |
| base model `Qwen/Qwen3.5-4B` | — | revision `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`, 9,319,737,856 bytes of weights |

The two shards partition `comparison-prompts.jsonl` (`cb859d8d…`, 472 prompts),
the matrix's pinned slice. References (`comparison-slice.jsonl`, evaluation,
probe and challenge references), boundary cases and learner data are never
uploaded.

## Regenerate (offline)

```sh
cd tools/extraction
bash scripts/comparison_pipeline.sh OUT                  # placeholders
bash scripts/comparison_pipeline.sh OUT values.json      # real values, kept outside the repo
```

`OUT/readiness/` then holds the package; the hashes must equal the table above
and, with placeholder values, `OUT/experiment-manifest.json` must equal
`experiment-manifest.json` here (job names carry the render time and differ).

## Bounded smoke-to-experiment sequence

Each step has a gate; a failed gate stops the sequence. Price: `ml.g5.xlarge`
training $1.408/h in us-east-1 (TRAINING_RUNBOOK.md §10).

| Step | What | Bound | Gate to continue |
|---|---|---|---|
| 0 | Offline gates (done 2026-11-12): pipeline, challenge check, readiness checks, tests | local | all pass (docs/validation/EXTRACTOR-COMPARISON-V1.md) |
| 1 | Tokenizer files and token-level check (no GPU): `scripts/check_model_assets.py`, then `scripts/verify_profile.py --tokenizer` | local | assets PRESENT_OK; 0 prefix errors, 0 over 1,280 tokens, 0 answers over 512 |
| 2 | Human review: `REVIEW_PACKET_V2.md` (25) and `REVIEW_PACKET_V3.md` (19) | owner | every item has a verdict; ≤ 10 % rejected; fixes regenerated |
| 3 | Build the GPU image from `tools/extraction` (pinned requirements), push, record the digest | — | the build's import and `flh_extraction.packaging` checks pass |
| 4 | Upload base weights (pinned revision), the two SFT files and the two prompt shards | storage cents | uploaded hashes = input manifest |
| 5 | `rendered/sft-smoke.json` (12 steps) | 0.5 h, **≤ $0.70** | output-manifest checks; projected experiment ≤ 9,000 s |
| 6 | `rendered/predict-base-a.json`, then `-b` (untuned Qwen3.5-4B) | 1 h each, **≤ $1.41 each** | 272 + 200 rows; inference rate known |
| 7 | `rendered/sft-experiment.json` (3 epochs, 234 steps) | 3 h, **≤ $4.22** | output-manifest checks; adapter copied to `extractor/adapters/<job>/` |
| 8 | `rendered/predict-eval-a.json`, then `-b` (adapter) | 1 h each, **≤ $1.41 each** | 272 + 200 rows |
| 9 | Current extractor: `extraction-render run` on `comparison-inputs.jsonl` | 472 paid provider requests (owner decision; not priced here) | results file with 472 rows |
| 10 | Local scoring: `compare`, then `decision-report` | local | see COMPARISON_RUNBOOK.md |

Worst case for steps 5–8: $0.70 + 2 × $1.41 + $4.22 + 2 × $1.41 = **$10.56**
of compute, plus cents of storage (the earlier single-job plan was $9.15;
sharding keeps every prediction job inside the reviewed one-hour bound). No step
retries automatically; a failed job is diagnosed from `/opt/ml/output/failure`
before anything is resubmitted. If step 6 shows that 272 prompts cannot finish
in an hour, stop and re-shard before step 8.

```sh
# Step 1 (owner, any machine; tokenizer files only, no weights): the exact command is in
# docs/validation/EXTRACTOR-COMPARISON-V1/asset-check.json ("owner_command", then "then").
# Steps 5-8: exactly as TRAINING_RUNBOOK.md §3-8, with the rendered files from build_readiness.py and real values
aws sagemaker create-training-job --region "$REGION" --cli-input-json file://OUT/readiness/rendered/sft-smoke.json
```

## Promotion

The earlier criteria (`promotion-check`, `flh_extractor_promotion_v1`) still
apply to a candidate against one baseline. The three-system decision is
`decision-report` (`flh_extractor_decision_v1`, `flh_extraction/decision.py`):
it proposes a winner to the owner only when every run is measured, every
human criterion is decided, the system passes every exact gate (strict
validity ≥ 0.98; abstention ≥ 0.90 on the frozen evaluation and the `rb`
probe; over-abstention ≤ 0.10 on both; challenge paired consistency ≥ 0.90 and
abstain-group paired accuracy ≥ 0.80) and it leads every other eligible system
on human-judged unit F1 by ≥ 0.05. Otherwise it answers PENDING or NO_WINNER.
Nothing here routes production traffic.
