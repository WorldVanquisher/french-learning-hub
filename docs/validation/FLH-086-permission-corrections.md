# FLH-086 — Corrections of the two material permission risks

**Status:** static and native validation only. Nothing has been validated
against AWS.
- **Not done:** no AWS call or mutation, no plan or apply, no Git command, no
  subagent.
- **`flh086.tfplan`:** now **obsolete**. It is kept, not deleted or
  regenerated; the human generates and reviews a replacement.
- **Supersedes:** the risk section of `FLH-086-operator-policy.md`, which is
  historical and unchanged.

## Minimal required changes

**1. Security groups.** The default security group of the new VPC cannot be
scoped safely.
- **Why not:** the AWS reference lists only two conditions for
  `RevokeSecurityGroupIngress`/`Egress` on `security-group`:
  - `aws:ResourceTag`/`ec2:ResourceTag`: the default group is untagged, and
    tagging it into scope is the hijack path being removed;
  - `ec2:Vpc`: the VPC ARN, unknown until apply.

  No static policy can name "the default group of the VPC this apply creates".
  Keeping `aws_default_security_group` therefore forces account-wide
  revocation.
- **Smallest Terraform change:** remove `aws_default_security_group.demo`, so
  the stack has **19** resources.
- **Deploy policy:**
  - the account-wide revoke statement and the
    "tag any security group into scope" statement are deleted;
  - `RevokeSecurityGroupEgress` remains only for **tagged** groups. The
    provider needs it to remove AWS's default allow-all egress from the host
    group it creates, which is tagged at creation.
- **Isolation, stated, not silently weakened:**
  - **Host:** unchanged. Its own group has no ingress and egress TCP 443 only.
  - **Default group of the new VPC:** keeps AWS's defaults (inbound only from
    members of the same group, all outbound), but nothing uses it, because the
    instance names its own group.
  - **Hardening:** stripping its rules becomes an optional one-time
    administrator step (`docs/AWS_DEMO.md` §4), outside Terraform.

**2. Host-role privilege escalation.**
- **New policy:** `deploy/aws/iam/flh-demo-host-boundary-policy.json`, created
  by an administrator as `flh-demo-host-boundary` and not attached to any user.
  It is the host role's ceiling:
  - `ssm:UpdateInstanceInformation` and the four `ssmmessages` channel
    actions;
  - `s3:GetObject` on `arn:aws:s3:::flh-demo-artifacts-*/releases/*`.
- **Terraform:** `data "aws_iam_policy" "host_boundary"`, by name (variable
  `host_role_permissions_boundary_name`, default `flh-demo-host-boundary`), and
  `permissions_boundary` on `aws_iam_role.host`. The plan fails if the boundary
  is missing.
- **Deploy policy:**
  - `iam:CreateRole`, `PutRolePolicy`, `DeleteRolePolicy` and `DeleteRole` on
    `role/flh-demo-host-*` now require `iam:PermissionsBoundary` to equal the
    boundary ARN. A role without it cannot be created, and its inline policy
    cannot be changed.
  - `TagRole`/`UntagRole` stay unconditioned on that name pattern. They do not
    support the key, and tags grant nothing here.
  - **Explicit deny 1:** `iam:PutRolePermissionsBoundary` and
    `iam:DeleteRolePermissionsBoundary` on every role.
  - **Explicit deny 2:** `iam:CreatePolicyVersion`, `DeletePolicyVersion`,
    `SetDefaultPolicyVersion`, `DeletePolicy`, `TagPolicy` and `UntagPolicy` on
    `flh-demo-host-boundary`, `flh-demo-deploy` and `flh-demo-operate`.

  The deploy identity is never granted IAM user-policy or managed-policy
  attachment actions, so it cannot attach new policies to itself or to the
  role.

**Result:** any `flh-demo-host-*` role the deploy identity can create or
modify is capped at the boundary. That holds even with an arbitrary inline
policy or a trust policy naming the user itself. The remaining reachable
privilege through the role is Session Manager instance registration and
release reads.

## Changed files

| File | Change |
|---|---|
| `deploy/aws/terraform/main.tf` | removed `aws_default_security_group.demo` (comment explains why); added `data.aws_iam_policy.host_boundary`; `aws_iam_role.host.permissions_boundary` |
| `deploy/aws/terraform/variables.tf` | `host_role_permissions_boundary_name` (default `flh-demo-host-boundary`) |
| `deploy/aws/iam/flh-demo-host-boundary-policy.json` | new boundary policy |
| `deploy/aws/iam/flh-experiment-demo-deploy-policy.json` | as above. 18 statements, **6,082 characters after substituting a 12-digit account** (limit 6,144, 62 to spare) |
| `deploy/aws/iam/README.md` | boundary first, exact names, obsolete plan, replacement plan, review points, AMI pin note |
| `docs/AWS_DEMO.md` | permission options (the `PowerUserAccess` supplement is withdrawn as an escalation path), 19 resources, boundary prerequisite and review check, obsolete plan, optional default-security-group step, §10 item 7 |
| `scripts/validation/flh084/static_checks.py` | the "default security group stripped" assertion is replaced by "not adopted", plus a boundary assertion |

