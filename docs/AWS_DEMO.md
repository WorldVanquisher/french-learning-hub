# AWS deployment of the read-only public demo (operator runbook)

This runbook deploys the existing read-only public demo (docs/PUBLIC_DEMO.md)
to one EC2 instance. The instance has no inbound network path. The operator
previews it privately over AWS Systems Manager Session Manager.

- **Configuration:** `deploy/aws/`.
- **Decisions and cost estimate:**
  [docs/plans/FLH-084-aws-demo-deployment.md](plans/FLH-084-aws-demo-deployment.md).

**Status:**
- **FLH-084:** prepared the configuration.
- **FLH-085:** natively validated it, without AWS. See "Validation status"
  for what that does and does not prove.
- **FLH-086:** corrected the permissions (host-role boundary, no
  default-security-group adoption).
- **FLH-087 (operator-reported):** the first deployment was applied from
  `flh086r2.tfplan`: 19 added, us-east-1, arm64 `t4g.micro`. rc1 was installed
  first. It was then upgraded to the verified-source package
  `flh-public-demo-flh087-rc1`, which is active and ready on loopback. rc1 is
  the previous release and rollback target.
  - Browser review: overall, no blocking issue reported. Individual features
    were not separately accepted.
  - Detachment of `flh-demo-deploy` is unconfirmed.
  - Evidence: `docs/validation/FLH-087-aws-first-deployment.md`.
- **FLH-088 (prepared, not applied):** an optional public HTTPS entry point
  (§11), off by default. Public HTTPS is unproven until live evidence is
  recorded.

Every step below is run by the human owner.

**Deployment stages are verified separately.** Each stage proves only itself:

| Stage | Proved by |
|---|---|
| 1. Infrastructure created | `terraform apply` result; SSM `PingStatus = Online` (§4) |
| 2. Host configured | `cloud-init status --wait` = done; schema check of the decoded config (§6); installer and unit present |
| 3. Runtime ready | `flh-release install` / `status` identity match; service active; `/readyz` = ready (§6, §7) |
| 4. Browser access | page loads through the SSM port forward (§7) |
| 5. Interactive acceptance | an explicit check of search, Concept detail and source record, and the language selector (§7) |

**Intended mode (owner decision, FLH-085):** continuous operation. The instance
runs all month, about $10.42/month in us-east-1 on `t4g.micro` before tax and
transfer; other regions are in plan §4.2. Stop/start (§8) is for maintenance,
not a cost-saving routine.

**Frozen in this phase** (the default, `public_https_enabled = false`):
- **DNS:** Namecheap stays authoritative. Add or change no records.
- **Public access:** no security-group ingress, no public HTTP/HTTPS, no
  host name in `HTTP_ALLOWED_HOSTS`.
- **Lifting it:** only through §11 (FLH-088), after the owner supplies the
  host name and decides to expose the demo.
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
| `cloud-init schema` | **NOT RUN** on the validation host (cloud-init is not installed). FLH-087, operator-reported on the instance: `--system` rejected the gzip header; the decoded `/var/lib/cloud/instance/cloud-config.txt` is "Valid cloud-config" (§6) |
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
  - **Apply and destroy (recommended):** attach the customer-managed
    `flh-demo-deploy` and `flh-demo-deploy-ec2` policies together
    (`deploy/aws/iam/`; split in FLH-088 for the 6,144-character limit), only
    while applying or destroying. It requires the host role to carry the administrator-managed
    permissions boundary `flh-demo-host-boundary`, and explicitly denies
    removing or changing that boundary. Procedure: `deploy/aws/iam/README.md`.
    It is **untested against AWS**: an `AccessDenied` names the missing action
    or condition.
  - **Apply and destroy (alternative):** `AdministratorAccess`. The boundary
    policy must still exist, because the plan looks it up by name.
  - **Withdrawn (FLH-086):** the earlier `PowerUserAccess` plus IAM supplement.
    It let the deploy identity create unbounded `flh-demo-host-*` roles, which
    is a privilege-escalation path.
  - **Operating only (§5 to §8, without Terraform):** the `flh-demo-operate`
    policy (`deploy/aws/iam/`) grants:
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
python3 -B scripts/validation/flh088/public_https_test.py   # FLH-088 host tool, offline
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
terraform plan -out <new-name>.tfplan
```

**Before planning:** an administrator must have created the
`flh-demo-host-boundary` policy (`deploy/aws/iam/README.md`). The plan reads it
by name and fails if it is missing.

**Obsolete plan:** `flh086.tfplan` predates the FLH-086 corrections. It still
adopts the default security group and creates the role without a boundary.
**Never apply it**; it is kept only as review evidence. Generate and review a
new plan.

**Review the plan before applying.** Expect exactly these **19** resources to
be created:
- **Network:**
  - `aws_vpc`, `aws_internet_gateway`, `aws_subnet`;
  - `aws_route_table` and `aws_route_table_association`;
  - `aws_vpc_endpoint` (S3, Gateway);
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
- **Role boundary:** `aws_iam_role.host` has `permissions_boundary` set to the
  ARN of `flh-demo-host-boundary`.
- **Default security group:** no `aws_default_security_group` resource.
- **Bucket:** `force_destroy = false`.

## 4. Apply (starts billing)

```sh
terraform apply <new-name>.tfplan     # the reviewed replacement plan, never flh086.tfplan
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

