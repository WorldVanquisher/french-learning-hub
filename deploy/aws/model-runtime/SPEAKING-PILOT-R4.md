# Speaking training pilot R4: design, owner commands, cost and teardown (PREPARED, NOT RUN)

**Status (2026-11-20).**
- **Not run:** no AWS command, no upload, no training job. R4 holds no authorization for AWS
  reads or writes; every command below is the owner's.
- **Rehearsed locally:**
  - training intake;
  - pre-registration;
  - render;
  - teardown-order check;
  - cancellation;
  - inference dry-run.

  Evidence is listed in `docs/validation/EXTRACTION-R4.md`.

## 1. Candidate, baseline and held-out split (R4-EXT-051)

| | Value |
|---|---|
| Task | French speech recognition for FLH's Speaking transcription (local provider) |
| Baseline | `openai/whisper-base` @ `e37978b9…`, deployment `whisper-base@e37978b90ca9/flh_speaking_transcribe_v1/cpu-fp32/ac92e8688ef9e17b`: the approved default, unchanged |
| Candidate | `tools/speaking/configs/punct-base-encoder.json` (SHA-256 `24dc107d…`): encoder-only, FLEURS fr_fr punctuated train (manifest `920b74a0…`, 1,440 utterances), 180 steps, seed 20261117. It is the R3 24-step smoke at full length |
| Held-out (`flh_speaking_heldout_r4_v1`, the same for both) | MLS test 240 utt / 8 speakers and SLR57 accented 515 utt / 12 speakers (decision, pooled: 20 speaker groups). FLEURS ood 289 utt is diagnostic only: same corpus as training, no speaker IDs |

**Pre-registration.** `tools/speaking/aws/r4-pilot.prereg.json` (SHA-256 `77a63007…`) was frozen
before any R4 run.

## 2. Thresholds, set before training (R4-EXT-052)

They are the unchanged candidate-review defaults (`flh_speaking_candidate_review_v1`) plus R3's
objective:

| Measure | Rule |
|---|---|
| WER | candidate − baseline ≤ −0.02, 95% speaker-bootstrap upper bound ≤ 0, no speaker group worse by more than 0.05 |
| CER | candidate − baseline ≤ 0 |
| Support | ≥ 30 paired samples and **≥ 30 speaker groups** |
| Resources | RTF ≤ 0.5, peak RSS ≤ 2,048 MB |
| G1–G3 | punctuated share ≥ 0.8 × base; MLS WER difference upper bound ≤ +1.0 pt; RTF ≤ 0.5 and RSS ≤ 2,048 MB |

**Declared outcome before running.** The pooled held-out has 20 speaker groups, so the review
ends `insufficient_support` (exit 4): **an observation, whatever the WER.**

**What the pilot can and cannot do.** It can show whether 180 steps keep G1–G3 and move WER or
CER. It cannot promote. Promotion needs an owner-approved evaluation source that adds at least
10 speaker groups disjoint from training. One candidate is Common Voice French (CC0, client IDs),
which needs the owner to accept its terms; an intake manifest for it would go through
`lab training-intake` first.

## 3. One bounded job (R4-EXT-053/054/055)

`python3 -I -B tools/speaking/aws/pilot_r4.py render VALUES.json OUT_DIR` checks the values against
the pre-registration, then renders through `render.py`.

The example rendered offline with placeholder account, bucket and image digest, and no
credentials: `speaking-r4/flh-speaking-r4pilot-20261120-000000.json`. Its settings:

| Setting | Value |
|---|---|
| Instance | 1 × `ml.g5.xlarge`, Spot, `MaxRuntimeInSeconds` 3600, `MaxWaitTimeInSeconds` 7200, one retry, network isolation |
| Inputs | `s3://BUCKET/speaking/datasets/<data sha>/`, `s3://BUCKET/speaking/models/whisper-base/<revision>/`, both pinned by hash; the job refuses another dataset hash |
| Checkpoints | `s3://BUCKET/speaking/checkpoints/<job>/` ↔ `/opt/ml/checkpoints`. The trainer saves every 5 steps and keeps 2; a Spot interruption resumes from the latest (byte-identical weights, R3) |
| Output | `s3://BUCKET/speaking/output/<job>/output/model.tar.gz` |
| Cancellation | `stop-training-job` sends SIGTERM. The trainer finishes the current step, writes a checkpoint and returns `interrupted` (tested: `tests/test_train.py` `test_sigterm_finishes_the_step_saves_and_resumes_identically`, run in the CPU image) |
| Tags | `Project`, `Component`, `Run=r4pilot`, `DatasetSha256`, `ImageDigest`, `Owner`, `DeleteAfter` ≤ 31 days |

The render refuses:
- another dataset, base revision or run name;
- a config changed since the pre-registration;
- a `DeleteAfter` beyond 31 days;
- any credential-like string;
- checkpoints outside the job's prefix;
- more than one retry;
- everything `render.py` already bounds.

## 4. Cost envelopes, dated (R4-EXT-061)

| Envelope | Estimate | Assumption (date, source) |
|---|---|---|
| **Training**, one pilot | ≤ **$1.41** compute (1 h cap × $1.408/h on-demand; Spot bills at most that). Expected 10–20 min ≈ $0.25–0.50 | `ml.g5.xlarge` training, us-east-1, AWS Price List extract of 2026-11-07 (`tools/speaking/aws/README.md` §3) |
| Training storage until teardown | ≈ $0.06/month S3 (dataset 0.55 GB + base 0.28 GB + output ≈ 1.6 GB at $0.023/GB-month) + ≈ $0.70/month ECR (GPU image ≈ 7 GB at $0.10/GB-month) | same extract; the ECR price is not verified per region |
| Logs and transfer | < $0.05 | a few hundred log lines; ≈ 0.3 GB model download at $0.09/GB |
| **Recommended ceiling** for one pilot, with one retry and a month of storage | **$5** | the owner sets the actual budget |
| **Inference A**: local CPU (current) | $0 cloud | the base serves on the learner's machine; measured RTF 0.08–0.53 (load-dependent) |
| **Inference B**: staging sidecar | +≈ $0.0208/h ≈ $15/month continuous: t3.small → t3.medium | t3.small cannot hold FLH plus the 1.5 GiB speech service. Needs Release's IAM template change (STAGING-PLAN §0). Third-party price tracker, 2026-11-20, unverified |
| **Inference C**: SageMaker real-time `ml.m5.large` | ≈ $0.115/h ≈ $84/month | third-party price, 2026-11-20, unverified; not recommended |

Verify every price in the AWS Pricing Calculator for the chosen region before approval.

## 5. Quotas and permissions to check before any run (R4-EXT-062)

| Item | Needed | How to check (owner) | Known state |
|---|---|---|---|
| `ml.g5.xlarge for spot training job usage` | ≥ 1 | `aws service-quotas list-service-quotas --service-code sagemaker $P --query "Quotas[?contains(QuotaName,'ml.g5.xlarge for spot training job usage')].[QuotaName,Value]"` | unknown: the R3 read-only profile was denied `ListServiceQuotas` |
| `ml.g5.xlarge for training job usage` (on-demand fallback) | ≥ 1 if Spot is not granted | same query with that name | unknown |
| Operator permissions | `sagemaker:CreateTrainingJob`, `DescribeTrainingJob`, `StopTrainingJob`, `ListTrainingJobs`, `AddTags`; `iam:PassRole` on the execution role only (`iam:PassedToService` = `sagemaker.amazonaws.com`); `s3:PutObject`/`GetObject`/`ListBucket`/`DeleteObject` on `speaking/*`; ECR push to `flh-speaking`; `logs:FilterLogEvents` on `/aws/sagemaker/TrainingJobs` | IAM policy simulator, or a dry review of the profile's policies | not granted to any agent profile |
| Execution role | `tools/speaking/aws/exec-role-policy.json`: `speaking/*` prefixes and ECR `flh-speaking` only | review before creating | not created |
| Read-only profile (`flh-staging-extraction`) | `servicequotas:ListServiceQuotas`, `sagemaker:ListModels`, `ListEndpointConfigs` | — | denied in R3 (Release also saw `ListTransformJobs`, `ListDomains` denied) |

