# FLH-084 — AWS deployment preparation for the read-only demo (handoff)

Owner: NAS Claude Code. Branch (human-prepared): `feat/flh-084-aws-demo-preparation`.

**Scope:** preparation only. These were not done:
- **AWS:** no account was contacted; no resource was created or planned; no
  AWS command was run.
- **Terraform and spending:** nothing was spent; no `terraform init`, `plan` or
  `apply` was run.
- **DNS and exposure:** no DNS change and no publication.
- **Release artifacts:** no vectors were regenerated and no historical release
  artifact was modified.
- **Process:** no Git command and no subagent.

## Result

| Deliverable | Where |
|---|---|
| Architecture and decision record, HTTPS options, future-scope separation | `docs/plans/FLH-084-aws-demo-deployment.md` §1 to §3 and §5 |
| Cost estimate: verified and unverified prices, a continuous month, an intermittent trial, stopped-instance charges, teardown obligations, calculator inputs | same file, §4 |
| Terraform configuration | `deploy/aws/terraform/` |
| Host release tool, systemd unit, journald limits | `deploy/aws/host/` |
| Operator runbook | `docs/AWS_DEMO.md` |
| Local validation | `scripts/validation/flh084/` |

**Design in one paragraph:**
- **Network:** a dedicated VPC with one public subnet and a security group with
  **no ingress** and egress TCP 443 only. A free S3 gateway endpoint carries
  artifact reads.
- **Instance:** one Amazon Linux 2023 EC2 instance. Region, architecture,
  instance type and AMI are variables; `t4g.micro` is suggested. IMDSv2 is
  required. The gp3 root volume is encrypted and deleted on termination.
  Burstable credits are `standard`.
- **Access:** Session Manager only, with AWS's documented minimal instance
  policy plus `s3:GetObject` on `<bucket>/releases/*`. The bucket is private,
  versioned, SSE-S3, TLS-only, not force-destroyable by default, and admits the
  host only through the endpoint.
- **Boot:** user-data carries the host tool, the unit, the journald limits and
  non-secret paths, gzipped. It contains no credentials or URLs and downloads
  nothing.
- **Install:** an operator, in a Session Manager session, runs
  `flh-release install <s3-uri> <sha256>`. It:
  1. verifies the operator-supplied hash and tar safety;
  2. requires the package's own `validate-release.sh` to report CANDIDATE;
  3. installs read-only under `releases/` and switches `current` atomically;
  4. restarts the unit and requires the live `/knowledge-library/demo`
     identity (version, manifest SHA-256, `real_model`) to match the release;
  5. restores the previous release on failure;
  6. logs time, package, tarball hash, `source_revision`, artifact version and
     result.
- **Preview:** an SSM port forward to the loopback-bound server. The unit keeps
  `HTTP_ALLOWED_HOSTS` empty; loopback is always allowed, and public host names
  are refused while the freeze holds.

**Defects found and fixed by the local test before handoff:**
1. **Moving the release:** `flh-release` made a release read-only before
   moving it. A read-only directory cannot be re-parented without root, so the
   tool now moves the release first and then locks it.
2. **Cleanup trap:** the EXIT trap referenced a function-local variable that
   was unbound at exit; it now uses a global.

**Hardening added after review:**
- **Region:** S3 downloads now pass the configured region explicitly, so they
  use the regional endpoint behind the gateway endpoint.
- **Bucket restriction:** `install` refuses URIs outside the configured bucket's
  `releases/`.

## Validation

**Environment:** NAS, Linux x86_64, Python 3.14, systemd 261.

| Check | Result |
|---|---|
| `python3 -B scripts/validation/flh084/static_checks.py` | **167 passed, 0 failed** (details below; the final run includes `deploy/aws/README.md`) |
| `python3 -B scripts/validation/flh084/release_tool_test.py --tarball ~/flh081/release/flh-public-demo-flh081-rc1.tar.gz --work <scratchpad> --port 18996` | **26 passed, 0 failed** (details below) |
| `systemd-analyze verify` on the rendered unit (stand-in executable under a temporary root) | exit 0 |
| `bash -n deploy/aws/host/flh-release` | passed (also inside the static checks) |
| `terraform fmt -check`, `terraform init`, `terraform validate`, `tflint` | **NOT RUN**: `terraform`, `tofu` and `tflint` are not installed, and `init` would download the provider (not authorised) |
| `terraform plan` / `apply` against an account | **NOT RUN** (forbidden by the task; no AWS CLI or credentials used) |
| `shellcheck` | **NOT RUN**: not installed |
| cloud-init schema validation | **NOT RUN**: `cloud-init` not installed. The size and contents of the document were checked by the static checks |
| arm64 server binary execution | **NOT RUN**: this host is x86_64. The test exercised `bin/linux-amd64` only |
| Behaviour on a real AL2023 instance: the SSM agent registering with the minimal policy, S3 access through the gateway endpoint under the bucket policy, the presence of tar/curl/python3 in the AMI, cloud-init `runcmd` | **NOT VERIFIED**: needs an account. The runbook §4 and §6 checks cover these on first apply |

