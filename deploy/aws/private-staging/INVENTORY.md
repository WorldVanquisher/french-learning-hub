# Private staging: resource and ownership inventory, expected changes, stop rule

The machine-readable copy is `staging/expected_resources.json`. The plan
checker `staging/tools/plan_check.py` enforces it offline on the plan JSON the
owner produces (RUNBOOK.md §3). Nothing here was planned or applied by an
agent: AGENTS.md forbids agents any AWS or Terraform command.

## 1. Terraform-managed (root `staging/terraform`, its own local state)

| # | Address | Owner | Holds data | First apply | Re-plan, nothing changed | Teardown |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `aws_vpc.stg` | staging root | no | create | no-op | delete |
| 2 | `aws_internet_gateway.stg` | staging root | no | create | no-op | delete |
| 3 | `aws_subnet.public` | staging root | no | create | no-op | delete |
| 4 | `aws_route_table.public` | staging root | no | create | no-op | delete |
| 5 | `aws_route_table_association.public` | staging root | no | create | no-op | delete |
| 6 | `aws_vpc_endpoint.s3` | staging root | no | create | no-op | delete |
| 7 | `aws_security_group.host` | staging root (**no ingress**) | no | create | no-op | delete |
| 8 | `aws_vpc_security_group_egress_rule.https` | staging root (TCP 443 out) | no | create | no-op | delete |
| 9 | `aws_s3_bucket.staging` | staging root; **objects** under `releases/` and `backups/` are the operator's | **yes** | create | no-op | delete (`force_destroy`, synthetic data only) |
| 10 | `aws_s3_bucket_public_access_block.staging` | staging root | no | create | no-op | delete |
| 11 | `aws_s3_bucket_ownership_controls.staging` | staging root | no | create | no-op | delete |
| 12 | `aws_s3_bucket_server_side_encryption_configuration.staging` | staging root | no | create | no-op | delete |
| 13 | `aws_s3_bucket_versioning.staging` | staging root | no | create | no-op | delete |
| 14 | `aws_s3_bucket_lifecycle_configuration.staging` | staging root | no | create | no-op | delete |
| 15 | `aws_s3_bucket_policy.staging` | staging root | no | create | no-op | delete |
| 16 | `aws_iam_role.host` | staging root, under the administrator's `flh-stg-host-boundary` | no | create | no-op | delete |
| 17 | `aws_iam_role_policy.host` | staging root | no | create | no-op | delete |
| 18 | `aws_iam_instance_profile.host` | staging root | no | create | no-op | delete |
| 19 | `aws_instance.host` | staging root; runtime state on it belongs to `flh-staging-bundle` | no (root disk is disposable) | create | no-op | delete |
| 20 | `aws_ebs_volume.data` | staging root; **contents** (`FLH_DATA_DIR`, backups) are the operator's | **yes** | create | no-op | delete |
| 21 | `aws_volume_attachment.data` | staging root | no | create | no-op | delete |

Data sources read during a plan (no change): `aws_ec2_instance_type.selected`,
`aws_iam_policy.host_boundary` (fails until the administrator has created the
boundary), `aws_caller_identity.current`, and three `aws_iam_policy_document`s.

**Expected plans:**
- **First apply:** 21 to add, 0 to change, 0 to destroy (`--mode create`).
- **Re-plan before teardown:** 0/0/0 (`--mode update`).
- **Destroy:** 0 to add, 0 to change, 21 to destroy (`--mode destroy`).

## 2. Outside Terraform

| What | Owner | Created by | Removed by |
| --- | --- | --- | --- |
| IAM policies `flh-stg-host-boundary`, `flh-stg-deploy`, `flh-stg-deploy-ec2`, `flh-stg-operate` (filled from `staging/iam/out/` by `render_policies.py`, outside Git) | IAM administrator | Console, RUNBOOK §2 | administrator, after the run (RUNBOOK §9) |
| SSM parameters `/flh/staging/*` (17 `String` values; no secret, every provider disabled) | operator | `aws ssm put-parameter`, RUNBOOK §4 | `aws ssm delete-parameters`, RUNBOOK §9 |
| S3 objects `releases/flh-staging-<tree12>.tar` (+ `.sha256`), `backups/<backup>.tar` (+ `.sha256`) | operator | `aws s3 cp`, RUNBOOK §5–6 | `terraform destroy` (`force_destroy`), and the 14-day lifecycle |
| Host files: `/srv/flh-staging/{bundles,current,previous,deploy.log,staging.env,transfer}` | `flh-staging-bundle` and the operator (as `ec2-user`) | RUNBOOK §5–6 | instance termination |
| Host data: `/srv/flh-staging/data/{app,app.backups}` on the data volume | `flh-daily.sh` | RUNBOOK §6–7 | `terraform destroy` (volume deleted) |
| Operator machine: `terraform.tfvars`, `*.tfstate`, `stg.tfplan`, `stg.plan.json`, filled IAM files | operator | RUNBOOK §2–3 | after teardown; ignored by Git (`.gitignore` here) |
| **The public demo stack** (`deploy/aws/terraform`, its own state, `flh-demo-*`) | demo operator | FLH-087 | **never touched by this root**. Any demo address in a staging plan is unexpected (STOP) |

