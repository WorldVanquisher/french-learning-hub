# FLH-085 — Native validation of the AWS deployment configuration (handoff)

Owner: NAS Claude Code. Branch (human-prepared): `feat/flh-085-aws-preflight`.

**Owner decisions recorded:**
- an AWS account is available;
- the intended service runs continuously;
- the budget is flexible, but this task authorises no spending or resource
  creation;
- the single-EC2 design is kept.

**Not done:**
- **AWS:** no AWS API calls; no `terraform plan`, `apply` or `destroy`; no
  resources, paid services, DNS or ingress changes.
- **Hosts and data:** no VPS access, model calls, or personal-data, `.env` or
  release-artifact changes.
- **Process:** no Git command and no subagent.

**Native validation versus real AWS verification:**
- **This report's scope:** everything here is *native* validation. It covers
  formatting, provider resolution, schema-level configuration validity and
  offline rendering, all on the NAS without credentials.
- **Still unverified:** nothing has been verified against a real AWS account.
  That starts with the owner's read-only `terraform plan` (`docs/AWS_DEMO.md`
  §3).

## Tools

**Terraform: 1.16.6, linux_amd64** (latest stable in the official index on
2026-10-20).
- **Install:** downloaded from `releases.hashicorp.com` into
  `~/tools/terraform/1.16.6/`, which is user-owned and outside the repository.
  No sudo, global install or shell-profile change.
- **Verification:**
  - the zip matched `terraform_1.16.6_SHA256SUMS` (`sha256sum -c`: OK);
  - the SUMS file's signature verified with `gpg` ("Good signature", HashiCorp
    Security, primary key `C874 011F 0AB4 0511 0D02 1055 3436 5D94 72D7 468F`),
    imported into an isolated `GNUPGHOME` in the same directory.

**Provider:** hashicorp/aws **6.69.1**, the newest release within the existing
constraint `>= 5.70.0, < 7.0.0`. Every package was "signed by HashiCorp".

**Other tools:** systemd 261, Python 3.14.

**Absent on this host:**
- `cloud-init`, `aws`, `session-manager-plugin`;
- `shellcheck`, `tflint`;
- Python `yaml` and `jsonschema`.

## Commands and results

All `terraform` commands ran in `deploy/aws/terraform` with
`CHECKPOINT_DISABLE=1`.

| Command | Result |
|---|---|
| `terraform fmt -check -diff -recursive` | exit 0, before and after the change below |
| `terraform init -backend=false -input=false` | success; created `.terraform/` (803 MB, git-ignored) and `.terraform.lock.hcl` |
| `terraform validate` / `validate -json` | valid, 0 errors, **0 warnings** |
| `terraform providers lock -platform=linux_amd64 -platform=linux_arm64 -platform=darwin_amd64 -platform=darwin_arm64 -platform=windows_amd64` | first attempt failed: `/tmp` (tmpfs) disk quota exceeded while unpacking; the lock file was unchanged. Re-run with `TMPDIR=~/tools/tmp`: success. The lock now has **5 `h1:` hashes (one per platform) and 16 `zh:` hashes** |
| `terraform init -backend=false -lockfile=readonly` then `terraform validate` (after the change below) | success; the lock file SHA-256 was unchanged (`b5d180e3…6e652cfb`); valid |
| `terraform fmt -check` on a copy of `terraform.tfvars.example` (renamed `.tfvars`) | **exit 3**: inline-comment alignment. Fixed by applying `terraform fmt` output; re-check exit 0 |
| `terraform console -var-file=<example copy>` (no network, `unshare -rn`) | variables accepted (`us-east-1`, `arm64`, `t4g.micro`, package arch `arm64`, credits `standard`). An invalid `architecture=aarch64` is rejected with the configured message |
| `scripts/validation/flh084/render_cloud_config.sh <out> arm64 us-east-1` and `<out> x86_64 ap-northeast-1` | details below |
| `cloud-init schema` | **NOT RUN.** cloud-init is not installed, and installing it was not authorised. No static assertion is presented as schema validation. Commands for the owner are in the runbook §2 and §6 (`sudo cloud-init schema --system --annotate` on the instance) |
| `python3 -B scripts/validation/flh084/static_checks.py` | **179 passed, 0 failed** (was 158/167). Now skips `.terraform/`, the lock file, tfvars, plans and state, and checks the new template wiring |
| `systemd-analyze verify`, `release_tool_test.py` | not re-run: the unit template and `flh-release` are unchanged since FLH-084 |
| `bash -n scripts/validation/flh084/render_cloud_config.sh` | pass |

**Rendering cloud-init:**
- **Method:** `render_cloud_config.sh` runs `terraform console` under
  `unshare -rn`, with no network and AWS config files set to `/dev/null`. It
  evaluates `templatefile(<real template>, merge(local.cloud_config_vars,
  {bucket = sample}))`, the configuration's own wiring, and Terraform's
  `yamldecode()` of the result.
