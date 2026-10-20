# AWS deployment of the read-only public demo (operator runbook)

This runbook deploys the existing read-only public demo (docs/PUBLIC_DEMO.md)
to one EC2 instance. The instance has no inbound network path. The operator
previews it privately over AWS Systems Manager Session Manager.

- **Configuration:** `deploy/aws/`.
- **Decisions and cost estimate:**
  [docs/plans/FLH-084-aws-demo-deployment.md](plans/FLH-084-aws-demo-deployment.md).

**Status:**
- **FLH-084:** prepared the configuration.
- **FLH-085:** natively validated it, without AWS. Nothing has been planned or
  applied, and no AWS account has been contacted. Every step below is run by
  the human owner. See "Validation status" for what that does and does not
  prove.

**Intended mode (owner decision, FLH-085):** continuous operation. The instance
runs all month, about $10.42/month in us-east-1 on `t4g.micro` before tax and
transfer; other regions are in plan §4.2. Stop/start (§8) is for maintenance,
not a cost-saving routine.

**Frozen in this phase:**
- **DNS:** Namecheap stays authoritative. Add or change no records.
- **Public access:** no security-group ingress, no public HTTP/HTTPS, no
  host name in `HTTP_ALLOWED_HOSTS`.
- **Workloads:** the personal database, the write-capable workbench, the model
  service and Qdrant never go on this host.

## Validation status

**Native validation (FLH-085, on the NAS):** every check below ran without AWS
credentials or API calls. The console steps ran with networking disabled.

| Check | Result |
|---|---|
| Terraform 1.16.6 (official zip, SHA-256 verified against `SHA256SUMS`, which is GPG-verified with HashiCorp key `C874 011F 0AB4 0511 0D02 1055 3436 5D94 72D7 468F`) | used for all of the following |
| `terraform fmt -check -diff -recursive` | pass |
| `terraform init -backend=false` | pass; hashicorp/aws **6.69.1** selected within `>= 5.70.0, < 7.0.0` |
| `terraform providers lock` for `linux_amd64`, `linux_arm64`, `darwin_amd64`, `darwin_arm64`, `windows_amd64` | 5 `h1:` and 16 `zh:` hashes in `.terraform.lock.hcl`; every package signed by HashiCorp |
| `terraform init -backend=false -lockfile=readonly` then `terraform validate` | pass, 0 errors, 0 warnings |
| `terraform fmt -check` of `terraform.tfvars.example`, `terraform console -var-file` with it | pass after formatting; variable validations evaluated |
| `scripts/validation/flh084/render_cloud_config.sh` (renders the real template wiring with a sample bucket) and Terraform `yamldecode` | parses; contents equal the source files byte for byte; 15.4 KB raw (EC2 limit 16 KB), 5.6 KB gzipped as sent |
| `cloud-init schema` | **NOT RUN**: cloud-init is not installed on the validation host. Run it on the instance after boot (§6) |
| `terraform plan` / `apply`, AWS CLI, Session Manager | **NOT RUN** (not authorised). Real AWS verification starts at §3 |

**What native validation does not prove:**
- that the account permits these resources and has quota for them;
- that the chosen instance type exists in the zone;
- that the SSM agent registers with the minimal policy;
- that the bucket policy and gateway endpoint admit the host;
- that cloud-init accepts the document on AL2023;
- that the service starts on the instance.

These are proved only by §3 to §7 against the real account.

## Steps that cost money or change external state

| Step | Changes AWS state | Incurs cost |
|---|---|---|
| §2 local checks, `terraform fmt`/`validate` | no | no (`init` downloads the provider from the Terraform registry) |
| §3 `aws sts get-caller-identity`, `terraform plan` | no (read-only API calls) | no |
| §4 `terraform apply` | **yes**: creates VPC, IAM role, bucket, instance | **yes**, about $10/month in us-east-1 while running (see the plan) |
| §5 `aws s3 cp` upload | **yes** | cents |
| §6 to §7 session, install, preview, rollback | instance contents only | no extra charge; instance hours continue |
| §8 `aws ec2 stop-instances` / `start-instances` | **yes** | stopped: EBS (~$0.64/month) and S3 still bill |
| §9 `terraform apply` (force_destroy) and `terraform destroy` | **yes**, deletes everything | stops charges |

## 1. Prerequisites (owner)

**AWS account and operator identity:**
- **Account:** an AWS account the owner controls, with MFA on the root user.
  Use the root user only for account and billing settings.
- **Operator identity:** an IAM Identity Center user, or an IAM user with MFA,
  for the operator.