## 6. Owner commands: parameter contract, start, watch, stop (R4-EXT-063)

| Parameter | Contract |
|---|---|
| `REGION` | the approved region (us-east-1 priced above) |
| `PROFILE` | a writer profile the owner controls; never the read-only agent profile; no keys in files of this repository |
| `ACCOUNT` | 12 digits |
| `BUCKET` | the private artifact bucket |
| `ROLE_ARN` | the execution role created from `exec-role-policy.json` |
| `IMAGE_DIGEST` | `sha256:<64 hex>` of the pushed `flh-speaking` GPU image |
| `DATA_SHA` | `920b74a02c33ff8482573d31971af05de709554570a4a869bfdcf63420a5379b` (pre-registered) |
| `JOB` | printed by `pilot_r4.py render` |

```sh
set -euo pipefail
P="--profile $PROFILE --region $REGION"
W=$HOME/flh-speaking-work          # prepared data-punct and the pinned base model (R3)
# 0. quotas (section 5)
aws service-quotas list-service-quotas --service-code sagemaker $P --query "Quotas[?contains(QuotaName,'ml.g5.xlarge for spot training job usage')].[QuotaName,Value]" --output table
# 1. inputs, pinned by hash
aws s3 sync $W/data-punct s3://$BUCKET/speaking/datasets/$DATA_SHA/ $P
aws s3 sync $W/sources/openai/whisper-base/e37978b90ca9030d5170a5c07aadb050351a65bb s3://$BUCKET/speaking/models/whisper-base/e37978b90ca9030d5170a5c07aadb050351a65bb/ $P
# 2. values (no credentials), render, start
python3 - <<PY > $W/values.r4.json
import json; v = json.load(open("tools/speaking/aws/values.r4.example.json"))
v.update(REGISTRY="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com", IMAGE_DIGEST="$IMAGE_DIGEST", EXEC_ROLE_ARN="$ROLE_ARN", BUCKET="$BUCKET")
print(json.dumps(v, indent=2))
PY
JOBFILE=$(python3 -I -B tools/speaking/aws/pilot_r4.py render $W/values.r4.json $W/rendered)
JOB=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['TrainingJobName'])" $JOBFILE)
aws sagemaker create-training-job --cli-input-json file://$JOBFILE $P
# 3. watch
aws sagemaker describe-training-job --training-job-name $JOB $P --query '{s:TrainingJobStatus,ss:SecondaryStatus,t:TrainingTimeInSeconds,b:BillableTimeInSeconds}'
# 4. stop (any time; the trainer saves and exits)
aws sagemaker stop-training-job --training-job-name $JOB $P
aws sagemaker wait training-job-completed-or-stopped --training-job-name $JOB $P
```

## 7. Evidence, then teardown, in a checked order (R4-EXT-064)

`tools/speaking/aws/r4-teardown-plan.json` is the order, checked with
`python3 -I -B tools/speaking/aws/pilot_r4.py teardown-check tools/speaking/aws/r4-teardown-plan.json`:

1. stop if running;
2. wait for a terminal state;
3. copy evidence;
4. endpoint → endpoint config → model (only if any were created; the pilot creates none);
5. the job's checkpoint and output prefixes;
6. the dataset prefix, only if unused;
7. the ECR image, last and only if unreferenced;
8. verify that everything is empty.

The checker refuses:
- a deletion before the evidence copy or before the job is terminal;
- the image not last;
- a bucket-wide deletion;
- any deletion of retained evidence;
- a plan that does not end with verification.

