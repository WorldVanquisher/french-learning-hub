# Private workbench staging on AWS: owner runbook (first run)

One isolated, private staging host for the full workbench (not the public
demo), reached only through an SSM port forward.
- **Run by:** the owner. Agents ran none of it: AGENTS.md forbids agents any
  AWS or Terraform command.
- **Scope:** every command below starts from a clean checkout of the
  repository. Paths are relative to its root unless absolute.
- **What it uses:** synthetic data only, and every provider disabled.
- **Also read:**
  - [INVENTORY.md](INVENTORY.md) (resources, owners, stop rule);
  - [AWS_STAGING_PLAN.md](AWS_STAGING_PLAN.md) (design and cost);
  - [STANDIN-REHEARSAL.md](STANDIN-REHEARSAL.md) (what was rehearsed locally);
  - [CUTOVER_DRY_RUN.md](CUTOVER_DRY_RUN.md) (NAS → AWS cutover and its
    rollback; dry runs only).

**Steps that cost money or change external state:** §2 (IAM, administrator),
§3.4 `terraform apply`, §4 parameters, §5–6 uploads, §9 teardown. Everything
else is local and read-only.

## 0. Inputs and decisions (fill before starting)

| Input | Where it comes from | Used in |
| --- | --- | --- |
| **Authorization:** budget cap, region, runtime window | the owner's decision. Proposed: $5 cap, us-east-1, 4 h. **Without it, stop here** | all |
| AWS account ID (12 digits) | `aws sts get-caller-identity --query Account --output text`. Never committed | §2 |
| AMI ID, Amazon Linux 2023 x86_64 | `aws ssm get-parameter --region us-east-1 --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 --query Parameter.Value --output text` | §2, §3 |
| Compose plugin SHA-256 (v2.29.7, linux x86_64) | `curl -fsSL https://github.com/docker/compose/releases/download/v2.29.7/checksums.txt \| grep ' \*\?docker-compose-linux-x86_64$'` | §3 |
| **Revision to deploy:** one commit on `main` | `git rev-parse origin/main` | §1 |
| Synthetic NAS-shaped backup | a directory made by `flh-daily.sh backup` holding synthetic data only: the release lane's `nas-fixture-20261118072610` (in its handoff area, with a `.json` description) or one made with `staging/rehearsal/make_fixture_backup.py`. **Never the daily data** in this run | §6 |
| Operator tools | terraform ≥ 1.6, AWS CLI v2, session-manager-plugin, docker, git, python3 ≥ 3.9, sha256sum, tar, sqlite3 | §1, §3 (`preflight.py --tools`) |

Shell variables used below (set them once per terminal):

```bash
S=deploy/aws/private-staging/staging          # from the repository root
OUT=~/flh-staging-out                          # build outputs, outside the repository
REGION=us-east-1
```

## 1. Build and verify the bundle (operator machine, no AWS)

```bash
git fetch origin && git status --short          # expect: nothing (a clean checkout)
REV=$(git rev-parse origin/main)
TREE=$(git rev-parse "$REV^{tree}")
NAME=flh-staging-${TREE:0:12}
mkdir -p "$OUT"
bash $S/build_bundle.sh --git . "$REV" "$OUT" --repro
BUNDLE_SHA=$(cut -d' ' -f1 "$OUT/$NAME.tar.sha256"); echo "$NAME $BUNDLE_SHA"   # write both down
```

**Expected output:**
- `exported … = commit <REV> (tree <TREE>)` and `reproducible server and web: true`;
- `flh-staging-bundle: VERIFIED flh-staging-<tree12>: commit <REV>, tree <TREE>, …`
  printed twice (the directory and the transfer file);
- the bundle, transfer and SHA-256 lines.

The builder refuses a tree that does not hash to `REV^{tree}`.

**Artifact names:** they are derived from the tree and used unchanged in
every later step:
- the directory `flh-staging-<tree12>/`;
- the transfer file `flh-staging-<tree12>.tar` and its `.tar.sha256`;
- the image `flh-staging:<tree12>`.