- **Permissions it needs in the chosen region:**
  - create and delete VPC, subnet, route table, internet gateway, gateway VPC
    endpoint, security group and EC2 instance resources;
  - create and delete an IAM role, its inline policy and an instance profile,
    including `iam:PassRole` on that role;
  - create, configure and delete an S3 bucket, and put objects into it;
  - `ssm:GetParameter` on the public AMI parameter;
  - `ssm:StartSession`, `ssm:TerminateSession`, `ssm:ResumeSession` and
    `ssm:DescribeInstanceInformation`.
- **Permission sets.** Use separate identities, or separate permission sets,
  for the read-only plan and for apply. `AdministratorAccess` is not required.
  - **Plan (§3), read-only:** the AWS managed `ReadOnlyAccess` policy covers
    what `terraform plan` reads for a new stack:
    - `sts:GetCallerIdentity`;
    - `ssm:GetParameter` on the public AMI parameter;
    - `ec2:DescribeInstanceTypes`;
    - the provider's account and partition lookups.

    It cannot create or change anything.
  - **Apply, operate and destroy, option 1:** `AdministratorAccess`. This is
    the simplest option for a single-owner account.
  - **Apply, operate and destroy, option 2:** `PowerUserAccess` plus the inline
    supplement below. `PowerUserAccess` covers EC2, VPC, S3 and SSM but
    excludes almost all of IAM. The supplement allows only roles and instance
    profiles whose names start with this stack's prefix.

    **Not tested against AWS:** if `plan` or `apply` reports `AccessDenied`,
    the error names the missing action. Add only that action, or use option 1.
    ```json
    {
      "Version": "2012-10-17",
      "Statement": [
        {
          "Sid": "FlhDemoHostRole",
          "Effect": "Allow",
          "Action": [
            "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:TagRole", "iam:UntagRole",
            "iam:PutRolePolicy", "iam:GetRolePolicy", "iam:DeleteRolePolicy",
            "iam:ListRolePolicies", "iam:ListAttachedRolePolicies",
            "iam:ListInstanceProfilesForRole", "iam:PassRole"
          ],
          "Resource": "arn:aws:iam::*:role/flh-demo-host-*"
        },
        {
          "Sid": "FlhDemoHostInstanceProfile",
          "Effect": "Allow",
          "Action": [
            "iam:CreateInstanceProfile", "iam:DeleteInstanceProfile", "iam:GetInstanceProfile",
            "iam:AddRoleToInstanceProfile", "iam:RemoveRoleFromInstanceProfile",
            "iam:TagInstanceProfile", "iam:UntagInstanceProfile"
          ],
          "Resource": "arn:aws:iam::*:instance-profile/flh-demo-host-*"
        }
      ]
    }
    ```
    The pattern `flh-demo-host-*` assumes the default `name_prefix`
    (`flh-demo`). It must change if the prefix does.
  - **Operating only (§5 to §8, without Terraform):** a narrower identity is
    enough:
    - `s3:PutObject` on `<bucket>/releases/*`;
    - `ssm:StartSession` on the instance and on the `AWS-StartPortForwardingSession`
      document;
    - `ssm:TerminateSession` and `ssm:ResumeSession` on the operator's own
      sessions;
    - `ssm:DescribeInstanceInformation`;
    - `ec2:StartInstances` and `ec2:StopInstances` on the instance.
- **Budget alert (recommended):** create an AWS Budgets alert in the Billing
  console, for example at $15/month with email notification. It **notifies
  only**; it does not cap or stop spending.

**Local tools on the operator machine, installed by the operator (not by
this repository):**
- **Terraform ≥ 1.5.** 1.16.6 is the version validated. The committed
  `.terraform.lock.hcl` pins hashicorp/aws 6.69.1, with checksums for Linux
  (amd64, arm64), macOS (amd64, arm64) and Windows (amd64). On any other
  platform, `terraform init` stops until that platform is added with
  `terraform providers lock -platform=<os_arch>`. OpenTofu is not tested.
- **AWS CLI v2:**
  <https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html>.
  Check with `aws --version`, which must print `aws-cli/2.`.
- **Session Manager plugin**, required by `aws ssm start-session` for §6 and
  §7:
  <https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html>.
  Check with `session-manager-plugin --version`.

**Where operator authentication is configured.** Terraform's AWS provider and
the AWS CLI read the same standard chain; nothing in this repository adds to
it. In order of precedence:
1. **Environment variables:** `AWS_PROFILE`, or temporary
   `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN`.
