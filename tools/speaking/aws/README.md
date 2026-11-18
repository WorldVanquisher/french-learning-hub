# Speaking training pilot on SageMaker: prepared, NOT launched

**Status: not submitted.** No AWS command was run by the agent.

- **No monetary budget is established.** The repository records prices and
  per-job runtime bounds (`tools/extraction/TRAINING_RUNBOOK.md` §10), but no
  approved spending limit.
- **The repository forbids agents from running AWS commands**: "the owner runs
  them" (`AGENTS.md`, FLH-084).

Per the batch rules, the pilot therefore ran locally on CPU (see the
validation memo). This directory holds what the owner needs to run the same
job on AWS: a template, an IAM policy, a bounded renderer, the cost estimate
and exact commands.

## 1. Existing infrastructure and limits found

| Item | Found | Source |
|---|---|---|
| Training service | SageMaker training jobs, `ml.g5.xlarge`, network isolation, image by digest | `deploy/aws/sagemaker-extractor/` |
| Execution role | `extractor/*` S3 prefixes and ECR repository `flh-extractor-sft` only | `deploy/aws/sagemaker-extractor/iam/exec-role-policy.json` |
| Price | `ml.g5.xlarge` training **$1.408/h** in us-east-1 ($2.04 in ap-northeast-1), from the AWS Price List extract of 2026-11-07 | `tools/extraction/TRAINING_RUNBOOK.md` §10 |
| Runtime bounds | smoke ≤ 0.5 h, experiment ≤ 3 h (extractor jobs) | same |
| Budget | **none established** (paid runs NO-GO in every FLH-154 handoff) | `docs/validation/FLH-154-part4-memo.md` |
| Region | not fixed in the repository; the price above is for us-east-1 | — |

The Speaking job needs its own role policy (`exec-role-policy.json`:
`speaking/*` prefixes, ECR repository `flh-speaking`). The extractor role is
deliberately not widened.

## 2. Smallest suitable option

One `ml.g5.xlarge` (1 × A10G 24 GB, 4 vCPU, 16 GiB), the instance the
repository already prices and allows.

- **Spot** (`EnableManagedSpotTraining`): the trainer resumes from
  `/opt/ml/checkpoints`, which SageMaker syncs to S3, so an interruption costs
  at most `save_every` steps. The trainer's own interrupted-then-resumed run
  gives bit-identical weights (tests).
- **Bounds**: `MaxRuntimeInSeconds` 3600 and `MaxWaitTimeInSeconds` 7200, one
  retry, network isolation, every input pinned by hash.
- **Not suitable**: the local CPU (four cores, about 2 GB of free memory beside
  the NAS services) only fits whisper-base with a frozen decoder. A full
  whisper-small fine-tune needs the GPU.

## 3. Cost estimate (one pilot)

| Item | Estimate | Basis |
|---|---|---|
| Training compute | **≤ $1.41** (1 h cap × $1.408; Spot bills the Spot price, at most on-demand) | expected 10–20 min including startup and image pull, so ≈ $0.25–0.50 on-demand |
| S3 storage | ≈ $0.07/month | dataset 0.92 GB + base model 0.29 GB + output ≈ 1.6 GB (model, trainer state, 2 checkpoints) at $0.023/GB-month (us-east-1) |
| ECR image | ≈ $0.70/month | GPU image ≈ 7 GB at $0.10/GB-month (unverified per region) |
| CloudWatch Logs | < $0.01 | a few hundred log lines |
| Data transfer | ≈ $0.03 | downloading ≈ 0.3 GB of model output at $0.09/GB |
| **Total** | **≈ $1.5 worst case for the run + ≈ $0.80/month until cleanup** | delete the artifacts after the evaluation (§6) |

## 4. Exact commands (owner, after setting a budget)

