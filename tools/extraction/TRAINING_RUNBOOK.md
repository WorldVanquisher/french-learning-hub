# Knowledge-extractor training: experiment proposal and runbook

**Status (2026-11-11): data and pipeline prepared; no model has been trained
or evaluated.** The default candidate is now **Qwen/Qwen3.5-4B** (§1a); the
pending Qwen3-1.7B baseline is **superseded and was never run**.

What actually ran:
- the CPU smoke runs of 2026-11-10 used a tiny, randomly initialized
  Qwen2-architecture fixture (`tests/build_tiny_model.py`, transformers 4.57.6),
  not Qwen3 or Qwen3.5;
- on 2026-11-11, a tiny randomly initialized **Qwen3.5-architecture** model
  (4 layers, 16 M parameters, the real Qwen3.5 tokenizer) was used only to
  prove loading, LoRA, save/reload and prediction under transformers 5.21.1.

Neither is a model. No real Qwen3.5-4B weights were downloaded and no
inference with them was run. No AWS command, upload or job has been run, and
no paid provider has been called.

**2026-11-12 (extractor-quality lane):** a failure-mode audit, a targeted
increment of 182 synthetic candidates (§1b), a separate-metric quality report
with a production-input probe and controlled failures, an offline verification
of the Qwen3.5-4B profile against the checkpoint's own files, and an AWS
readiness package (`deploy/aws/sagemaker-extractor/readiness/`). Still no
model has been trained or evaluated, and no quality improvement is claimed.
Evidence: `docs/validation/EXTRACTOR-QUALITY-V1.md`.

## 1. The experiment (one, bounded)

| Item | Choice |
|---|---|
| Task | the production `knowledge_extraction_v2` contract: the same developer instruction and user payload (`extraction-render render`), the same JSON output |
| Base model | `Qwen/Qwen3.5-4B`, Apache-2.0, revision `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` (Hugging Face API, 2026-11-11); profile `qwen3.5-4b` in `flh_extraction/models.py` |
| Superseded | `Qwen/Qwen3-1.7B` revision `70d244cc…` (profile `qwen3-1.7b`, `configs/sft-qwen3-1.7b-lora.json`): never run, kept for reproducibility |
| Why this model | French and Chinese capable (both statements are required); Apache-2.0; a chat template with a non-thinking mode; fits one 24 GB GPU with LoRA in bf16 (§1a). Text-only fine-tuning was verified to load and train through the standard causal-LM path (§1a) |
| Method | LoRA r=16 on the text stack's attention, linear-attention and MLP projections (profile targets), bf16, 3 epochs, lr 2e-4, batch 1 × accumulation 16, max_length 1280 (`configs/sft-qwen3.5-4b-lora.json`); loss on the answer tokens only |
| Data | 1,245 train + 137 dev synthetic, machine-authored, **unreviewed** candidates (base 1,076 + 124, increment v2 169 + 13, §1b); split by learning point and family. The base-only files stay reproducible for an ablation |
| Comparison | the current extractor and the fine-tuned model on the **same frozen 200 evaluation candidates and the same 200 as the production analyzer presents them** (`rb` probe, §1b), both through the production validator (`extraction-render validate`) and the harness (`python3 -m flh_extraction quality`), with human match judgments |

**Pre-registered success criteria** (on the frozen evaluation set, semantic
numbers from human judgments only):
1. structural validity ≥ 0.98 (production validator);
2. abstention on zero-unit references ≥ 0.90, and no `INJECTION_FOLLOWED`;
3. unit F1 within 0.05 of the current extractor or better, with
   `FALSE_CLAIM` no higher than the current extractor;
4. no evidence of overfitting on dev (dev loss rises for two evaluations in a row → stop).

These criteria, plus production-input robustness on the `rb` probe, data
integrity and the review gate, are evaluated mechanically by
`python3 -m flh_extraction promotion-check` (PASS / FAIL / PENDING;
`deploy/aws/sagemaker-extractor/readiness/README.md`).

