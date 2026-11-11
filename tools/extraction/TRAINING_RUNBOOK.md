# Knowledge-extractor training: experiment proposal and runbook

**Status (2026-11-10): data and pipeline prepared; no model has been trained
or evaluated.** The only training runs were CPU smoke runs of a tiny,
randomly initialized fixture model that prove the pipeline mechanics. No
AWS command, upload or job has been run, and no paid provider has been called.

## 1. The experiment (one, bounded)

| Item | Choice |
|---|---|
| Task | the production `knowledge_extraction_v2` contract: the same developer instruction and user payload (`extraction-render render`), the same JSON output |
| Base model | `Qwen/Qwen3-1.7B`, Apache-2.0, revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e` (Hugging Face API, 2026-11-10) |
| Why this model | small enough for one 24 GB GPU with LoRA; French and Chinese capable (both statements are required); a chat template with a non-thinking mode (`enable_thinking: false`), checked on all 1,200 records: the prompt is an exact token prefix and every record fits 1,024 tokens (max 988, median 628) |
| Alternative to check first | the Qwen3.5 small models (0.8B/2B, published 2026-02) are tagged image-text-to-text on Hugging Face; confirm text-only fine-tuning support before comparing |
| Method | LoRA r=16 on attention and MLP projections, bf16, 3 epochs, lr 2e-4, batch 4 × accumulation 4 (`configs/sft-qwen3-1.7b-lora.json`); loss on the answer tokens only |
| Data | 1,076 train + 124 dev synthetic, machine-authored, **unreviewed** candidates; split by learning point and family |
| Comparison | the current extractor and the fine-tuned model on the **same frozen 200 evaluation candidates**, both through the production validator (`extraction-render validate`) and the harness (`python3 -m flh_extraction evaluate`), with human match judgments |

**Pre-registered success criteria** (on the frozen evaluation set, semantic
numbers from human judgments only):
1. structural validity ≥ 0.98 (production validator);
2. abstention on zero-unit references ≥ 0.90, and no `INJECTION_FOLLOWED`;
3. unit F1 within 0.05 of the current extractor or better, with
   `FALSE_CLAIM` no higher than the current extractor;
4. no evidence of overfitting on dev (dev loss rises for two evaluations in a row → stop).

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

## 2. Local checks (no network after installation)

```sh
cd tools/extraction
python3 -B -m unittest discover -s tests -t tests                      # standard-library tests
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
python3 -c "from huggingface_hub import snapshot_download as s; s('Qwen/Qwen3-1.7B', revision='70d244cc86ccca08cf5af4e1e306ecf908b1ad5e', local_dir='qwen3-1.7b')"
aws s3 cp --recursive qwen3-1.7b s3://$BUCKET/extractor/models/qwen3-1.7b-70d244cc/
# 5. Synthetic SFT data (train and dev only; never the evaluation references)
TRAIN_SHA=$(sha256sum OUT/sft-train.jsonl | cut -d' ' -f1)
aws s3 cp OUT/sft-train.jsonl s3://$BUCKET/extractor/datasets/$TRAIN_SHA/train/sft-train.jsonl
aws s3 cp OUT/sft-dev.jsonl   s3://$BUCKET/extractor/datasets/$TRAIN_SHA/dev/sft-dev.jsonl
# 6. Smoke job: render locally (bounds enforced), read it, then submit
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
`BUCKET`, `BASE_MODEL_KEY` (`qwen3-1.7b-70d244cc`), `TRAIN_SHA256`,
`DEV_SHA256`, `CONFIG_JSON` (the config as a JSON string) and, for
prediction, `PROMPTS_SHA256` and `ADAPTER_KEY`. The renderer refuses another
instance type, a longer runtime than the run's bound, network access, an
image tag instead of a digest, a smoke config in the experiment, and any
`eval` channel. The container refuses a dataset whose hash differs from the
hyperparameter and refuses an `eval` channel too.

## 9. Scoring (local)

```sh
# Attach the candidates' inputs to the predictions, then the production validator and the harness:
python3 -B -m flh_extraction attach-inputs --predictions predictions.jsonl --candidates OUT/eval/eval_candidates.jsonl --out predictions-with-inputs.jsonl
/tmp/extraction-render validate -in predictions-with-inputs.jsonl -out results-sft.jsonl
# The current extractor's baseline: one paid request per input (owner decision; never run here)
EXTRACTOR_PROVIDER=openai OPENAI_MODEL=<model> OPENAI_API_KEY=… \
  /tmp/extraction-render run -in OUT/eval/eval_candidates.jsonl -out results-current.jsonl -max-requests 200 -confirm-paid-calls
python3 -B -m flh_extraction evaluate --refs OUT/eval/eval_candidates.jsonl --results results-current.jsonl --judgments judgments.jsonl --title "Current extractor" --out report-current
python3 -B -m flh_extraction evaluate --refs OUT/eval/eval_candidates.jsonl --results results-sft.jsonl --judgments judgments.jsonl --title "Qwen3-1.7B LoRA" --out report-sft
```

## 10. Cost bound

`ml.g5.xlarge` training is **$1.408 per hour** in us-east-1 ($2.04 in
ap-northeast-1), from the official AmazonSageMaker Price List extract kept
with the A6 handoff (publication 2026-11-07). Bounds by `MaxRuntimeInSeconds`:
smoke ≤ 0.5 h = **$0.70**; experiment ≤ 3 h = **$4.22**; prediction ≤ 1 h =
**$1.41**; storage of ~3.5 GB of weights is cents per month. The current
extractor's baseline is 200 provider requests at the owner's model price.

## 11. Never

- Training on evaluation records or boundary cases; uploading learner data;
  routing production extraction to a trained model (nothing here touches the
  live extractor configuration).
- Calling a smoke checkpoint a model: every `run_manifest.json` says
  `suitable_for_production: false`.