### 1.1 What the bundle pins

`MANIFEST.json`:
- `revision.commit` and `revision.tree_id`;
- `content_sha256`, a digest of every source file's path, mode and SHA-256;
- the image tag and the labels `org.opencontainers.image.revision` and
  `org.flh.staging.tree-id`;
- the SHA-256 of `/app/server` and the digest of the `/app/web` files;
- the migration ledger it ships (21);
- the SHA-256 of every script, doc and override in the bundle.

`BUILD.json` records this build: the image ID, the `image.tar` SHA-256 and
the time. `SHA256SUMS` covers every file.

### 1.2 Reproducibility: which hashes are stable

| Artifact | Same commit, built twice | Why |
| --- | --- | --- |
| Tree ID, `content_sha256`, bundle and image names | **stable** | computed from the exported source only |
| `/app/server` SHA-256, `/app/web` digest | **stable** (checked by `--repro` with a no-cache rebuild) | pinned base images, `npm ci`, `go build -trimpath`, verified modules |
| `repo/*` scripts and docs, `staging.override.yaml` | **stable** | copied bytes; the override names the tree tag |
| `MANIFEST.json` | **stable** (byte-identical) | holds only the stable values above |
| Image ID, `image.tar` | stable only while Docker's build cache is reused; a no-cache build changes them | layer and config timestamps |
| `BUILD.json`, `SHA256SUMS`, the transfer `.tar` and its SHA-256 | **differ per build** | `BUILD.json` holds the build time and image ID |

So compare two builds by `MANIFEST.json`, not by the tar SHA-256. The tar
SHA-256 identifies one specific build, and the host requires it at install
time. Evidence: STANDIN-REHEARSAL.md "Reproducibility".

## 2. IAM (an IAM administrator, Console; once)

```bash
python3 -I $S/iam/render_policies.py --account <ACCOUNT_ID> --ami <AMI_ID> --out ~/flh-stg-iam
python3 -I $S/tools/preflight.py --policies ~/flh-stg-iam     # expect READY
```

1. **Create the four policies with exactly these names:**
   - `flh-stg-host-boundary` from `flh-stg-host-boundary-policy.json`;
   - `flh-stg-deploy`;
   - `flh-stg-deploy-ec2`;
   - `flh-stg-operate`.

   Use **IAM → Policies → Create policy → JSON** for each. Attach the
   boundary to nobody.
2. **Attach the last three to the operator user** (FLH-087: `flh-experiment`).
   Keep `ReadOnlyAccess` on that user: Terraform's reads rely on it, as in the
   demo.
3. **Delete `~/flh-stg-iam`** after creating the policies. It holds the
   account ID.

### 2.1 Offline permission review (release lane, 20261118; untested until used)

`python3 -I $S/iam/review_permissions.py` maps every Terraform resource
type, every runbook call of the operator and every host call (80 actions) to
the templates. Expected: `every required action is allowed`. The templates
equal `make_policies.py`'s output (`preflight.py`).

**Fixed in this review:** this would have ended the first apply in
`AccessDenied`. `CHANGES.txt` records it:
- **The data volume:** it is created with tags. That needs `ec2:CreateTags`
  under `ec2:CreateAction=CreateVolume`, which the template lacked.
- **Leftovers removed:** the demo's `AllocateAddress` and
  `AuthorizeSecurityGroupIngress` came off the same tag-on-create list.

Details: STANDIN-REHEARSAL.md §16.

**Deliberately broad:**
- `ssm:UpdateInstanceInformation` and `ssmmessages:*Channel` on `*`: the AWS
  minimum for Session Manager.
- `kms:Decrypt` on `*`, but only through SSM.

Everything else is scoped by name prefix `flh-stg-*`, by the tags
`Project=flh` and `Component=workbench-staging`, or by the reviewed instance
shape and AMI.

## 3. Terraform: preflight, plan, offline check, apply (operator)