**What must exist before GPU time is justified:**
1. The 30-item priority review packet and the topic-stratified queue reviewed
   (`REVIEW_QUEUE.md`), with ≤ 10 % of labels rejected. Otherwise the
   training labels are not trustworthy enough to learn from.
2. Human-reviewed labels for the evaluation set: at least the 40 edge cases
   and a stratified 100 single/multi items. Without them, every semantic
   number is agreement with machine-authored labels.
3. The current extractor's baseline on the evaluation set (step 9, one paid
   provider request per item: owner decision).
4. A passing SageMaker smoke job (step 6).

## 1a. Qwen3.5-4B: wiring and what was verified (2026-11-11)

The model-specific parts live in one profile (`flh_extraction/models.py`):
loader, chat-template options, LoRA targets and verified library versions.
Datasets, prompts, splits and the evaluator do not know which model is used.

Verified, in a disposable container (torch 2.15.0 CPU, transformers 5.21.1,
tokenizers 0.23.3, peft 0.21.2, huggingface_hub 2.4.0; network off for the checks):

| Check | Result |
|---|---|
| Library support | transformers 4.57.6 (the earlier pin) has **no `qwen3_5`**; 5.21.1 has it |
| Checkpoint | `Qwen3_5ForConditionalGeneration` (image-text-to-text): 24 Gated DeltaNet layers (`linear_attn.*`) and 8 full-attention layers (`self_attn.*`), vocabulary 248,320, tied embeddings, a 24-layer vision tower, 15 MTP tensors |
| Loader | `AutoModelForCausalLM` → `Qwen3_5ForCausalLM` loads `model.language_model.*` from a multimodal checkpoint with no missing or unexpected keys; logits equal the multimodal model's on a text prompt (tiny random model). The vision tower is not loaded; no processor, Pillow or torchvision is needed |
| Tokenizer / template | `Qwen3_5Tokenizer`, template from `chat_template.jinja`. **The template's default opens a thinking block** (`<think>\n`); the profile sets `enable_thinking: false`, so prompts end with an empty `<think></think>` block and labels contain no `<think>` |
| Masking | 1,076 train + 124 dev SFT records: 0 prefix errors. Fixed in `train.encode`: the template closes the turn itself (`<|im_end|>\n`), so the target now ends at that first `<|im_end|>` instead of `…<|im_end|>\n<|im_end|>` (this also affected the 1.7B template) |
| Lengths (Qwen3.5 tokenizer, after the masking fix) | train median 632 / p95 820 / max 980 tokens; dev max 965; answers max 386; eval prompts max 584. `max_length` 1280 truncates nothing; `max_new_tokens` 512 covers every answer |
| LoRA | profile regex targets `in_proj_qkv`, `in_proj_z`, `out_proj`, `q/k/v/o_proj` and the MLPs of the text stack only (25 modules in the 4-layer tiny model; vision and MTP never match) |
| Save / reload / predict | tiny Qwen3.5 model: 3 LoRA steps, adapter saved, base + adapter reloaded, prediction through `predict.py --profile qwen3.5-4b`; `scripts/untuned_baseline.sh` ran end to end (outputs unparseable, as expected from random weights) |
| Kernels | without `causal-conv1d` and `flash-linear-attention`, transformers uses a correct but much slower PyTorch fallback for the linear-attention layers. Not installed or tested here |

Estimates (not measured with real weights):
- **Disk:** 9,319,737,856 bytes of weights (BF16, two shards) plus about
  23 MB of tokenizer files: keep ≥ 20 GB free on the target volume, never `/tmp`.
- **Memory, inference:** about 9–10 GB of GPU memory in bf16 (text stack about
  8.5 GB, full-attention KV for 1.1 k tokens about 40 MB). On CPU, about 10–12 GB
  of RAM and the slow fallback kernels: not practical on the NAS (15 GB RAM, no GPU).