**Default security group (optional, administrator, once).** Terraform does not
manage the new VPC's default security group, because adopting it would need
account-wide rule revocation for the deploy identity. AWS creates it with an
inbound rule from members of the same group and all outbound traffic.
- **Exposure:** no network interface uses it, since the instance names its own
  group, and it admits nothing from the internet.
- **Optional hardening:** an administrator can strip its rules once with
  administrator credentials. Look up its ID with `aws ec2 describe-security-groups
  --filters Name=vpc-id,Values=<vpc-id> Name=group-name,Values=default`, then
  run `aws ec2 revoke-security-group-ingress` / `revoke-security-group-egress`
  with the listed rule IDs.
- **Drift:** this is outside Terraform, so it causes no drift.

Use **EC2 → Instance → Actions → Monitor → Get system log** (read-only) to see
cloud-init output.

## 5. Upload the release

**Migration compatibility (FLH-095).** A release package is self-contained: its
binary and artifact were built from one tree, and the server checks that the
artifact's migration ledger matches the binary's exactly. Packages built and
deployed before migration `012` keep working unchanged. A new package from a
tree with `012` must contain an artifact rebuilt from that same tree; never
copy an older artifact into a newer package (see `docs/PUBLIC_DEMO.md`,
"Migration 012").

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
sudo cloud-init schema -c /var/lib/cloud/instance/cloud-config.txt --annotate   # see the note below
sudo /usr/local/sbin/flh-release install s3://<bucket>/releases/flh-public-demo-<label>.tar.gz <sha256 from the .sha256 file>
sudo /usr/local/sbin/flh-release status
exit
```

**Installer path:** `flh-release` lives at `/usr/local/sbin/flh-release`.
`sudo`'s `secure_path` may not include `/usr/local/sbin`, so use the full path.

**Schema check of the user data:** the user data is sent gzip-compressed.
- **Observed (FLH-087, cloud-init 22.2.2 on the deployed AL2023 AMI):**
  `cloud-init schema --system` rejected the compressed input header.
  `/var/lib/cloud/instance/user-data.txt` begins with the gzip magic bytes.
- **What passed:** validating the decoded configuration that cloud-init wrote,
  `/var/lib/cloud/instance/cloud-config.txt`, reported "Valid cloud-config".
- **Other versions:** other cloud-init versions may behave differently. If
  `--system` succeeds on a later AMI, either check is acceptable.

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
- **Deployed identity:** `/usr/local/sbin/flh-release status` prints the tarball SHA-256,
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
  is empty, unless §11 is enabled.
- **Boundary:** the read-only allowlist is unchanged. Non-demo routes are 404
  and other methods are 405.
- **Tunnel scope:** closing the port-forward session ends only the preview.
  The instance and the service keep running and billing.

**Interactive acceptance (stage 5).** Through the tunnel, record the result of:
- one keyword search;
- opening a Concept;
- opening a supporting unit's source record;
- the language selector: English on first load, switching to 简体中文 and back.

A page that loads is browser access only, not acceptance.

**Host commands, run in a session:**

| Purpose | Command |
|---|---|
| Health | `curl -s http://127.0.0.1:18970/healthz` and `/readyz` |
| Identity | `sudo /usr/local/sbin/flh-release status` |
| Logs | `journalctl -u flh-public-demo -n 200 --no-pager` (persistent, capped at 200 MB / 30 days) |
| Releases and history | `sudo /usr/local/sbin/flh-release list` |
| Rollback to the previous release (verified as in §6) | `sudo /usr/local/sbin/flh-release rollback`. Running it again swaps back |
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