```sh
set -euo pipefail
REGION=us-east-1; ACCOUNT=<12 digits>; BUCKET=<artifact bucket>; W=$HOME/flh-speaking-work
cd tools/speaking
# 0. Budget alert (notifies only, never stops spending)
aws budgets create-budget --account-id $ACCOUNT --budget '{"BudgetName":"flh-speaking-pilot","BudgetLimit":{"Amount":"5","Unit":"USD"},"TimeUnit":"MONTHLY","BudgetType":"COST"}' \
  --notifications-with-subscribers '[{"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80},"Subscribers":[{"SubscriptionType":"EMAIL","Address":"<owner email>"}]}]'
# 1. GPU image (CUDA torch from PyPI), pushed by digest
aws ecr create-repository --region $REGION --repository-name flh-speaking --image-scanning-configuration scanOnPush=true
docker build -t flh-speaking:gpu .
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.$REGION.amazonaws.com
docker tag flh-speaking:gpu $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/flh-speaking:pilot
docker push $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/flh-speaking:pilot      # note the printed sha256 digest
# 2. Inputs, by hash (public CC-BY-4.0 audio; no learner data)
DATA_SHA=$(python3 -c "import json;print(json.load(open('$W/data-v1/dataset_manifest.json'))['manifest_jsonl_sha256'])")
aws s3 sync $W/data-v1 s3://$BUCKET/speaking/datasets/$DATA_SHA/ --exclude '*.tmp'
aws s3 sync $W/sources/openai/whisper-base/e37978b90ca9030d5170a5c07aadb050351a65bb s3://$BUCKET/speaking/models/whisper-base/e37978b90ca9030d5170a5c07aadb050351a65bb/
# 3. Role (trust: deploy/aws/sagemaker-extractor/iam/exec-role-trust.json; policy: this directory)
aws iam create-role --role-name flh-speaking-sagemaker-exec --assume-role-policy-document file://../../deploy/aws/sagemaker-extractor/iam/exec-role-trust.json
sed -e "s/__BUCKET__/$BUCKET/g" -e "s/__AWS_REGION__/$REGION/g" -e "s/__AWS_ACCOUNT_ID__/$ACCOUNT/g" aws/exec-role-policy.json > $W/speaking-role-policy.json
aws iam put-role-policy --role-name flh-speaking-sagemaker-exec --policy-name flh-speaking-train --policy-document file://$W/speaking-role-policy.json
# 4. Render (refuses anything outside the bounds) and submit
cp aws/values.example.json $W/values.json   # edit REGISTRY, IMAGE_DIGEST, EXEC_ROLE_ARN, BUCKET, DELETE_AFTER
JOB=$(python3 aws/render.py $W/values.json configs/pilot-base-encoder.json $W/rendered)
aws sagemaker create-training-job --region $REGION --cli-input-json file://$JOB
# 5. Monitor to completion or failure
NAME=$(python3 -c "import json;print(json.load(open('$JOB'))['TrainingJobName'])")
aws sagemaker wait training-job-completed-or-stopped --region $REGION --training-job-name $NAME
aws sagemaker describe-training-job --region $REGION --training-job-name $NAME \
  --query '{s:TrainingJobStatus,f:FailureReason,secs:TrainingTimeInSeconds,billable:BillableTimeInSeconds,model:ModelArtifacts.S3ModelArtifacts}'
aws logs tail /aws/sagemaker/TrainingJobs --region $REGION --log-stream-name-prefix $NAME > $W/$NAME.log
# 6. Fetch, verify, evaluate offline with the same commands as the local pilot
aws s3 cp s3://$BUCKET/speaking/output/$NAME/output/model.tar.gz $W/$NAME/ && tar -xzf $W/$NAME/model.tar.gz -C $W/$NAME/
python3 -c "import sys; sys.path.insert(0,'.'); from flh_speaking import train; print(train.verify_checkpoint('$W/$NAME'))"   # expect []
```

A failed or stopped job leaves `/opt/ml/output/failure` (one line, no data) and
its checkpoints. Resubmitting with the same `CheckpointConfig` URI resumes, and
the trainer refuses to resume if the config, data or base model changed. Never
resubmit a job whose outcome is unknown without describing it first.

## 5. Cleanup and inventory