```bash
python3 -I $S/tools/preflight.py --tools                     # expect READY
cd $S/terraform
cp terraform.tfvars.example terraform.tfvars                 # ignored by Git
#   fill: run_id (UTC, e.g. 20261118T090000Z), expires_at (<= 24 h ahead), ami_id, compose_plugin_sha256
cd - && python3 -I $S/tools/preflight.py --tfvars $S/terraform/terraform.tfvars --policies ~/flh-stg-iam --bundle "$OUT/$NAME.tar" --sha256 "$BUNDLE_SHA"
```

**Expected:** `READY: N passed, 0 failed`. A `FAIL` names what to fix.

### 3.1 Init and validate

```bash
cd $S/terraform
terraform fmt -check && terraform init && terraform validate
cd - && python3 -I $S/tools/preflight.py --after-init        # provider checksums == the reviewed demo lock
```

The lock file `$S/terraform/.terraform.lock.hcl` is created by `init`.
Commit it after review, as FLH-085 did for the demo; it is not ignored.

### 3.2 Plan and check offline (read-only)

```bash
cd $S/terraform
terraform plan -out stg.tfplan                               # expect: 21 to add, 0 to change, 0 to destroy
terraform show -json stg.tfplan > stg.plan.json              # both ignored by Git: they hold the account ID
python3 -I ../tools/plan_check.py --mode create stg.plan.json
```

**Expected:** `plan (create): 21 to add, 0 to change, 0 to destroy, 0 to replace`
followed by `SAFE`.
- **On `STOP`, do not apply.** INVENTORY.md §4 explains each rule.
- **Before the plan:** `data.aws_iam_policy.host_boundary` fails until §2 is
  done.

### 3.3 Apply (starts billing)

```bash
terraform apply stg.tfplan
IID=$(terraform output -raw instance_id); BUCKET=$(terraform output -raw bucket); echo "$IID $BUCKET"
cd -
```

Re-plan at any time with `--mode update`; it must say `0 to add, 0 to change,
0 to destroy`.

## 4. Parameters (operator; no value is ever printed back)

```bash
for kv in FLH_DATA_DIR=/srv/flh-staging/data/app FLH_HOST_PORT=8080 FLH_UID=1000 FLH_GID=1000 AI_PROVIDER=rule-based \
  EXTRACTOR_PROVIDER=disabled SUGGESTION_PROVIDER=disabled LISTENING_PROVIDER=disabled READING_PROVIDER=disabled \
  WRITING_PROVIDER=disabled SPEAKING_TRANSCRIPTION_PROVIDER=disabled SPEAKING_PROVIDER=disabled HTTP_WRITE_TIMEOUT=75 \
  LISTENING_PLAYLIST_SOURCE=disabled LISTENING_AUTO_PREPARE=disabled LISTENING_NOTIFY=disabled; do
  aws ssm put-parameter --region $REGION --type String --overwrite --name "/flh/staging/${kv%%=*}" --value "${kv#*=}" > /dev/null
done
aws ssm get-parameters-by-path --region $REGION --path /flh/staging --query 'length(Parameters)'   # expect 16
```

## 5. Upload and install the bundle

On the operator machine:

```bash
aws s3 cp "$OUT/$NAME.tar" "s3://$BUCKET/releases/" && aws s3 cp "$OUT/$NAME.tar.sha256" "s3://$BUCKET/releases/"
aws ssm start-session --region $REGION --target "$IID"
```

In the session: the host waits for cloud-init, and the operator works as
`ec2-user`. That is uid 1000, the container's `FLH_UID`; never use root for
the steps below.

```bash
sudo cloud-init status --wait                                # expect: status: done
sudo -iu ec2-user
. /etc/flh/staging.conf                                      # REGION BUCKET PARAM_DIR ROOT PORT (no secret)
docker compose version && sqlite3 --version && findmnt "$ROOT/data" && systemctl list-timers flh-staging-expire.timer
flh-staging-env "$REGION" "$PARAM_DIR" "$ROOT/staging.env"    # names with set/empty only; 0600
NAME=flh-staging-<tree12>; BUNDLE_SHA=<the 64-hex value from §1>   # typed from the operator machine, not read from S3
aws s3 cp --region "$REGION" "s3://$BUCKET/releases/$NAME.tar" "$ROOT/transfer/"
flh-staging-bundle install "$ROOT/transfer/$NAME.tar" --sha256 "$BUNDLE_SHA"
flh-staging-bundle status
```