## 3. What changes a re-plan, and what it does

| Change | Plan shows | Consequence |
| --- | --- | --- |
| Edit `cloud-config.yaml.tftpl` or anything under `staging/host/` (user data) | **replace** `aws_instance.host` and `aws_volume_attachment.data` (`user_data_replace_on_change`) | New root disk. The data volume is detached and reattached, and its contents are kept. Bundles, `current` and `staging.env` on the root disk are lost: reinstall (RUNBOOK §5). Allowed only with `--allow-replace aws_instance.host --allow-replace aws_volume_attachment.data`, after a backup |
| `expires_at` or `run_id` | update in place (tags) on every tagged resource | none |
| `instance_type` | update in place (stop/start) | outside the IAM shape (t3.small): AccessDenied |
| `vpc_cidr`, `aws_region` | replace of the network, bucket, volume… | **STOP**: destroy and start over instead |
| `data_volume_size_gib` | update in place (grow only) | the filesystem must be grown on the host (`xfs_growfs`) |

## 4. Stop rule

Run `staging/tools/plan_check.py` on every plan before `terraform apply`.
**Do not apply** when it prints `STOP`:
- **Unexpected addresses:** anything not in §1, including any demo resource.
- **Public paths:** an inbound rule, ingress on the security group, an
  Elastic IP, a load balancer, a DNS record, CloudFront, an API gateway, or
  any public-access-block setting off.
- **Deletes and replaces outside teardown:**
  - any `delete` in an update;
  - a replace of the data volume or the bucket (never allowed);
  - a replace of the instance or the attachment without the explicit
    `--allow-replace`.
- **Weakened settings:** IMDSv1, an unencrypted volume, a shutdown behaviour
  other than terminate, egress other than TCP 443, missing
  `Project`/`Component`/`ExpiresAt`/`Run`/`ManagedBy` tags, another provider.

Fix the cause, plan again, check again. The fixed fixtures in
`staging/tests/fixtures/` show one safe and one unsafe example of each rule.

## 5. Production instance of this root (R3; nothing applied)

The same 21 addresses serve production when `environment = "production"`
(`docs/plans/FLH-R3-aws-migration.md` §5). Owner decisions A7/A8 come first.

| Setting | Staging | Production |
| --- | --- | --- |
| Terraform workspace | any but `production` (the runbook uses `default`) | `production` only (precondition on `aws_vpc.stg`) |
| Variables | `terraform.tfvars` | `-var-file=production.tfvars`; no `terraform.tfvars` in the root (preflight FAILs: it would be merged in) |
| Names and tags | `flh-stg-*`, `Component=workbench-staging`, `Environment=staging` | `flh-prd-*`, `Component=workbench-production`, `Environment=production` |
| Network | 10.85.0.0/24 | 10.86.0.0/24 |
| Parameters | `/flh/staging/*` | `/flh/production/*` |
| Data volume | 8 GiB | 20 GiB (grow-only) |
| Expiry | `ExpiresAt` time, power-off timer enabled, shutdown terminates | `ExpiresAt=never`, timer installed disabled, shutdown **stops** |
| Termination protection | off | **on** (`disable_api_termination`) |
| Bucket on destroy | emptied (`force_destroy`) | **kept** while objects remain |
| S3 lifecycle | every object 14 days | `backups/` `backup_retention_days` (35) + 7 days as old versions; `releases/` kept, old versions 30 days |
| IAM | `staging/iam/out/flh-stg-*` | `staging/iam/out-production/flh-prd-*`: **no** delete of the data volume, bucket, objects or parameters (administrator-only) |
| Plan check | `plan_check.py --env staging` (default) | `plan_check.py --env production`: also STOPs on any destroy and on a plan made for the other environment |

Both environments get a read-only verification policy (`<prefix>-verify-readonly`):
- it allows only describe, list, get and view;
- it explicitly denies parameter values, KMS decrypt and `backups/*` objects.

That is the policy to grant the release lane's read-only profile (plan §9).
