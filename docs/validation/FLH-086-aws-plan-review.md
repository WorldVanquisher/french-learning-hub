# FLH-086 — Review of the saved AWS plan `flh086.tfplan`

**Scope:**
- **Reviewer:** NAS Claude Code.
- **Input:** the human-generated `deploy/aws/terraform/flh086.tfplan`.
- **Method:** local inspection only, with
  `~/tools/terraform/1.16.6/terraform show -json` under `unshare -rn` (no
  network, AWS config files set to `/dev/null`), plus local parsing of the plan
  archive.
- **Not done:** no AWS API call, no plan regeneration, no apply, no permission
  change, no Git command.
- **Data handling:** the JSON export was kept in a private scratch directory
  outside the repository and deleted afterwards. Account IDs are redacted here.

**Verdict: READY FOR OWNER REVIEW.** The plan matches the FLH-084/085 contract
and needs no correction. **First apply is still blocked** by the operator
permissions (§5). A successful plan does not guarantee a successful deployment.

## 1. Plan integrity

- **Plan state:** format 1.2, Terraform 1.16.6. `applyable: true`,
  `complete: true`, `errored: false`.
- **Actions:** 20 creates, 0 updates, 0 deletes, 0 replacements, 0 drift.
  `prior_state` contains only the three data sources read during planning; no
  existing infrastructure is managed.
- **Configuration snapshot:** the `.tf` files and `.terraform.lock.hcl` inside
  the plan are byte-identical to the current working tree.
- **Checks:** all passed. That covers the `aws_instance.host` precondition
  (`t4g.micro` supports arm64) and every variable validation.
- **Variables:** `us-east-1`, `arm64`, `t4g.micro`, `ami_id = null` (resolved
  below), 8 GiB root, `delete_on_termination = true`, `cpu_credits = standard`,
  `force_destroy = false`, `termination_protection = false`, VPC
  `10.84.0.0/24`, port 18970.

## 2. Resources (20 creates, plus 2 data reads at apply)

**Network (9):**
- `aws_vpc.demo`;
- `aws_subnet.public`;
- `aws_internet_gateway.demo`;
- `aws_route_table.public`;
- `aws_route_table_association.public`;
- `aws_vpc_endpoint.s3`;
- `aws_default_security_group.demo`;
- `aws_security_group.host`;
- `aws_vpc_security_group_egress_rule.https`.

**IAM (3):**
- `aws_iam_role.host`;
- `aws_iam_role_policy.host`;
- `aws_iam_instance_profile.host`.

**Storage (7):**
- `aws_s3_bucket.artifacts`;
- `aws_s3_bucket_public_access_block.artifacts`;
- `aws_s3_bucket_ownership_controls.artifacts`;
- `aws_s3_bucket_server_side_encryption_configuration.artifacts`;
- `aws_s3_bucket_versioning.artifacts`;
- `aws_s3_bucket_lifecycle_configuration.artifacts`;
- `aws_s3_bucket_policy.artifacts`.

**Compute (1):** `aws_instance.host`.

**Read at apply** (they depend on unknown ARNs):
`data.aws_iam_policy_document.host` and `data.aws_iam_policy_document.artifacts`.

**Absent:**
- NAT gateway, load balancer, RDS, ECS/EKS;
- Elastic IP, interface endpoints;
- Route 53, CloudFront, CloudWatch;
- GPU or any additional instance or volume.

Nothing touches DNS, the VPS, xray or nginx.

## 3. Findings by area

**EC2:**
- **Type and AMI:** `t4g.micro`, AMI `ami-04048e843b318bc37`. The AMI came from
  the public parameter `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64`,
  and the instance-type data source reports `supported_architectures = ["arm64"]`
  (2 vCPU, 1024 MiB).
- **Root disk:** gp3, 8 GiB, `encrypted = true`, `delete_on_termination = true`.
- **CPU credits:** `standard`.
- **Metadata:** IMDSv2 (`http_tokens = required`), hop limit 1, instance tags
  not exposed.
- **Other settings:** monitoring off, termination protection off,
  `user_data_replace_on_change = true`.
- **SSH key:** none. `key_name` is not configured; it shows as computed-unknown
  only because the provider reports it after creation.
- **Public IPv4:** `associate_public_ip_address = true`. The instance **will
  have a public IPv4 address**, billed at $0.005/h. It exists for outbound
  connectivity to SSM, S3 and package repositories; there is no inbound path
  to it.

**Security groups:**
- **Host group:** no inline rules and no ingress rule resource. One separate
  egress rule: TCP 443 to `0.0.0.0/0`. No port 22, 80 or 18970 anywhere.
- **Default security group of the new VPC:** managed with no rules.
- **Apply-time behaviour:** both groups' `ingress`/`egress` attributes are
  apply-time unknowns. The documented provider behaviour is to:
  - revoke AWS's default allow-all egress when it creates `aws_security_group`;
  - strip all rules from an adopted `aws_default_security_group`.

  This is not provable from the plan; verify it after apply (§5).

**Routing and endpoints:**
- **Routing:** the route table has `0.0.0.0/0` to the internet gateway (target
  ID unknown until apply), associated with the single subnet.
- **Subnet:** `map_public_ip_on_launch = false`; the public IP is set per
  instance.
- **S3 endpoint:** the Gateway endpoint `com.amazonaws.us-east-1.s3` is
  attached to that route table.
- **Consistency with SSM and artifact reads:** the SSM endpoints are reached
  over 443 through the internet gateway. Artifact reads use the gateway
  endpoint, which is what the bucket policy's `aws:SourceVpce` deny requires.

**IAM:**
- **Trust policy:** only `ec2.amazonaws.com` may assume the role.
- **Instance policy:** five Session Manager actions on `*`, plus
  `s3:GetObject` on `<bucket ARN>/releases/*`. The final JSON is rendered at
  apply, but the configuration is fully constant apart from the bucket ARN.
