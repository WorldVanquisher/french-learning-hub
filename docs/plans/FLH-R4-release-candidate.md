# FLH R4: release candidate, verified rollback, synthetic staging rehearsal (release lane)

Release lane, 2026-11-20.
- **Base:** `main` at `58c0ba8bb36777ccd445c0f95be09e752a6459ab` (tree `35da542d0dd4`). It includes the
  R3 work of every lane (#164–#167).
- **Worktree:** `worker/20261120-r4/release`.
- **Not done:** no AWS call (not even read-only), no Terraform plan or apply, no push, nothing on the
  daily instance.
- **Evidence:** the lane's handoff area `~/flh-handoff/overnight-20261120-flh/release-r4/`, cited by
  folder.
- **Evidence classes:** as in R3 (`docs/plans/FLH-R3-aws-migration.md` §2).
  - **L:** offline;
  - **S:** a local stand-in (Docker, loopback, synthetic data);
  - **G and P:** owner-run on AWS; none exists.

## 1. Merged layout and the commands that produce plans (R4-REL-001)

| Path | Owner | What |
| --- | --- | --- |
| `deploy/aws/terraform`, `deploy/aws/host`, `deploy/aws/iam` | Demo | the public demo stack (one t4g.micro, public HTTPS) |
| `deploy/aws/private-staging/staging/terraform` | **Release** | the private root: `environment = staging` (default) or `production` (workspace `production`); 21 resources each |
| `deploy/aws/private-staging/staging/{tools,iam,host,rehearsal,tests}` | **Release** | `preflight.py`, `plan_check.py`, `plan_review.py`, `candidate.py` (R4); IAM `out/` + `out-production/`; host tools; stand-in rehearsals; tests |
| `deploy/aws/private-staging/*.md` | **Release** | RUNBOOK, INVENTORY, CUTOVER_DRY_RUN, STANDIN-REHEARSAL, AWS_STAGING_PLAN |
| `deploy/aws/model-runtime/STAGING-PLAN.md`, `deploy/aws/sagemaker-extractor` | Extraction | model runtime plan (sidecars, not applied); training jobs |
| `scripts/release/*` | **Release** | smoke, disk preflight, cutover_check, backup_tool, evidence_share, `test_compose_forwarding.py` |
| `scripts/validation/migration/*` | Workbooks | `inventory.py` (restore acceptance), rehearse, cutover edges |

**Staging plan:** `staging/terraform`, the default workspace, `terraform.tfvars` from the example:

```bash
terraform plan -out stg.tfplan && terraform show -json stg.tfplan > stg.plan.json
python3 -I ../tools/plan_check.py --env staging --mode create stg.plan.json
```

**Production plan:** workspace `production`, **no** `terraform.tfvars` in the root:

```bash
terraform workspace select production || terraform workspace new production
terraform plan -var-file=production.tfvars -out prd.tfplan && terraform show -json prd.tfplan > prd.plan.json
python3 -I ../tools/plan_check.py --env production --mode create prd.plan.json
```

Both are printed, filled from the reviewed tfvars, by `candidate.py authorize` (§2).

## 2. The candidate (R4-REL-002 to R4-REL-005)

`candidate.py identity` (class S):

| Field | Value |
| --- | --- |
| Bundle | `flh-staging-35da542d0dd4` |
| Source | commit `58c0ba8bb36777ccd445c0f95be09e752a6459ab`, tree `35da542d0dd460cb992788a075563ae7cee57025` |
| Transfer SHA-256 | `d9db57a6edb5dfcc22e3ffc63a1fa2913ca7ad867917588919429ca9f8d88f70` |
| Image | `sha256:35ba0d45add4…`, platform `linux/amd64` (MANIFEST and image config agree) |
| Server / web | `1394cf1717bf…` / `6b43fb7e478d…`; a no-cache rebuild gives byte-identical server and web |
| Migration ledger | 21, last `021_listening_authored_scripts.sql` (unchanged since R3: binary-compatible rollback) |
| Runtime contract (bundle's own `compose.yaml` and wrapper) | user `${FLH_UID}:${FLH_GID}`; published `127.0.0.1:${FLH_HOST_PORT}:8080` only; `restart: unless-stopped`; 45 forwarded settings; always required `AI_PROVIDER`, `EXTRACTOR_PROVIDER`, `FLH_DATA_DIR`; `/healthz` liveness, `/readyz` readiness (write probe) |
| Rollback bundle (nominated) | `flh-staging-57ec7085dc61` (R3 release, commit `b96675f8`), SHA-256 `d53d71b76f1f…d7988` |

**Gates:**
- **Provenance and promotion (R4-REL-004):** `candidate.py provenance` writes the build machine's record
  right after `build_bundle.sh`. `candidate.py promote-check` answers PROMOTE only when every identity
  field and the typed SHA-256 agree; anything else is REFUSED, naming each field.
- **Authorization dry run (R4-REL-003):** `candidate.py authorize` prints, and runs nothing:
  - the environment, workspace, region, run and expiry, shape and estimate;
  - the candidate identity and the IAM policies;
  - the approvals needed and the exact commands.

  It refuses on any silent input or identity disagreement.

## 3. Configuration and environment isolation (R4-REL-006 to R4-REL-010)

- **Account, region, environment (R4-REL-006):** `candidate.py gate` reads `aws sts get-caller-identity`
  JSON (the owner runs it). It compares the account **by SHA-256** with the allowed hash the owner
  supplies, so no account ID is stored or printed. It requires us-east-1, an environment of
  `staging|production`, a workspace matching the environment, and a user or role principal. FAIL means
  "prepare no live command".
- **Workspace separation (R4-REL-007):**
  - the Terraform precondition (mocked tests, both directions);
  - `candidate.py gate --workspace` (synthetic identities: 2 valid PASS, 2 crossed FAIL, wrong region
    FAIL, other account FAIL);
  - `plan_check.py` STOPs when a plan's recorded environment differs from `--env`.
- **Effective variables (R4-REL-008):** `candidate.py vars --tfvars F` gives every variable, its value
  and its source (default, the environment's local default, `-var-file`, an auto-loaded file, a `TF_VAR_`
  variable). Account IDs, ARNs and keys are redacted.
- **No silent production values in a staging run (R4-REL-009):**
  - `TF_VAR_environment=production` in the shell, or an auto-loaded `terraform.tfvars`, is refused by
    `vars` and `authorize` (exit 1, naming the variable);
  - an unknown `TF_VAR_` is refused;
  - the null defaults resolve by the environment actually chosen.
- **Preflight (R4-REL-010):** it rejects a missing `expires_at`, a missing or malformed `run_id`, and a
  non-RFC 3339 expiry (new tests).

## 4. IAM review (R4-REL-011 to R4-REL-015)

- **Baseline (R4-REL-011):** `make_policies.py` regenerates both sets byte-identical to the merged
  `iam/out` and `iam/out-production`. Every change against the reviewed demo policies is in
  `CHANGES.txt`:
  - **6 expansions,** all scoped to the stack: the encrypted, tagged data volume (create, attach, detach
    and, in staging only, delete); `backups/` read and write; `/flh/<env>` parameters; `kms:Decrypt`
    only via SSM; bucket lifecycle, versioning and tagging puts; the required `ExpiresAt` and `Run` tags
    on RunInstances.
  - **11 reductions:** no EIP or inbound rule; production withholds every delete of data or settings.
- **Matrix (R4-REL-012):** `review_permissions.py --matrix` gives, per role (deployer, operator, host,
  verifier) and service, the number of actions and the resource types.
- **Wildcards (R4-REL-013):** every `*` or account-wide resource must be in `BROAD_OK`, with its reason.
  A conditioned entry must keep its condition. The fixture `tests/fixtures/iam-unexpected-wildcard-operate.json`
  (S3ReadBackups widened to `*`) is refused.
- **Backups and the verifier (R4-REL-014):** `review_permissions.py --simulate s3:GetObject
  arn:aws:s3:::flh-stg-…/backups/…` gives `verify: Deny` (explicit), host `Allow`, operator `Allow`,
  deployer implicit-deny. The same holds in production.
- **Read-only grants the owner reviews separately (R4-REL-015, A1):** the verify policy reveals account
  metadata beyond this stack:
  - every instance, volume, address, image and network via `ec2:Describe*` on `*`;
  - every bucket name (`s3:ListAllMyBuckets`);
  - every tagged resource (`tag:GetResources`);
  - CloudWatch metrics and alarms, Service Quotas, list prices;
  - parameter **names** (`ssm:DescribeParameters`; values denied);
  - the `flh-*` budgets.

  It reads no backup, parameter value or object other than `releases/*.sha256`. Whether that account-wide
  metadata is acceptable for the `FLHStagingRelease` permission set is the owner's decision.

## 5. Terraform gates (R4-REL-016 to R4-REL-020)

- **Mocked suite (R4-REL-016):** Terraform 1.15.9 with hashicorp/aws 6.69.1 from the committed demo lock;
  `fmt -check` 0, `validate` OK, staging 4/4 (default workspace), production 3/3 (workspace `production`).
  It runs in a scratch copy, never in the repository.
- **Data volume across an instance replacement (R4-REL-017, R4-REL-018):** `plan_check.py` requires the
  attachment to keep its `volume_id` and `device_name`.
  - `plan-update-replace-instance-keeps-data.json` is SAFE: "re-attaches the same data volume".
  - `plan-unsafe-attachment-other-volume.json` and `plan-unsafe-attachment-edit.json` (an in-place edit,
    another device) STOP.
- **Out-of-scope production resources (R4-REL-019):** `plan-staging-unsafe-production-resource.json` (a
  production-tagged data volume in a staging plan) STOPs on Component, Environment and the name prefix.
- **Change summary (R4-REL-020):** `plan_review.py summary` gives changes by service and blast radius
  (data-loss, access, service, data, network). Nothing is applied.

## 6. Cost and lifecycle (R4-REL-021 to R4-REL-025)

`staging/cost_sheet.json` (as of 2026-11-20; list prices, **not fetched**) and `tools/lifecycle.py`:

| Scenario | compute | disk | snapshots | storage | IPv4 | logs | total |
| --- | --- | --- | --- | --- | --- | --- | --- |
| staging pass (4 h, destroyed the same day) | 0.08 | 0.01 | 0 | 0.00 | 0.02 | 0 | **$0.12** |
| staging not destroyed for 7 days | 0.08 | 0.15 | 0 | 0.00 | 0.02 | 0 | **$0.25** |
| production month | 15.18 | 2.88 | 0 | 0.09 | 3.65 | 0.20 | **$22.00** |
| production peak month | 30.37 | 5.28 | 1.00 | 0.42 | 3.65 | 0.73 | **$41.45** |

- **After shutdown (R4-REL-023):** the data volume and the bucket objects keep billing in both
  environments, and so does the root volume in production (it stops, never terminates). Compute and the
  auto-assigned IPv4 end.
- **Teardown rehearsal (R4-REL-024):** the synthetic inventory shows the expiry, the power-off and
  `terraform destroy`. A **hand-made snapshot** is the billable residual that destroy does not remove.
- **Residual check (R4-REL-025):** `lifecycle.py verify-commands` prints the read-only CLI calls (verify
  profile) into a directory. `lifecycle.py residual DIR` gives PASS/RESIDUAL per check with its evidence
  fields; synthetic clean PASS, dirty FAIL. The real run is the owner's.

## 7. Deployment verification, restore and rollback (R4-REL-031 to R4-REL-045)

### 7.1 The binary-only rollback window (R4-REL-043)

A binary rollback (`flh-staging-bundle rollback [--to …]`) is safe only while the database ledger is no
larger than the target bundle's (`MANIFEST.migrations.count`).
- **The window ends** at the first start of a release that adds a migration (the ledger grows).
- **Candidate `35da542d0dd4` to rollback `57ec7085dc61`:** both are at 21, so the window stays open
  indefinitely for this pair.
- **After a migration:** the tool refuses with its reason ("the database has 22 migrations but … knows
  only 21"). Recovery is a **database** rollback first (restore the pre-install backup named in
  `deploy.log`, losing writes made after it), then the binary rollback.
- **The operator's signal:** a candidate MANIFEST whose migration count exceeds the running ledger. That
  is the moment to take, and keep, the pre-install backup.

### 7.2 Minimum staging evidence for handover (R4-REL-035)

One COMPLETE run in `evidence_index.py` with every gate PASS, plus the owner's real-host rows:

| Evidence | Stand-in (have) | Needs the real host (owner) |
| --- | --- | --- |
| Identity (image, labels, server, served page, readiness) | yes | yes, on AL2023 |
| `/readyz` reports a read-only database | yes | EBS permissions after restore |
| Restore + Workbooks inventory parity | yes | S3 transfer and EBS times |
| Binary and database rollback; ledger refusal | yes | — |
| Reboot | container crash and restart only | **a real instance reboot** (Docker enabled at boot, `restart: unless-stopped`) |
| Power-off timer and terminate | — | **yes** |
| IMDSv2, SSM session and port forward, S3 TLS-only, IAM AccessDenied | — | **yes** |
| Residual check after destroy | synthetic | **yes** (`lifecycle.py verify-commands`, then `residual`) |

## 8. Cutover (R4-REL-046 to R4-REL-050)

### 8.1 Timed checklist (R4-REL-046)

Stand-in times are measured; S3 and EBS times are the owner's to measure. The stop-at limits are
proposals the owner confirms at P4.

| Phase | Steps (CUTOVER_DRY_RUN.md) | Stand-in | Stop at |
| --- | --- | --- | --- |
| Freeze | 2a export, 2 stop (T0), 2b settings moved aside, 2c DUMP/COUNTS | seconds | any NAS write after T0 means a new boundary |
| Transfer | 3 backup + sums, 3b inventory, 4 tar to S3 to host, verified | backup 2.5 s, transfer < 1 s (local) | sums fail twice |
| Verify | 5 restore, 5b inventory + export + import-preview, 6 smoke | restore to ready ~2 s; inventory equal | any mismatch: DO-NOT-SWITCH |
| Switch decision | 7 access to AWS (T1), 8 first write | freeze T1 − T0 measured 7 s (R3) | freeze over 30 min: abort |
| Watch | `/readyz`, identity, `cutover_check.py check` | — | `/readyz` not 200 for 5 min, or identity mismatch: ROLLBACK-A/B |

### 8.2 Human decision points (R4-REL-049)

- **Before T0:** the cutover window, the decider and the abort limit (P4); the rollback window (for
  example 14 days); which providers are enabled after the move (A7).
- **At T1:** the switch itself, i.e. where the browser goes (an SSM port forward; no DNS, A10).
- **After T1:** ROLLBACK-A or B, and on DIVERGED **which side's data wins**. The tool never chooses.
- **Production data:** the real data move (A9), retention, and when the NAS copy may be deleted.

## 9. Runtime handoff (R4-REL-051 to R4-REL-055)

- **The merged contract (R4-REL-051):** `tools/extraction/SERVICE.md` (`flh_extraction_service_v1`).
  The Extraction lane's R4 note adds:
  - flags only, no environment;
  - read-only, 256 MiB, no swap, 64 processes, no capabilities;
  - pin the **deployment_id** (`flh-extraction-rules@e978b6c2bdb6/…` on its R4 branch;
    `@b0bd175f5d97/…` on `main`);
  - nothing retries automatically.
- **Offline Compose check (R4-REL-052, R4-REL-053):** `staging/runtime/extraction.override.yaml`, opt-in
  (A11), is checked by `tools/runtime_check.py` (`docker compose config` only). It confirms:
  - no published port; the app's network only;
  - read-only, user 10002, no capabilities, 256 MiB, no swap, 64 processes, a `/readyz` health check;
  - the deployment_id recorded as a label;
  - no environment passed;
  - the app service byte-identical with and without the override;
  - a missing image or deployment_id fails visibly.

  Recorded difference (accepted by Extraction): `restart: unless-stopped` here, `--restart no` in their
  rehearsal.
- **Capacity (R4-REL-054, stand-in):**
  - extraction ready in 0.95 s, 14.9 MiB resident, cgroup peak 22.2 MiB (cap 256 MiB);
  - the app 9.8 MiB resident, peak 16.5 MiB on the synthetic fixture.

  A t3.small (2 GiB) carries both with a wide margin. Only the speech sidecar (about 1.5 GiB, A11)
  needs a t3.medium, plus the IAM shape change. The real database size, and so SQLite's page cache, is
  unknown.

### 9.1 Prerequisites for an owner-run staging pass (R4-REL-055)

All local prerequisites are verified:
- the pinned candidate (PROMOTE);
- the rollback bundle (VERIFIED);
- preflight READY;
- the mocked Terraform tests;
- the IAM review and `render_policies.py`;
- the plan check fixtures;
- the cost sheet and lifecycle;
- the stand-in rehearsal.

Still needed from the owner: A2 (budget, runtime window, account confirmation, synthetic scope), the
allowed-account SHA-256 for `candidate.py gate`, A3 (the IAM policies created by an administrator), the
reviewed AMI ID, the Compose plugin SHA-256, and A1 (the verify policy for the read-only profile).

## 10. Integration (R4-REL-066 to R4-REL-070)

- **Demo boundary (R4-REL-066):**
  - the private bundle carries no demo file, and the demo package script names no private path;
  - preflight confirms staging never runs the public demo mode;
  - the demo unit binds 127.0.0.1;
  - public provenance is on main (#167).
- **Workbooks evidence fields (R4-REL-067):** `inventory.json` (`flh_migration_inventory_v1`) maps onto
  the checklist:
  - `verdict` READY, `exit_code` 0, `partial` empty and ledger parity `EQUAL` on both sides;
  - equal `logical_digest` and `rows_by_table`;
  - `source_unchanged` true.

  Sample: run 2, all match, 53 tables.
- **Staging after the production defaults (R4-REL-068):** unchanged: t3.small, 4 h, 8 GiB, 10.85.0.0/24,
  `flh-stg-host-boundary` (`candidate.py vars` on the example tfvars).

### 10.1 Dependency report (R4-REL-069)

| Lane | Decision or input | State | Effect on release |
| --- | --- | --- | --- |
| Extraction | runtime contract, deployment_id pin | agreed (cross-session); `e978b6c2bdb6` on its R4 branch, `b0bd175f5d97` on main | update the override's default pin when its branch merges |
| Extraction | app provider for the extraction service (`EXTRACTION_SERVICE_*`) | proposal, no names wired | none until the owner approves a shared contract |
| Extraction / owner | speech sidecar (A11) | open | wrapper `local`, Compose `BASE_URL`/`TIMEOUT` forwarding and IAM t3.medium change together |
| Extraction | restart policy of the sidecar | difference accepted (`unless-stopped` vs `no`) | owner confirms |
| Workbooks | backup contract (46 tables, `max(rowid)`) | agreed (R3) | `cutover_check.py` measures every table |
| Workbooks | `verify_restore.sh`, `inventory.py --expect` | **sealed** in workbooks-r4 handoff-075 (`SHA256SUMS` `c93eb479…00862`, 85 files verify); no path overlaps this branch | applied to a scratch export of `58c0ba8b`: `test_inventory.py` 11/11; `verify_restore.sh` VERIFIED on the synthetic fixture with main's and with this branch's `backup_tool.py` |
| Workbooks | `backup_tool.py pack` traceback on a missing directory | **fixed in this branch** (refusal + test) | its sequence already creates the directory |
| Demo | `/` ETag patch (`0002-page-etag.patch`, shared `workbench.go`) | owner decision | until then, the rollback browser step in RUNBOOK §8 |
| Demo | the clean rollback package `pkg-ba2ff1b23210` | recorded | a public rollback, not part of the private release |

### 10.2 After these branches merge (R4-REL-070)

From a clean checkout of the merged `main`, in order. Each step must pass before the next:

```bash
S=deploy/aws/private-staging/staging
python3 -I -B $S/tests/test_staging_tools.py                      # all OK
python3 -I -B -m unittest discover -s scripts/release -p 'test_*.py'
python3 -B scripts/ci/python_suites.py --hermetic                  # every suite PASS, 0 trapped calls
python3 -I -B $S/tools/runtime_check.py                            # RUNTIME CHECK PASSED
python3 -I -B $S/iam/review_permissions.py --env staging && python3 -I -B $S/iam/review_permissions.py --env production
# mocked Terraform in a scratch copy with the demo lock (RUNBOOK §3.1): staging 4/4, production 3/3 (workspace production)
bash $S/build_bundle.sh --git . "$(git rev-parse HEAD)" "$OUT" --repro
python3 -I -B $S/tools/candidate.py provenance "$OUT/<flh-staging-TREE12>.tar" --commit "$(git rev-parse HEAD)" --out "$OUT/provenance.json"
python3 -I -B $S/tools/candidate.py promote-check "$OUT/<flh-staging-TREE12>.tar" --provenance "$OUT/provenance.json"
python3 -I -B $S/rehearsal/r4_cutover_edges.py "$WORK/edges"       # 4 PASS
python3 -I -B $S/rehearsal/r4_release_rehearsal.py --candidate … --rollback … --broken … --ahead … \
    --fixture … --inventory scripts/validation/migration/inventory.py "$WORK/run"   # 24 PASS
python3 -I -B $S/tools/evidence_index.py "$WORK/run" --out "$WORK/INDEX.md" --approve <run_id>   # APPROVABLE
```

Then each lane's own post-merge check: Extraction `runtime_rehearsal.py`, Workbooks
`bash scripts/validation/migration/verify_restore.sh BACKUP_DIR WORK` (from the sealed handoff-075 until it is on `main`; VERIFIED on the synthetic fixture), Demo `check_package.sh`.

## 11. Owner package (R4-REL-071 to R4-REL-074)

### 11.1 Go or hold (R4-REL-071)

- **GO for the first owner-run synthetic staging pass** once A1, A2 and A3 are given.

  Checks performed for candidate `flh-staging-35da542d0dd4` (58c0ba8b), all on this machine:
  - PROMOTE against its provenance, and a content-identical independent rebuild;
  - preflight READY;
  - mocked Terraform 4/4 + 3/3;
  - IAM review in both environments, no unexpected wildcard, the verifier denied backups;
  - the plan stop-rule fixtures;
  - runtime_check;
  - a final stand-in rehearsal of 24/24 including both rollbacks and the ledger refusal (APPROVABLE);
  - cutover edges 4/4;
  - staging 99 tests, release 127, every hermetic suite PASS.
- **HOLD for production** (A7–A9): the staging pass first, then the production design, budget and the
  real data move.
- **HOLD for the speech sidecar** (A11).

### 11.2 First authorized synthetic staging pass (R4-REL-072)

Run from the repository root of the release commit. **Stop at the first refusal.**

```bash
S=deploy/aws/private-staging/staging; OUT=~/flh-r4-out; mkdir -p "$OUT"
aws sts get-caller-identity --profile <operator-profile> --output json > "$OUT/caller.json"           # owner
python3 -I $S/tools/candidate.py gate --caller-identity "$OUT/caller.json" --allowed-account-sha256 <sha256-of-account> \
    --region us-east-1 --env staging --workspace default                                                # GATE PASSED
python3 -I $S/tools/candidate.py promote-check "$OUT/flh-staging-35da542d0dd4.tar" --provenance "$OUT/provenance.json" \
    --sha256 d9db57a6edb5dfcc22e3ffc63a1fa2913ca7ad867917588919429ca9f8d88f70                            # PROMOTE
python3 -I $S/tools/candidate.py authorize --tfvars $S/terraform/terraform.tfvars --bundle "$OUT/flh-staging-35da542d0dd4.tar" \
    --provenance "$OUT/provenance.json"                                                                  # READY (dry run)
python3 -I $S/iam/render_policies.py --account <account-id> --ami <ami-id> --out ~/flh-stg-iam            # administrator: A3
# RUNBOOK §3 (plan, plan_check --env staging, checklist, freshness, apply), §4 parameters, §5 install, §6 restore, §7 checks
```

### 11.3 Teardown and recovery, with stopping conditions (R4-REL-073)

```bash
# Recovery: a bad release (window open: ledger <= the target's)
flh-staging-bundle rollback --to flh-staging-57ec7085dc61            # stop if REFUSED (ledger): database rollback first
# Recovery: a bad database: restore the pre-install backup named in deploy.log
stg restore "$ROOT/data/app.backups/<flh-TIMESTAMP>"                 # stop if the sums fail: the backup is damaged
# Teardown (same day; synthetic data only)
cd $S/terraform && terraform plan -destroy -out stg-destroy.tfplan && terraform show -json stg-destroy.tfplan > stg-destroy.plan.json
python3 -I ../tools/plan_check.py --env staging --mode destroy stg-destroy.plan.json   # stop on STOP
terraform apply stg-destroy.tfplan
python3 -I ../tools/lifecycle.py verify-commands --env staging --out ~/flh-stg-residual   # run the printed read-only commands
python3 -I ../tools/lifecycle.py residual ~/flh-stg-residual --env staging            # stop only when RESIDUAL CHECK PASSED
```

**Stopping conditions:**
- any `STOP`, `REFUSED`, `GATE FAILED`, `NOT READY` or `RESIDUAL`;
- an `IDENTITY MISMATCH` after an install or rollback;
- a cost alert over the A2 budget.

**Production is never torn down this way:** `plan_check.py --env production --mode destroy` always STOPs.

### 11.4 Costs and times the owner confirms (R4-REL-074)

- **Prices:** every unit price in `cost_sheet.json` (list prices as of 2026-11-20, not fetched): t3.small,
  gp3, snapshots, S3, IPv4, CloudWatch.
- **Estimates:** a staging pass of about $0.12; about $22 a month for production.
- **Not measured:** EBS and S3 transfer and restore times, the AL2023 cloud-init time, and the
  power-off-to-terminate time.
- **Unknown:** the account's vCPU and EIP quotas and the t3.small offering in the zone (the verify policy
  allows reading them, A1).
- **Production:** the real database size (it drives the disk, backup and restore times) and the backup
  retention (35 days proposed).

## 12. Decision log (reversible choices made in R4)

| # | Decision | Why | How to reverse |
| --- | --- | --- | --- |
| D1 | No AWS command in R4, not even read-only | the repository forbids agents AWS commands, and R4 grants none (R3's read-only check was a separate authorization) | the owner runs `candidate.py gate` and `lifecycle.py verify-commands` |
| D2 | One gate tool `staging/tools/candidate.py` (identity, provenance, promote-check, gate, vars, authorize) | one place for candidate identity; no logic duplicated across scripts | delete the file; nothing else imports it |
| D3 | The account allow-list is a **SHA-256** of the account ID supplied by the owner | the gate never stores or prints an account ID | pass the plain ID in a private wrapper (not recommended) |
| D4 | The nominated rollback is the R3 release `flh-staging-57ec7085dc61` (b96675f8), built by the R3 builder | it is the last verified release, and the new host tool verifies it | nominate another installed bundle with `rollback --to` |
| D5 | New `cost_sheet.json` and `lifecycle.py`; `cost_assumptions.json` and `plan_review.py cost` unchanged | categories and scenarios without changing a reviewed tool | remove the two new files |
| D6 | The data-volume attachment must keep `volume_id` and `device_name` (`plan_check.py`) | an instance replacement must re-attach the same data | delete the rule block; its fixtures show the effect |
| D7 | Wildcard resources are enforced through `BROAD_OK` | a widened statement fails instead of being listed | move a statement into `BROAD_OK` with its reason |
| D8 | The host tool accepts linux/amd64 and linux/arm64 and requires the host's platform | the t4g option without a silent mismatch; this machine builds amd64 only | `FLH_STAGING_HOST_ARCH` checks another host's bundle |
| D9 | `identity` also compares the page served on `/` with the image's `index.html` | ties a response to the verified bundle digest | drop the served-page facts; the other checks stand |
| D10 | Extraction sidecar override: opt-in, deployment_id pin (a label), no image-digest requirement, `restart: unless-stopped` | a loaded image has no registry digest; it returns after a reboot (the Extraction lane accepted the difference) | `--restart no` in the override; nothing else uses it |
| D11 | Evidence: `results.jsonl` + `summary.json` per run, `evidence_index.py` refuses mixed or partial runs | an approval names one complete run | read `results.tsv` directly; the index only adds checks |
| D12 | Stand-in defaults: `standin_lib` hosts, free loopback ports, the sealed synthetic fixture `nas-fixture-20261118072610` (ledger 21) | same isolation as R3; the daily instance is fingerprinted before and after | another fixture via `--fixture` |
