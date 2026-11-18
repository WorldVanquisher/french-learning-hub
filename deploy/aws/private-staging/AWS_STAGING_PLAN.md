# NAS → AWS staging: migration plan with exact resource changes (batch 5, items 17–24)

Release lane, run 20261117T042813Z. **Nothing here was run against AWS.** The
repository forbids agents any AWS or Terraform command (AGENTS.md, FLH-084).
No staging budget, spend limit or runtime has been authorized (items 21, 25).
This is the reviewable plan: Terraform, IAM, a host bundle, the commands the
owner would run, and costs. The same procedure was rehearsed locally on a
stand-in target (`STANDIN-REHEARSAL.md`, items 26–31).

Builds on, and does not repeat, the demo-refresh lane's sealed pilot
(`lanes/demo-refresh/pilot5-final/pilot5/migration/`): `RUNTIME-INVENTORY.md`,
`MIGRATION-REHEARSAL.md` (29/0/3 on its worktree image) and
`CUTOVER-RUNBOOK.md`. Its decisions are kept:
- a separate host, never the public-demo instance;
- a durable data volume;
- private access only (the workbench has no authentication);
- SQLite stays;
- exactly one writable instance at any time.

## 17. Current AWS resources and Terraform state references

| Source | What it says |
| --- | --- |
| `docs/validation/FLH-087-aws-first-deployment.md` (operator-reported) | One stack in **us-east-1**: `terraform apply flh086r2.tfplan`, **19 added**; t4g.micro arm64, AMI `ami-04048e843b318bc37`; the public demo package under systemd; reached by SSM port forward |
| `deploy/aws/terraform/*.tf` | The 19 resources: VPC, internet gateway, subnet, route table + association, S3 gateway endpoint, security group + egress-443 rule, host IAM role + inline policy + instance profile, artifact bucket + public-access block, ownership, encryption, versioning, lifecycle and bucket policy, EC2 instance. `public_https.tf` adds an EIP and inbound 80/443 rules only when enabled (FLH-088, prepared, not applied) |
| Terraform state | **Local state on the operator's machine**: `versions.tf` declares no remote backend, and `.gitignore` keeps `*.tfstate` out of Git. No state file or plan is in the repository or the handoff areas. `flh086.tfplan` is obsolete (`deploy/aws/iam/README.md`) |
| IAM | Administrator-made managed policies `flh-demo-host-boundary`, `flh-demo-deploy`, `flh-demo-deploy-ec2`, `flh-demo-operate` attached to the user `flh-experiment` (detachment of the deploy policy after apply: still "PENDING CONFIRMATION" in FLH-087) |
| SageMaker (extraction lane) | `deploy/aws/sagemaker-extractor/`: prepared jobs, none authorized (paid runs NO-GO) |
| demo-refresh pilot | No resource created (its `START-HERE.md`); E5 pilot and training blocked by the same missing authorization |

Agents cannot list live resources. The owner can confirm the inventory with the
read-only commands in "Billable-resource check" below.

## 18. NAS runtime dependencies → isolated staging target

| Dependency (NAS today) | Staging target (this plan) | Notes |
| --- | --- | --- |
| One Docker image (Go server + workbench), Compose project `french-learning-hub`, `scripts/daily/flh-daily.sh` | **The same image, byte for byte** (`docker save` of the tested candidate, `image.tar` in the bundle), Docker + pinned Compose plugin on Amazon Linux 2023 x86_64, `flh-daily.sh` in isolated mode (`flh-staging` project, bundle override, no build on the host) | x86_64 (t3.small) because no arm64 image can be built here (no buildx/QEMU); t4g.small is ~20% cheaper once an arm64 image is built and tested |
| SQLite `app.db` + WAL in `FLH_DATA_DIR`, 21 migrations checked at start | Separate encrypted gp3 EBS volume mounted at `/srv/flh-staging/data` | Never the root volume (deleted on termination) |
| Backups: `flh-daily.sh backup` / `restore` | Same commands on the host; copies off-host to `s3://<bucket>/backups/` (SSE-S3, 14-day lifecycle for staging) | The restore runs `restore_write_check.py` (PR 5) and refuses a database the service cannot write |
| Settings `~/.config/flh/daily.env` (0600) with `OPENAI_API_KEY` etc. | SSM Parameter Store under `/flh/staging/` (String; SecureString for keys), rendered to `/etc/flh/staging.env` (0600, root) by `flh-staging-env` | Values never in user data, Terraform state, logs or the repository. **Staging keeps every provider disabled** |
| Providers (OpenAI analyzer/extractor, optional others) | Disabled | No paid call; matches the batch's rules |
| Optional Qdrant, E5 on the owner's laptop | Not deployed | Semantic search stays off; the index is rebuilt from SQLite, never copied |
| Daily Listening timer (optional) | Not installed | Only after a cutover, and never on two hosts |
| Health: Compose healthcheck `/readyz`, `/healthz` | Same; plus `flh-daily.sh status` over SSM | `/readyz` does not yet detect a read-only database (finding, items 41–44) |
| Access: loopback port over SSH tunnel | Loopback port over **SSM port forwarding**; no inbound rule, no EIP, no DNS name | Public DNS stays untouched |
| Logs: `flh-daily.sh logs`, journald | Same (Docker json-file, journald) | No CloudWatch Logs (cost) |

