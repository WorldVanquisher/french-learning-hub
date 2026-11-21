# FLH AWS prep: daytime plan for private staging, model runtime and an invite-only pilot

Release lane, 2026-11-21. Worktree branch `worker/20261121-aws-prep` (owner-confirmed; the exact commit is
**unverified** because agents may not run Git here). Everything in this plan was produced offline with
synthetic data. No AWS call, paid job, DNS change, push or invitation was made; those steps are owner-only and
are marked **OWNER** below.

The ledger (REL-001 to REL-150, status and one evidence point each) and the replay commands are in the
on-disk handoff, not in this file.

## 1. Merged staging tool entry points (REL-001)

| Purpose | Entry point |
| --- | --- |
| Build and identify a candidate | `staging/build_bundle.sh`, `bundle_identity.py`, `bundle_compare.py`, `tools/candidate.py` (`identity`, `provenance`, `promote-check`, `gate`, `vars`, `authorize`) |
| Host-side install and verification | `staging/host/flh-staging-bundle` (`verify`, `install`, `rollback`, `identity`), `host/flh-staging-env` |
| IAM | `iam/render_policies.py`, `iam/make_policies.py`, `iam/review_permissions.py` (`--matrix`, `--simulate`) |
| Terraform gates | `tools/preflight.py`, `tools/plan_check.py` (`--mode create/update/destroy`, `--env`), `tools/plan_review.py` |
| Cost, lifecycle and teardown | `tools/lifecycle.py` (`cost`, `after-shutdown`, `teardown-rehearse`, `verify-commands`, `residual`) |
| Evidence | `tools/evidence_index.py` (`--approve RUN_ID`), `scripts/release/release_report.py`, `evidence_share.py`, `redact.py` |
| Local stand-in rehearsals | `rehearsal/r4_release_rehearsal.py` (first boot, failed boot, restore, rollback, crash restart, teardown), `r4_cutover_edges.py`, `first_run.py`, `recovery_rehearsal.py`, `bundle_rehearsal.py`, `e2e_rehearsal.py` |
| Extraction sidecar config | `tools/runtime_check.py`, `runtime/extraction.override.yaml` |
| Daily-use and release scripts | `scripts/daily/flh-daily.sh`, `scripts/release/backup_tool.py`, `cutover_check.py`, `restore_write_check.py`, `diagnose.py`, `smoke.sh`, `disk_preflight.sh`, `publish_metadata_check.py` |
| **New here** | `tools/daytime.py` (`template`, `check`, `roles`, `limits`, `page`) |

Paths are under `deploy/aws/private-staging/` unless they start with `scripts/`. The full list with usage
lines is in the handoff evidence (`rel001-entry-points.txt`).

## 2. What the latest AWS report says, and what the bill still does not (REL-002, REL-003)

The R5 report (`release-r5/FLH-AWS-bill-resources-staging.html`, seal `984aba19…`) uses the read-only snapshot of
**2026-11-20T21:09:14Z**, taken with `flh-staging-release` only. Its findings:
- **Running:** only the public demo: one `t4g.micro`, running since 2026-10-20, one public IPv4, ports 80/443 open.
- **Estimate:** about $10.30 for November before credits; no staging stack exists.
- **Read access:** 30 of 35 reads were refused, including every billing read.

**Still unknown in the bill:**

| Unknown | Why | Who can supply it |
| --- | --- | --- |
| Amount due after credits | billing reads refused; Cost Explorer not approved | owner (Bills page) |
| Credits: remaining, expiry, applicable products | same | owner (Credits page) |
| Tax | not estimated | owner (Bills page) |
| Data transfer out | no approved rate in the cost sheet; assumed inside the 100 GB/month free allowance | owner (Bills, by service) |
| Whether the demo's public IPv4 is an Elastic IP | `describe-addresses` refused | owner (EC2 → Elastic IPs) or the A1 verify policy |
| Demo root volume size and artifact bucket size | `describe-volumes`, `list-buckets` refused | owner console or A1 |
| Leftovers of the FLH-064 CloudFormation smoke stack | `list-stacks` refused | owner (CloudFormation → Deleted stacks) |
| SageMaker endpoints or jobs | refused to the release profile | owner, or the Extraction profile in its own lane |
| Account plan (Free or Paid) and its end date | Free Tier reads refused | owner (Billing home) |

## 3. Owner inputs for one synthetic staging run (REL-004)

`daytime.py template --out ~/flh-daytime/inputs.json` writes the exact inputs as placeholders. Keep the file
outside the repository; it holds no credential:
- **Profiles:** names only.
- **Account:** its SHA-256, which `candidate.py gate` compares.

| Group | Field | Value or source |
| --- | --- | --- |
| run | `run_id` | `YYYYMMDDTHHMMSSZ`, the same as `terraform.tfvars` |
| run | `region`, `environment` | `us-east-1`, `staging` (fixed) |
| run | `window_start_utc`, `window_end_utc` | the daytime slot, at most 6 h |
| run | `expires_at` | after the window end, at most 24 h after its start |
| run | `max_runtime_hours` | 4 (1–4 accepted for a first pass) |
| account | `allowed_account_sha256` | `printf %s <account-id> \| sha256sum` on the owner's machine |
| account | `readonly_profile`, `operator_profile` | `flh-staging-release`; the operator profile's **name** |
| approvals | `A1_teardown_verification` | `granted` (verify-readonly policy attached) or `use-operator-profile` |
| approvals | `A2_staging_pass`, `A3_iam_policies_created`, `synthetic_data_only` | `true` once decided and done |
| limits | `budget_cap_usd`, `budget_alert_usd`, `max_compute_hours` | proposed 5, 2, 4 (§4) |
| host | `ami_id`, `ami_architecture`, `instance_type` | AL2023 x86_64 from the public SSM parameter; `x86_64`; `t3.small` |
| host | `compose_plugin_version`, `compose_plugin_sha256` | from the Compose release's checksum file |
| candidate | bundle and rollback, with SHA-256 | `flh-staging-35da542d0dd4.tar` (`d9db57a6…`), `flh-staging-57ec7085dc61.tar` (`d53d71b7…`) |
| capacity | `running_standard_vcpu_quota` | Service Quotas; must be ≥ 4 (demo 2 + staging 2) |
| billing | `baseline_recorded` | `true` after noting today's month-to-date charges |

## 4. Roles, limits and what is actually enforced (REL-005 to REL-007)

`daytime.py roles` and `daytime.py limits` print these tables from one source:
- **Roles:** the read-only profile never writes. Terraform, SSM parameters, uploads and sessions use the operator
  profile with the staging policies. The policies are created by an IAM administrator; the budget, quota and
  bills belong to the account owner.
- **Proposed limits:** 4 h of compute, a $5 cap with a $2 alert, a window of at most 6 h, teardown the same day.

**Enforced versus alert-only:**

| Kind | Limits |
| --- | --- |
| ENFORCED | runtime (power-off timer + terminate behaviour); instance type `t3.small` and volume type gp3 (IAM conditions) |
| ENFORCED before apply | expiry tag ≤ 24 h (preflight); volume sizes and the 21-address resource set (plan_check) |
| ALERT-ONLY | the $5 cap and $2 alert (AWS Budgets notifies hours later and stops nothing) |
| PROCEDURAL | synthetic-only data and same-day teardown (the owner) |

## 5. Daytime go-or-hold (REL-008, REL-009)

```sh
S=deploy/aws/private-staging/staging
python3 -I $S/tools/daytime.py check ~/flh-daytime/inputs.json          # GO (exit 0) or HOLD with every reason (exit 1)
python3 -I $S/tools/daytime.py page  ~/flh-daytime/inputs.json --out ~/flh-daytime/go-or-hold.md
```

The page lists the hold reasons, the limits, the roles and the offline gates. A synthetic example of each
verdict is in the handoff evidence (`first-slice/page-hold.md`, `page-go.md`).

The offline rehearsal behind the slot is unchanged from R4:
- **Rehearsal:** `rehearsal/r4_release_rehearsal.py`. The final run `R4-20261120T181639Z-62aa5a` passed 24/24 and is
  APPROVABLE in `evidence_index.py`.