- **Memory, LoRA training on a 24 GB A10G:** weights about 8.5 GB plus activations
  for one 1,280-token sequence without gradient checkpointing; batch 1 is set for
  this reason. Confirm with the smoke job before the experiment.
- **Time:** unknown. The fallback kernels may make the 3 h experiment bound
  (§10) too short; the smoke job's duration decides.

## 1b. Increment v2 and what the audit found (2026-11-12)

`python3 -m flh_extraction audit` counts the training data by failure mode
(HEURISTIC; `docs/validation/EXTRACTOR-QUALITY-V1/`). The base set had one
misconception record, no wrong explanation, no record teaching that several
examples of one rule are one unit, and no `unreviewed` analysis. Above all,
`effective_category == "other"` separated zero-unit from unit records
perfectly, in training (203/203) **and in the frozen evaluation (20/20)**,
and zero-unit explanations described the abstention itself. The production
default analyzer (`rule-based:v2`) gives `other` only to input without
letters (0 of the 200 evaluation inputs) and explanations such as
`Local classification selected "grammar" because rule "multi_token_fallback" …`.
A model that abstains by reading the category is perfect on the frozen
evaluation and wrong on every production-style input (control
`category_shortcut`: 20/20 false extractions, 180/180 over-abstentions on the
`swap` probe).

`authoring/generate_increment.py` (hand-written `bank_increment_v2.py`, 182
records, every unit a training-bank point reused verbatim): 54
misconceptions, 15 wrong explanations, 40 zero-unit records under the real
analyzer's category and explanation, 29 counter-shortcut unit records (6 with
category `other`), 14 fragmentation, 14 two-error, 6 several-edits, 4
duplicate-question and 6 explanation-extra records; 133 `unreviewed`. The
analyzer's outputs for 123 inputs are frozen in
`authoring/increment_v2_rule_based.json` (`extraction-render analyze`).
`increment-check`: 182/182 production-valid, no new or evaluation point, no
canonical or headword shared with evaluation, no near pair ≥ 0.5 with
evaluation or boundary inputs, combined split check passes.

```sh
python3 -I -B authoring/generate_increment.py OUT/inc     # increment_candidates.jsonl 5a40c6e7…
/tmp/extraction-render expected -in OUT/inc/increment_candidates.jsonl -out OUT/inc/production-validation.jsonl
python3 -B -m flh_extraction increment-check --base OUT/train/candidates.jsonl --increment OUT/inc/increment_candidates.jsonl \
  --eval OUT/eval/eval_candidates.jsonl --boundary OUT/boundary/boundary_cases_v1.jsonl \
  --validated OUT/inc/production-validation.jsonl --out OUT/inc/increment-check.json
python3 -B -m flh_extraction audit --train OUT/train/candidates.jsonl OUT/inc/increment_candidates.jsonl \
  --eval OUT/eval/eval_candidates.jsonl --boundary OUT/boundary/boundary_cases_v1.jsonl --out OUT/audit
# Production-input probes of the frozen evaluation (never training data) and the controlled failures:
/tmp/extraction-render analyze -in OUT/eval/eval_candidates.jsonl -out OUT/eval-analyses.jsonl
python3 -B -m flh_extraction probe --eval OUT/eval/eval_candidates.jsonl --analyses OUT/eval-analyses.jsonl --variant rb --out OUT/probe-rb.jsonl
python3 -B -m flh_extraction probe --eval OUT/eval/eval_candidates.jsonl --analyses OUT/eval-analyses.jsonl --variant swap --out OUT/probe-swap.jsonl
python3 -B -m flh_extraction control-matrix --refs OUT/eval/eval_candidates.jsonl --render /tmp/extraction-render \
  --probe OUT/probe-swap.jsonl --out OUT/controls
python3 -B -m flh_extraction review-packet --base OUT/train/candidates.jsonl --increment OUT/inc/increment_candidates.jsonl \
  --probe OUT/probe-rb.jsonl --out OUT/review-packet
```

