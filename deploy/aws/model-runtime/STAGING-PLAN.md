# Model runtime on AWS staging: plan, cost and teardown (PREPARED, NOT RUN)

**Status.** Agents ran only the owner-authorized **read-only** checks of 2026-11-20 (profile
`flh-staging-extraction`, us-east-1): caller identity, SageMaker training jobs (0) and endpoints
(0). The quota query was denied. Training, uploads, deployments and every other AWS write need
the owner's separate approval. Each step below is a command for the owner. The local rehearsal
of every step and its results: `docs/validation/EXTRACTION-3.md`.

Two runtime pieces, staged privately beside the Release lane's staging host
(`deploy/aws/private-staging/`, one t3.small, SSM port forwarding, no inbound rule):

| Piece | Image | Model | Memory | Reached by |
|---|---|---|---|---|
| Speech recognition (`flh_speaking` service) | `flh-speaking:cpu-final-20261120` | pinned `whisper-base` (approved default) and, for comparison only, the candidate bundle | 1.5 GiB limit (base peak ≈ 0.64–0.95 GB) | FLH, over the Compose network only |
| Extraction service (`flh_extraction.service`) | `flh-extraction-service:postmerge-20261120` | none (rules) | 256 MiB | FLH or the operator, over the Compose network or SSM |

## 0. Platform findings from the Release lane (2026-11-20; they edited none of this lane's files)

1. **`local` is refused by the daily wrapper, not only missing from Compose.**
   - `scripts/daily/flh-daily.sh check` accepts only `openai` or `disabled` for
     `SPEAKING_TRANSCRIPTION_PROVIDER`, so `local` stops at `check`/`up`.
   - Enabling it is one Release change set: the wrapper accepts `local` and requires `_BASE_URL`
     and `_MODEL`; Compose forwards `_BASE_URL` and `_TIMEOUT` (default empty, so the server's
     60 s applies); `RELEASE.md` and `test_wrapper.sh` change with it.
   - Release holds it as a patch until the owner approves the sidecar (their decision A11).
     Phase 1 keeps the provider disabled.
2. **The host shape is t3.small only.** The staging deploy policy (`flh-stg-deploy-ec2`) allows
   `ec2:InstanceType` t3.small only, and preflight checks the tfvars against it. A t3.medium host
   needs a Release IAM template change, plus the owner's acceptance of about +$15/month if left on.
3. **No IAM change for the artifacts.** The host can read `releases/*`, and `flh-stg-operate`
   can upload there, so `releases/model-runtime/…` is covered.
4. **The Compose network is `flh-staging_default`** (project `flh-staging`). The `docker port`
   check below, plus Release's plan check (no ingress, no EIP or load balancer), give no public
   route.
5. **Lifecycle:**
   - the sidecars run outside the bundle tool, so `flh-staging-bundle rollback` leaves them as
     they are;
   - with `--restart no` they do not survive the 4 h power-off, and a new host starts fresh;
   - the 16 GiB root holds two FLH bundles plus about 1.4 GB of image and weights.
6. **Request IDs.** The speech service neither reads nor echoes `X-Request-Id`, and FLH does not
   forward its own. Release records it as an application change gated on this lane and the
   owner. The extraction service already echoes it.

## 1. Deployment form (R3-061)

| Option | Cost | Latency and fit | Verdict |
|---|---|---|---|
| **Sidecar containers on the staging host** | t3.small → **t3.medium** (4 GiB) for the speech model: +$0.0208/h, ≈ +$15/month if left on | CPU transcription; RTF about 0.05–0.14 measured on 4 cores, and slower on a burstable 2-vCPU host; nothing leaves the VPC | **recommended for staging** |
| SageMaker real-time endpoint `ml.m5.large` | ≈ $0.115/h, about $84/month if left on (third-party price tracker; verify) | callers need SigV4: FLH's OpenAI-style client cannot call it without a proxy | not justified at this size |
| SageMaker serverless inference | per request, plus cold starts of tens of seconds for a 1.4 GB image | same SigV4 gap | not for an interactive "Transcribe" click |

**Sizing.** Whisper-base fits beside the app on 4 GiB. Whisper-small (about 1.3 GB peak) needs
the same host with its memory limit raised, or a larger host. That is the owner's choice (D1 in
`SPEAKING-MODEL-V1.md`).

## 2. IAM actions needed before provisioning (R3-001)

**Operator** (the person who runs the commands):