```sh
aws s3 rm --recursive s3://$BUCKET/speaking/checkpoints/$NAME/
aws s3 rm --recursive s3://$BUCKET/speaking/output/$NAME/          # after the evaluation is sealed
aws ecr batch-delete-image --region $REGION --repository-name flh-speaking --image-ids imageTag=pilot
aws s3 ls --recursive --summarize s3://$BUCKET/speaking/ | tail -2       # remaining bytes
aws sagemaker list-training-jobs --region $REGION --status-equals InProgress --name-contains flh-speaking   # expect none
aws resourcegroupstaggingapi get-resources --region $REGION --tag-filters Key=Project,Values=flh Key=Component,Values=speaking-asr
```

Training jobs stop billing on completion; no endpoint, notebook or instance is
created. Only S3 objects, the ECR image and CloudWatch logs remain until
deleted.

## 6. Next job: the punctuated-target experiment (v2), prepared, NOT launched

The v1 pilot lost punctuation and case: its MLS targets have none, and the
encoder learned to steer the frozen decoder towards them. The next job repeats
it with one change, the training data: FLEURS French train with raw
transcriptions. Config: `configs/punct-base-encoder.json`, identical to
`pilot-base-encoder.json` except the note. The local CPU smoke of the same
settings ran 24 steps (validation memo, items 17-18). The full 180 steps need
the GPU: about 100 min of CPU time for the pilot, beside the NAS services.

| Input | Value |
|---|---|
| Dataset | `prepare-punctuated` output: 1,440 train utterances (4.65 h, 1,382 FLoRes sentences, 99.9 % punctuated) + 100 dev sentences; `manifest_jsonl_sha256` **`920b74a02c33ff8482573d31971af05de709554570a4a869bfdcf63420a5379b`**; 551 MB; FLEURS CC BY 4.0, no learner data |
| Base model | whisper-base `e37978b90ca9030d5170a5c07aadb050351a65bb` (as the pilot) |
| Image | the GPU image built from `requirements-gpu.lock`, referenced by digest |
| Bounds | as §2: 1 × `ml.g5.xlarge`, Spot, 1 h runtime cap, 2 h wait cap, network isolation, one retry |
| Expected runtime | 180 steps × batch 16 on an A10G: well under 15 min, plus 5-10 min startup and image pull |

Cost (us-east-1 prices from §1, which the owner should re-check):

| Item | Estimate |
|---|---|
| Training compute | **≤ $1.41** (1 h cap); expected ≈ $0.35-0.50 on demand, less on Spot |
| S3 | ≈ $0.06/month (dataset 0.55 GB + model 0.29 GB + output ≈ 1.6 GB) |
| ECR | ≈ $0.70/month (GPU image ≈ 7 GB), shared with the pilot |
| **Total** | **≈ $1.5 worst case + ≈ $0.76/month until cleanup (§5)** |

Owner commands: §4 with three changes.

```sh
DATA_SHA=920b74a02c33ff8482573d31971af05de709554570a4a869bfdcf63420a5379b
python3 -m flh_speaking fetch --dest $W/sources --what fleurs-fr-train          # pinned, verified
docker run --rm --network none -v $W/sources:/sources:ro -v $W/data-v1:/base:ro -v $W/data-punct:/out \
    flh-speaking:cpu prepare-punctuated --sources /sources --base-data /base --out /out
python3 -c "import json;print(json.load(open('$W/data-punct/dataset_manifest.json'))['manifest_jsonl_sha256'])"   # must print $DATA_SHA
aws s3 sync $W/data-punct s3://$BUCKET/speaking/datasets/$DATA_SHA/ --exclude '*.tmp'
# values.json: DATA_SHA256=$DATA_SHA, RUN=punct (the job is named flh-speaking-punct-<time>, tag Run=punct)
JOB=$(python3 aws/render.py $W/values.json configs/punct-base-encoder.json $W/rendered)
aws sagemaker create-training-job --region $REGION --cli-input-json file://$JOB
```

Evaluate the result exactly like the smoke candidate: `evaluate` on data-v1
`test` and `ood`, then data-accent `accent`, then `probes`, then
`accept --data $W/data-punct`. Promote only under `flh_speaking_acceptance_v1`.
For this candidate, FLEURS dev is near-domain, so read A2 with SLR57 accent
beside it.