**Unchanged:**
- `flh-experiment-demo-operate-policy.json`;
- the host templates, `outputs.tf`, `storage.tf`, `versions.tf` and the lock
  file;
- every historical report.

**Local and unstaged:**
- `deploy/aws/terraform/flh086.tfplan.OBSOLETE.txt`, a marker next to the
  plan;
- `flh086.tfplan`, which remains git-ignored.

## Validation

**Static compatibility, offline:**
- **Source:** AWS programmatic Service Authorization Reference, ec2, iam, s3,
  ssm and ssmmessages JSON, downloaded 2026-10-20.
- **Checker (scratch, not committed):** confirms that every action exists, that
  every Resource ARN matches a resource type of an action in its statement, and
  that every condition key is listed for that action or resource type.
- **Results:** all three policy files had **0 errors**. A negative control was
  rejected with 2 errors: `iam:PermissionsBoundary` on `TagRole`, and
  `ec2:VpcID` on `RevokeSecurityGroupEgress`.
- **Facts confirmed from the reference:**
  - `iam:PermissionsBoundary` is listed for `CreateRole`, `PutRolePolicy`,
    `DeleteRolePolicy`, `DeleteRole`, `PutRolePermissionsBoundary` and
    `DeleteRolePermissionsBoundary`, and not for `TagRole`/`UntagRole`;
  - the `ssmmessages` channel actions have no resource types, so they take
    `Resource "*"`. This is necessary, in the boundary as in the role policy;
  - `ssm:UpdateInstanceInformation` supports the `instance` and
    `managed-instance` resource types. It is left on `"*"` in the boundary,
    matching AWS's documented minimal policy; narrowing it is optional.

**Native Terraform:** Terraform 1.16.6, hashicorp/aws 6.69.1.

| Command | Result |
|---|---|
| `terraform fmt -check -diff -recursive` | exit 0 |
| `terraform init -backend=false -lockfile=readonly` | success; the lock file's SHA-256 is unchanged (`b5d180e3…6e652cfb`) |
| `terraform validate -json` | valid, 0 errors, 0 warnings |
| `python3 -B scripts/validation/flh084/static_checks.py` | **225 passed, 0 failed** (final run; now includes the IAM files and README in the secret and account-ID scan) |
| `scripts/validation/flh084/render_cloud_config.sh` (no network) | renders; 15,453 bytes, identical in size to FLH-085. User data is unaffected |

**Not validated:**
- **Real AWS behaviour** of the boundary, the conditions, the denies and the
  provider's tag-on-create calls. That needs the replacement plan and apply.
- **The replacement plan itself**, which the human generates.
- **The boundary lookup:** `data.aws_iam_policy` by name needs `iam:ListPolicies`
  and `iam:GetPolicy` at plan time. `ReadOnlyAccess` is expected to include
  them; this was not verified.

## Remaining risks

**The obsolete plan:**
- **Never apply `flh086.tfplan`.** With `flh-demo-deploy` it would fail at
  `CreateRole`, which has no boundary, after creating the VPC and bucket
  resources: a partial apply.
- With an administrator identity it would succeed without a boundary.

**Remaining scope of the deploy identity:**
- tag-scoped management of resources it created;
- launches of `t4g.micro` instances, with no count or root-size cap; set a
  budget alert;
- `CreateTags` of `Name=flh-demo-root` on any volume (harmless).

**Untested assumptions:**
- the provider sends tags at creation (`TagSpecifications`);
- the account uses the AWS-managed `aws/ebs` key;
- `flh-plan` resolves to the IAM user, not an assumed role;
- the reviewed AMI is still resolved, or is pinned.

**Policy size:** the deploy policy has 62 characters of headroom. Any
addition may require moving a statement to a third policy.

## Human steps

1. Substitute the account ID, then create `flh-demo-host-boundary`,
   `flh-demo-deploy` and `flh-demo-operate`, and attach the latter two
   (`deploy/aws/iam/README.md` §1–§2).
2. Generate the replacement plan and review it: 19 creates, no default
   security group, boundary ARN on the role, AMI.
3. Apply only that plan, then detach `flh-demo-deploy`.
