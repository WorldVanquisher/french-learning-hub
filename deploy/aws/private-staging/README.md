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
| `staging/terraform/` | the staging root (21 resources; separate state) |
| `staging/iam/` | `make_policies.py` (derives the templates from `deploy/aws/iam`), `out/` (templates + `CHANGES.txt`), `render_policies.py` (fills account and AMI outside the repository), `review_permissions.py` (offline: every action the Terraform, the runbook and the host need is allowed; broad and unused grants) |
| `staging/expected_resources.json`, `staging/tools/plan_check.py` | offline plan check (stop rule) |
| `staging/tools/preflight.py` | offline preflight: Terraform files, user data size, tfvars, filled policies, bundle, tools |
| `staging/rehearsal/` | local stand-in rehearsals (Docker on loopback; never the daily instance): `make_fixture_backup.py` (synthetic NAS-shaped backup), `bundle_rehearsal.py` (verify, install, rollback, failed installs), `standin_rehearsal.py` (restore, health, persistence, second target, failures), `cutover_dry_run.py` (endpoint checks, cutover, rollback); shared helpers in `standin_lib.py` |
| `staging/tests/` | offline tests and the fixed plan fixtures |

Local checks (no AWS, no Terraform, no Docker):
`python3 -I -B deploy/aws/private-staging/staging/tests/test_staging_tools.py`
and `python3 -I deploy/aws/private-staging/staging/tools/preflight.py`.
`.gitignore` here keeps Terraform state, `terraform.tfvars`, plans and plan
JSON, filled IAM policies and bundle files out of Git.