**With public HTTPS enabled (§11):** the Elastic IP is kept, so the DNS record
stays valid. It bills $0.005/h (about $3.65/month) while the instance is
stopped. nginx and the demo start on boot.

**On start:**
- Without §11, the instance gets a new public IP. Nothing depends on it.
- The unit is enabled, so the selected release starts on boot. Confirm with
  `/usr/local/sbin/flh-release status`.
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
   For apply, the administrator-created `flh-demo-host-boundary` plus
   `flh-demo-deploy` and `flh-demo-deploy-ec2` (or `AdministratorAccess`); `flh-demo-operate` to operate
   (§1). Plus the budget alert threshold.
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
terraform -chdir=deploy/aws/terraform plan -out <new-name>.tfplan
```

**Lifting the freeze** is §11. It needs separate, explicit decisions:
- the public host name;
- the Namecheap record, preserving the existing records;
- the HTTPS option and inbound path (plan §3), chosen in FLH-088 as option A;
- `HTTP_ALLOWED_HOSTS`, set by `flh-public-https` through a unit drop-in.

## 11. Optional public HTTPS (FLH-088)

**Prepared, not applied.** The full procedure, cost, acceptance checks and
rollback are in
[docs/validation/FLH-088-public-demo.md](validation/FLH-088-public-demo.md)
(§8–§10).

**Design:**
- **Edge:** nginx with a Let's Encrypt certificate, on the existing instance,
  in front of the unchanged loopback demo.
- **Packages:** nginx and certbot from the Amazon Linux repositories.
- **Terraform:** `public_https_enabled = true` adds an Elastic IP, its
  association and inbound TCP 80/443. It does not replace the instance.
- **Unchanged:** port 18970 stays closed; SSM is unchanged.
- **Host tool:** `deploy/aws/host/flh-public-https`, installed over SSM:
  `preflight`, `enable` (with a `--staging` dry run), `status`, `disable`.

**Host tool safeguards (FLH-088 §12):**
- **DNS:** `preflight` requires exactly one A record equal to the instance's
  public IPv4, no CNAME, and a verified empty AAAA answer. A failed lookup is
  a refusal.
- **nginx:** `enable` refuses a modified or foreign nginx configuration. A
  rerun is safe.
- **Renewal:** HTTPS is served only once the certbot package's own renewal
  schedule works; otherwise the result is exit 3, INCOMPLETE.

**Order** (the host name currently points at the owner's VPS; this is a
controlled cutover of that one A record):
1. **Record DNS facts:** A, AAAA, CNAME and TTL values; CAA at the host and its
   parent; the nameservers.
2. **IAM:** the administrator creates `flh-demo-deploy-ec2` and saves the new,
   smaller `flh-demo-deploy` version (`deploy/aws/iam/README.md` §2b). Attach
   both while applying, and detach both afterwards.
3. **Plan** with the deployed inputs and the deployed AMI (from `terraform
   output -raw ami_id`). Review the full plan: exactly 4 to add, nothing
   changed, destroyed or replaced. Then apply.
4. **Install the tool** over SSM. Run `preflight`: before the cutover it must
   fail only at the DNS check.
5. **Cut over DNS:** lower the TTL, then **replace** the A value with the
   Elastic IP and remove any AAAA record. Wait for propagation.
6. **Enable:** `preflight`, then `enable --staging`, then `enable`; then
   `certbot delete --cert-name flh-demo-staging`.
7. **Verify renewal:** `status`, `systemctl list-timers`,
   `certbot renew --dry-run`.
8. **Record** the live acceptance checks.

**Recovery to the VPS:**
1. Restore the recorded A (and any AAAA) records with their TTL.
2. Wait out caches until resolvers return the VPS address again. Check that
   the VPS's `:8443` entry loads.
3. Run `flh-public-https disable`.
4. Only then apply `public_https_enabled = false`: exactly 4 to destroy.

The VPS, its xray/nginx and its `:8443` configuration are never changed.