## 19. Storage requirements

| Item | Size now | Staging allocation |
| --- | --- | --- |
| Application image | 46.3 MB (`flh-staging:80e4e125b55b`, linux/amd64) | root volume 16 GiB gp3 (OS, Docker, image) |
| SQLite database | Synthetic fixtures: 0.65–0.67 MB (`app.db`); the real NAS size is **unknown** (the daily data is not read by agents) | data volume 8 GiB gp3: room for the database, 2 restore copies and ~10 backups at up to ~500 MB |
| Backups | one `app.db` copy + WAL/SHM + `SHA256SUMS` per backup | on the data volume, and in `s3://…/backups/` |
| Audio | **none**: Speaking stores metadata only (no column, file or log for audio, ARCHITECTURE §4.7) | none |
| Model artifacts | none on the host (embedding/E5 disabled) | none |
| Search index | Qdrant optional and rebuildable; off | none |

The owner sizes production from `du -sh` of the real data directory and backup.
Staging needs only the synthetic fixtures.

## 20. IAM actions from the concrete plan

`staging/iam/make_policies.py` derives four policies from the reviewed demo
policies (FLH-086/088): the same guards, names `flh-stg-*`, tag
`Component=workbench-staging`. Output is in `staging/iam/out/`. Every change is
listed in `CHANGES.txt`:

| Policy | Statements | Size (limit 6,144) | Change against the demo |
| --- | --- | --- | --- |
| `flh-stg-deploy-ec2` | 11 | 4,668 | EIP and inbound rules removed; `t3.small`, AMI `__STAGING_AMI_ID__`; RunInstances also requires `ExpiresAt` and `Run` tags; data volume create (encrypted gp3, tagged), attach/detach/delete (tagged) |
| `flh-stg-deploy` | 9 | 2,539 | renamed; bucket lifecycle, versioning, tagging puts; guards unchanged (boundary required, no boundary removal, no editing of the four policies) |
| `flh-stg-host-boundary` | 5 | 921 | + `backups/*` get/put, `/flh/staging` parameters, `kms:Decrypt` only via SSM |
| `flh-stg-operate` | 7 | 1,755 | + upload `backups/*`, read `backups/*`, manage `/flh/staging` parameters |

These are **untested until used against AWS**, as the demo policies were. An
`AccessDenied` names the missing action. Add only that action, and record it.

## 21. Region, budget, lifecycle

| Setting | Value | Status |
| --- | --- | --- |
| Region | us-east-1 (where the demo runs, FLH-087) | owner choice, documented |
| Monetary limit | **none established** for staging | **BLOCKS launch** (item 25). Proposed: a $5 cap for one staging pass, plus an AWS Budgets alert at $2 on `Component=workbench-staging` (an alert notifies; it does not stop spend) |
| Runtime bound | `max_runtime_hours` = 4: a systemd timer powers the host off, and `instance_initiated_shutdown_behavior = terminate` ends the instance | in the Terraform |
| Expiry tag | `ExpiresAt` (required by the deploy policy), `Run`, `Component`, `Project` on every resource (provider `default_tags`) | in the Terraform and IAM |
| Teardown | `terraform destroy` (the bucket has `force_destroy` because staging holds synthetic data only), then the billable check | owner command below |
| Object lifecycle | staging bucket: objects expire after 14 days, old versions after 1 day, incomplete uploads after 1 day | in the Terraform |

## 22. Reproducible build and artifact checksums

`staging/build_bundle.sh TREE OUT --repro` builds the deployable bundle from
the integration tree (never a worktree), then rebuilds without cache and
compares. Result for v6: `bundle-v6/VERSION.json` and `bundle-v6/SHA256SUMS`
(summarised in `STANDIN-REHEARSAL.md`).

## 23. Staging configuration with secret references

- **Parameters:** `/flh/staging/<NAME>` in SSM Parameter Store. They hold the
  wrapper's settings: `FLH_DATA_DIR`, `FLH_HOST_PORT`, `FLH_UID`, `FLH_GID`, every
  `*_PROVIDER=disabled`, and the `LISTENING_*` switches. A key, if ever needed,
  is a SecureString.