- **Result:** both documents parse. The decoded `write_files` contents are
  byte-equal to `flh-release`, `journald-flh.conf`, the rendered unit for that
  architecture, and the expected `deploy.env`. Modes are `0755` and `0644`, and
  the first line is `#cloud-config`.
- **Size:** 15,453 and 15,458 bytes raw (EC2 limit 16,384); 5,559 and 5,563
  bytes gzipped, as sent through `user_data_base64`.
- **Scope:** this is a YAML parse and a content round-trip, **not** a
  cloud-init schema check.

## Fixes

**1. `terraform.tfvars.example`:** formatting, the only concrete error the
native tools found.

**2. User data moved into a template:**
- **Problem:** the user data could not be rendered for validation. It was built
  inline in `main.tf` and embeds the generated bucket name, so `terraform
  console` returned `(known after apply)`.
- **Fix:** the same structure moved, unchanged, into
  `deploy/aws/host/cloud-config.yaml.tftpl`, with an explicit
  `local.cloud_config_vars` map. Only the not-yet-known bucket is substituted
  when rendering offline.
- **Effect:** the produced cloud-config is the same document: same keys, file
  contents, modes and runcmd. A first apply is therefore unaffected.

**3. No configuration or template errors were reported** by
`fmt`/`init`/`validate`. The single-EC2 design is unchanged.

## Next human step: read-only plan

**Authentication:**
- **On the NAS:** there are no `AWS_*` environment variables, no `~/.aws`, and
  no AWS CLI or Session Manager plugin. Only names and existence were checked;
  nothing was read.
- **Therefore:** the account's authentication is configured on the operator
  workstation, through the standard chain: environment variables, then
  `~/.aws/config` / `~/.aws/credentials` profiles (including SSO and
  `credential_process`), or the Windows `%USERPROFILE%\.aws\`.
- **Plan host:** the plan runs there (runbook §1 and §10).

**Prerequisites on that machine:**
- AWS CLI v2 (`aws --version` prints `aws-cli/2.`);
- the Session Manager plugin (`session-manager-plugin --version`);
- Terraform ≥ 1.5 (1.16.6 validated).

**Lock-file platforms:** the lock covers linux_amd64, linux_arm64,
darwin_amd64, darwin_arm64 and windows_amd64. Any other platform must be added
with `terraform providers lock`.

**Permissions** (runbook §1). `AdministratorAccess` is not the only option:
- **Plan:** `ReadOnlyAccess` is sufficient.
- **Apply:** `AdministratorAccess`, or `PowerUserAccess` plus a scoped inline
  IAM supplement limited to `role/flh-demo-host-*` and
  `instance-profile/flh-demo-host-*`. The supplement is untested against AWS
  and documented as such.
- **Operating:** a narrower identity is listed.

No IAM or authentication setting was changed.

**Remaining choices for the plan:**
1. the AWS profile;
2. the region;
3. the architecture and instance type;
4. the release package (rc1 or a new build), which is needed right after apply.

## Remaining blockers and risks

**Blockers:**
- **Operator workstation:** must have the AWS CLI v2, the Session Manager
  plugin and a working profile. None exists on the NAS.
- **cloud-init schema:** validation is still NOT RUN. The first real check is on
  the instance after apply, or on any host where the owner installs cloud-init.

**Risks:**
- **Untested permissions:** the PowerUser supplement's action list. An
  `AccessDenied` names the missing action.
- **User-data headroom:** the raw user data is 15.4 KB. Gzip keeps it at about
  5.6 KB as sent, but the raw document is within 1 KB of the uncompressed
  limit. Large growth of `flh-release` must keep using `user_data_base64`
  gzip, which is already the case.
- **OS updates:** continuous operation needs an OS update routine. AL2023 does
  not auto-update; the options and cadence are an owner choice (runbook §10).
- **Real AWS behaviour, all unverified until §3 to §7:**
  - quotas, and instance-type availability in the zone;
  - SSM registration with the minimal policy;
  - the bucket policy and the S3 gateway endpoint;
  - cloud-init on AL2023;
  - service start on the instance.

**Local leftovers, untracked and outside staging:**
- `deploy/aws/terraform/.terraform/` (provider binaries; may be deleted any
  time);
- `~/tools/terraform/1.16.6/` (binary, download and GPG home).

## Files

**New:**
- `deploy/aws/host/cloud-config.yaml.tftpl`
- `deploy/aws/terraform/.terraform.lock.hcl`
- `scripts/validation/flh084/render_cloud_config.sh`
- this report

**Modified:**
- `deploy/aws/terraform/main.tf`
- `deploy/aws/terraform/terraform.tfvars.example`
- `deploy/aws/README.md`
- `scripts/validation/flh084/static_checks.py`
- `docs/AWS_DEMO.md`
- `AGENTS.md` (`CLAUDE.md` is a symlink to it)

**Unchanged by design:**
- `README.md` and `README.zh-CN.md`: the AWS row already says
  "prepared, not deployed", which is still true;
- the FLH-084 plan and report (historical).