- **Cutover edges:** `r4_cutover_edges.py`, 4/0.
- **Plan:** `docs/plans/FLH-R4-release-candidate.md` §7 and §11.2 (the owner's command sequence).

## 6. Cost and capacity (REL-011 to REL-020)

**Rates:** only dated rates already in the repository; none was fetched or invented.
- **Cost sheet:** `staging/cost_sheet.json`, list prices as of **2026-11-20**.
- **Training:** `ml.g5.xlarge` $1.408/h, `tools/extraction/TRAINING_RUNBOOK.md` §10, as of **2026-11-07**.
- **Transfer:** has no approved rate. It is assumed inside the 100 GB/month free allowance and shown as n/a.

`daytime.py cost` uses `lifecycle.py`'s own cost function:

| Group | Scenario | Compute | Disks | Storage | Public IPv4 | Total |
| --- | --- | --- | --- | --- | --- | --- |
| One run, private staging | staging pass (4 h, destroyed the same day) | $0.08 | $0.01 | <$0.01 | $0.02 | **$0.12** |
| One run, private staging | not destroyed for 7 days (residual) | $0.08 | $0.15 | <$0.01 | $0.02 | $0.25 |
| Steady state, private production (not approved) | always on | $15.18 | $2.88 | $0.29 | $3.65 | $22.00 / month |
| Steady state, private production (not approved) | peak (t3.medium, more backups and logs) | $30.37 | $6.28 | $1.15 | $3.65 | $41.45 / month |
| Steady state, **public demo** (existing, Demo lane) | always on, bucket 0.05–1 GiB | $6.13 | $0.64 | $0.00–0.02 | $3.65 | $10.42–10.45 / month |

The demo rows are the existing public service, listed for the bill only. A staging pass adds only its own row.

### Residual charges after teardown (REL-014)

`daytime.py residual` lists what can still bill, and the listing that shows each item:
- **If destroy is not run:** the data volume and bucket.
- **If destroy fails:** old object versions in the bucket, or an unattached volume.
- **Only if made by hand:** a snapshot, an Elastic IP or a CloudWatch Logs group.
- **Free:** the alert budget (first budgets; confirm), SSM parameters, IAM policies and default KMS keys.
- **Unchanged:** the demo.

### Model costs (REL-017, REL-018)

**Unknown and not measured:**
- model inference on the staging host (the extraction sidecar is rule-based, so no model runs there);
- GPU inference outside SageMaker (no approved instance);
- SageMaker predict and experiment steps 6–8 (bounded, not run);
- ECR and S3 request costs during training.

**Illustrative bounded smoke (OWNER, paid, not approved):** readiness step 5, `rendered/sft-smoke.json`, 12
steps, `MaxRuntimeInSeconds` 1800.
- **Compute:** 0.5 h × $1.408 = **$0.70**.
- **Storage:** 9.32 GB of base weights in S3 for a day, about $0.01.
- **Bound:** at most **$0.71**.

### Billing inputs (REL-016)

`daytime.py bill-template --out ~/flh-daytime/bill.json` writes the redacted fields:
- **Bills:** charges, credits applied, tax, total due, charges by service.
- **Credits:** amount remaining, expiration, applicable products.
- **Account plan.**

`daytime.py bill ~/flh-daytime/bill.json` computes the amount due as max(0, charges − credits) + tax, checks it
against the stated total, and gives the months of demo the remaining credits cover. It refuses a file containing a
12-digit number, an e-mail or a card-like number. The R5 HTML page has the same calculator.

### Quotas (REL-019)

`daytime.py quotas [--running-vcpu N]` prints each check with its formula:

| Quota | Formula | Needed |
| --- | --- | --- |
| EC2 running on-demand standard vCPU (L-1216C47A) | quota − running vCPU ≥ 2 | ≥ 4 with the demo running |
| VPCs per Region | existing (2) + 1 | ≤ quota (default 5) |
| Internet gateways per Region | existing (2) + 1 | ≤ quota (default 5) |
| Elastic IPs | — | 0 for staging |
| gp3 storage | used + 0.024 TiB | ≤ quota |
| S3 buckets | existing + 1 | ≤ quota |
| SageMaker ml.g5.xlarge for training job usage | ≥ 1 | model smoke only; new accounts often start at 0 |

### Reproducing the estimate (REL-020)

```sh
python3 -I deploy/aws/private-staging/staging/tools/daytime.py cost --json   # every row, rate date and assumption
python3 -I deploy/aws/private-staging/staging/tools/lifecycle.py cost --scenario staging-pass --json
```

The inputs are `cost_sheet.json` (its `assumptions` list), the `demo_scenario` in `daytime.py` (t4g.micro,
730 h, an 8 GiB root as the Terraform default, one IPv4, bucket 0.05–1 GiB) and `TRAINING_RATE`. Changing a rate
means editing the sheet and its `as_of` date; nothing else holds prices.

## 7. Private deployment (REL-021 to REL-030)

### Staging and production stay apart (REL-021, offline)

| Setting | Staging | Production |
| --- | --- | --- |
| Component tag / name prefix | `workbench-staging` / `flh-stg-` | `workbench-production` / `flh-prd-` |
| Shutdown behaviour / termination protection | terminate / off | stop / on |
| Bucket `force_destroy` / `ExpiresAt = never` / destroy allowed | yes / no / yes | no / yes / no |

**Checks:**
- No staging policy names a production resource, and none of the five production policies names a staging one.
- `review_permissions.py --env staging|production` both report every required action allowed.
- `plan_check.py --env staging` STOPs on a production address (fixture `plan-staging-unsafe-production-resource.json`).

Evidence: `evidence/deploy/env-separation.txt`.

### The candidate (REL-022 to REL-024)

A fresh candidate must carry the **approved main commit** the owner records (`git rev-parse HEAD` at build time).
- **Identity:** `build_bundle.sh --git` pins that commit and checks that the exported tree hashes to its Git
  tree; `MANIFEST.json` records commit, tree, content digest, image labels, server and web digests and the
  migration ledger.
- **This worktree:** its content is newer than the R4 candidate's commit `58c0ba8b`, in the public demo's
  `web/src` and docs only. Migrations (21), Dockerfile, dependencies and the host tool are unchanged. So the R4
  candidate stays valid for the host test, and a production candidate needs a fresh build.

**Owner build and verification (OWNER: needs Git):**

```sh
OUT=~/flh-build; mkdir -p "$OUT"; REV=<approved-main-commit>
bash deploy/aws/private-staging/staging/build_bundle.sh --git . "$REV" "$OUT" --repro
T=$(ls "$OUT"/flh-staging-*.tar | head -1)
deploy/aws/private-staging/staging/host/flh-staging-bundle verify "$T" --sha256 "$(cut -d' ' -f1 "$T.sha256")"
python3 -I deploy/aws/private-staging/staging/tools/candidate.py identity "$T" --json
python3 -I deploy/aws/private-staging/staging/tools/candidate.py provenance "$T" --commit "$REV" --out "$OUT/provenance.json"
python3 -I deploy/aws/private-staging/staging/tools/candidate.py promote-check "$T" --provenance "$OUT/provenance.json" --sha256 "$(cut -d' ' -f1 "$T.sha256")"
```

Then run the stand-in rehearsal (§9) with the new candidate before the slot.

**Architecture (REL-024):**
- **App image:** `linux/amd64`. `candidate.py identity` on the R4 candidate reports `image_platform linux/amd64`.
- **Host:** AL2023 **x86_64** AMI on `t3.small`, which the deploy-ec2 policy enforces.
- **Refusal:** `flh-staging-bundle` refuses an image whose platform differs from the host's (`linux/amd64` or
  `linux/arm64`).
- **Demo:** the public demo is a separate arm64 `t4g.micro` and is not a target.

### Restore, readiness and rollback (REL-025 to REL-028)

**Backup and restore, rehearsed on the synthetic NAS-shaped fixture:**
1. `backup_tool.py pack` and the transfer check.
2. `unpack`, then the restore into the data directory.
3. `chmod 600 app.db*`.
4. `restore_write_check.py` and Workbooks' `inventory.py --expect BASELINE` (READY, equal row counts).