```sh
E=$W/evidence/$JOB; mkdir -p $E
aws sagemaker describe-training-job --training-job-name $JOB $P > $E/describe.json
aws s3 cp s3://$BUCKET/speaking/output/$JOB/output/model.tar.gz $E/ $P && sha256sum $E/model.tar.gz > $E/model.tar.gz.sha256
aws logs filter-log-events --log-group-name /aws/sagemaker/TrainingJobs --log-stream-name-prefix $JOB $P > $E/logs.json
cp $JOBFILE $W/values.r4.json $E/
aws s3 rm --recursive s3://$BUCKET/speaking/checkpoints/$JOB/ $P
aws s3 rm --recursive s3://$BUCKET/speaking/output/$JOB/ $P
# only if no other approved job uses them:
aws s3 rm --recursive s3://$BUCKET/speaking/datasets/$DATA_SHA/ $P
aws ecr batch-delete-image --repository-name flh-speaking --image-ids imageDigest=$IMAGE_DIGEST $P
# verify
aws sagemaker list-training-jobs --name-contains flh-speaking-r4pilot $P --query 'TrainingJobSummaries[].[TrainingJobName,TrainingJobStatus]'
aws s3 ls s3://$BUCKET/speaking/ --recursive $P | grep -c "$JOB" || true    # expect 0
```

## 8. Conditions for a later live synthetic pilot (R4-EXT-065)

All of these, recorded by the owner before the first AWS write:

1. **Authorization.** Written approval naming:
   - the account and region;
   - the writer profile;
   - the budget ceiling (≤ $5 recommended for one run);
   - a budget alert. The alert notifies and never stops spending.
2. **Data scope.** Public, licensed data only: FLEURS train CC BY 4.0; held-out MLS CC BY 4.0
   and SLR57 Apache-2.0. No learner audio or text, and no new source without an eligible
   `lab training-intake` report and the owner's fetch approval.
3. **Quotas.** Spot (or on-demand) `ml.g5.xlarge` training quota ≥ 1, confirmed by the owner's
   query (§5).
4. **Frozen inputs.**
   - pre-registration `77a63007…` unchanged;
   - config `24dc107d…`;
   - dataset `920b74a0…`;
   - image pushed by digest, built from the reviewed `tools/speaking/Dockerfile`;
   - the render passes.
5. **Local gates green on the same tree.**
   - the strict Speaking suite in the image (135 run, 0 skipped);
   - the teardown plan check;
   - the cancellation test.
6. **Stop rules accepted.**
   - 180 steps;
   - 1 h runtime;
   - 2 h Spot wait;
   - one retry;
   - an owner stop at any time.
7. **Promotion is separate.** The result stays an observation (20 speaker groups). Production
   promotion is a separate owner decision after an evaluation source brings support to 30
   groups.

## 9. Candidate report (R4-EXT-060)

Deterministic checks, which need no trained model:
- intake eligibility and refusals;
- pins and identities: the bundle seal verifies, and the deployment ID changes with the weights;
- the pre-registration hash;
- the render bounds;
- cancellation and resume determinism;
- service readiness, abstention (silence and tone give `no_speech`; an empty file gives 422)
  and pin enforcement (`unknown_model`).

These hold for any weights.

Trained-model evidence, which applies to the R3 24-step candidate only:

| Slice | WER base → candidate | Paired / CI | Standing |
|---|---|---|---|
| MLS test, 8 speakers | 27.12% → 27.32% | paired difference +0.21 pts, 95% −0.58 to +0.94 | observation |
| SLR57, 12 speakers | 37.69% → 36.48% | candidate CI 31.6–41.6% | observation |
| FLEURS ood, sentence clusters | 27.52% → 26.94% | — | diagnostic only (same corpus as training) |

Punctuation was kept (G1). Acceptance was KEEP_BASELINE.

It is unsuitable as promotion evidence because:
- support is 20 < 30 groups;
- there is a single seed;
- it was a 24-step smoke;
- FLEURS speaker overlap is unknown;
- the same author designed and evaluated it.

**Recommendation: keep the baseline.**