**Expected:**
- `verified and unpacked`, then `image sha256:… loaded`;
- the wrapper's summary: `project: flh-staging (isolated rehearsal; image flh-staging:<tree12>)`,
  every provider off;
- `IDENTITY OK {"commit": "<REV>", "image_matches": true, "labels_match": true, "readyz": 200, "ready": "ready", "server_matches": true, …}`;
- `INSTALLED flh-staging-<tree12>`.

**Refusals:** the tool refuses, before touching the service, an altered or
wrong transfer file (SHA-256), unsafe tar members, changed, added or missing
files, inconsistent identity, or a database newer than the bundle.

**A dropped SSM session does not interrupt `install` or `rollback`:** both
ignore SIGHUP and keep `deploy.log`. Reconnect and run `flh-staging-bundle
status`. Rehearsed: about 4 s for an install on the stand-in.

The daily wrapper is the bundle's own copy. Define a shell helper for the
later steps:

```bash
stg() { FLH_DAILY_ENV="$ROOT/staging.env" FLH_COMPOSE_PROJECT=flh-staging \
        FLH_COMPOSE_OVERRIDE="$ROOT/current/staging.override.yaml" bash "$ROOT/current/repo/scripts/daily/flh-daily.sh" "$@"; }
stg status
```

## 6. Restore the synthetic NAS-shaped backup

On the operator machine, `FIX` is the backup directory from §0:

```bash
FIX=<backup dir>; B=$(basename "$FIX")
tar -C "$(dirname "$FIX")" -cf "$OUT/$B.tar" "$B" && (cd "$OUT" && sha256sum "$B.tar" > "$B.tar.sha256")
aws s3 cp "$OUT/$B.tar" "s3://$BUCKET/backups/" && aws s3 cp "$OUT/$B.tar.sha256" "s3://$BUCKET/backups/"
cat "$OUT/$B.tar.sha256"                                     # note the value
```

On the host, as `ec2-user`:

```bash
B=<backup dir name>
cd "$ROOT/transfer" && aws s3 cp --region "$REGION" "s3://$BUCKET/backups/$B.tar" . && aws s3 cp --region "$REGION" "s3://$BUCKET/backups/$B.tar.sha256" .
sha256sum -c "$B.tar.sha256"                                 # compare the value with the operator's note too
tar -xf "$B.tar" && (cd "$B" && sha256sum --quiet -c SHA256SUMS) && cd
time stg restore "$ROOT/transfer/$B"
curl -fsS "http://127.0.0.1:$PORT/readyz"; echo
```

**Expected:** `restored … the previous data is kept at …`, then healthy and
`{"status":"ready"}`.
- **Read-only backup:** a backup whose files are read-only is refused with
  "the service could not write the restored database". Run `chmod 600` on its
  `app.db*` files as the message says, then `stg start`.
- **Measured on the stand-in:** restore → healthy 2.4 s for a 651 KB
  `app.db` (STANDIN-REHEARSAL.md §14). AWS adds the S3 transfer.
- **If the restore is refused or fails while preparing:** a checksum
  mismatch, too little space, a full disk or a read-only destination. The
  service keeps running and nothing changes; fix the cause and rerun.
- **Session dropped during `stg backup`:** the partial copy is kept only as
  `.incomplete` and the service is left stopped (documented). Run
  `stg start`.

## 7. Checks (endpoint checklist)

Run every row; each has an exact expected result.