2. **Shared config and credentials files:** profiles, including IAM Identity
   Center (SSO) profiles and `credential_process`, in `~/.aws/config` and
   `~/.aws/credentials`. On Windows these are under `%USERPROFILE%\.aws\`.
   The locations can be overridden with `AWS_CONFIG_FILE` and
   `AWS_SHARED_CREDENTIALS_FILE`.

**What FLH-085 found on the NAS:** no `AWS_*` variables, no `~/.aws`, and no
AWS CLI or Session Manager plugin. Only names and existence were checked; no
file was read. The account's authentication therefore lives on another machine
(the operator workstation), and §3 onwards runs there.

**Checking the active identity:** list profile names with
`aws configure list-profiles`, which prints names only, and confirm the
identity with `aws sts get-caller-identity`. Credentials are never written
into this repository, Terraform files, tfvars or state. If no profile exists
yet:
```sh
aws configure sso          # once, creates a named profile
aws sso login --profile <profile>
export AWS_PROFILE=<profile>
```

## 2. Local validation (no AWS access)

```sh
python3 -B scripts/validation/flh084/static_checks.py
python3 -B scripts/validation/flh084/release_tool_test.py \
  --tarball /path/to/flh-public-demo-<label>.tar.gz --work /tmp/flh084-test --port 18996