- **Renderer:** `staging/host/flh-staging-env REGION /flh/staging /etc/flh/staging.env`
  writes `NAME='value'` lines atomically with mode 0600.
  - It refuses unexpected names and quotes.
  - It prints names with set/empty only.
  - It requires the four `FLH_*` values.
- **Wrapper:** `flh-daily.sh` reads the rendered file as its settings file, the
  same path as on the NAS.
- **Where secrets never appear:** in user data (it carries only the region,
  bucket, parameter path and port), in Terraform state, in the bundle or in the
  repository.
- **Stand-in proof:** the rehearsal's renderer output and wrapper check show
  "set" for a placeholder secret, never its value (`STANDIN-REHEARSAL.md`, D4).

## 24. Exact resource changes (proposed `staging/terraform`, separate root and state)

`terraform plan` for a fresh staging root should show **21 to add, 0 to change,
0 to destroy**, and the demo stack's state is never read or changed:

| # | Resource | Key settings |
| --- | --- | --- |
| 1 | `aws_vpc.stg` | 10.85.0.0/24 (demo: 10.84.0.0/24), DNS on |
| 2 | `aws_internet_gateway.stg` | |
| 3 | `aws_subnet.public` | whole VPC range, no auto public IP |
| 4 | `aws_route_table.public` | 0.0.0.0/0 → IGW |
| 5 | `aws_route_table_association.public` | |
| 6 | `aws_vpc_endpoint.s3` | Gateway, free |
| 7 | `aws_security_group.host` | **no ingress** |
| 8 | `aws_vpc_security_group_egress_rule.https` | TCP 443 out only |
| 9 | `aws_s3_bucket.staging` | prefix `flh-stg-`, `force_destroy` |
| 10 | `aws_s3_bucket_public_access_block.staging` | all four blocks |
| 11 | `aws_s3_bucket_ownership_controls.staging` | BucketOwnerEnforced |
| 12 | `aws_s3_bucket_server_side_encryption_configuration.staging` | SSE-S3 |
| 13 | `aws_s3_bucket_versioning.staging` | Enabled |
| 14 | `aws_s3_bucket_lifecycle_configuration.staging` | 14 d / 1 d / 1 d |
| 15 | `aws_s3_bucket_policy.staging` | deny non-TLS |
| 16 | `aws_iam_role.host` | `flh-stg-host-*`, boundary `flh-stg-host-boundary` |
| 17 | `aws_iam_role_policy.host` | SSM minimum, `releases/*` get, `backups/*` get/put, `/flh/staging` read, decrypt via SSM |
| 18 | `aws_iam_instance_profile.host` | |
| 19 | `aws_instance.host` | t3.small, AL2023 x86_64 (pinned AMI), IMDSv2 (hop limit 2), 16 GiB encrypted root, standard credits, shutdown → terminate, gzipped cloud-config |
| 20 | `aws_ebs_volume.data` | 8 GiB gp3, encrypted |
| 21 | `aws_volume_attachment.data` | `/dev/sdf` |

Outside Terraform:
- **Administrator (IAM console):** four managed policies from `iam/out/`, with
  the account ID and AMI substituted locally.
- **Operator:** about 17 SSM parameters under `/flh/staging/`, and two objects
  under `releases/` (the bundle tar and its `.sha256`).

The Terraform is **unvalidated**: agents may not run `terraform fmt`, `init` or
`validate`. FLH-085's authorization was for that task only. The owner's first
step is `terraform fmt -check && terraform init -backend=false && terraform validate`.

## Cost estimate (us-east-1 list prices; verify in the calculator before approval)

| Item | Rate | One 4-hour staging pass | Left running 30 days |
| --- | --- | --- | --- |
| t3.small | $0.0208/h | $0.08 | $15.18 |
| Public IPv4 | $0.005/h | $0.02 | $3.65 |
| gp3 16 + 8 GiB | $0.08/GB-month | < $0.01 | $1.92 |
| S3 (bundle ~50 MB, backups ~1 MB), requests | | < $0.01 | < $0.05 |
| SSM Parameter Store standard, Session Manager | free | $0 | $0 |
| Data transfer | in: free; S3 via gateway endpoint: free | $0 | ~$0 |
| **Total** | | **≈ $0.11** | **≈ $21** |

The 4-hour power-off makes "forgotten for a month" impossible for compute. The
volume and bucket still cost cents until `terraform destroy`.

## Owner commands (in order; nothing here was run)