| Purpose | Actions |
|---|---|
| Identity and listing | `sts:GetCallerIdentity`, `sagemaker:ListTrainingJobs`, `sagemaker:ListEndpoints`. All held by `flh-staging-extraction` (verified) |
| Quotas | `servicequotas:ListServiceQuotas` / `GetServiceQuota`. **Missing** on `flh-staging-extraction` (denied) |
| Training job (only if approved) | `sagemaker:CreateTrainingJob`, `DescribeTrainingJob`, `StopTrainingJob`, `iam:PassRole` on `flh-speaking-sagemaker-exec`, `s3:PutObject`/`GetObject`/`ListBucket` on `speaking/*`, `logs:FilterLogEvents`/`GetLogEvents` on `/aws/sagemaker/TrainingJobs` |
| Image push | `ecr:GetAuthorizationToken`; `ecr:CreateRepository` once; `ecr:InitiateLayerUpload`, `UploadLayerPart`, `CompleteLayerUpload`, `PutImage`, `BatchCheckLayerAvailability` on `flh-speaking` |
| Staging artifacts | `s3:PutObject` on `releases/model-runtime/*` of the existing artifact bucket (the host already has `s3:GetObject` on `releases/*`) |
| Endpoint (not recommended) | `sagemaker:CreateModel`, `CreateEndpointConfig`, `CreateEndpoint`, `InvokeEndpoint`, and the matching `Delete*` for teardown |

**Training execution role:** `tools/speaking/aws/exec-role-policy.json`: `speaking/*` prefixes,
ECR `flh-speaking` pull, training logs. Its trust policy is
`deploy/aws/sagemaker-extractor/iam/exec-role-trust.json`.

**Endpoint cleanup before provisioning:** none needed. 0 endpoints and 0 training jobs on
2026-11-20.

## 3. The shortest credible AWS training run (R3-057; prepared, not submitted)

| Setting | Value |
|---|---|
| Config | `tools/speaking/configs/punct-base-encoder.json`: whisper-base, encoder-only, FLEURS fr_fr punctuated train, 180 steps, seed 20261117. The 24-step smoke of the same config ran locally |
| Instance | `ml.g5.xlarge` (1 × A10G), Spot, `MaxRuntimeInSeconds` 3600, `MaxWaitTimeInSeconds` 7200, network isolation, inputs pinned by hash |
| Dataset | `data-punct`, manifest SHA-256 `920b74a02c33ff8482573d31971af05de709554570a4a869bfdcf63420a5379b` (0.55 GB) |
| Base model | `openai/whisper-base` @ `e37978b90ca9030d5170a5c07aadb050351a65bb` (0.28 GB) |
| Rendered job | `tools/speaking/aws/render.py` produced a valid job file offline (with placeholder account, bucket and image digest) |

**Cost envelope** (per run): ≤ $1.41 compute (1 h cap × $1.408/h on-demand; Spot bills less),
plus about $0.80/month for S3 and ECR storage until cleanup, and under $0.05 in logs and
transfer. Basis: `tools/speaking/aws/README.md` §3, which uses the AWS price-list extract of
2026-11-07.

**Commands.** The `tools/speaking/aws/README.md` §4 sequence, with two substitutions: the
punctuated data and config.

```sh
REGION=us-east-1; ACCOUNT=<12 digits>; BUCKET=<artifact bucket>; W=$HOME/flh-speaking-work; P="--profile <writer profile> --region $REGION"
# quotas first (the read-only role cannot list them)
aws service-quotas list-service-quotas --service-code sagemaker $P --query "Quotas[?contains(QuotaName,'ml.g5.xlarge for spot training job usage') || contains(QuotaName,'ml.g5.xlarge for training job usage')].[QuotaName,Value]" --output table
DATA_SHA=920b74a02c33ff8482573d31971af05de709554570a4a869bfdcf63420a5379b
aws s3 sync $W/data-punct s3://$BUCKET/speaking/datasets/$DATA_SHA/ $P
# … image push, role, values.json exactly as tools/speaking/aws/README.md §4, with DATA_SHA256=$DATA_SHA, then:
JOB=$(python3 tools/speaking/aws/render.py $W/values.json tools/speaking/configs/punct-base-encoder.json $W/rendered)
aws sagemaker create-training-job --cli-input-json file://$JOB $P
aws sagemaker wait training-job-completed-or-stopped --training-job-name $(python3 -c "import json;print(json.load(open('$JOB'))['TrainingJobName'])") $P
```

**Stop rule (R3-059).** The job stops at the first of these:
- 180 steps;
- `MaxRuntimeInSeconds` 3600;
- `MaxWaitTimeInSeconds` 7200;
- `aws sagemaker stop-training-job --training-job-name NAME $P`.

A budget alert notifies; it never stops spending.

## 4. Staging deployment (R3-072–R3-077; prepared, not run)