**Static checks:**
- **Terraform text:**
  - balanced blocks;
  - every `var.*` and `local.*` declared and used;
  - region, architecture and type without defaults;
  - no ingress resource, one egress rule (443/tcp), no port 22 or application
    port, `0.0.0.0/0` only in that rule and the internet route;
  - no LB/NAT/RDS/ECS/EKS/EIP, interface endpoint or Route 53;
  - IMDSv2, encrypted gp3, explicit `delete_on_termination`, no `key_name`;
  - the exact IAM action set and `releases/*` scope;
  - bucket public-access block, SSE, versioning, TLS-only, `force_destroy`
    false.
- **Forbidden patterns**, in every file under `deploy/aws`: access keys,
  presigned-URL parameters, 12-digit account IDs, the owner's domain, private
  keys.
- **Rendered unit**, for both architectures: environment, ExecStart, sandbox
  and loopback-only directives.
- **User-data:** gzipped document size 5.2 KB against the 16 KB limit (raw
  14.3 KB, hence the gzip); no non-loopback URL.

**End-to-end test:**
- **Setup:** `flh-release` runs unprivileged against a temporary root. A fake
  `aws` copies from a local "bucket". A fake `systemctl` starts the package's
  real `flh-server` with exactly the unit's environment. The rc1 tarball is
  only read; renamed copies serve as a second release and a never-ready one.
- **Refusals before install:**
  - wrong hash;
  - malformed hash;
  - an object outside the configured bucket;
  - a BLOCKED name;
  - a path-traversal tarball.

  None of them leaves anything behind.
- **Install:**
  - serves the rc1 identity, read-only;
  - `/readyz` returns 200;
  - the workbench is reachable with a `localhost:<port>` Host and an empty
    `HTTP_ALLOWED_HOSTS`;
  - keyword search returns 200;
  - `/entries` returns 404 and `POST` returns 405;
  - a non-loopback Host is refused.
- **Failure and rollback:**
  - a never-ready release fails and is automatically rolled back to rc1, which
    keeps serving;
  - a second release installs;
  - the same name with different bytes is refused;
  - rollback works both ways, and re-selection works.
- **Records:** status and the deployment log record every switch with hash
  and source revision.
- **Cleanup:** the server and temporary directory were removed afterwards.

## Unresolved owner choices (before apply)

The full list is in `docs/AWS_DEMO.md` §10:
- **Region and instance:** region, architecture and instance type; pin the AMI
  or not; availability zone.
- **Bucket name:** generated or explicit.
- **Release package:** the existing rc1, whose workbench predates the FLH-083
  language selector, or a new package built from the current source with the
  existing `package.sh` and real-model artifact, plus its `source_revision`
  label.
- **Operator identity:** the identity and permission set, and the budget alert
  threshold.
- **Defaults and duration:** confirm the volume, credit, version-expiry and
  termination-protection defaults; choose a continuous month or an
  intermittent trial, and the teardown date.
- **Later, separately:** a public host name, the Namecheap record that
  preserves existing records, the HTTPS option (plan §3) and
  `HTTP_ALLOWED_HOSTS`. All remain frozen.

## Limits and risks

- **Unverified prices:** regional gp3 and snapshot rates (the EBS page shows
  only an example region), S3 and data-transfer rates outside us-east-1,
  interface-endpoint, NAT and CloudFront prices, and tax. All are marked in the
  plan; confirm them in the AWS Pricing Calculator.
- **Provider pin:** the AWS provider range is `>= 5.70, < 7.0`. The attributes
  used (`insecure_value`, `aws_vpc_security_group_egress_rule`,
  `user_data_replace_on_change`, `user_data_base64`) exist in that range by my
  knowledge, but they were not validated by Terraform here.
- **Minimal SSM policy:** Session Manager works with it, but the agent may log
  access-denied messages for features it cannot use, such as associations and
  inventory. Run Command and Fleet Manager are intentionally unavailable.
- **`user_data_replace_on_change = true`:** changing the host tool or unit
  replaces the instance. The release must then be re-installed (§6). This is
  documented in the runbook.
- **Housekeeping:** an earlier FLH-083 edit had left that section duplicated in
  `AGENTS.md` (`CLAUDE.md` is a symlink to it). The duplicate was removed while
  adding the FLH-084 section; no other text changed.

## Files

**New:**
- `deploy/aws/README.md`
- `deploy/aws/terraform/versions.tf`
- `deploy/aws/terraform/variables.tf`
- `deploy/aws/terraform/main.tf`
- `deploy/aws/terraform/storage.tf`
- `deploy/aws/terraform/outputs.tf`
- `deploy/aws/terraform/terraform.tfvars.example`
- `deploy/aws/terraform/.gitignore`
- `deploy/aws/host/flh-release`
- `deploy/aws/host/flh-public-demo.service.tftpl`
- `deploy/aws/host/journald-flh.conf`
- `scripts/validation/flh084/static_checks.py`
- `scripts/validation/flh084/release_tool_test.py`
- `docs/AWS_DEMO.md`
- `docs/plans/FLH-084-aws-demo-deployment.md`
- this report

**Modified:**
- `README.md`, `README.zh-CN.md`: a documentation row and a layout line;
- `docs/PUBLIC_DEMO.md`: a pointer;
- `AGENTS.md`: the FLH-084 section and the duplicate removal.
