# FLH-086 follow-up — Operator policies for the approved apply

**Status: UNTESTED against AWS.** This prepares permissions; it changes none.
- **Not done:** no AWS call, no apply, no IAM change, no Git command, no
  subagent.
- **Unchanged:** the reviewed plan, Terraform files and host templates.

**Owner approval:** create and continuously run the reviewed 20-resource plan
(`flh086.tfplan`) in us-east-1, on arm64 `t4g.micro` with an encrypted 8 GiB
gp3 root volume.

## Deliverables

| File | Content |
|---|---|
| `deploy/aws/iam/flh-experiment-demo-deploy-policy.json` | 17 statements, 5,711 characters after account substitution |
| `deploy/aws/iam/flh-experiment-demo-operate-policy.json` | 5 statements, 1,248 characters |
| `deploy/aws/iam/README.md` | account-ID substitution, Console steps to create and attach, the exact apply command, and post-apply detachment |

**Why two files:** combined, the policies are 6,860 characters, over IAM's
6,144-character limit for one managed policy. The split is also the main risk
control: the deploy policy only needs to be attached while applying or
destroying.

**Placeholder:** `__AWS_ACCOUNT_ID__` in 27 places. The README substitutes it
into copies outside the repository.

**Apply command (human-run):**

```sh
cd deploy/aws/terraform
AWS_PROFILE=flh-plan ~/tools/terraform/1.16.6/terraform apply flh086.tfplan
```

## Scope

**EC2 / VPC:**
- **Create statements:** `CreateVpc`; `CreateSubnet`, `CreateRouteTable`,
  `CreateSecurityGroup` and `CreateInternetGateway`; the S3 gateway
  `CreateVpcEndpoint` (with `ec2:VpceServiceName =
  com.amazonaws.us-east-1.s3`); and the egress-rule `AuthorizeSecurityGroupEgress`.
  Each one requires the stack's default tags in the request:
  `aws:RequestTag/Project = flh` and `aws:RequestTag/Component = public-demo`.
- **Existing resources:** every modify, delete, attach, route, association,
  instance lifecycle and tag action on existing resources requires
  `aws:ResourceTag/Project = flh` and `Component = public-demo`. This also
  covers the parent VPC, subnet and security group of a create.
- **`RunInstances` on the new instance** requires:
  - the stack tags;
  - `ec2:InstanceType = t4g.micro`;
  - `ec2:MetadataHttpTokens = required`;
  - `ec2:InstanceProfile` like `instance-profile/flh-demo-host-*`.

  Its launch inputs are limited to the reviewed AMI ARN
  (`ami-04048e843b318bc37`) plus the new volume and network interface.
- **Tag-on-create:** `CreateTags` is allowed only with `ec2:CreateAction` for
  the eight create calls above.

**IAM:**
- **Roles:** create, delete, tag and inline-policy put/delete, on
  `role/flh-demo-host-*` only.
- **Instance profiles:** create, delete, add or remove role, tag, on
  `instance-profile/flh-demo-host-*` only.
- **`iam:PassRole`:** only `role/flh-demo-host-*`, only with
  `iam:PassedToService = ec2.amazonaws.com` and `iam:AssociatedResourceARN`
  like `arn:aws:ec2:*:<account>:instance/*`. This is the form AWS documents;
  it also covers `AddRoleToInstanceProfile`, which requires PassRole.
- **Not granted:** `UpdateAssumeRolePolicy`, `UpdateRole` and the managed
  policy attach/detach actions. The stack does not use them.

**S3:**
- **Bucket creation:** `CreateBucket` on `flh-demo-artifacts-*`.
- **Bucket configuration:** policy, public-access block, ownership,
  encryption, versioning, lifecycle and tagging (put and delete forms) and
  `DeleteBucket`, all with `s3:ResourceAccount = <account>`.
- **Release upload:** `PutObject` and `AbortMultipartUpload` on
  `releases/*`.
- **Teardown:** `DeleteObject` and `DeleteObjectVersion` on the bucket.

The S3 "delete" APIs used during teardown map to `Put*` actions:
`DeleteBucketEncryption` → `PutEncryptionConfiguration`, and likewise for
lifecycle, ownership, public-access block and tagging. These mappings come
from the service reference.

**Session Manager:**
- **`StartSession` on instances:** only those tagged Project/Component, with
  `BoolIfExists ssm:SessionDocumentAccessCheck = true`.
- **Documents:** `AWS-StartPortForwardingSession` (AWS-owned) and the
  account's `SSM-SessionManagerRunShell`.
- **Own sessions:** `TerminateSession` and `ResumeSession` only on
  `session/${aws:username}-*`.

**Operate policy:** `StartInstances`, `StopInstances` and `RebootInstances` on
tagged instances, plus the upload and session statements.

**Resource `"*"`:** no statement uses `Resource: "*"`, `NotAction`,
`NotResource` or `Deny`.
- **Actions that genuinely need `"*"`:** the `Describe*`/`List*` reads
  Terraform and the CLI make, such as `ec2:DescribeInstances`,
  `ec2:DescribeInstanceTypes` and `ssm:DescribeInstanceInformation`.