## 2. Local checks (no network after installation)

```sh
cd tools/extraction
python3 -B -m unittest discover -s tests -t tests                      # standard-library tests (37, 7 skipped)
TINY_SFT=OUT/sft-sample.jsonl python3 -B -m unittest discover -s tests -t tests   # + backend tests (needs requirements-train.txt)
python3 -B scripts/check_tokenizer.py qwen3.5-4b-851bf6e8 OUT/sft-train.jsonl --profile qwen3.5-4b --max-length 1280
# Profile vs the checkpoint's own small files (template, masking text, LoRA targets on the real weight names);
# add --tokenizer DIR for token-level masking and lengths:
python3 -B scripts/verify_profile.py --profile qwen3.5-4b --meta qwen3.5-4b-851bf6e8 --sums configs/qwen3.5-4b-851bf6e8.sha256 \
  --sft OUT/sft-train.jsonl OUT/sft-dev.jsonl --max-length 1280 --out OUT/profile-verification.json
go build -o /tmp/extraction-render ../../cmd/extraction-render
# Rebuild every dataset deterministically from the hand-written banks:
python3 -I -B authoring/build_boundary.py OUT/boundary
python3 -I -B authoring/generate_train.py OUT/train
python3 -I -B authoring/generate_eval.py OUT/eval
/tmp/extraction-render expected -in OUT/train/candidates.jsonl -out OUT/train/production-validation.jsonl
python3 -B -m flh_extraction check --train OUT/train/candidates.jsonl --eval OUT/eval/eval_candidates.jsonl \
  --boundary OUT/boundary/boundary_cases_v1.jsonl --out OUT/split-check.json
/tmp/extraction-render render -in OUT/train/candidates.jsonl -out OUT/rendered-train.jsonl
python3 -B -m flh_extraction sft --candidates OUT/train/candidates.jsonl --rendered OUT/rendered-train.jsonl --out OUT/sft-all.jsonl
# Backend tests and the CPU image (needs torch/transformers/peft; see requirements-train.txt):
docker build --build-arg TORCH_INDEX=cpu -t flh-extractor-sft:smoke-cpu .
```

## 3–8. SageMaker (owner, prepared, not run)

Prerequisites: a private, versioned S3 bucket; an ECR repository
`flh-extractor-sft`; an execution role from `deploy/aws/sagemaker-extractor/iam/`
(fill `__AWS_ACCOUNT_ID__`, `__AWS_REGION__`, `__BUCKET__` outside the
repository); a quota of at least 1 for `ml.g5.xlarge for training job usage`.
The A6 stack (unapplied) is bound to `flh-reranker-*` and `ml.m5.large`; if
it is reused, its submit policy must allow `ml.g5.xlarge` and
`flh-extractor-*` deliberately.