| # | Check | Command | Expected |
| --- | --- | --- | --- |
| E1 | SSM agent online (operator) | `aws ssm describe-instance-information --region $REGION --filters Key=InstanceIds,Values=$IID --query 'InstanceInformationList[].PingStatus' --output text` | `Online` |
| E2 | App identity (host) | `flh-staging-bundle status` | `IDENTITY OK`, commit = `REV` from §1, `server_matches: true` |
| E3 | Readiness and liveness (host) | `curl -fsS http://127.0.0.1:$PORT/readyz; curl -fsS http://127.0.0.1:$PORT/healthz` | `{"status":"ready"}` and 200 |
| E4 | First supported write (host) | `curl -fsS -X POST -H 'Content-Type: application/json' --data @first-write.json http://127.0.0.1:$PORT/captures` (a synthetic `learning_capture_v1` document) | 201, then a replay 200 |
| E5 | Logs carry no failed request and no content (host) | `stg logs --since 30m \| grep -c 'request failed:'` | `0` (each 5xx would be one line with route, status and `X-Request-Id`) |
| E6 | Listener is loopback only (host) | `ss -ltn \| grep ":$PORT "` | only `127.0.0.1:8080` |
| E7 | No inbound rule (operator) | `aws ec2 describe-security-groups --region $REGION --filters Name=tag:Component,Values=workbench-staging --query 'SecurityGroups[].IpPermissions'` | `[[]]` |
| E8 | No Elastic IP and no DNS change (operator) | `aws ec2 describe-addresses --region $REGION --filters Name=tag:Component,Values=workbench-staging --query 'Addresses'` | `[]`; DNS untouched (Namecheap) |
| E9 | No public workbench access (operator) | `IP=$(aws ec2 describe-instances --region $REGION --instance-ids $IID --query 'Reservations[].Instances[].PublicIpAddress' --output text); curl -m 5 -sS "http://$IP:8080/" ; echo "exit $?"` | a timeout (exit 28) or refusal; **never** an HTTP answer |
| E10 | Private access works (operator) | `aws ssm start-session --region $REGION --target $IID --document-name AWS-StartPortForwardingSession --parameters portNumber=8080,localPortNumber=18080`, then `curl -fsS http://127.0.0.1:18080/readyz` in a second terminal | `{"status":"ready"}`; the browser at http://127.0.0.1:18080/ shows the workbench |
| E11 | Bounded runtime armed (host) | `systemctl list-timers flh-staging-expire.timer` | next run ≤ `max_runtime_hours` after boot |
| E12 | Restart persistence (host) | `stg restart` then re-read the E4 entry | the same entry, 200 |
| E13 | Backup to S3 (host) | `stg backup`, then tar + `sha256sum` + `aws s3 cp … s3://$BUCKET/backups/` | the `.sha256` verifies after download to a second target |

## 8. Rollback and recovery

- **Rollback to the previous verified bundle:** `flh-staging-bundle rollback`.
  - It verifies `previous` again from its files and refuses if the database
    has more migrations than that bundle knows.
  - It swaps `current` and `previous`, starts the bundle and checks identity.
    On a failed check it switches back.
  - Expected: `ROLLED BACK to flh-staging-<old> in N s`, with `IDENTITY OK`
    for the old commit (2.8 s on the stand-in).
  - Data written since the install stays: the same database, no migration in
    this release.
- **A failed install** checks the new bundle after the switch; if that fails,
  it switches back automatically and prints `FAILED: switching back`, then
  `IDENTITY OK` for the previous bundle.
  - Expect about a minute of downtime: the wrapper waits 60 s for health.
  - Exit 3 means the previous bundle could not be restored either. Then
    run `status` and read `deploy.log`.
- **An install interrupted halfway** (session dropped, Ctrl-C) leaves:
  - an unfinished unpack as `bundles/.partial-*`, removed by the next run;
  - `current` unchanged, or, if it stopped right after the switch, the
    service still on the previous image.

  `flh-staging-bundle status` says which. Run `install` again or `rollback`.
  Rehearsed: STANDIN-REHEARSAL.md §9–10.
- **A database newer than the bundle** (after a migration): restore the
  pre-install backup that `install` took (named in
  `$ROOT/deploy.log` as `backup`), then `rollback`.