- **Where they come from:** these stay with the retained `ReadOnlyAccess` and
  are not added here.
- **Account-wide ARN wildcards** (`arn:aws:ec2:us-east-1:<account>:*`) appear
  only where resource IDs are unknown before creation. They are always paired
  with a tag or `CreateAction` condition.

## Compatibility check (offline)

**Source:** AWS's programmatic Service Authorization Reference
(`servicereference.us-east-1.amazonaws.com`, the ec2, iam, s3 and ssm JSON),
downloaded 2026-10-20. The HTML reference pages now redirect.

**What a scratch checker verified,** for both files:
- every action exists;
- every Resource ARN matches a resource type of at least one action in its
  statement;
- every condition key is listed for that action or its matched resource type.

**Results:**
- both policies: 0 errors;
- a negative control (`ec2:InstanceType` on `iam:CreateRole`, and an EC2 ARN
  for `s3:PutObject`) was rejected with 3 errors.

**IAM documentation checked:**
- `AddRoleToInstanceProfile` requires PassRole;
- the documented `iam:PassedToService` + `iam:AssociatedResourceARN` form for
  EC2.

**Not covered by the checker:** whether the AWS provider sends each tag at
creation. That determines whether the `aws:RequestTag` conditions are
satisfied, and only a real apply shows it.

## Residual privilege risks

1. **Privilege escalation through the host role (material).**
   `iam:CreateRole` and `iam:PutRolePolicy` on `role/flh-demo-host-*` cannot be
   limited by policy content: IAM has no condition on the policy document. A
   holder of the deploy policy could:
   1. create a `flh-demo-host-*` role trusting their own user, or with any
      inline policy, or add permissions to the existing host role;
   2. obtain those permissions directly, or through an instance they can
      launch and reach with Session Manager.

   **Mitigation:** attach `flh-demo-deploy` only while applying or destroying.
   **Future hardening:** a permissions boundary on the host role. That needs a
   Terraform change and a new plan, where the `iam:PermissionsBoundary`
   condition would then be enforced on `CreateRole`/`PutRolePolicy`.
2. **Security-group tag hijack.** The deploy policy lets the user:
   - revoke rules on **any** security group in us-east-1 of this account. This
     is needed to strip the untagged default security group of the new VPC; it
     only removes rules;
   - add the stack tags to any security group, which then makes that group
     manageable (delete it, or add egress). Ingress authorisation is not
     granted at all.

   The account is believed to hold nothing else in us-east-1; this was not
   verified.
3. **Cost.**
   - **Instances and IPs:** the policy allows more than one `t4g.micro`, each
     with a public IPv4 address. It cannot limit the count.
   - **Root volume size:** `RunInstances` exposes no condition key for volume
     size on the volume resource type, so the size is not capped.
   - **Buckets:** any number of `flh-demo-artifacts-*` buckets.
   - **Recommendation:** a budget alert.
4. **Session Manager:** a shell on the stack instance is effectively root on
   it, with the instance role's credentials: Session Manager plus
   `s3:GetObject` on releases.
5. **Root-volume naming:** `CreateTags` with only `Name = flh-demo-root` on
   any volume (harmless, but broader than one volume). It is needed because the
   provider tags the root volume after launch.

## Untested assumptions that can block a first apply

- **Tagging at creation:** the AWS provider (hashicorp/aws 6.69.1) sends tags
  at creation (`TagSpecifications`) for the VPC, subnet, internet gateway,
  route table, security group, endpoint, egress rule and instance. If any one
  is tagged afterwards instead, its create is denied.
- **Root-volume tag:** the root volume `Name` tag may arrive either at launch
  or by `CreateTags` afterwards. Both are allowed; a different provider call
  would be denied.
- **EBS key:** the encrypted root volume uses the account's default EBS key.
  If it is the AWS-managed `aws/ebs`, no IAM KMS permission is needed (its key
  policy grants use through EC2). If EBS default encryption was set to a
  customer-managed key, the launch needs `kms:CreateGrant`/`GenerateDataKey*`
  on that key. None is granted.
- **Session ARNs and `ReadOnlyAccess`:**
  - `${aws:username}` session scoping assumes `flh-plan`'s `credential_process`
    returns credentials of the IAM user `flh-experiment`, including temporary
    `GetSessionToken` credentials. If it assumes a role instead, this user
    policy does not apply at all.
  - `ReadOnlyAccess` must stay attached.
- **Shell document:** `SSM-SessionManagerRunShell` exists only once Session
  Manager preferences have been saved in the account. The port-forwarding
  document needs no preparation.
- **Pinned AMI:** a re-plan that resolves a different AMI needs a policy
  update.

## Human steps remaining

1. Substitute the account ID locally (README §1).
2. Create `flh-demo-deploy` and `flh-demo-operate` in the Console and attach
   them to `flh-experiment`, keeping `ReadOnlyAccess` (README §2).
3. Set a budget alert.
4. Run the apply command above, then the runbook §4 to §7.
5. Detach `flh-demo-deploy` after a successful apply.