```sh
REGION=us-east-1; REG=<account>.dkr.ecr.$REGION.amazonaws.com; BUCKET=<bucket>
# 3. GPU image (torch from PyPI includes its CUDA runtime), pushed and pinned by digest
docker build -t flh-extractor-sft:gpu tools/extraction
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $REG
docker tag flh-extractor-sft:gpu $REG/flh-extractor-sft:gpu && docker push $REG/flh-extractor-sft:gpu
aws ecr describe-images --region $REGION --repository-name flh-extractor-sft --image-ids imageTag=gpu --query 'imageDetails[0].imageDigest'
# 4. Pinned base weights (network isolation: the job cannot download them)
hf download Qwen/Qwen3.5-4B --revision 851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a --local-dir qwen3.5-4b-851bf6e8   # ~9.3 GB
aws s3 cp --recursive qwen3.5-4b-851bf6e8 s3://$BUCKET/extractor/models/qwen3.5-4b-851bf6e8/
# 5. Synthetic SFT data (train and dev only; never the evaluation references)
TRAIN_SHA=$(sha256sum OUT/sft-train.jsonl | cut -d' ' -f1)
aws s3 cp OUT/sft-train.jsonl s3://$BUCKET/extractor/datasets/$TRAIN_SHA/train/sft-train.jsonl
aws s3 cp OUT/sft-dev.jsonl   s3://$BUCKET/extractor/datasets/$TRAIN_SHA/dev/sft-dev.jsonl
# 6. Smoke job (configs/sft-qwen3.5-4b-lora-smoke.json: 12 steps): render locally (bounds enforced), read it, then submit.
#    deploy/aws/sagemaker-extractor/build_readiness.py renders all four jobs at once from the data hashes.
python3 deploy/aws/sagemaker-extractor/render_job.py deploy/aws/sagemaker-extractor/jobs/sft-smoke.json.tmpl smoke state/ values.json
aws sagemaker create-training-job --region $REGION --cli-input-json file://state/<job>.json
aws sagemaker wait training-job-completed-or-stopped --region $REGION --training-job-name <job>
aws sagemaker describe-training-job --region $REGION --training-job-name <job> \
  --query '{Status:TrainingJobStatus,Billable:BillableTimeInSeconds,Failure:FailureReason}'
aws s3 cp s3://$BUCKET/extractor/output/<job>/output/model.tar.gz state/<job>/
# 7. Experiment job (only after the gates in §1): jobs/sft-experiment.json.tmpl, run "experiment"
# 8. Prediction job: inputs-only prompts + base model + the experiment's adapter
aws s3 cp OUT/eval-prompts-inputs-only.jsonl s3://$BUCKET/extractor/prompts/<sha>/eval-prompts.jsonl
python3 deploy/aws/sagemaker-extractor/render_job.py deploy/aws/sagemaker-extractor/jobs/predict-eval.json.tmpl predict state/ values.json
```

`values.json` holds `REGISTRY`, `IMAGE_DIGEST` (`sha256:…`), `EXEC_ROLE_ARN`,
`BUCKET`, `BASE_MODEL_KEY` (`qwen3.5-4b-851bf6e8`), `TRAIN_SHA256`,
`DEV_SHA256`, `CONFIG_JSON` (the config as a JSON string) and, for
prediction, `PROMPTS_SHA256` and `ADAPTER_KEY`. The renderer refuses another
instance type, a longer runtime than the run's bound, network access, an
image tag instead of a digest, a smoke config in the experiment, and any
`eval` channel. The container refuses a dataset whose hash differs from the
hyperparameter and refuses an `eval` channel too.

## 9. Scoring (local)

```sh
# Attach the candidates' inputs to the predictions, then the production validator and the harness
# (the predict-eval job answers the 200 frozen prompts and the 200 rb-probe prompts, so attach both):
cat OUT/eval/eval_candidates.jsonl OUT/probe-rb.jsonl > OUT/eval-and-probe.jsonl
python3 -B -m flh_extraction attach-inputs --predictions predictions.jsonl --candidates OUT/eval-and-probe.jsonl --out predictions-with-inputs.jsonl
/tmp/extraction-render validate -in predictions-with-inputs.jsonl -out results-sft.jsonl
# The current extractor's baseline: one paid request per input (owner decision; never run here)
EXTRACTOR_PROVIDER=openai OPENAI_MODEL=<model> OPENAI_API_KEY=… \
  /tmp/extraction-render run -in OUT/eval/eval_candidates.jsonl -out results-current.jsonl -max-requests 200 -confirm-paid-calls
python3 -B -m flh_extraction evaluate --refs OUT/eval/eval_candidates.jsonl --results results-current.jsonl --judgments judgments.jsonl --title "Current extractor" --out report-current
python3 -B -m flh_extraction evaluate --refs OUT/eval/eval_candidates.jsonl --results results-sft.jsonl --judgments judgments.jsonl --title "Qwen3.5-4B LoRA" --out report-sft
# Separate metrics, each labelled exact / heuristic / human; --outputs adds parse diagnostics of invalid outputs:
python3 -B -m flh_extraction quality --refs OUT/eval/eval_candidates.jsonl --results results-sft.jsonl --outputs predictions.jsonl \
  --judgments judgments.jsonl --title "Qwen3.5-4B LoRA" --out quality-sft
python3 -B -m flh_extraction quality --refs OUT/probe-rb.jsonl --results results-sft.jsonl --outputs predictions.jsonl \
  --judgments judgments.jsonl --title "Qwen3.5-4B LoRA, rb probe" --out probe-quality-sft
python3 -B -m flh_extraction quality-compare --a quality-sft.json --b probe-quality-sft.json --out frozen-vs-probe-sft
```

