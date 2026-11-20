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
cd - && python3 -I $S/tools/preflight.py --inputs --tfvars $S/terraform/terraform.tfvars --policies ~/flh-stg-iam --bundle "$OUT/$NAME.tar" --sha256 "$BUNDLE_SHA" \
  --render-compose --card ~/flh-stg-launch-card.md
```

**Expected:** `READY: N passed, 0 failed, K open owner inputs`. A `FAIL` names what to fix.
- **`--inputs`:** every Terraform variable as SET, DEFAULT, MISSING, PLACEHOLDER or INVALID; the
  16 parameters of §4; the owner decisions still OPEN (authorization, backup).
- **The card:** a private (0600) copy of this run's values and commands, outside the repository.

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
python3 -I ../tools/plan_review.py stamp stg.plan.json --tfvars terraform.tfvars    # input hashes, ignored by Git
python3 -I ../tools/plan_review.py summary stg.plan.json                            # by service and blast radius
python3 -I ../tools/plan_review.py cost stg.plan.json                               # counts x cost_assumptions.json
```

To compare a new plan with the reviewed one, `plan_review.py diff reviewed.plan.json
stg.plan.json`: it ignores order and values known only after apply.

**Expected:** `plan (create): 21 to add, 0 to change, 0 to destroy, 0 to replace`
followed by `SAFE`.
- **On `STOP`, do not apply.** INVENTORY.md §4 explains each rule.
- **Before the plan:** `data.aws_iam_policy.host_boundary` fails until §2 is
  done.

### 3.3 Apply (starts billing)

```bash
python3 -I ../tools/plan_review.py freshness stg.plan.json --tfvars terraform.tfvars   # FRESH, else plan again
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
eval "$(flh-staging-bundle shell)"     # REGION BUCKET PARAM_DIR ROOT PORT and the helpers stg, bt, cc, dx (no secret)
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

The `eval` line above defines the helpers for the later steps. Each runs a copy
from the installed bundle (`$ROOT/current/repo/…`):
- `stg`: the daily wrapper, `flh-daily.sh`, in isolated mode;
- `bt`: `backup_tool.py`;
- `cc`: `cutover_check.py`;
- `dx`: `diagnose.py`.

Every value is shell-quoted. The bundle's SHA-256 is deliberately not among
them: type it from §1.

```bash
stg status
dx --env "$ROOT/staging.env" --running        # nothing found; else one [code] and its RECOVER line
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
aws s3 cp --region "$REGION" "s3://$BUCKET/backups/$B.tar" "$ROOT/transfer/"
bt unpack "$ROOT/transfer/$B.tar" --sha256 <the value noted on the operator machine> "$ROOT/transfer"
time stg restore "$(bt latest "$ROOT/transfer")"
curl -fsS "http://127.0.0.1:$PORT/readyz"; echo
```

**Expected:** `unpacked <B>: COMPLETE`, `restored … the previous data is kept
at …`, then healthy and `{"status":"ready"}`.
- **`bt unpack` checks first:** the SHA-256, then every member, then the
  backup's own sums and integrity. Only then does it rename the directory
  into place.
- **A truncated or damaged archive** is refused with what to do. Nothing is
  left behind.
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

### 7.1 Owner verification: logging, storage, restart, teardown (OWNER-ONLY)

These need the real host. Each row's local rehearsal is named; the AWS behaviour itself is unproven
until the owner runs it.

| # | Area | Command (host unless noted) | Expected | Rehearsed locally |
| --- | --- | --- | --- | --- |
| V1 | Logging: no failed request | `stg logs --since 30m \| grep -c 'request failed:'` | `0` | E5 on the stand-in (STANDIN-REHEARSAL.md) |
| V2 | Logging: no secret, no learner text | `stg logs --since 30m \| grep -c -E 'sk-[A-Za-z0-9]{8}\|AKIA[0-9A-Z]{12}\|FIXTURE-PRIVATE'` | `0` (synthetic captures carry `FIXTURE-PRIVATE` markers) | deploy-controls rehearsal: 0 in the logs of a failing start |
| V3 | Logging: diagnostics stay private | `ls -l "$ROOT/diagnostics"` after a failed install | files `-rw-------`, paths and IDs masked | deploy-controls rehearsal D4 |
| V4 | Storage: the data volume holds the data | `findmnt -no SOURCE,FSTYPE "$ROOT/data"; df -h "$ROOT/data"` | the attached EBS device, `xfs`, not the root disk | not possible locally |
| V5 | Storage: encrypted, tagged, survives a restart (operator) | `aws ec2 describe-volumes --region $REGION --filters Name=tag:Component,Values=workbench-staging --query 'Volumes[].[Encrypted,State,Size]'` | `[[true, "in-use", 8]]` | plan_check (encrypted) only |
| V6 | Restart: service | `stg restart && flh-staging-bundle status && dx --env "$ROOT/staging.env" --running` | `IDENTITY OK`, the E4 entry reads back, `nothing found` | first-run and recovery rehearsals |
| V7 | Restart: host reboot keeps the data and the timer (operator) | `aws ec2 reboot-instances --region $REGION --instance-ids $IID`, reconnect, `stg start`, V6 | the same data; `flh-staging-expire.timer` armed again (`OnBootSec`) | not possible locally |
| V8 | Teardown: nothing billable left (operator) | §9 listings | every listing `[]` | `plan_check --mode destroy` fixture only |
| V9 | Teardown: no local state left (operator) | `ls $S/terraform` after §9 | no `*.tfplan`, `*.plan.json`, `*.plan-stamp.json`, `terraform.tfvars` kept only if wanted | preflight publication check |

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
  - R3: `rollback --to flh-staging-<tree12>` chooses any installed bundle. The
    tool first prints the target it chose and why.
  - **The browser after a rollback (R3, demo lane finding):** the page `/` is
    revalidated by its file time. A browser that cached the newer page can get
    `304` from the older server and keep a page whose assets no longer exist.
    After a rollback:
    - reload with the cache bypassed, or clear the site data of the forwarded
      origin (`http://127.0.0.1:18080`);
    - check that the entry script in the page source (`/assets/index-….js`)
      equals what the server sends now:
      `curl -s http://127.0.0.1:18080/ | grep -o '/assets/index-[^"]*\.js'`
      (curl keeps no cache). The private build has no `flh-build` meta tag;
      only the demo build sets one.

    An ETag fix for `/` is proposed for the owner; it protects only releases
    built after it.
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
rm -f stg.tfplan stg.plan.json stg.plan-stamp.json stg-destroy.tfplan stg-destroy.plan.json stg-destroy.plan-stamp.json; cd -
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

