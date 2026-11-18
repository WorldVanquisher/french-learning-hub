# NAS → AWS staging: migration plan with exact resource changes (batch 5, items 17–24)

Release lane, run 20261117T042813Z; paths and commands updated for the first
owner run (release lane, 20261118). **Nothing here was run against AWS.** The
repository forbids agents any AWS or Terraform command (AGENTS.md, FLH-084).
No staging budget, spend limit or runtime has been authorized (items 21, 25).
This is the reviewable plan: Terraform, IAM, a host bundle and costs. **The
commands live in one place: [RUNBOOK.md](RUNBOOK.md)**. The resource list and
the stop rule are in [INVENTORY.md](INVENTORY.md). The same procedure was
rehearsed locally on a stand-in target ([STANDIN-REHEARSAL.md](STANDIN-REHEARSAL.md)).

Builds on, and does not repeat, the demo-refresh lane's sealed pilot records
`RUNTIME-INVENTORY.md`, `MIGRATION-REHEARSAL.md` (29/0/3 on its worktree image)
and `CUTOVER-RUNBOOK.md`. They are kept in that lane's handoff area, not in Git.
Its decisions are kept:
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
| One Docker image (Go server + workbench), Compose project `french-learning-hub`, `scripts/daily/flh-daily.sh` | **The same image, byte for byte** (`docker save` of the pinned revision, `image.tar` in the bundle), Docker + pinned Compose plugin + sqlite on Amazon Linux 2023 x86_64, `flh-daily.sh` in isolated mode (`flh-staging` project, bundle override, no build on the host), installed and identity-checked by `flh-staging-bundle` | x86_64 (t3.small) because no arm64 image can be built here (no buildx/QEMU); t4g.small is ~20% cheaper once an arm64 image is built and tested |
| SQLite `app.db` + WAL in `FLH_DATA_DIR`, 21 migrations checked at start | Separate encrypted gp3 EBS volume mounted at `/srv/flh-staging/data` | Never the root volume (deleted on termination) |
| Backups: `flh-daily.sh backup` / `restore` | Same commands on the host; copies off-host to `s3://<bucket>/backups/` (SSE-S3, 14-day lifecycle for staging) | The restore runs `restore_write_check.py` (PR 5) and refuses a database the service cannot write |
| Settings `~/.config/flh/daily.env` (0600) with `OPENAI_API_KEY` etc. | SSM Parameter Store under `/flh/staging/` (String; SecureString for keys), rendered to `/srv/flh-staging/staging.env` (0600, `ec2-user` = uid 1000, the container's `FLH_UID`) by `flh-staging-env` | Values never in user data, Terraform state, logs or the repository. **Staging keeps every provider disabled** |
| Providers (OpenAI analyzer/extractor, optional others) | Disabled | No paid call; matches the batch's rules |
| Optional Qdrant, E5 on the owner's laptop | Not deployed | Semantic search stays off; the index is rebuilt from SQLite, never copied |
| Daily Listening timer (optional) | Not installed | Only after a cutover, and never on two hosts |
| Health: Compose healthcheck `/readyz`, `/healthz` | Same; plus `flh-staging-bundle status` (identity) and `flh-daily.sh status` over SSM | `/readyz` includes a write probe: a read-only database answers 503 `storage_read_only` |
| Access: loopback port over SSH tunnel | Loopback port over **SSM port forwarding**; no inbound rule, no EIP, no DNS name | Public DNS stays untouched |
| Logs: `flh-daily.sh logs`, journald | Same (Docker json-file, journald) | No CloudWatch Logs (cost) |

## 19. Storage requirements

| Item | Size now | Staging allocation |
| --- | --- | --- |
| Application image | 46.4 MB (`flh-staging:<tree12>`, linux/amd64); a bundle with its image is ~47 MB | root volume 16 GiB gp3 (OS, Docker, two bundles for rollback) |
| SQLite database | Synthetic fixtures: 0.65–0.67 MB (`app.db`); the real NAS size is **unknown** (the daily data is not read by agents) | data volume 8 GiB gp3: room for the database, 2 restore copies and ~10 backups at up to ~500 MB |
| Backups | one `app.db` copy + WAL/SHM + `SHA256SUMS` per backup | on the data volume (`/srv/flh-staging/data/app.backups/`), and in `s3://…/backups/` |
| Audio | **none**: Speaking stores metadata only (no column, file or log for audio, ARCHITECTURE §4.7) | none |
| Model artifacts | none on the host (embedding/E5 disabled) | none |
| Search index | Qdrant optional and rebuildable; off | none |

The owner sizes production from `du -sh` of the real data directory and backup.
Staging needs only the synthetic fixtures.

## 20. IAM actions from the concrete plan

`staging/iam/make_policies.py` derives four policies from the reviewed demo
policies (FLH-086/088): the same guards, names `flh-stg-*`, tag
`Component=workbench-staging`. Output is in `staging/iam/out/`. Every change is
listed in `staging/iam/out/CHANGES.txt`. `staging/iam/render_policies.py` fills
the account ID and AMI into a directory outside the repository:

| Policy | Statements | Size (limit 6,144) | Change against the demo |
| --- | --- | --- | --- |
| `flh-stg-deploy-ec2` | 11 | 4,668 | EIP and inbound rules removed; `t3.small`, AMI `__STAGING_AMI_ID__`; RunInstances also requires `ExpiresAt` and `Run` tags; data volume create (encrypted gp3, tagged), attach/detach/delete (tagged) |
| `flh-stg-deploy` | 9 | 2,539 | renamed; bucket lifecycle, versioning, tagging puts; guards unchanged (boundary required, no boundary removal, no editing of the four policies) |
| `flh-stg-host-boundary` | 5 | 921 | + `backups/*` get/put, `/flh/staging` parameters, `kms:Decrypt` only via SSM |
| `flh-stg-operate` | 7 | 1,755 | + upload `backups/*`, read `backups/*`, manage `/flh/staging` parameters |

These are **untested until used against AWS**, as the demo policies were. An
`AccessDenied` names the missing action. Add only that action, and record it.
The offline review of these templates against the Terraform (missing and broad
permissions) is in RUNBOOK.md §2.1.

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

`staging/build_bundle.sh --git . <commit> OUT_PARENT --repro` exports one
pinned revision with `git archive`, checks its Git tree, builds the image
labelled with the commit and tree, and writes `flh-staging-<tree12>/`
(`MANIFEST.json` = the stable identity, `BUILD.json` = this build), the
transfer file `flh-staging-<tree12>.tar` and its `.sha256`. It then verifies
the result with the host tool. `--repro` rebuilds without cache and compares.
Which hashes are stable across builds: RUNBOOK.md §1.2.

## 23. Staging configuration with secret references

- **Parameters:** `/flh/staging/<NAME>` in SSM Parameter Store. They hold the
  wrapper's settings: `FLH_DATA_DIR`, `FLH_HOST_PORT`, `FLH_UID`, `FLH_GID`, every
  `*_PROVIDER=disabled`, and the `LISTENING_*` switches. A key, if ever needed,
  is a SecureString.
- **Renderer:** `flh-staging-env "$REGION" "$PARAM_DIR" /srv/flh-staging/staging.env`
  (installed from `staging/host/flh-staging-env`, run as `ec2-user`) writes
  `NAME='value'` lines atomically with mode 0600.
  - It refuses unexpected names and quotes.
  - It prints names with set/empty only.
  - It requires the four `FLH_*` values.
- **Wrapper:** `flh-daily.sh` reads the rendered file as its settings file, the
  same mechanism as on the NAS (`FLH_DAILY_ENV`).
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
steps are `staging/tools/preflight.py` (offline) and then
`terraform fmt -check && terraform init && terraform validate` (RUNBOOK.md §3).

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

## Owner commands

Moved to [RUNBOOK.md](RUNBOOK.md), the single copy-paste runbook. The earlier
block here named a v6 bundle, handoff-area paths and a root settings file that
the host no longer uses. Teardown and the billable-resource check are in
RUNBOOK.md §9.