**Readiness after a restore (REL-026)** needs all of these:
- `/healthz` 200 and `/readyz` 200;
- `flh-staging-bundle identity` IDENTITY OK (image, labels, `/app/server` SHA-256, and the served page equal to the
  bundle's);
- `restore_write_check.py` passes;
- inventory READY against the backup's baseline.

A read-only database gives `/readyz` 503 `storage_read_only`.

**What the rollback target reads (REL-027):**
- **Its own files:** `ROOT/previous` is verified again from its files (MANIFEST, SHA256SUMS, image ID).
- **The settings file:** `staging.env`.
- **The data directory:** the database's `schema_migrations` count, which must be ≤ the target's ledger. Otherwise
  it refuses and names the pre-install backup in `deploy.log`.
- **Permissions:** the data files must be readable and writable by the container user (`chmod 600 app.db*` after a
  restore).

### What the stand-in cannot prove (REL-029)

These need a real host (R4 plan §7.2):
- AL2023 cloud-init: Docker, the pinned Compose plugin, the data volume mount;
- IMDSv2, the SSM session and port forward;
- S3 transfer and EBS timings, S3 TLS-only, IAM AccessDenied on an out-of-scope call;
- a real instance reboot;
- the power-off timer and terminate;
- the residual listing after destroy.

### Owner sequence from preflight to first smoke (REL-030)

Stop at the first refusal.

1. `daytime.py check ~/flh-daytime/inputs.json`: **GO**.
2. Sign in: `aws sso login --profile <operator-profile>`, then
   `aws sts get-caller-identity --profile <operator-profile> --output json > ~/flh-daytime/caller.json`.
3. `candidate.py gate --caller-identity ~/flh-daytime/caller.json --allowed-account-sha256 <sha256> --region us-east-1 --env staging --workspace default`: **GATE PASSED**.
4. `candidate.py promote-check <bundle.tar> --provenance <provenance.json> --sha256 <sha256>`: **PROMOTE**.
5. Policies (administrator, A3):
   `render_policies.py --account <account-id> --ami <ami-id> --out ~/flh-stg-iam`, then create them, then
   `review_permissions.py --simulate …`.
6. RUNBOOK §3: `preflight.py --tfvars terraform.tfvars`, `terraform plan -out stg.tfplan`,
   `plan_check.py --env staging --mode create`: **SAFE, 21 to add**. Then apply.
7. RUNBOOK §4 (16 parameters), §5 (upload, `flh-staging-bundle install`: **IDENTITY OK**) and §6 (synthetic restore:
   inventory **READY**).
8. **First smoke:** RUNBOOK §7, E1 onwards, through the SSM port forward. `curl -fsS http://127.0.0.1:<local-port>/readyz`
   must return 200.

## 8. Model runtime (REL-031 to REL-040)

**Coordination (REL-031):** Extraction confirmed every runtime assumption on 2026-11-21, checked on its own branch,
with one rounding note (interface note §1):
- staging runs only the rule-based extraction service, with no model on the host;
- the limits (256m memory and memory-swap, 1 CPU, 64 pids, read-only, user 10002, no port, 5 s deadline);
- pinning the `deployment_id`, not the image ID;
- the fallback (`unavailable` once, no retry, no fallback);
- Qwen stays SageMaker-only, and E5 is outside the staging pass.

### Proposed artifacts (REL-032)

| Artifact | Coordinate | Digest / identity | License | Where it runs |
| --- | --- | --- | --- | --- |
| App candidate | `flh-staging-35da542d0dd4.tar` (commit `58c0ba8b`) | tar SHA-256 `d9db57a6…8f70`; server `1394cf17…` | MIT (repository `LICENSE`) | staging host |
| Extraction service | built by the owner from `tools/extraction/Dockerfile.service` | base `python:3.12-slim@sha256:6c4dd321…fa8e`; `deployment_id flh-extraction-rules@e978b6c2bdb6/…` | MIT (repository); base image Python/Debian licenses | staging host, optional sidecar |
| Base model | `Qwen/Qwen3.5-4B` | revision `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`, 9,319,737,856 bytes, small files in `configs/qwen3.5-4b-851bf6e8.sha256` | Apache-2.0 (`models.py` `"license": "apache-2.0"`; `TRAINING_RUNBOOK.md` §1, Hugging Face API 2026-11-11) | SageMaker only (OWNER) |
| Training image | `tools/extraction/Dockerfile` | same pinned base; the registry digest is recorded by the owner at push (readiness step 3) | MIT + pinned requirements | SageMaker only (OWNER) |
| Embedding model | `intfloat/multilingual-e5-base` | revision `d128750597153bb5987e10b1c3493a34e5a4502a`; `model.safetensors` `a18a44fa…` | MIT | local CUDA service; **not** in the staging pass |

### Smoke input, provenance and the local interface (REL-033 to REL-035)

**Smoke with a known output:** `POST /v1/review` with `tools/extraction/fixtures/service_v1/01-review-first-revision.request.json`
must return exactly `01-review-first-revision.response.json`; `GET /manifest` must return the pinned `deployment_id`.

**Owner provenance checks (REL-034):**
- **Service:** build from `Dockerfile.service` (base pinned by digest), then compare `/manifest`'s `deployment_id` and
  the per-file `code_sha256` with the release record.
- **Base model:** `scripts/check_model_assets.py` must report PRESENT_OK against `configs/qwen3.5-4b-851bf6e8.sha256`.
- **Training image:** record its registry digest; `flh_extraction.packaging` must pass.
- **E5:** the manifest-derived `deployment_id` (FLH-054).

**Local interface (REL-035):** `python3 -I -B scripts/service_examples.py --check` (in `tools/extraction`) regenerates
every example through the in-process loopback service. Result: "the examples equal fixtures/service_v1/"
(handoff `evidence/model/service-examples-check.txt`).

### Size, time, cleanup and fallback (REL-036 to REL-038)

| Item | Evidence | Value |
| --- | --- | --- |
| Extraction service memory | R4 measurement (SERVICE.md §7) | ready 14.9 MiB, peak 22.2 MiB, limit 256 MiB |
| App memory | R4 measurement | peak 16.5 MiB; the t3.small host has 2 GiB |
| Images on disk | local `docker image ls` | app 47.1 MB, extraction service 119 MB; the 16 GiB root fits both |
| Qwen weights | input manifest | 9.32 GB in S3; SageMaker volume 50 GB per job; the A10G GPU's memory fits a 4B model in bf16 (estimate, not measured) |
| E5 weights | e5 README | 1.11 GB safetensors; CUDA only |

**Timeouts and cleanup:**
- **Service:** 5 s per request (504 `timeout`, the result discarded); at most 4 in flight (503 `busy`).
- **SageMaker:** `MaxRuntimeInSeconds` is 1800 for the smoke, 3600 per predict job and 10800 for the experiment.
- **After a daytime test:**
  - stop the sidecar with the stack;
  - delete the job's S3 output prefix once its manifest checks are recorded;
  - keep the base weights only while a next step is scheduled;
  - the ECR image stays until the owner deletes it.

**Fallback (REL-038):**
- The app works without the service. The client reports `unavailable` once, never retries and has no silent
  fallback.
- The product extractor stays `EXTRACTOR_PROVIDER=disabled` by default (503).
- Semantic search has no keyword fallback.

### Evidence fields and the owner checklist (REL-039, REL-040)

`daytime.py model-record` writes `flh-model-evidence/v1` with two independent sections:
- **`render`:** the job file's SHA-256, instance, count, volume, runtime cap and isolation, and whether placeholders
  remain.
- **`readiness`:** the `/readyz` status, and the observed against the expected `deployment_id`.

A dry render is `not_submittable`, and a ready service says nothing about a job. Neither stores the account, role,
bucket or registry.

**Owner checklist (fill the `<…>`; OWNER, daytime):**

```sh
X=tools/extraction; S=deploy/aws/private-staging/staging
python3 -I -B $X/scripts/service_examples.py --check                                   # equal fixtures
docker build -f $X/Dockerfile.service -t flh-extraction-service:<tag> $X                # base pinned by digest
python3 -I -B $S/tools/runtime_check.py --image flh-extraction-service:<tag> --deployment-id <deployment_id>
# on the staging host, after the sidecar starts (through the SSM port forward):
curl -fsS http://127.0.0.1:<port>/manifest > manifest.json; code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:<port>/readyz)
python3 -I -B $S/tools/daytime.py model-record --manifest manifest.json --readyz-status "$code" --expect-deployment <deployment_id>
# SageMaker (paid, OWNER, only after the readiness/README.md gates): render with real values, then
python3 -I -B $S/tools/daytime.py model-record --rendered <rendered/sft-smoke.json with real values>   # must be "ok"
```

## 9. Portal and HTTPS (REL-041 to REL-050)

**Purpose of `flh.vanquisher.world` (REL-041):**
- **Before:** FLH-081 proposed it as the public demo's name, pending owner confirmation; that plan recorded no
  DNS record.
- **Now proposed:** make it the **portal**, the static front door that names FLH and links to the demo. It has no
  application, form, sign-in or invitation.
- **Your decision (OWNER):** keep the FLH-081 meaning or take this split. Both are reversible (change C4).

The proposal is `deploy/aws/private-staging/staging/portal/routing_plan.json`; `tools/portal_check.py validate|simulate`
checks it offline.

| Host | Role | Target | DNS (proposed, OWNER) | TLS |
| --- | --- | --- | --- | --- |
| `flh.vanquisher.world` | portal | static hosting (proposal: GitHub Pages, like the apex) | CNAME → `<pages host>`, TTL 300 | the static host's certificate |
| `demo.flh.vanquisher.world` | public demo (existing, Demo lane) | demo Elastic IP → nginx (`flh-public-https`) → loopback demo | A → `<demo Elastic IP>`, TTL 300 | Let's Encrypt (certbot webroot on the demo host) |
| `app.flh.vanquisher.world` | private pilot | **none while pre-launch** | **no record** | only with the pilot |
| staging | — | SSM port forward to 127.0.0.1 | none | — |

**Separation (REL-042):** the demo keeps its own name and target, and the portal never proxies to an FLH server.

**Responsibilities (REL-043):**

| Area | Owner | Tool or check |
| --- | --- | --- |
| DNS | domain owner (Namecheap) | console |
| Demo certificate and host-name drop-in | operator over SSM | the Demo lane's `flh-public-https` |
| Host check | app | `HTTP_ALLOWED_HOSTS` (browser protection, **not authentication**) |
| Demo allowlist | app | `NewPublicDemoBoundary`, GET/HEAD only |
| Portal page | static host | — |

### Proposed DNS changes and their rollback (REL-044, REL-049)

| ID | Change | Verify | Rollback |
| --- | --- | --- | --- |
| C1 | CNAME `flh` → static host; publish the pre-launch page | V-portal | delete the CNAME (TTL 300, wait 5 min); unpublish |
| C2 | A `demo.flh` → demo Elastic IP | V-dns | delete the A record; the demo keeps its previous name |
| C3 | `flh-public-https` for `demo.flh.vanquisher.world` | V-tls | re-run with the previous host name; the old certificate stays valid until expiry |
| C4 | move `flh` away from the demo, if it ever pointed there | V-portal | restore the record value written down before C4 |

### Certificate and host identity (REL-045), OWNER after each change

- **V-dns:** `dig +short demo.flh.vanquisher.world` equals the demo Elastic IP (EC2 console).
- **V-tls:**
  - `openssl s_client -connect demo.flh.vanquisher.world:443 -servername demo.flh.vanquisher.world </dev/null | openssl x509 -noout -subject -ext subjectAltName -enddate`
    must show the SAN `demo.flh.vanquisher.world`, issuer Let's Encrypt and more than 30 days left;
  - `curl -fsS https://demo.flh.vanquisher.world/readyz` must return 200;
  - `curl -fsS https://demo.flh.vanquisher.world/knowledge-library/demo` must report the installed release's demo
    identity (as `flh-release` checks).
- **V-portal:**
  - `curl -sI https://flh.vanquisher.world/` returns 200 with the static host's certificate;
  - `curl -s -o /dev/null -w '%{http_code}' -X POST https://flh.vanquisher.world/captures` does not return 2xx.

### Private routes before a pilot (REL-046, REL-047)

**Today:**
- **No protection:** the private workbench has no authentication or accounts; the browser boundary is
  explicitly not authentication.
- **Only path in:** private routes are reachable only on the staging host through the owner's SSM port forward.
  `plan_check.py` STOPs on ingress, Elastic IP, load balancer or DNS for the staging root, and `preflight.py`
  refuses `LISTEN_HOST`/`HTTP_ALLOWED_HOSTS` in its user data.
- **So:** pilot access stays **blocked until authentication exists**, and the pilot host gets no DNS record (§10).

**Safe pre-launch portal:**
- one static page: the FLH name, a sentence on what it is, and a link to the demo;
- "the private pilot is not open";
- no form, sign-in, invitation link, analytics or third-party script.

### Mock routing test (REL-048) and the live steps left (REL-050)

`portal_check.py simulate` runs 22 synthetic requests: portal pages, demo allowlist routes, demo writes
(405), private workbench routes on every host (404), path traversal, the pilot (no record) and unknown hosts
(refused). Result: 22 of 22 as expected. `test_portal_plan.py` also checks that its demo rules equal the Go
allowlist.

**Owner-run live steps:**
1. Decide the portal split.
2. C1–C4 at Namecheap and on the static host.
3. `flh-public-https` over SSM for the new demo name.
4. V-dns, V-tls and V-portal.
5. Record the previous DNS values before every change.

## 10. Invite-only pilot (REL-051 to REL-060)

### What exists today (REL-051)

The server is a **single-learner** service with no authentication:
- **No credentials read:** no account, session, cookie or invitation. `Authorization` appears only on outbound
  provider calls (OpenAI, embedding) and in test fakes.
- **Browser boundary only:** `NewBrowserBoundary` and `HTTP_ALLOWED_HOSTS` check Host and Origin and say so
  explicitly: "browser-request protection, not authentication".
- **No identity anywhere else:**
  - `Idempotency-Key` is a write receipt, not an identity;
  - browser storage holds UI preferences only;
  - all 53 tables in one SQLite database belong to the one learner;
  - the public demo is a separate read-only allowlist with no learner data.

### Missing for a pilot (REL-052): implementation, not in this task's scope

| Piece | Why |
| --- | --- |
| Accounts and an owner role | every record needs an owner |
| Sessions: HTTPS-only, `Secure`/`HttpOnly`/`SameSite=Strict` cookies, idle and absolute expiry, CSRF protection on every write | the browser is the client |
| Invitations | single use, expiring, revocable, stored hashed |
| Per-account scoping of all 53 tables and 126 routes | reads, writes, idempotency receipts, capture IDs and exports |
| Scoping in derived reads | inventory, Knowledge Library search, the annotation dataset, retrieval and evaluation reports |
| Per-account backup selection or an explicit all-accounts backup policy | restores |
| Rate limits and an audit log of sign-ins, invitations and revocations | accountability |
| Privacy notice, retention and deletion | real people's data |

This is a cross-layer feature. It needs an owner decision and its own milestone; AGENTS.md lists authentication
and multi-user features as excluded unless explicitly requested.

### Enrollment, expiry, revocation and the owner bootstrap (REL-053, REL-054)

**Invitations and sessions:**
- **Issuing:** an invitation is issued by the owner only, for one named synthetic or real person. It is a random
  token shown once and stored as a hash. It expires after 72 h and is used at most once.
- **Refusals:** a second use is refused (409 or 410) and changes nothing; an expired one is 410.
- **Revocation:** ends every session of that account at once (the next request is 401) and keeps the data for the
  retention decision.
- **Restores:** a restore never revives a revoked account or session.

**Bootstrap:**
- The owner account is created by a command run on the host over the SSM session, never through the web.
- It prints a one-time sign-in token to that terminal only.
- There is no default password and no sign-up route.
- The pilot host stays without a DNS record until bootstrap and §11 pass.

### Two-account isolation case (REL-055 to REL-057)

`deploy/aws/private-staging/staging/pilot/isolation_case_v1.json` has 20 steps for accounts A and B:
- **Enrollment:** invitation reuse and expiry.
- **Writes:** `POST /captures`, including the same `capture_id` used by both accounts.
- **Reads:** own reads; cross-account reads and writes that must answer 404, identical to a missing ID.
- **Exports:** all four exports (`/learning-history/export`, `/learning-records/export`, `/speaking/export`,
  `/annotation-dataset/v1/export`).
- **Anonymous requests:** 401 on every private GET.
- **Revocation.**
- **Backup and restore:** isolation and revocation both hold after a restore.

`pilot_check.py validate` checks the case (VALID). `pilot_check.py run` is **BLOCKED**: there is no pilot API.

### Data handling and preview versus production (REL-058, REL-059)

**Pilot data:**
- learning captures and practice records only;
- no audio is stored, as today;
- feedback is limited to the fields in §18;
- retention and deletion are decided before the first invitation;
- backups contain every account and are encrypted at rest (SSE-S3) with owner-only access.

**Preview versus production access:**
- **Preview-only:** the public demo, the static portal and anything behind the SSM port forward. None of these is
  pilot access.
- **Production-ready access** exists only when `pilot_check.py probe` is READY against the candidate and the
  isolation case passes on a stand-in, then on staging.

### Conditions before any invitation (REL-060)

1. Authentication, sessions and invitations are implemented and reviewed.
2. `pilot_check.py probe http://127.0.0.1:<port>` is **READY** on the candidate.
3. The isolation case passes on the stand-in, then on staging.
4. HTTPS with HSTS is live on the pilot host, and V-tls passes.
5. Retention, deletion and the incident template (§18) are approved.
6. The owner approves each invitation by name.

Today condition 1 fails, so **invitations stay on hold**.

## 11. Synthetic rehearsal (REL-061 to REL-070)

**Inputs (REL-061):** every input is synthetic and pinned in the handoff's `evidence/fixtures/PINNED.txt`
(27 entries), each checked before and after every run:
- the four bundles (candidate, rollback, broken migration, newer ledger), with their SHA-256;
- the NAS-shaped fixture's `SHA256SUMS`;
- the 15 Extraction service fixtures;
- the routing plan and the isolation case;
- the synthetic daytime inputs.

| Item | Command | Result |
| --- | --- | --- |
| Preflight on a synthetic environment (REL-062) | `preflight.py --tfvars <synthetic terraform.tfvars>` (kept outside the repository) | READY: 45 passed, 0 failed |
| First start (REL-063) | `r4_release_rehearsal.py …` run `R4-20261121T055720Z-1dff76` | B1 install identity OK; B2 image, process and ready timed apart; F1 failed first boot keeps diagnostics |
| Restore from a disposable backup (REL-064) | same run | S1–S7: checksums, corrupted copy refused, restore, inventory READY with equal digests |
| Restart and readiness (REL-065) | same run | R1 crash restart (SIGKILL of the server) and R2 wrapper restart: identity OK, data kept |
| Failed rollout and recovery (REL-066) | `bundle_rehearsal.py OLD NEW BROKEN FIXTURE WORK` run `bundles-run2` | F2a broken migration: switched back automatically; F2b ledger and data unchanged |
| Teardown (REL-067) | both runs | T1 and C1/C2: no stand-in object left; daily container and image unchanged |

All rows PASS: 24 of 24 and 27 of 27. The first `bundle_rehearsal.py` attempt failed at setup: it needs the OLD
bundle's unpacked directory beside its tar. The fix was to unpack it in this handoff; the sealed R4 folder was
not touched.

**Nothing else changed (REL-068):**
- The sealed R4 handoff verifies (509 files) and the fixture verifies.
- The daily instance's image and start time are unchanged.
- A Git-free content fingerprint shows every repository area unchanged except the files this task wrote (16 at the end; handoff `evidence/changed-files-final.txt`)
  (`evidence/intact/`).

**Redacted logs (REL-069):** `evidence_share.py share` copied 10 files (logs and per-step `results.tsv`/`.jsonl`)
into `share/` through `redact.py`. `evidence_share.py audit share/` reports 0 findings.

### Operator replay walkthrough (REL-070)

From the worktree root:

```sh
H=<handoff folder>; export TMPDIR=$H/scratch/tmp
bash scripts/release/disk_preflight.sh WORK=$H:2048 TMPDIR=$TMPDIR:1024          # OK lines, or exit 3 = BLOCKED
bash $H/tools/rehearse.sh "$PWD" $H <new-run-name>                                # 24 PASS, about 95 s
BUNDLES=$H/standin/bundles bash $H/tools/rehearse_bundles.sh "$PWD" $H <new-run-name>   # 27 PASS, about 90 s
python3 -I deploy/aws/private-staging/staging/tools/evidence_index.py $H/standin/<run> --out index.md --approve <run_id>
```

**Rules:**
- Always use a **new** run name; evidence is never edited.
- A FAIL stops the slot until it is understood.
- The R4 bundles and fixture are read through their checksums only.

## 12. Teardown and recovery (REL-071 to REL-080)

### What the plan creates and what it leaves (REL-071 to REL-073)

| Kind | Terraform addresses (21, `expected_resources.json`) | Holds data | Expected final state after RUNBOOK §9 |
| --- | --- | --- | --- |
| Network | VPC, internet gateway, subnet, route table + association, S3 gateway endpoint, security group + egress rule | no | gone |
| Storage | S3 bucket (+ public access block, ownership, encryption, versioning, lifecycle, policy) | **yes** (synthetic) | gone; `force_destroy` removes every version |
| Compute | instance, data volume + attachment | **yes** (data volume) | instance terminated (the power-off may already have done it); data volume gone |
| Identity | host role, inline policy, instance profile | no | gone |
| Outside Terraform | 16 SSM parameters under `/flh/staging` | no | deleted by RUNBOOK §9 |
| Outside Terraform | the four staging policies + boundary; the $2 budget | no | **retained deliberately** (free; reused by the next pass) until the owner removes them |
| Not staging | the public demo and its stack | — | unchanged |

### Proving it (REL-074 to REL-076)

**Permissions:** the `flh-stg-verify-readonly` policy (A1) grants every listing below: EC2
`Describe{Instances,Volumes,Snapshots,Addresses,…}`, `s3:ListAllMyBuckets`/`ListBucketVersions`, `tag:GetResources`,
`ssm:GetParametersByPath`/`DescribeParameters` and the IAM `Get*`/`List*` on the staging role. Today's read-only
profile is refused all of them except `DescribeInstances`/`SecurityGroups`/`Vpcs`/`Subnets` (R5 snapshot).

**Owner sequence (credential placeholders only):**

```sh
python3 -I deploy/aws/private-staging/staging/tools/lifecycle.py verify-commands --env staging --out ~/flh-stg-residual --profile <verify-profile>
# run the printed aws commands; then:
python3 -I deploy/aws/private-staging/staging/tools/lifecycle.py residual ~/flh-stg-residual --env staging   # RESIDUAL CHECK PASSED
aws ssm get-parameters-by-path --path /flh/staging --profile <verify-profile> --region us-east-1 --query 'length(Parameters)'   # 0
```

**Untagged leftovers (REL-076):** the tag filters miss a resource that lost its tags, so also run:

```sh
aws ec2 describe-volumes --filters Name=status,Values=available --profile <verify-profile> --region us-east-1 \
    --query 'Volumes[].{id:VolumeId,gib:Size,created:CreateTime}'                     # unattached disks, any tag
aws ec2 describe-addresses --profile <verify-profile> --region us-east-1 \
    --query 'Addresses[?AssociationId==null].AllocationId'                             # Elastic IPs not attached
```

A volume or address listed there that is not the demo's is a residual. The demo's own root volume is attached and
does not appear in the first listing.

### Retention, partial teardown and the next day (REL-077 to REL-079)

**Retention:**
- **Staging bucket:** objects expire after 14 days, old versions after 1 day, and `force_destroy` empties it at
  destroy.
- **Local copies:** the candidate and rollback bundles stay in the owner's local handoff, and the synthetic fixture
  stays local and checksummed.
- **Logs:** no CloudWatch Logs in staging; host logs go with the instance.

**If teardown is partial:**
1. Stop and change nothing by hand yet.
2. Re-plan the destroy and run `plan_check.py --mode destroy`; it must say SAFE.
3. Apply it.
4. Run the residual check into a **new** directory.
5. For each kind still listed:
   - a volume: `aws ec2 delete-volume`, once it is unattached and tagged `workbench-staging`;
   - a bucket: empty its versions, then delete it;
   - an address: release it;
   - parameters: RUNBOOK §9.
6. Never delete anything without the `workbench-staging` tag or the `flh-stg-` prefix: that is the demo or someone
   else's.
7. Record what was removed by hand.

**Next-day bill review:** use `daytime.py bill-template` and compare with the baseline recorded before the slot:
- **Bills, per service:** EC2 (compute + EBS), VPC (public IPv4) and S3, against the baseline plus about $0.12.
- **Bills:** credits applied and tax.
- **Any new service line:** it means something else was created.

### Parser on incomplete evidence (REL-080)

`lifecycle.py residual` was exercised on synthetic evidence:
- **Clean:** PASSED.
- **Residual:** FAILED, 3 checks.
- **Missing or truncated file:** exit 2.

**Found and fixed here:** a listing without its top-level key (an error envelope or the wrong command) was read as
"zero resources" and **passed**. It is now refused as incomplete (exit 2), covered by
`ResidualEvidenceIncomplete` (5 cases).

## 13. Operational security (REL-081 to REL-090)

| Check | How (offline) | Result |
| --- | --- | --- |
| Least privilege (REL-081) | `review_permissions.py --matrix`, `--env staging`, `--env production` | every required action allowed; 0 unexpected wildcards; production and staging policies never name each other |
| Boundaries in scope (REL-082) | `iam/out*/flh-{stg,prd}-host-boundary-policy.json` | in scope for the owner: the staging host boundary (A3) and later the production one. Out of scope: the demo's `flh-demo-host-boundary` (Demo lane) and the Identity Center permission sets (managed outside the repository) |
| Credential placeholders (REL-083) | `PlanCommandHygiene` test | every `--profile` is a `<placeholder>` or `flh-staging-release`; every `--account` is a placeholder; no access key, 12-digit number or secret |
| Public ingress defaults (REL-084) | staging Terraform, demo variables, Compose | staging has **no ingress rule** (egress 443 only); the demo's `public_https_enabled` defaults to `false` (the live demo has 80/443 open: §9); Compose binds `127.0.0.1` only; preflight refuses `LISTEN_HOST`/`HTTP_ALLOWED_HOSTS` in staging user data |
| Backup access (REL-085) | RELEASE.md, staging bucket, IAM | backup and data directories mode 700, `app.db*` 600 after a restore; bucket TLS-only, public access blocked, SSE; the host role is scoped to its bucket; the verifier cannot read backups (`test_verifier_cannot_read_backups`) |
| Logs (REL-086) | synthetic entry texts searched in 22 log and result files | 0 hits (narrow sample: the fixture has only 3 entries over 12 characters); stand-in data stays in `standin/`, which is never shared |
| Evidence archives (REL-087) | `evidence_share.py audit` on `share/`, `evidence/` and the changed repo files (16 at the end) | 0 findings, after redacting 5 local logs (home paths) and assembling one synthetic test address |
| State files (REL-088) | **new** `tools/state_guard.py` (`scan`, `--stdin`, `ignore-check`) | `deploy`, `docs`, `share` and `evidence` CLEAN; `standin/` REFUSED (42 synthetic databases, by design never shared); both Terraform roots ignore state, plans and `.terraform/`. NOTE: the demo root ignores `terraform.tfvars` only (interface note §3) |

**Before committing (OWNER):**

```sh
git diff --cached --name-only | python3 -I deploy/aws/private-staging/staging/tools/state_guard.py --stdin   # CLEAN
python3 -I scripts/release/publish_metadata_check.py --kind commit <message-file>
```

**Configuration diff (REL-089), compared with main `576630bb`:**
- **Identical:** IAM templates and rendered policies, staging and demo Terraform, the cost sheet.
- **One existing file changed:** `tools/lifecycle.py` (the residual-shape fix, +9 lines; handoff
  `evidence/security/lifecycle.diff`).
- **Everything else is new:** `daytime.py`, `portal_check.py`, `pilot_check.py`, `state_guard.py`, the routing plan,
  the isolation case, three test files and two plan documents.

**Ledger labels (REL-090):** every action needing the cloud, DNS, Git, money or a person is marked **OWNER** in
this plan and `owner-only` or `blocked` in the ledger. `owner-tasks.md` in the handoff lists them.

## 14. Morning handoff (REL-091 to REL-100)

**Start (REL-091):**
- **Worktree:** `~/workspace/overnight/20261120-r4/release`, branch `worker/20261121-aws-prep` as you confirmed.
- **Commit:** **unverified**; agents may not run Git.
- **Content:** a Git-free content fingerprint is in the handoff's `start.manifest`.
- **Changes:** only the 16 files of this task (§13; handoff `evidence/changed-files-final.txt`).

### One-page owner runbook (REL-093)

1. `daytime.py template --out ~/flh-daytime/inputs.json`, then fill it.
2. `daytime.py check ~/flh-daytime/inputs.json`, which must say **GO**. `daytime.py page … --out go-or-hold.md`
   gives the page to read before starting.
3. Record the billing baseline (`daytime.py bill-template`).
4. Create the $2 budget alert (A2).
5. An administrator creates the policies (A3), or A1 is granted.
6. §7 steps 2–8: sign-in, gate, promote-check, preflight, `plan_check` SAFE, apply, parameters, install
   (**IDENTITY OK**), synthetic restore (**READY**), `/readyz` smoke, then RUNBOOK §7 E1–E13.
7. Real-host-only checks (§7): a reboot, rollback and back, and the power-off timer.
8. Teardown (§12): destroy plan SAFE, apply, RUNBOOK §9, `lifecycle.py residual` **PASSED**, the untagged-leftover
   listings.
9. Next day: `daytime.py bill` against the baseline.

**Stop at the first refusal.** The rollback for each step is in §7 and §12, and for each DNS change in §9.

### Still open (REL-094)

| Area | Dependency |
| --- | --- |
| IAM | A3: four staging policies and the boundary, created by an administrator; A1: verify-readonly attached, or use the operator profile |
| DNS | the portal-name decision (§9); C1–C4 at Namecheap; recording FLH-088's live apply (the demo has 80/443 open, but the repository says not applied) |
| Model | SageMaker quota for ml.g5.xlarge; the human review gates of `readiness/README.md`; the training-image digest; nothing model-related in the staging pass |
| Privacy | authentication, accounts and isolation (not implemented); retention and deletion decisions; the incident template (§18) before any pilot |

### Cloud evidence and what is still live-only (REL-095, REL-096)

**Cloud evidence:** no AWS call was made in this task.

| Source | Time | Profiles | Findings |
| --- | --- | --- | --- |
| R5 refresh snapshot | 2026-11-20T21:09:14Z | `flh-staging-release` only | one demo instance; no staging stack; 30 of 35 reads refused; billing refused |
| R3 run 3 | 2026-11-20T14:34:49Z | release + extraction | identical resources; SageMaker 0/0 (extraction profile) |

**Pending, live only:**
- every AWS call in §7 and §12;
- the actual bill and credits;
- real-host timings;
- the SageMaker smoke cost (bound $0.71);
- certificate issuance;
- DNS propagation.

The figures in §6 are estimates from dated list prices.

### Rollback point and evidence gaps (REL-097)

**Rollback point:**
- **App:** the R4 rollback bundle `flh-staging-57ec7085dc61.tar` (`d53d71b7…`).
- **This task's changes:** discard the 16 listed files; the only edit to an existing file is the `lifecycle.py` fix.

**Evidence gaps:**
- the exact commit;
- live AWS behaviour (§7 "stand-in cannot prove");
- billing;
- the demo's DNS and Elastic IP state;
- GPU memory for Qwen (an estimate);
- the log-content scan's small sample (3 entries).

### Integration boundaries (REL-098)

`docs/plans/FLH-AWS-PREP-interfaces.md` covers:
- **§1 Extraction:** confirmed.
- **§2 UI:** this task changes no `web/` file. A portal page is a separate static build with no API calls; pilot UI
  waits for authentication; new text needs both locale catalogs.
- **§3 Demo:** the FLH-088 record; `*.tfvars` in the demo root's `.gitignore`; C2/C3 use `flh-public-https`.

### Next owner decision (REL-099)

**A2 plus A3 for one synthetic staging pass**, about $0.12 under a $5 cap and a 4 h runtime:
- **Why it comes first:** it unblocks every live check in §7 and §12 and costs the least.
- **Second:** whether to start an authentication milestone. The pilot depends on it, and today 32 of 78 private GET
  routes, including all five exports, answer anonymously.

### Runnable local demo (REL-100)

`bash <handoff>/tools/local_demo.sh "$PWD" <handoff>` runs every offline check in one pass:
- **Daytime:** the template HOLDs with 14 reasons, the synthetic inputs give GO, and it produces the page, the cost
  and the quotas.
- **Portal:** VALID, 22 of 22.
- **Pilot:** VALID; `run` is BLOCKED.
- **State guard:** CLEAN.

It then starts the R4 candidate on loopback with an empty folder and probes it anonymously (GET only). Result:
**NOT READY**, 32 of 78 private routes answered anonymously. Afterwards the container is removed and the daily
instance is unchanged.

## 15. Daytime entry criteria (REL-101 to REL-110)

**The go-or-hold checklist (REL-101, REL-107, REL-110):** `daytime.py checklist` prints the copyable checklist. It
turns the R4 handoff's go/hold (R4 plan §11.1) and this plan's limits into:
- **12 items:** each says who supplies it and how it is checked;
- **10 stop triggers:** each applies before any live write;
- **a 5-step rollback entry.**

A copy is in the handoff (`evidence/daytime-checklist.md`). Two triggers are new here:
- the **residual listing must PASS before the start**, so a leftover from an earlier attempt is never mistaken for
  this run's;
- the slot stops when **less than 1 h** is left before teardown must begin.

### Who can supply each missing billing input (REL-102)

| Input | Who | Where |
| --- | --- | --- |
| Charges, credits applied, tax, total due, charges per service | account owner with billing access | Billing → Bills |
| Credits remaining, expiry, applicable products | account owner with billing access | Billing → Credits |
| Account plan and end date | account owner (root or billing admin) | Billing home / Free Tier |
| Existing budgets | account owner | Billing → Budgets (`budgets describe-budgets` refused to the read-only profile) |
| Quotas | account owner | Service Quotas (refused to the read-only profile; not in verify-readonly either) |
| Elastic IP, volume and bucket sizes (demo) | owner, or an IAM administrator granting A1 | EC2 and S3 consoles |
| None of these | agents | billing is never readable here, and Cost Explorer is not approved |

### Approvals versus permissions already observed (REL-103)

| Owner policy approval (decided, not observed) | Permission observed on earlier read-only runs (R3/R5) |
| --- | --- |
| A1: attach verify-readonly, or use the operator profile for listings | `flh-staging-release` allowed: `sts get-caller-identity`, `ec2 describe-instances`, `describe-security-groups`, `describe-vpcs`, `describe-subnets`; refused 28 other reads |
| A2: budget cap, window, account, synthetic data only | `flh-staging-extraction` (R3 only) allowed SageMaker `list-endpoints` and `list-training-jobs` |
| A3: create the four staging policies and the boundary | no write permission was ever observed or used by an agent |

An observed permission is not an approval, and an approval does not create a permission. The daytime check reads
only the approvals the owner writes into the inputs file.

### Profile and region without exposing the account (REL-104)

```sh
aws configure get region --profile <operator-profile>                       # us-east-1 (local config; no API call)
aws sts get-caller-identity --profile <operator-profile> --output json > ~/flh-daytime/caller.json   # never pasted
aws sts get-caller-identity --profile <operator-profile> --query Arn --output text | sed -E 's/[0-9]{12}/<account>/'   # role name only
python3 -I deploy/aws/private-staging/staging/tools/candidate.py gate --caller-identity ~/flh-daytime/caller.json \
    --allowed-account-sha256 <sha256> --region us-east-1 --env staging --workspace default   # compares the hash, prints no ID
```

### Quota headroom (REL-105)

**Formula:** headroom = quota − in use − needed ≥ 0 for each line of `daytime.py quotas`.
- **vCPU:** quota − 2 (demo) − 2 (`t3.small`) ≥ 0.
- **VPCs and internet gateways:** 5 − 2 − 1 ≥ 0 at the defaults.
- **Elastic IPs:** staging needs none.
- **SageMaker:** `ml.g5.xlarge` training ≥ 1 for the model smoke only.

The detail is in §6 (REL-019).

### Decision log: cost cap and run duration (REL-106)

| ID | Decision | Why | Reversible by |
| --- | --- | --- | --- |
| D1 | $5 cap for the pass | about 40× the $0.12 estimate: room for a repeat or a forgotten day, still trivial | editing `limits.budget_cap_usd` (the tool allows ≤ $10) |
| D2 | $2 Budgets alert | Budgets only alerts, and late; $2 means "something besides the pass is billing" | the Budgets console |
| D3 | 4 h runtime (`max_runtime_hours = 4`, the Terraform default) | R4 timings: install, restore and checks fit in about 1–1.5 h; 4 h covers a reboot and a rollback | `terraform.tfvars` (1–4 accepted for a first pass) |
| D4 | window ≤ 6 h | runtime plus install before and teardown after | the inputs file |
| D5 | the R4 candidate, not a fresh build | the pass tests host mechanics; app inputs to the host are unchanged | building from the approved commit (§7) |

### Build provenance inputs against the merged scripts (REL-108)

`PlanCommandsMatchTheTools` parses every tool command in this plan and the interface note. It checks each flag
against that tool's own `--help`, or its source for tools that read `sys.argv`, and passes.

**Checked by hand (shell):**
- `build_bundle.sh` names `--git`, `--repro`, `--tree`, `--expect-tree` and `--commit` in its usage header;
- `flh-staging-bundle` has `verify`, `install`, `plan`, `cleanup`, `rollback`, `status` and `identity`;
- `candidate.py provenance` needs `--commit` and `--out`, corrected in §7 on 2026-11-21.

### Demo validation, apart from staging (REL-109)

| Item | Status | Owner |
| --- | --- | --- |
| FLH-088 public HTTPS: live 80/443 versus "not applied" in the repository | **unrecorded** | Demo lane / owner |
| Demo package built from newer `web/src/demo` (merged after `58c0ba8b`) | not validated by Release; outside the staging candidate | Demo lane |
| Public release with real-model vectors | **BLOCKED** by design (FLH-073 release validation) | Demo lane |
| Moving the demo to `demo.flh.vanquisher.world` | proposal only (§9) | owner |

None of these blocks the staging pass, and the staging pass changes none of them.

## 16. Dry-run release mechanics (REL-111 to REL-120)

All on the local stand-in with synthetic data. Runs: `bundles-run2` (`bundle_rehearsal.py`, 27/27) and
`R4-20261121T055720Z-1dff76` (24/24). The handoff's `evidence/mechanics/` holds the provenance cases.

| Item | Case | Result |
| --- | --- | --- |
| REL-111 | verify the candidate | V0 `flh-staging-bundle verify` VERIFIED; `candidate.py promote-check` with its R4 provenance: **PROMOTE** (commit `58c0ba8b`, tree `35da542d`, `linux/amd64`) |
| REL-112 | invalid digest | V1 wrong SHA-256: refused before install. V2–V7 (altered, added or missing file, renamed identity, swapped image) also refused |
| REL-113 | missing provenance metadata | each of the 11 provenance fields removed in turn (and a wrong commit): **REFUSED**, exit 1, every time |
| REL-114 | interruption before the switch | F1a SIGKILL while unpacking or verifying: `current`, running image and identity unchanged. F1b: `status` names the partial unpack and the next run removes it |
| REL-115 | interruption after the switch | F3 session dropped (SIGHUP, output closed) right after the switch: the install continued and verified NEW. F2a failure after the switch: switched back automatically (65.3 s, the 60 s health wait) |
| REL-116 | the old release stays usable | F1a: the previous release keeps serving with IDENTITY OK. F2a: the previous release is re-verified and serving; F2b: ledger and data unchanged |
| REL-118 | records written during a rollout | U2/R2: W1 (written on OLD) and W2 (written on NEW) both survive the binary rollback (same database, same ledger). RB3: a **database** rollback restores the pre-install backup, so writes after it are lost, as RUNBOOK §8 says |

### Rehearsal against the runbook (REL-117)

RUNBOOK §8 and the evidence agree on:
- rollback re-verifies `previous` and refuses a newer database (RB4);
- the switch-back after a failed install;
- `.partial-*` cleanup;
- the database-newer procedure.

**Timing:** rollback measured 2.0–2.1 s, against the runbook's 2.8 s; a failed install about 65 s, against "about a
minute".

**Not exercised by any rehearsal:**
- a SIGKILL right after the switch (F3 covers a hangup there, which finishes the install);
- the browser-cache note after a rollback (only the served page's identity is checked, V1 of the R4 run).

Both stay as runbook guidance.

### Residual local state (REL-119)

After every run, including the interrupted ones: 0 stand-in containers, volumes or networks, and 0 `.partial-*`
directories. Two things remain:
- **20 `flh-staging:*` images:** loaded by R3–R5 rehearsals; none was built today. Prune with
  `docker image rm flh-staging:<tag>` when no session needs them, never `french-learning-hub:local`.
- **1.7 GB of stand-in host roots:** in the handoff's `standin/` (synthetic databases, never shared).

The throwaway data folder of the local demo also stays in the handoff's `scratch/`.

### Owner replay: the three cases that matter most (REL-120)

| Case | Replay locally | On the staging host (OWNER) | Pass |
| --- | --- | --- | --- |
| A failed install switches back | `rehearse_bundles.sh … <new-run>` (F2a/F2b) | never install a broken bundle on staging; watch for `FAILED: switching back` during any install | previous IDENTITY OK, ledger unchanged |
| Rollback, and the newer-ledger refusal | `rehearse.sh … <new-run>` (RB1, RB4) | `flh-staging-bundle rollback` to `57ec7085dc61`, then install the candidate again | `ROLLED BACK … IDENTITY OK`; data kept |
| Restore with parity | `rehearse.sh … <new-run>` (S4, S5) | RUNBOOK §6 + `scripts/validation/migration/verify_restore.sh BACKUP_DIR WORK` | inventory READY, equal digests |

## 17. Inference plan refinement (REL-121 to REL-130)

### Runtime profiles (REL-121): no owner-approved profile yet

| Profile | Source | Revision | License | Size | Measured here |
| --- | --- | --- | --- | --- | --- |
| `qwen3.5-4b` (default candidate) | `tools/extraction/flh_extraction/models.py` | `851bf6e8…` | apache-2.0 | 9,319,737,856 bytes | **no**: tokenizer and weights are not on the Extraction machine (`check_model_assets` exits 3) |
| `qwen3-1.7b` | same | `70d244cc…` | apache-2.0 | not recorded | no |
| Whisper base (speech) | Extraction R4 | pinned files present | — | — | ready 13 s; a 16.5 s clip in 8.7 s; RSS about 0.6–1.2 GB (one shared laptop) |
| Rules-only extraction workflow | Extraction (EXT-079) | `deployment_id e978b6c2bdb6` | MIT | — | about 0.3 ms per step warm, 76 ms cold, 35 MiB peak; nothing beyond the existing service |

The model rows are reported by Extraction from its branch (`deploy/aws/model-runtime/MODEL-READINESS-20261121.md`,
not in this tree) and were not re-measured here. A comparison under owner-approved inputs waits for the owner to
approve a profile and supply its assets. Until then no model profile is part of any AWS step.

### Probes, fixtures, fallback and limits (REL-122 to REL-125)

**Process boot versus model load (REL-122):**
- **Rule:** `/healthz` means the process is up; `/readyz` is 200 only after the files match the manifest, the model
  is loaded and a warm-up succeeded. This is the rule of the E5 service (FLH-054 README), the extraction service's
  self-check and the app's `/readyz` (database).
- **Measured apart:** R4 B2 measured them separately (image 0.49 s, healthz 1.0 s, readyz 1.0 s).
- **Mock smoke:** S1 shows `/healthz` 200 while `/readyz` is 503 `loading`; S2 shows ready only with the pinned
  identity.

**Fixture requests (REL-123):**

| Request | Real service | Mock smoke |
| --- | --- | --- |
| Known-good | extraction service `01-review-first-revision` (response fixed in `fixtures/service_v1`) | S3: fixed output for a fixed input |
| Wrong contract or source | fixtures 05 `contract_mismatch` and 06 `invalid_source` | — |
| Unknown model | — | S4: 404 `unknown_model`, nothing loaded |

**Fallback and retry (REL-124):**
- **Runtime:** the caller reports `unavailable` once (503 while not ready, as in mock S7) and never retries; there is
  no other model and no keyword fallback.
- **SageMaker:** a failed job is never resubmitted automatically. The owner renders a new job name after reading its
  output manifest.

**Proposed limits (REL-125):** `staging/runtime/model-runtime.example.json`:
- 2048 MiB memory and memory-swap, 2 CPUs, 128 pids, 4 GiB disk;
- 64 KiB request body, 30 s request timeout, 2 in flight, 120 s startup deadline.

These are for a later, larger host. A `t3.small` has 2 GiB, so **no model runs in the staging pass**. The extraction
sidecar keeps its own 256 MiB limits (`runtime/extraction.override.yaml`).

### Identity, cleanup and rollback (REL-126 to REL-128)

**Identity in logs (REL-126):**
- **Model:** one `model_ready` line with `name@revision12` and the first 16 hex digits of the manifest SHA-256. Each
  request line carries `request_id`, status and byte count, **never the text** (mock S6 checks a marker string).
- **Extraction service:** method, path, status, code, `request_id`, bytes and milliseconds only (its
  `service_examples` output).
- **Never logged:** paths, keys, account or bucket names.

**Storage cleanup (REL-127):**
1. Stop the runtime.
2. Delete the unpacked model cache.
3. Keep the pinned package only while a next step is scheduled.
4. Delete SageMaker output prefixes once their manifest checks are recorded.
5. Prune `flh-extraction-service:*` and `flh-staging:*` images no session uses.

Mock S9 shows only the evidence left.

**Rollback of the app and model pair (REL-128):** record the pair (app bundle, model `deployment_id` or manifest
SHA-256) before each change.
- **App:** `flh-staging-bundle rollback`, which re-verifies the previous bundle.
- **Model:** start the previous model image with its recorded ID (`FLH_EXTRACTION_IMAGE`,
  `FLH_EXTRACTION_DEPLOYMENT_ID` in `extraction.override.yaml`).
- **Check both identities:** `IDENTITY OK`, and `/manifest` or `/readyz` showing the recorded model.

Mock S8 upgrades v1 → v2, rolls back, and the pair equals the one before.

### Capacity: measured versus estimated (REL-129)

| Quantity | Measured (where) | Estimated or unknown |
| --- | --- | --- |
| App ready after install | 1.0 s (R4 B2, stand-in) | real host: unknown |
| Rollback | 2.0–2.1 s (stand-in) | real host: unknown |
| Failed-install recovery | 65.3 s (stand-in) | same order on the host |
| Extraction service | 0.95 s ready, 14.9/22.2 MiB (R4); 0.3 ms per step warm (Extraction) | — |
| Whisper base | 8.7 s per 16.5 s clip, 0.6–1.2 GB (Extraction laptop) | the staging host cannot hold it |
| Qwen3.5-4B predict | — | up to 272 prompts per job within 1 h (job bound); the real rate is unknown until readiness step 6 |

### Local mock model smoke (REL-130)

```sh
python3 -I deploy/aws/private-staging/staging/rehearsal/mock_model_smoke.py <new work dir>   # 9 PASS, 0 FAIL
```

**Exit criteria:** S1–S9 above all PASS, and only `mock.log` and the results remain. `test_mock_model.py` runs it on
every suite run.

## 18. Pilot acceptance and operations (REL-131 to REL-140)

### Invitation reuse and revocation; anonymous access (REL-131 to REL-134)

**The invitation scenario (REL-131)** is part of `pilot/isolation_case_v1.json`, all with synthetic accounts:
- **E3:** a second redemption of invitation A is refused with no session and no change.
- **E4:** an expired invitation is 410 and creates nothing.
- **V1:** after revoking B, B's next request is 401 and B's data is kept.
- **V2:** A is unaffected.
- **B3:** B's old session is still 401 after a restore.

**Anonymous access (REL-132):**
- **Probe:** `pilot_check.py probe http://127.0.0.1:<port>` sends GET only, to loopback only. It ran against the
  real candidate started locally on an empty folder.
- **Result:** **NOT READY**. 32 of 78 private GET routes answered 2xx anonymously; the rest were 404, 400 or 503;
  none answered 401.
- **Why:** authentication is implemented **nowhere**, so no private route rejects anonymous requests.

**Two-account exports (REL-133):** not supported, because the server has one store and no accounts. All five export
routes answered 200 to an anonymous request. Kept as **blocked** until accounts exist.

**Bootstrap gaps while authentication is absent (REL-134):**
- no owner account to bootstrap;
- no invitation store or token format;
- no sign-in or session route;
- no CSRF protection;
- no audit log;
- no per-account backup selection.

The bootstrap path in §10 is a specification only. Nothing in the staging pass creates a pilot entry point.

### Shutdown after a suspected exposure (REL-135)

1. **Cut the path first:**
   - delete the pilot host's DNS record (`app.flh…`) at Namecheap;
   - on the host, stop the pilot service (`flh-daily.sh stop` over SSM);
   - leave the demo and portal running unless they are involved.
2. **Revoke:** every session and unused invitation (pilot admin command). Rotate the provider keys in SSM
   (`OPENAI_*`) if logs show any use.
3. **Preserve:** do not delete anything.
   - Copy `deploy.log`, the service logs and a fresh backup to an owner-only location.
   - Record the times as UTC.
   - Take an EBS snapshot only if the owner decides; it bills per GiB-month.
4. **Assess:** use the incident handoff below. Decide whether anyone's data was read or written, and tell affected
   people as the owner decides.
5. **Resume only after the cause is fixed and §10's conditions pass again.** Otherwise run the teardown (§12).

### Retained data and backups: owner review (REL-136)

- [ ] **Where data lives:**
  - the data volume (`/srv/flh-staging/data` or production);
  - S3 backup prefixes;
  - local handoff copies;
  - the NAS;
  - none in CloudWatch Logs.
- [ ] **Retention:** each place has a retention period (staging bucket: 14 days; production: `backup_retention_days`)
  and an owner who can delete it.
- [ ] **Access:**
  - only the owner and the host role can read backups (bucket policy TLS-only, the verifier cannot read backups);
  - nobody else has an IAM principal in the account.
- [ ] **Deletion:** confirmed with a listing (`lifecycle.py residual` for staging; `aws s3api list-object-versions`
  for a prefix). A deleted person's records are removed from the live database **and** expire from every backup
  within the retention period.
- [ ] **Learner data:** none was ever placed in staging (synthetic only, A2).

### Portal cutover tied to readiness and rollback (REL-137)

| Before | Change | Watch for 15 min after | Roll back if |
| --- | --- | --- | --- |
| demo `/readyz` 200 and its demo identity equals the installed release (`flh-release`) | C2/C3 (demo name, certificate) | V-dns, V-tls, `/readyz` 200 on the new name every minute | any check fails twice: delete the new record, re-run `flh-public-https` with the previous name |
| static page published and `curl -sI` 200 on the static host's own URL | C1 (portal CNAME) | V-portal; POST to the portal is not 2xx | delete the CNAME (TTL 300) |
| pilot conditions (§10) all pass | (future) pilot record | `pilot_check.py probe` READY, isolation case PASS | delete the record, then the shutdown above |

### Feedback fields and retention (REL-138), proposal

| Field | Values | Note |
| --- | --- | --- |
| `received_at` | UTC time | server-set |
| `area` | one of: capture, library, listening, reading, writing, speaking, exam, other | no free-form page path |
| `kind` | bug, confusing, idea | — |
| `text` | at most 500 characters | the form says not to paste learning content or personal data |
| `account` | pseudonymous account ID (pilot only) | never a name or e-mail |

**Not collected:** IP addresses, user agents, screenshots or recordings.

**Retention:** 90 days, then deleted from the live database. Feedback is excluded from training data and from the
annotation dataset.

### Incident handoff template (REL-139)

```text
INCIDENT <YYYYMMDD>-<n>      opened <UTC time> by <owner name or role>
Contact (owner):             <phone or messenger handle, kept outside Git>
Backup contact:              <name/role and how to reach them>
What was seen:               <one paragraph: symptom, first time seen, how noticed>
Scope:                       <hosts: demo / portal / pilot / staging>; <accounts affected: none / list of pseudonymous IDs>
Actions taken (UTC):         <time> DNS record removed | <time> service stopped | <time> sessions revoked | <time> keys rotated
Evidence kept at:            <owner-only location>; checksums <SHA256SUMS digest>
Data read or written?        <unknown / no / yes: what>
People to tell:              <none / list>, by <date>, decided by <owner>
Next step and who:           <...>
Closed:                      <UTC time>, cause <...>, fix <...>, §10 conditions re-checked <yes/no>
```

### Conditions keeping invitations on hold (REL-140)

Invitations stay on hold while any of these is true. Today **all six are true**:
1. authentication, sessions and invitations are not implemented;
2. `pilot_check.py probe` is NOT READY on the candidate (32 of 78 routes answer anonymously);
3. the isolation case has not run (no pilot API);
4. retention, deletion and feedback retention are not approved;
5. the incident template has no filled contacts;
6. the pilot host has no HTTPS (and no DNS record, deliberately).

## 19. Owner package and reset handoff (REL-141 to REL-150)

### First hour (REL-141, REL-142)

| Minutes | Action | Authoritative script or runbook |
| --- | --- | --- |
| 0–10 | Read `go-or-hold.md`; decide A2 | `daytime.py page`, §15 checklist, §4 limits |
| 10–20 | Fill `inputs.json`; record the billing baseline | `daytime.py template`, `daytime.py bill-template`; Billing console |
| 20–30 | Create the $2 budget alert; check the vCPU quota ≥ 4 | Billing → Budgets; Service Quotas; `daytime.py quotas` |
| 30–45 | IAM administrator: render and create the staging policies (A3); attach verify-readonly or choose the operator profile (A1) | `iam/render_policies.py`; RUNBOOK §2; `review_permissions.py --simulate` |
| 45–55 | Sign in; `candidate.py gate`; `promote-check`; `authorize` (dry run); `preflight.py` | §7 steps 2–4; R4 plan §11.2; RUNBOOK §3 |
| 55–60 | `terraform plan`, then `plan_check.py --mode create --env staging`: SAFE, 21 to add. **Go or stop here** | RUNBOOK §3; `plan_check.py` |

`PlanCommandsMatchTheTools` checks that every flag used in this plan exists in the tool it names.

### The same sequence, locally, on synthetic inputs (REL-143, REL-144)

`<handoff>/tools/owner_sequence_local.sh <worktree> <handoff> <new-run>` runs 15 steps end to end, each AWS step
replaced by its offline gate or the stand-in:
- **01–02:** daytime check GO; checklist.
- **03:** `candidate.py gate` with a synthetic caller: GATE PASSED. 03b: a wrong account hash gives GATE FAILED.
- **04–06:** promote-check PROMOTE; authorize READY (dry run); preflight READY 45/0.
- **07:** `plan_check` create SAFE. 07b: a public-ingress plan gives STOP.
- **08:** stand-in install, restore and rollback (24/24).
- **09:** model readiness record.
- **10:** destroy plan SAFE.
- **11:** residual PASSED. 11b: leftovers give FAILED.
- **12:** next-day bill.

Run `seq1`: 15 PASS, 0 FAIL. The embedded stand-in run `R4-20261121T062218Z-b8a50b` is 24/24 and APPROVABLE.

**Proof of a recoverable failure:** the handoff's `share-f2/` holds the redacted log of a broken-migration install,
its `deploy.log` lines, the diagnostics and the results row:
- `FAILED: switching back to flh-staging-35da542d0dd4`, then `IDENTITY OK`;
- ledger and data unchanged.

It audits clean.

### Teardown evidence fields (REL-145)

| Evidence | Fields | Pass |
| --- | --- | --- |
| `collected-at.txt` | UTC time of collection | present; after the destroy |
| `ec2-instances.json` | Reservations[].Instances[] (not terminated) | none |
| `ec2-volumes.json`, `ec2-snapshots.json`, `ec2-addresses.json` | Volumes[], Snapshots[], Addresses[] tagged `workbench-staging` | none |
| `s3-buckets.json` | Buckets[] named `flh-stg-*` | none |
| `tagged-resources.json` | ResourceTagMappingList[] tagged `workbench-staging` | none |
| `lifecycle.py residual --json` | per check: `check`, `source`, `collected_at`, `count`, masked `ids`, `status` | every status PASS |
| Untagged listings (§12) | available volumes; addresses without an association | none that is not the demo's |
| SSM | `get-parameters-by-path /flh/staging` count | 0 |
| Next-day bill | per-service charges against the baseline | no staging line beyond about $0.12 |

A listing without its top-level key is refused as incomplete (exit 2), never read as empty.

### Cloud behaviour not verified (REL-146), and what stays (REL-147)

| Unverified | Why |
| --- | --- |
| AL2023 cloud-init, the Compose plugin download, the data volume mount, IMDSv2, the SSM session and port forward | needs a real host (§7) |
| IAM policy evaluation (conditions on instance type, volume type, tags; AccessDenied for out-of-scope calls) | `review_permissions.py` checks actions offline only and does not evaluate conditions |
| S3 TLS-only enforcement, gateway endpoint routing, transfer and EBS timings | needs AWS |
| The power-off timer and terminate behaviour; a real reboot | needs a real host |
| The residual listings after a real destroy | needs AWS and A1 |
| The bill, credits, tax, account plan; budget alert delivery | billing is unreadable to agents |
| Quotas (vCPU, VPC, IGW, SageMaker) | Service Quotas refused |
| The demo's Elastic IP, root and bucket sizes; FLH-064 leftovers | refused reads |
| DNS propagation and certificate issuance for the portal and demo names | owner DNS |
| SageMaker job behaviour and cost | paid, owner-only |

**Retained deliberately after the proposed run:**
- the four staging policies and the host boundary;
- the $2 budget (free; reused next time);
- the local bundles and fixture.

Everything the 21 Terraform addresses created is gone, and the 16 SSM parameters are deleted. The public demo is
unchanged and not part of the run (§12).

### Offline verification done and skipped (REL-148)

**Done:**
- `python_suites.py --hermetic` (every Python suite, with aws, terraform and docker trapped);
- `test_daytime_plan.py`, `test_portal_plan.py`, `test_pilot_plan.py` and `test_mock_model.py`, inside the
  private-staging suite;
- the stand-in rehearsals: 24/24 three times, 27/27 once;
- the mock model smoke (9/9), the local demo and the local owner sequence (15/15);
- `evidence_share.py` audits and `state_guard.py`.

**Skipped, with reasons:**
- **`terraform test` and `validate`:** Terraform commands stay owner-only here, and no `.tf` file changed (identical
  to main).
- **`make verify`, and `npm run typecheck` in `web/`:** no Go or TypeScript file changed, and `web/node_modules` is
  absent. Installing it is a dependency change this task did not need.
- **Go tests:** no Go change.
- **Git checks:** not allowed.

### Smallest deployable slice and open approvals (REL-149)

**The smallest deployable slice:** one synthetic staging pass of the R4 candidate in its own stack.
- **Size:** 21 resources, 4 h runtime, about $0.12 estimated, under a $5 cap.
- **Completion:** it is complete when RUNBOOK §7 passes on the host, the rollback and reboot work, and the teardown
  residual check passes.

**Open approvals:** A2, A3 and A1, plus inputs (AMI, Compose checksum, quota, billing baseline).
**Not in the slice:** the model runtime, the portal, DNS, the pilot and production.