## 9. Teardown and billable checks (same day)

On the host (optional), take a final backup and copy it to S3 as in E13 if
you want to keep it beyond the run. Then, on the operator machine:

```bash
cd $S/terraform
terraform plan -destroy -out stg-destroy.tfplan && terraform show -json stg-destroy.tfplan > stg-destroy.plan.json
python3 -I ../tools/plan_check.py --mode destroy stg-destroy.plan.json     # expect SAFE, 21 to destroy
terraform apply stg-destroy.tfplan
aws ssm delete-parameters --region $REGION --names $(aws ssm get-parameters-by-path --region $REGION --path /flh/staging --query 'Parameters[].Name' --output text)
aws ec2 describe-instances --region $REGION --filters Name=tag:Component,Values=workbench-staging Name=instance-state-name,Values=pending,running,stopping,stopped --query 'Reservations[].Instances[].InstanceId'
aws ec2 describe-volumes --region $REGION --filters Name=tag:Component,Values=workbench-staging --query 'Volumes[].VolumeId'
aws ec2 describe-addresses --region $REGION --filters Name=tag:Component,Values=workbench-staging --query 'Addresses'
aws s3api list-buckets --query "Buckets[?starts_with(Name, 'flh-stg-')].Name"
aws ssm get-parameters-by-path --region $REGION --path /flh/staging --query 'Parameters[].Name'
rm -f stg.tfplan stg.plan.json stg-destroy.tfplan stg-destroy.plan.json; cd -
```

**Expected:** every listing prints `[]`. The administrator then detaches
`flh-stg-deploy`, `flh-stg-deploy-ec2` and `flh-stg-operate`, or deletes the
four policies.

**Cost if forgotten:**
- The host powers itself off after `max_runtime_hours` and is then
  terminated.
- The data volume (~$0.64/month for 8 GiB) and the bucket remain until
  `terraform destroy`.

## 10. Cost assumptions (us-east-1 list prices; confirm in the AWS calculator)

| Item | Rate | 4-hour pass | Left running 30 days |
| --- | --- | --- | --- |
| t3.small | $0.0208/h | $0.08 | $15.18 |
| Public IPv4 (outbound only) | $0.005/h | $0.02 | $3.65 |
| gp3, 16 + 8 GiB | $0.08/GB-month | < $0.01 | $1.92 |
| S3 (bundle ~47 MB, backups < 1 MB), requests | | < $0.01 | < $0.05 |
| SSM parameters (standard), Session Manager | free | $0 | $0 |
| Transfer in; S3 via the gateway endpoint | free | $0 | ~$0 |
| **Total** | | **≈ $0.11** | **≈ $21** |

## 11. Live checks still pending (cannot be proven without AWS)

1. IAM: the four policies against real calls. Every `AccessDenied` names the
   action; add only that and record it.
2. `terraform validate` and plan for this root: 21 to add, against the
   provider lock.
3. AL2023 cloud-init:
   - the `docker`, `sqlite` and `python3` packages (Python 3.9 runs
     `flh-staging-bundle`);
   - the Compose plugin download and checksum;
   - the data-volume detection on Nitro NVMe;
   - `ec2-user` in `docker`;
   - the expiry timer.
4. Compose plugin v2.29.7 with the features the wrapper uses:
   `build: !reset null` and `config --environment`. The stand-in ran
   Compose 5.7.0; check with `stg check` right after cloud-init.
5. The IAM fix of §2.1 and every other statement under real requests.
6. SSM: session as `ssm-user`, then `sudo -iu ec2-user`; port forwarding to
   127.0.0.1:8080.
7. S3: upload and download through the gateway endpoint; the bucket policy's
   TLS-only rule.
8. Real transfer and restore times; the power-off and terminate at the
   deadline.
9. Teardown leaves nothing billable (§9 listings).
10. The cutover and its rollback (CUTOVER_DRY_RUN.md): dry runs only. A
    cutover for daily use needs its own production decision, because this
    root is bounded to 12 h by design.