- **Wildcards, all necessary:**
  - `Resource "*"` for the `ssmmessages:*Channel` actions is required: they
    have no resource-level scoping.
  - For `ssm:UpdateInstanceInformation` it follows AWS's documented minimal
    policy. It could be narrowed to `instance/*`, but that is optional, with
    marginal benefit.
  - `releases/*` is a required object-key wildcard.
  - In the bucket policy, `s3:*` with `Principal *` appears only inside the
    TLS **Deny**, which is appropriate.
- **No excessive wildcard:** no managed policies, no `iam:*`, no
  `ssm:GetParameter*`.

**S3:**
- **Access:** all four public-access-block flags true; ownership
  `BucketOwnerEnforced`.
- **Encryption and versioning:** SSE `AES256`; versioning `Enabled`.
- **Lifecycle:** non-current versions expire after 30 days; incomplete
  multipart uploads are aborted after 7 days.
- **Lifecycle settings:** `force_destroy = false`. The name uses the prefix
  `flh-demo-artifacts-`; the final name is unknown until apply.
- **Bucket policy (rendered at apply):** a TLS-only deny, and a deny of
  `s3:GetObject` for the host role outside the gateway endpoint.

**Startup configuration:**
- **Not in the plan:** `user_data_base64` is an apply-time unknown, because it
  embeds the generated bucket name. Terraform renders it at apply from the
  working-tree files `deploy/aws/host/*`.
- **Those files are not part of the plan snapshot.** They are unchanged since
  FLH-085: the last change was 2026-10-20 10:58, before the plan at 13:38.
- **Rendered values:** they will render the FLH-085-validated document with
  `us-east-1`, `arm64` and port 18970.
- **Loopback demo mode preserved:** the unit sets `LISTEN_HOST=127.0.0.1` and
  disables every provider (`AI_PROVIDER=rule-based`, others `disabled`). It
  also sets an empty `HTTP_ALLOWED_HOSTS`, `IPAddressDeny=any` /
  `IPAddressAllow=localhost`, `ReadOnlyPaths` and the `-public-demo-artifact`
  ExecStart.

## 4. Known values versus unknowns and untested behaviour

**Known in the plan:**
- every action;
- region, AMI, type and architecture;
- volume type, size and encryption;
- credits, IMDS settings and the public-IP flag;
- the security-group rule set as configured;
- the endpoint service and route CIDR;
- trust policy, S3 settings and lifecycle.

**Unknown until apply:**
- all IDs and ARNs, the bucket name, the availability zone, the public and
  private IPs;
- the final IAM and bucket policy JSON;
- the rendered user data;
- the default-security-group and host-SG effective rules.

**Untested** (only a real apply and the runbook §4 to §7 can prove these):
- capacity for `t4g.micro` in the zone AWS picks (`availability_zone = null`);
- whether 8 GiB satisfies this AMI's root snapshot size. AL2023 AMIs are
  normally 8 GiB, but this was not checked against AWS;
- SSM agent registration with the minimal policy;
- bucket-policy and gateway-endpoint reads;
- cloud-init schema acceptance and the boot `runcmd`;
- the service starting.

## 5. Remaining prerequisites before apply

1. **Apply identity (blocking).** `flh-experiment` has `ReadOnlyAccess` only;
   apply would fail with `AccessDenied`. The owner must approve and configure
   one of these and run apply under that profile:
   - `AdministratorAccess`;
   - `PowerUserAccess` plus the scoped IAM supplement in `docs/AWS_DEMO.md`
     §1 (untested), which needs `iam:PassRole` on `role/flh-demo-host-*`.

   A saved plan stores no credentials, so it can be applied with a different
   profile. This task changed no permission.
2. **Operator access for the post-apply steps (blocking for install and
   preview).** The same or another identity needs:
   - `s3:PutObject` on `<bucket>/releases/*`;
   - `ssm:StartSession`, `ssm:TerminateSession` and `ssm:ResumeSession`;
   - `ssm:DescribeInstanceInformation`.

   The workstation also needs the AWS CLI v2 and the Session Manager plugin
   (runbook §1).
3. **Apply exactly this plan from this working tree.** Do not edit
   `deploy/aws/host/*` or the `.tf` files before
   `terraform apply flh086.tfplan`. Terraform rejects a stale plan only if
   state changed; it does not detect template edits. Regenerate the plan if
   anything changes.
4. **Optional read-only confirmations** (owner's choice; they are AWS API
   calls):
   - `aws ec2 describe-images --image-ids ami-04048e843b318bc37`: architecture
     `arm64`, root snapshot ≤ 8 GiB;
   - `aws ec2 describe-instance-type-offerings --location-type availability-zone --filters Name=instance-type,Values=t4g.micro`.
5. **Release package choice** for §5 and §6 of the runbook: rc1, or a new
   build.
6. **Budget alert and continuous-operation acceptance:** about
   $10.42/month in us-east-1 before tax and transfer. No free tier is assumed,
   even though the data source reports `free_tier_eligible = true`.

**After apply, verify read-only before installing:**
- the host SG has only the 443 egress rule and no ingress;
- the default SG has no rules;
- SSM `PingStatus = Online`;
- `cloud-init status --wait` and `sudo cloud-init schema --system --annotate`
  on the instance.

## 6. Handling of the plan

- **Plan file:** `flh086.tfplan` (mode 0600) contains account and resource
  identifiers. It is matched by `deploy/aws/terraform/.gitignore` (`*.tfplan`).
- **Other files:** no `terraform.tfvars` or state file exists in the
  directory. `.terraform/` is ignored.
- **This report:** the only file added by FLH-086.