The `quality` report never adds heuristic and human numbers together, counts
an invalid output as invalid (not as an abstention), and labels a merged
unit MERGED (the automatic matcher previously reported it as MISSED).

## 9a. First untuned Qwen3.5-4B run (50 frozen examples, local GPU)

One command, no training, no network (weights at the pinned revision must
already be on disk). It selects a fixed 50-item subset of the frozen evaluation
set (all 20 zero-unit references, the fragmentation/duplicate/mixed cases, 10
two-unit references, 15 evenly spaced singles), predicts with thinking off,
validates with the production validator, runs the harness and reports
**schema validity, unsupported claims, abstention and splitting separately**
(`categories.md`). The evaluation file is only read.

```sh
cd tools/extraction
EVAL=OUT/eval/eval_candidates.jsonl PROMPTS=OUT/eval-prompts-inputs-only.jsonl RENDER=/tmp/extraction-render \
  bash scripts/untuned_baseline.sh /path/to/qwen3.5-4b-851bf6e8 OUT/untuned-qwen3.5-4b qwen3.5-4b
```

With `PROBE=OUT/probe-rb.jsonl PROBE_PROMPTS=OUT/probe-rb-prompts.jsonl` the
script also predicts the same 50 items as the production analyzer presents
them and writes `frozen-vs-probe.md`; `ADAPTER=DIR` evaluates a trained
adapter the same way. Every prediction row records `generated_tokens` and
`stopped` (`eos` / `max_new_tokens`). The script ran end to end on 2026-11-12
in the CPU image with a tiny random fixture (plumbing only).

Expected subset: candidates SHA-256 `6969427c508148c88a0ef116131f8ef09f802e7347934e8ff554d4502f68ef3a`,
prompts `656a24d50858ff063ef54d37db190c91c010f3d641c7bd879a22fd7df3231118`
(from eval `99602feb…` and prompts `68a2c499…`). Semantic numbers are
PROVISIONAL (automatic matcher); FALSE_CLAIM needs human claim judgments.
The SageMaker prediction template always mounts an `adapter` channel, so an
untuned prediction job there needs a template variant (owner decision).

## 10. Cost bound

`ml.g5.xlarge` training is **$1.408 per hour** in us-east-1 ($2.04 in
ap-northeast-1), from the official AmazonSageMaker Price List extract kept
with the A6 handoff (publication 2026-11-07). Bounds by `MaxRuntimeInSeconds`:
smoke ≤ 0.5 h = **$0.70**; experiment ≤ 3 h = **$4.22**; prediction ≤ 1 h =
**$1.41**; storage of ~9.3 GB of weights is cents per month. With Qwen3.5-4B
these bounds are untested: the smoke job (≤ 0.5 h) must show the step time
before the experiment is submitted. The current
extractor's baseline is 200 provider requests at the owner's model price.

## 11. Never

- Training on evaluation records or boundary cases; uploading learner data;
  routing production extraction to a trained model (nothing here touches the
  live extractor configuration).
- Calling a smoke checkpoint a model: every `run_manifest.json` says
  `suitable_for_production: false`.
