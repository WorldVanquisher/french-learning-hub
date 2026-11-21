# deploy/aws/private-staging: private workbench staging (owner-run)

An isolated AWS staging target for the **private workbench** (the full
service, synthetic data, every provider disabled), separate from the public
demo in `deploy/aws/terraform`. Nothing here has been applied. Agents may run
no AWS or Terraform command (AGENTS.md).

| Path | Purpose |
| --- | --- |
| [RUNBOOK.md](RUNBOOK.md) | **Start here**: the owner's copy-paste runbook (inputs, build, IAM, plan, apply, install, restore, checks, rollback, teardown, cost, pending live checks) |
| [INVENTORY.md](INVENTORY.md) | resources, owners, expected plan per mode, stop rule |
| [AWS_STAGING_PLAN.md](AWS_STAGING_PLAN.md) | design: NAS dependencies → AWS, storage, IAM derivation, lifecycle, cost |
| [STANDIN-REHEARSAL.md](STANDIN-REHEARSAL.md) | what was rehearsed locally (stand-in for EC2/S3/SSM) and its results |
| [CUTOVER_DRY_RUN.md](CUTOVER_DRY_RUN.md) | NAS → AWS cutover and the rollback that keeps writes accepted on AWS (dry runs) |
| [DEMO_REFRESH_STAGING.md](DEMO_REFRESH_STAGING.md) | the demo-refresh lane's **public demo** staging record (a different target) |
| `staging/build_bundle.sh` | builds `flh-staging-<tree12>` for one pinned commit (`--git . <rev>`) |
| `staging/bundle_identity.py` | Git tree ID without Git; writes `MANIFEST.json` |
| `staging/host/flh-staging-bundle` | host tool: verify, install, rollback, status, identity |
| `staging/host/flh-staging-env` | renders the settings file from SSM parameters (values never printed) |
| `staging/host/flh-staging-expire.service` | bounded runtime (power-off → terminate) |
| `staging/terraform/` | the staging root (21 resources; separate state). R3: the same root also renders **production** with `environment = "production"` in the workspace `production` (INVENTORY.md §5); `tests/*.tftest.hcl` check both with a mocked provider |
| `staging/iam/` | `make_policies.py` (derives the templates from `deploy/aws/iam`; `--env production` writes `out-production/`), `out/` (templates + `CHANGES.txt`, plus the read-only `flh-stg-verify-readonly`), `render_policies.py` (fills account and AMI outside the repository), `review_permissions.py` (offline: every action the Terraform, the runbook and the host need is allowed; broad and unused grants) |
| `staging/expected_resources.json`, `staging/tools/plan_check.py` | offline plan check (stop rule) |
| `staging/tools/candidate.py` (R4) | release-candidate gates: `identity`, `provenance` + `promote-check` (bundle vs build record), `gate` (account by SHA-256, region, environment, workspace), `vars` (effective variables and sources; refuses silent `TF_VAR_`/auto-loaded inputs), `authorize` (dry run of the approval material) |
| `staging/cost_sheet.json`, `staging/tools/lifecycle.py` (R4) | dated cost sheet by category and scenario; billable-after-shutdown; teardown rehearsal on a synthetic inventory; read-only residual commands and checklist |
| `staging/tools/evidence_index.py` (R4) | one offline index over stand-in runs; partial runs named; redaction; an approval names exactly one complete run |
| `staging/runtime/extraction.override.yaml`, `staging/tools/runtime_check.py` (R4) | opt-in private extraction sidecar (A11) and its offline `docker compose config` check |
| `staging/rehearsal/r4_release_rehearsal.py`, `r4_cutover_edges.py` (R4) | candidate bootstrap, failed boot, restart, served-page identity, writability, restore + Workbooks inventory, binary and database rollback, ledger refusal, teardown; stale snapshot / DIVERGED / ROLLBACK-A verdicts |
| `staging/tools/preflight.py` | offline preflight: Terraform files, user data size, tfvars, filled policies, bundle, tools |
| `staging/rehearsal/` | local stand-in rehearsals (Docker on loopback; never the daily instance): `make_fixture_backup.py` (synthetic NAS-shaped backup), `bundle_rehearsal.py` (verify, install, rollback, failed installs), `standin_rehearsal.py` (restore, health, persistence, second target, failures), `cutover_dry_run.py` (endpoint checks, cutover, rollback); shared helpers in `standin_lib.py` |
| `staging/tools/daytime.py` (aws-prep) | owner daytime slot, offline: `template`/`check`/`page` (go or hold), `checklist`, `roles`, `limits` (enforced vs alert-only), `cost` (dated rates, demo apart), `residual`, `bill-template`/`bill`, `quotas`, `model-record` (render vs readiness) |
| `staging/tools/portal_check.py` + `staging/portal/routing_plan.json` (aws-prep) | proposed portal / demo / pilot host routing; `validate` and a 22-request synthetic `simulate` mirroring the Go demo allowlist |
| `staging/tools/pilot_check.py` + `staging/pilot/isolation_case_v1.json` (aws-prep) | two-account invite-only pilot acceptance case; `probe` sends GET only to a loopback server and is READY only if every private route answers 401 |
| `staging/tools/state_guard.py` (aws-prep) | refuses Terraform state, plans, filled-in tfvars, databases, keys and env files (`scan`, `--stdin`, `ignore-check`) |
| `staging/rehearsal/mock_model_smoke.py` + `staging/runtime/model-runtime.example.json` (aws-prep) | local mock model runtime: boot vs ready, known-good / unknown-model requests, limits, identity logs without input text, app+model rollback, cleanup |
| `staging/tests/` | offline tests and the fixed plan fixtures |

Local checks (no AWS, no Terraform, no Docker):
`python3 -I -B deploy/aws/private-staging/staging/tests/test_staging_tools.py`
and `python3 -I deploy/aws/private-staging/staging/tools/preflight.py`.
Terraform without AWS (a mocked provider; R3): in `staging/terraform`, `terraform
init -backend=false`, then `terraform test -filter=tests/staging.tftest.hcl`, and in a
workspace named `production`, `terraform test -filter=tests/production.tftest.hcl`.
`.gitignore` here keeps Terraform state, every local `*.tfvars`, plans and plan
JSON, filled IAM policies and bundle files out of Git.