cd deploy/aws/terraform
terraform fmt -check -diff
terraform init -backend=false -lockfile=readonly   # downloads hashicorp/aws 6.69.1 into .terraform/ (git-ignored)
terraform validate
cd ../../..
TERRAFORM=terraform scripts/validation/flh084/render_cloud_config.sh /tmp/flh-userdata arm64 <region>
# where cloud-init is installed (any Linux host, or the instance itself):
cloud-init schema --config-file /tmp/flh-userdata/user-data-arm64.yaml --annotate
```

**Lock file:** `.terraform.lock.hcl` is committed and must not be regenerated
with `-upgrade` unless a provider upgrade is intended. `-lockfile=readonly`
fails if the lock does not match.

**Choose the release package:**
- **rc1 (existing):** `flh-public-demo-flh081-rc1.tar.gz`, SHA-256
  `536966c46cc3ed70d201fbd2439cd0e1eb3c047151af86de011d8580bb3981df`, artifact
  `d025f217f4d76396`. It is a valid CANDIDATE, but its workbench build predates
  the FLH-083 language selector.
- **A new package from the current source:** build it with the existing
  tooling, from the same real-model artifact. No vectors are regenerated.
  ```sh
  bash scripts/demo/flh076/package.sh --artifact "$HOME/flh076/artifact-e5" \
    --revision "<commit or tag you are deploying>" --label <new-label> --out "$HOME/flh084/packages" \
    --expected-deployment 'multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/flh_e5_role_prefix_v1/float16/singleton_v1/5a3e23f28a05baff'
  (cd "$HOME/flh084/packages/flh-public-demo-<new-label>" && ./validate-release.sh)   # must print CANDIDATE
  ```

**Package rules:**
- Keep the `.tar.gz.sha256` file next to the tarball. It is the only source of
  the expected hash used in §6.
- A `-BLOCKED` (mechanical-vector) package is refused by the host.

## 3. Configure and plan (read-only)

```sh
cd deploy/aws/terraform
cp terraform.tfvars.example terraform.tfvars    # git-ignored; edit the owner choices (§10)
aws sts get-caller-identity                     # confirm the intended account before planning
terraform plan -out flh084.tfplan
```

**Review the plan before applying.** Expect exactly these resources to be
created:
- **Network:**
  - `aws_vpc`, `aws_internet_gateway`, `aws_subnet`;
  - `aws_route_table` and `aws_route_table_association`;
  - `aws_vpc_endpoint` (S3, Gateway);
  - `aws_default_security_group` (no rules);
  - `aws_security_group` and one `aws_vpc_security_group_egress_rule` (tcp/443).
- **IAM:** `aws_iam_role`, `aws_iam_role_policy`, `aws_iam_instance_profile`.
- **Storage:** `aws_s3_bucket` plus its public access block, ownership controls,
  encryption, versioning, lifecycle configuration and policy.
- **Instance:** `aws_instance`.

**Check in the plan output:**
- **No ingress rule anywhere.** No `key_name`.
- **Instance:** `associate_public_ip_address = true`,
  `http_tokens = "required"`, and the root block device has
  `encrypted = true` and `volume_type = "gp3"`.
- **Selection:** the AMI ID and instance type are the ones intended. Pin the
  AMI ID in `terraform.tfvars` if it should not drift.
- **Instance policy:** contains only the five Session Manager actions plus
  `s3:GetObject` on `<bucket>/releases/*`.
- **Bucket:** `force_destroy = false`.

## 4. Apply (starts billing)

```sh
terraform apply flh084.tfplan
terraform output
```

The outputs are `instance_id`, `artifact_bucket`, `ami_id`, `package_arch` and
`preview_command`.

**Wait until the instance is registered with Systems Manager.** This usually
takes a few minutes:

```sh
aws ssm describe-instance-information \
  --filters "Key=InstanceIds,Values=$(terraform output -raw instance_id)" \
  --query 'InstanceInformationList[].{id:InstanceId,ping:PingStatus,agent:AgentVersion}'
```

`PingStatus` must be `Online`. If it stays empty after 15 minutes, check these
causes, which are the usual ones:
- the instance role is missing;
- outbound 443 is blocked;
- there is no public IPv4 address.

Use **EC2 → Instance → Actions → Monitor → Get system log** (read-only) to see
cloud-init output.

## 5. Upload the release

```sh
BUCKET=$(terraform output -raw artifact_bucket)
aws s3 cp /path/to/flh-public-demo-<label>.tar.gz "s3://$BUCKET/releases/"
cat /path/to/flh-public-demo-<label>.tar.gz.sha256      # note the hash; do not upload it
```

## 6. Install over Session Manager

```sh
aws ssm start-session --target "$(terraform output -raw instance_id)"
```

**In the session (shell as `ssm-user`, which has sudo):**

```sh
cloud-init status --wait                     # must end with: status: done
sudo cloud-init schema --system --annotate   # first real schema check of the user data
sudo flh-release install s3://<bucket>/releases/flh-public-demo-<label>.tar.gz <sha256 from the .sha256 file>
sudo flh-release status
exit
```

**What `install` does, in order:**
1. Downloads the tarball and requires its SHA-256 to equal the one given.
2. Refuses absolute paths, `..`, links or device entries in the tarball.
3. Runs the package's `validate-release.sh`, which must report CANDIDATE.
4. Requires `bin/linux-<arch>/flh-server`.
5. Moves the release to `/srv/flh-demo/releases/<package>` and makes it
   root-owned and read-only.
6. Switches `/srv/flh-demo/current` atomically.
7. Restarts `flh-public-demo.service`.
8. Requires `/readyz` to answer, and `/knowledge-library/demo` to report the
   release's own artifact version and `artifact/manifest.json` SHA-256 with
   `real_model: true`.

**If any check after the switch fails**, the previous release is restored and
re-verified. If there is no previous release, the service is stopped.

**Recorded state and deployed identity:**
- **Deployment log:** every action is appended to
  `/srv/flh-demo/state/deployments.log`, with time, action, package, tarball
  SHA-256, source revision, artifact version and result.
- **Re-installing a package:** a package name already installed is accepted
  again only with the same tarball hash. Releases are immutable; use a new
  label for new bytes.
- **Deployed identity:** `flh-release status` prints the tarball SHA-256,
  source object, `source_revision` and artifact version from `RELEASE.json`,
  and the live identity check.

## 7. Private preview, health, logs, rollback

**Preview from the operator's machine** (no inbound rule is involved):

```sh
aws ssm start-session --target "$(terraform output -raw instance_id)" \
  --document-name AWS-StartPortForwardingSession \
  --parameters portNumber=18970,localPortNumber=18970
# keep it running; in a browser open http://127.0.0.1:18970/
curl -s http://127.0.0.1:18970/readyz
curl -s http://127.0.0.1:18970/knowledge-library/demo | python3 -m json.tool | head -20
```

**Preview details:**
- **Local port:** if 18970 is busy on the operator's machine, choose another
  `localPortNumber`.
- **Host header:** requests arrive with a loopback `Host`, which the server
  always accepts. Public host names stay refused because `HTTP_ALLOWED_HOSTS`
  is empty.
- **Boundary:** the read-only allowlist is unchanged. Non-demo routes are 404
  and other methods are 405.

**Host commands, run in a session:**

| Purpose | Command |
|---|---|
| Health | `curl -s http://127.0.0.1:18970/healthz` and `/readyz` |
| Identity | `sudo flh-release status` |
| Logs | `journalctl -u flh-public-demo -n 200 --no-pager` (persistent, capped at 200 MB / 30 days) |
| Releases and history | `sudo flh-release list` |
| Rollback to the previous release (verified as in §6) | `sudo flh-release rollback`. Running it again swaps back |
| Stop serving without uninstalling | `sudo systemctl disable --now flh-public-demo` |

**Upgrading:** upload a new label (§5) and `install` it. The old release stays
under `releases/` for rollback.

**Disk:** each kept release uses about 70 MB. Remove old releases only by
deleting their directories after checking that `current` does not point at
them: `sudo rm -rf /srv/flh-demo/releases/<old>`.

## 8. Stop and start

```sh
aws ec2 stop-instances --instance-ids "$(terraform output -raw instance_id)"
aws ec2 start-instances --instance-ids "$(terraform output -raw instance_id)"
```

**While stopped:**
- **Billed:** the EBS volume and S3 objects.
- **Not billed:** instance hours and the auto-assigned public IPv4, which is
  released.

**On start:**
- The instance gets a new public IP. Nothing depends on it.
- The unit is enabled, so the selected release starts on boot. Confirm with
  `flh-release status`.
- `terraform plan` does not track the running or stopped state.

## 9. Teardown

```sh
cd deploy/aws/terraform
# 1. Allow the versioned bucket and every object version to be deleted:
#    set artifact_bucket_force_destroy = true in terraform.tfvars, then
terraform apply            # review: only the bucket's force_destroy changes
# 2. Delete everything this configuration created:
terraform destroy          # review the list; type yes
```

**If termination protection was enabled,** set `termination_protection = false`
and `apply` first.

**Then confirm nothing billable remains in the region.** These checks are
read-only:

```sh
aws resourcegroupstaggingapi get-resources --tag-filters Key=Task,Values=FLH-084 --query 'ResourceTagMappingList[].ResourceARN'
aws ec2 describe-instances --filters Name=tag:Task,Values=FLH-084 --query 'Reservations[].Instances[].[InstanceId,State.Name]'
aws ec2 describe-volumes --filters Name=tag:Task,Values=FLH-084 --query 'Volumes[].VolumeId'
aws ec2 describe-addresses --query 'Addresses[].PublicIp'
aws ec2 describe-snapshots --owner-ids self --query 'Snapshots[].SnapshotId'
aws s3api list-buckets --query 'Buckets[?starts_with(Name, `flh-demo`)].Name'
```

**Expected:** no instances, or only `terminated` ones, and every other list
empty. The tagging API may list deleted resources for a short while.

**Local files:** keep `terraform.tfstate` until destroy has succeeded, then
delete it with `.terraform/` if the stack will not be recreated. The released
tarballs remain on the operator's machine.

## 10. Owner choices required before `terraform apply`

1. **Region** (`aws_region`): price versus latency (plan §4.1).
2. **Architecture and instance type:** `arm64` with `t4g.micro` is the
   suggestion; `t4g.nano` is the cheapest; `x86_64` with `t3.micro` is the
   alternative.
3. **AMI:** use the current AL2023 AMI that the plan resolves, then pin
   `ami_id`; or leave it unpinned.
4. **Availability zone:** only if the chosen type is unavailable in the zone
   AWS picks.
5. **Artifact bucket name:** generated (default), or an explicit name.
6. **Release package:** rc1, or a newly built package from the current source
   (§2), with its `source_revision` label.
7. **Operator identity and permission set:** `ReadOnlyAccess` for the plan.
   For apply, `AdministratorAccess`, or `PowerUserAccess` plus the scoped IAM
   supplement (§1). Plus the budget alert threshold.
8. **Defaults to confirm or change:**
   - root volume size and `delete_on_termination`, defaults 8 GiB and true;
   - `cpu_credits = standard`;
   - non-current version expiry, default 30 days;
   - termination protection, default off.
9. **Duration:** decided (FLH-085): continuous operation, about $10–12 a
   month. Still open: whether a Savings Plan or Reserved Instance is worth it
   for a year-long run. Not evaluated here.
10. **OS updates for a continuously running host:** Amazon Linux 2023 does not
    apply updates automatically. Options:
    - run `sudo dnf upgrade --releasever=latest` in a session periodically,
      then reboot;
    - replace the instance with a newer pinned AMI (`terraform apply`), then
      re-install the release (§6).

    The cadence is an owner choice. It is not automated by this configuration.

**Next human step (read-only plan).** On the operator workstation, with the
tools above, only these choices remain:
1. the AWS profile (`AWS_PROFILE`) with at least `ReadOnlyAccess`;
2. the region (`aws_region`);
3. the architecture and instance type (`arm64` + `t4g.micro` suggested);
4. which release package will follow (rc1 or a new build). It is not needed
   for the plan itself, but it is needed right after apply.

Then:
```sh
aws sts get-caller-identity
terraform -chdir=deploy/aws/terraform init -lockfile=readonly
terraform -chdir=deploy/aws/terraform plan -out flh084.tfplan
```

**Lifting the freeze is outside this runbook.** It needs separate, explicit
decisions:
- the public host name;
- the Namecheap record, preserving the existing records;
- the HTTPS option and inbound path (plan §3);
- `HTTP_ALLOWED_HOSTS`.