```bash
# 0. Decide: region (us-east-1), cap ($5), runtime (4 h), window. Then, read-only lookups:
aws ssm get-parameter --region us-east-1 --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 --query Parameter.Value --output text
curl -fsSL https://github.com/docker/compose/releases/download/v2.29.7/checksums.txt | grep ' \*\?docker-compose-linux-x86_64$'
# 1. Administrator: create flh-stg-host-boundary, flh-stg-deploy, flh-stg-deploy-ec2, flh-stg-operate from
#    staging/iam/out/ (substitute __AWS_ACCOUNT_ID__ and __STAGING_AMI_ID__ locally), attach the last three to flh-experiment.
# 2. Plan and apply (operator, separate directory and state):
cd staging/terraform && cp terraform.tfvars.example terraform.tfvars   # fill ami_id, compose_plugin_sha256, expires_at
terraform fmt -check && terraform init && terraform validate && terraform plan -out stg.tfplan   # expect 21 to add
terraform apply stg.tfplan
# 3. Parameters (no value is ever printed back):
for kv in FLH_DATA_DIR=/srv/flh-staging/data/app FLH_HOST_PORT=8080 FLH_UID=1000 FLH_GID=1000 AI_PROVIDER=rule-based \
  EXTRACTOR_PROVIDER=disabled SUGGESTION_PROVIDER=disabled LISTENING_PROVIDER=disabled READING_PROVIDER=disabled \
  WRITING_PROVIDER=disabled SPEAKING_TRANSCRIPTION_PROVIDER=disabled SPEAKING_PROVIDER=disabled HTTP_WRITE_TIMEOUT=75 \
  LISTENING_PLAYLIST_SOURCE=disabled LISTENING_AUTO_PREPARE=disabled LISTENING_NOTIFY=disabled; do
  aws ssm put-parameter --region us-east-1 --type String --overwrite --name "/flh/staging/${kv%%=*}" --value "${kv#*=}" > /dev/null; done
# 4. Upload the bundle (from the handoff area):
B=$(terraform output -raw bucket); cd ~/flh-handoff/release-20261117T042813Z/batch5/aws
tar -cf bundle-v6.tar bundle-v6 && sha256sum bundle-v6.tar > bundle-v6.tar.sha256
aws s3 cp bundle-v6.tar "s3://$B/releases/" && aws s3 cp bundle-v6.tar.sha256 "s3://$B/releases/"
# 5. On the host (aws ssm start-session --target <instance_id>), as root:
. /etc/flh/staging.conf; cd /srv/flh-staging/bundles
aws s3 cp "s3://$BUCKET/releases/bundle-v6.tar" . && aws s3 cp "s3://$BUCKET/releases/bundle-v6.tar.sha256" . && sha256sum -c bundle-v6.tar.sha256
tar -xf bundle-v6.tar && cd bundle-v6 && sha256sum -c --quiet SHA256SUMS && docker load -i image.tar
docker image inspect -f '{{.Id}}' "$(python3 -c 'import json;print(json.load(open("VERSION.json"))["image_tag"])')"   # == VERSION.json image_id
flh-staging-env "$REGION" "$PARAM_DIR" /etc/flh/staging.env
export FLH_DAILY_ENV=/etc/flh/staging.env FLH_COMPOSE_PROJECT=flh-staging FLH_COMPOSE_OVERRIDE=$PWD/staging.override.yaml
bash repo/scripts/daily/flh-daily.sh check && bash repo/scripts/daily/flh-daily.sh up
# 6. Restore a synthetic NAS-shaped backup (uploaded to backups/ the same way, checksum first):
bash repo/scripts/daily/flh-daily.sh restore /srv/flh-staging/transfer/<backup dir>
# 7. Checks: the stand-in rehearsal's steps 28-31 (STANDIN-REHEARSAL.md), via the port forward:
aws ssm start-session --region us-east-1 --target <instance_id> --document-name AWS-StartPortForwardingSession --parameters portNumber=8080,localPortNumber=18080
# 8. Teardown and billable check:
terraform destroy
aws ec2 describe-instances --region us-east-1 --filters Name=tag:Component,Values=workbench-staging Name=instance-state-name,Values=pending,running,stopping,stopped --query 'Reservations[].Instances[].InstanceId'
aws ec2 describe-volumes --region us-east-1 --filters Name=tag:Component,Values=workbench-staging --query 'Volumes[].VolumeId'
aws s3api list-buckets --query "Buckets[?starts_with(Name, 'flh-stg-')].Name"
aws ssm get-parameters-by-path --region us-east-1 --path /flh/staging --query 'Parameters[].Name'   # delete with aws ssm delete-parameters when done
```

All four listings must come back empty. The last one costs nothing, but it is
tidy.