```sh
# 0. on the build machine: images and the model bundle, by identity
docker save flh-speaking:cpu-final-20261120 | gzip > speaking-image.tar.gz
docker save flh-extraction-service:postmerge-20261120 | gzip > extraction-image.tar.gz
tar -C $HOME/flh-speaking-work/sources/openai/whisper-base -czf whisper-base.tar.gz e37978b90ca9030d5170a5c07aadb050351a65bb
sha256sum speaking-image.tar.gz extraction-image.tar.gz whisper-base.tar.gz > SHA256SUMS
# 1. upload only these approved artifacts to the private store (R3-072)
aws s3 cp . s3://$BUCKET/releases/model-runtime/20261120/ --recursive --exclude '*' --include '*.tar.gz' --include SHA256SUMS $P
# 2. on the host (SSM session): fetch, verify, load, run on the Compose network only (no published port)
aws s3 cp s3://$BUCKET/releases/model-runtime/20261120/ /srv/flh-staging/model-runtime/ --recursive --region $REGION
cd /srv/flh-staging/model-runtime && sha256sum -c SHA256SUMS && docker load < speaking-image.tar.gz && docker load < extraction-image.tar.gz
mkdir -p models && tar -C models -xzf whisper-base.tar.gz
docker run -d --name flh-speaking --network flh-staging_default --restart no --oom-score-adj 1000 --memory 1536m --read-only \
    -v /srv/flh-staging/model-runtime/models:/models:ro flh-speaking:cpu-final-20261120 \
    serve --model /models/e37978b90ca9030d5170a5c07aadb050351a65bb --host 0.0.0.0 --port 8765
docker run -d --name flh-extraction --network flh-staging_default --restart no --read-only --memory 256m --cap-drop ALL \
    --security-opt no-new-privileges flh-extraction-service:postmerge-20261120
# 3. FLH settings (Release lane): see "Configuration inputs" below; restart the app, then:
docker exec flh-speaking python3 -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8765/manifest').read()[:200])"
```

## 5. Configuration inputs for Release (R3-070)

| Setting | Value |
|---|---|
| `SPEAKING_TRANSCRIPTION_PROVIDER` | `local`. Forwarded by `compose.yaml`, but **refused by `flh-daily.sh check`** until Release's change set lands (§0.1) |
| `SPEAKING_TRANSCRIPTION_MODEL` | the `deployment_id` from the service's `GET /manifest`; for the pinned base in the final image it is recorded in `docs/validation/EXTRACTION-3.md` |
| `SPEAKING_TRANSCRIPTION_BASE_URL` | `http://flh-speaking:8765/v1`. **Not forwarded by `compose.yaml` yet** |
| `SPEAKING_TRANSCRIPTION_TIMEOUT` | `60`. **Not forwarded by `compose.yaml` yet** |
| Extraction service | `http://flh-extraction:8090`; the app does not call it until an owner-approved change wires it in (`tools/extraction/SERVICE.md` §7) |

**Proposed `compose.yaml` hunk.** This is the Release lane's file, so this lane has not changed
it. Under the app's `environment`, next to the two existing lines:

```yaml
      SPEAKING_TRANSCRIPTION_BASE_URL: ${SPEAKING_TRANSCRIPTION_BASE_URL:-}
      SPEAKING_TRANSCRIPTION_TIMEOUT: ${SPEAKING_TRANSCRIPTION_TIMEOUT:-60}
```

## 6. Checks on staging (R3-074–R3-079), the same as the local rehearsal

1. Only the Compose network reaches either service: `docker port flh-speaking` and
   `docker port flh-extraction` print nothing, and no security-group rule changes.
2. Model-only probes, inside the host:
   ```sh
   docker run --rm --network flh-staging_default -v /srv/flh-staging/model-runtime/probe-audio:/a:ro flh-speaking:cpu-final-20261120 …
   ```
   Use the synthetic or public clips that `verify_local_provider.py prep` writes.
3. Extraction health and grounding: `python3 -B -m flh_extraction.service smoke --url http://flh-extraction:8090`, from a one-off container on the same network.
4. The full FLH capture and review: `tools/extraction/scripts/app_workflow.py --service-url …`, through the SSM port forward.
5. Compare with the local baseline: the same `deployment_id`, and the same draft IDs and WER on
   the probe clips.
6. Record request time, memory (`docker stats --no-stream`) and failures (`/metrics`) per piece.

## 7. Rollback and teardown (R3-069, R3-080, R3-085)

**Model rollback.** Start the previous tag and weights, set `SPEAKING_TRANSCRIPTION_MODEL` back,
and restart FLH. FLH refuses answers from any other deployment, so a half-finished switch cannot
mislabel a transcript (`tools/speaking/RUNBOOK.md` §6–§7).

**Teardown (no idle compute):**

```sh
docker rm -f flh-speaking flh-extraction                              # on the host
aws s3 rm s3://$BUCKET/releases/model-runtime/20261120/ --recursive $P   # artifacts (keep only what the owner keeps)
# training artifacts, if a job ran:
aws s3 rm s3://$BUCKET/speaking/ --recursive $P; aws ecr delete-repository --repository-name flh-speaking --force $P
aws sagemaker list-endpoints $P; aws sagemaker list-training-jobs --status-equals InProgress $P   # both must be empty
```

The host itself follows the Release runbook: power-off after 4 h, then `terraform destroy`.