The rates are also in `staging/cost_assumptions.json`; `plan_review.py cost` multiplies them by
the counts in the plan and names any resource type without a rate.

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

**Simulated locally vs needs AWS (release lane, 20261119):**

| Capability | Simulated locally (stand-in or offline tool) | Needs the real AWS run (owner) |
| --- | --- | --- |
| Inputs, tools, binding, publication | `preflight.py` on synthetic tfvars, parameters, stubs | `--tools` on the operator machine; real parameters |
| Plan review | `plan_check.py`, `plan_review.py` on synthetic plans | a real `terraform show -json` (with `variables`, `timestamp`) |
| Bundle | build, cache, reproduce, verify, compare, attest (real Docker) | `--git` build from a commit on main |
| Install, plan, target identity, diagnostics, cleanup | `flh-staging-bundle` on a stand-in (real Docker, isolated project) | the AL2023 host: Python 3.9, Docker, Compose v2.29.7 |
| Backup, restore, failed prepare, receipt | `recovery_rehearsal.py` (two sizes) | S3 transfer and EBS times |
| Cutover and rollback | `aborted_cutover_rehearsal.py` with recorded evidence | the NAS and AWS hosts, SSM as the access path, DNS unchanged |
| First run | `first_run.py` from a fresh fixture | §0–§4 and §9 (authorization, IAM, Terraform, parameters, teardown) |
| CI | the runner, hermetic, on this machine | GitHub Actions: `python-tools`, and `speaking.yml` after the Speaking Lab commit |
| Logging, storage, restart, teardown | partly (§7.1 "Rehearsed locally") | V4, V5, V7, V8 |

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
