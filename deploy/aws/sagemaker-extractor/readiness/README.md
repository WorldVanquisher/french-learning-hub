# Extractor training: AWS readiness package (prepared 2026-11-12, nothing submitted)

No AWS command, upload or job has been run. Every file here was produced
offline by `build_readiness.py` from deterministically regenerated data, with
placeholder account values (`values.example.json`). The owner runs every
step below.

| File | What it is |
|---|---|
| `input-manifest.json` | every file a job reads: SHA-256, bytes, records, S3 key; base model and revision; what is never uploaded |
| `output-manifest.json` | what each job must leave behind, and the offline checks before the next step |
| `rendered/*.json` | the four jobs rendered and bound-checked by `render_job.py` (1 × ml.g5.xlarge, runtime caps, network isolation, image by digest, no `eval` channel); **placeholder** registry, digest, role and bucket |
| `values.example.json` | the placeholders; real values stay outside the repository |

## Inputs (from `input-manifest.json`)

| File | Records | SHA-256 |
|---|---|---|
| `sft-train.jsonl` (base 1,076 + increment v2 169) | 1,245 | `4dab4e7bd8e2d14f174328ea221f43dc452f8954ec49ec348c6fa091d45eb1dd` |
| `sft-dev.jsonl` (base 124 + increment v2 13) | 137 | `31285fe884c8990f7f04bf13f6fb1aab1505bf9df2110bd8d5d8515c9de736fc` |
| `predict-smoke/eval-prompts.jsonl` (50-item frozen subset + the same 50 as the `rb` probe) | 100 | `d63dc7f5295e026ea991d3a87416c468d724573f2631a81ae22f2daa0dc31b22` |
| `predict-full/eval-prompts.jsonl` (200 frozen + 200 `rb` probe, inputs only) | 400 | `2974e13e66b7cb2816cb550ce33b764941f07a9e30f5d91bfe1b3d08d38d57eb` |
| base model `Qwen/Qwen3.5-4B` | — | revision `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`, 9,319,737,856 bytes of weights |

The base-only data (`2d9e7efe…` train, `fd58903c…` dev) remain reproducible
with the same commands for an ablation. References, probe references,
boundary cases and learner data are never uploaded.

## Regenerate and rebuild (offline)

```sh
cd tools/extraction
go build -o "$BIN/extraction-render" ../../cmd/extraction-render
python3 -I -B authoring/generate_train.py OUT/train
python3 -I -B authoring/generate_eval.py OUT/eval
python3 -I -B authoring/generate_increment.py OUT/inc
for f in train/candidates inc/increment_candidates eval/eval_candidates; do
  "$BIN/extraction-render" render -in OUT/$f.jsonl -out OUT/$(basename $f)-rendered.jsonl; done
python3 -B -m flh_extraction sft --candidates OUT/train/candidates.jsonl OUT/inc/increment_candidates.jsonl \
  --rendered OUT/candidates-rendered.jsonl OUT/increment_candidates-rendered.jsonl \
  --out OUT/sft-v2-all.jsonl --out-train OUT/rd/sft-train.jsonl --out-dev OUT/rd/sft-dev.jsonl
python3 -B -m flh_extraction eval-prompts --candidates OUT/eval/eval_candidates.jsonl \
  --rendered OUT/eval_candidates-rendered.jsonl --out OUT/rd/eval-prompts-inputs-only.jsonl
"$BIN/extraction-render" analyze -in OUT/eval/eval_candidates.jsonl -out OUT/eval-analyses.jsonl
python3 -B -m flh_extraction probe --eval OUT/eval/eval_candidates.jsonl --analyses OUT/eval-analyses.jsonl --variant rb --out OUT/probe-rb.jsonl
"$BIN/extraction-render" render -in OUT/probe-rb.jsonl -out OUT/probe-rb-rendered.jsonl
python3 -B -m flh_extraction eval-prompts --candidates OUT/probe-rb.jsonl --rendered OUT/probe-rb-rendered.jsonl --out OUT/rd/probe-rb-prompts.jsonl
python3 -B scripts/select_eval_subset.py OUT/eval/eval_candidates.jsonl OUT/rd/eval-prompts-inputs-only.jsonl OUT/sub50
python3 -B scripts/select_eval_subset.py --like OUT/sub50/ids.txt '#rb' OUT/probe-rb.jsonl OUT/rd/probe-rb-prompts.jsonl OUT/sub50-probe
cp OUT/sub50/prompts.jsonl OUT/rd/sub50-prompts.jsonl; cp OUT/sub50-probe/prompts.jsonl OUT/rd/sub50-probe-prompts.jsonl
python3 -B ../../deploy/aws/sagemaker-extractor/build_readiness.py OUT/rd OUT/readiness values.json   # real values, outside the repo
```

The file hashes must equal the table above; a difference means the inputs changed.

## Bounded smoke-to-experiment sequence

Each step has a gate; a failed gate stops the sequence. Prices: `ml.g5.xlarge`
training $1.408/h in us-east-1 (TRAINING_RUNBOOK.md §10).

| Step | What | Bound | Gate to continue |
|---|---|---|---|
| 0 | Offline gates (done 2026-11-12): audit, increment-check, split check, SFT hashes, template/LoRA verification, 37 tests | local | all pass (docs/validation/EXTRACTOR-QUALITY-V1.md) |
| 1 | Token-level check with the real tokenizer (no GPU): `scripts/verify_profile.py --tokenizer` | local | 0 prefix errors, 0 over 1,280 tokens, 0 answers over 512 |
| 2 | Human review packet (`tools/extraction/review/REVIEW_PACKET_V2.md`, 25 items) | owner | ≤ 10 % rejected; fixes applied and regenerated |
| 3 | Build the GPU image from `tools/extraction` (pinned requirements), push, record the digest | — | the image's build-time import check passes |
| 4 | Upload base weights (pinned revision) and the two SFT files under `extractor/datasets/<train sha>/` | storage cents | uploaded hashes = input manifest |
| 5 | `rendered/sft-smoke.json` (12 steps) | 0.5 h, **≤ $0.70** | output-manifest checks; projected experiment ≤ 9,000 s |
| 6 | `rendered/predict-base.json` (untuned Qwen3.5-4B, 100 prompts) | 1 h, **≤ $1.41** | 100 rows; inference rate known; untuned baseline reports written |
| 7 | `rendered/sft-experiment.json` (3 epochs, 234 steps) | 3 h, **≤ $4.22** | output-manifest checks; adapter copied to `extractor/adapters/<job>/` |
| 8 | `rendered/predict-eval.json` (adapter, 400 prompts) — split into two jobs if step 6's rate says 400 will not fit in 1 h | 1 h each, **≤ $1.41 each** | 400 rows |
| 9 | Local scoring and `promotion-check` | local | see below |

Worst case for steps 5–8: $0.70 + $1.41 + $4.22 + 2 × $1.41 = **$9.15** of
compute, plus cents of storage. No step retries automatically; a failed job
is diagnosed from `/opt/ml/output/failure` before anything is resubmitted.

```sh
# Step 1 (owner, any machine with requirements-train.txt installed; tokenizer files only, no weights)
hf download Qwen/Qwen3.5-4B config.json tokenizer_config.json tokenizer.json vocab.json merges.txt chat_template.jinja \
  model.safetensors.index.json --revision 851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a --local-dir ~/models/qwen3.5-4b-851bf6e8-meta
python3 -B tools/extraction/scripts/verify_profile.py --profile qwen3.5-4b --meta ~/models/qwen3.5-4b-851bf6e8-meta \
  --sums tools/extraction/configs/qwen3.5-4b-851bf6e8.sha256 \
  --tokenizer ~/models/qwen3.5-4b-851bf6e8-meta --sft OUT/rd/sft-train.jsonl OUT/rd/sft-dev.jsonl \
  --max-length 1280 --max-new-tokens 512 --out OUT/qwen3.5-4b-verification-tokens.json
# Steps 5-8: exactly as TRAINING_RUNBOOK.md §3-8, with the rendered files from build_readiness.py and real values
aws sagemaker create-training-job --region "$REGION" --cli-input-json file://OUT/readiness/rendered/sft-smoke.json
```

## Promotion acceptance criteria (pre-registered: `flh_extraction/promotion.py`)

"Promotion" means only: eligible to be proposed to the owner as the
extractor candidate in a separate, owner-approved integration task. Nothing
here routes production traffic.

| # | Criterion | Basis |
|---|---|---|
| 1 | structural validity ≥ 0.98 on the frozen evaluation **and** on the `rb` probe | exact |
| 2 | abstention on zero-unit references ≥ 0.90 on both | exact |
| 3 | production-input robustness: probe abstention drops by ≤ 0.10 and over-abstention rises by ≤ 5 % of unit references | exact |
| 4 | exact unit-count rate ≥ baseline − 0.05 | exact |
| 5 | human-judged unit F1 ≥ baseline − 0.05, with ≥ 100 judged examples for each model | human |
| 6 | human-judged unsupported / false-claim rate ≤ baseline | human |
| 7 | dev loss never rises at two consecutive evaluations | exact |
| 8 | the run's data hashes equal this input manifest; `suitable_for_production` false | exact |
| 9 | review packet: ≥ 25 verdicts, ≤ 10 % rejected | human |

The baseline is the current extractor (one paid request per input, owner
decision) or, failing that, the untuned Qwen3.5-4B from step 6. Heuristic
metrics (split/merge, grounding, bilingual) are reported and never gate.
`promotion-check` answers ELIGIBLE_FOR_OWNER_DECISION only when every
criterion passes; until human judgments exist it answers PENDING.

```sh
python3 -B -m flh_extraction promotion-check --candidate-frozen OUT/cand/quality.json --candidate-probe OUT/cand/probe-quality.json \
  --baseline-frozen OUT/base/quality.json --baseline-probe OUT/base/probe-quality.json --losses OUT/exp/losses.jsonl \
  --run-manifest OUT/exp/run_manifest.json --input-manifest deploy/aws/sagemaker-extractor/readiness/input-manifest.json \
  --review tools/extraction/review/review-packet-v2.jsonl --out OUT/promotion
```
