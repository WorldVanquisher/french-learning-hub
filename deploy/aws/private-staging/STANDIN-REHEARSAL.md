# Private staging: what was rehearsed locally, and the results

Release lane, 20261118. It builds on the batch-5 stand-in (run 20261117T042813Z,
summarised at the end).

**What a stand-in is:** a directory laid out like `/srv/flh-staging` on the
EC2 host. The real image, the real `flh-staging-bundle` and the bundle's own
`flh-daily.sh` run against it unchanged. Two services are replaced:
- **S3:** a tar plus a SHA-256 copy, checked on arrival;
- **SSM:** a parameters file read by the same renderer.

**Isolation:**
- Every Compose project is `flh-stg-<run>-<name>`, on a free loopback port.
- The daily instance's container and image fingerprint was equal before and
  after every run (C2).

**What was not run:** no AWS, Terraform or Git command, and no provider
call (a local fake answered the Speaking fixture's calls).

**Where the evidence is:** the release lane's handoff area (outside Git,
run `release-staging-20261118`): `runs/<item>/results.tsv`, `evidence/`
and `timings.json`.

**Scripts:** all in `staging/rehearsal/`.

| Run | Script | Result |
| --- | --- | --- |
| 11 fixture | `make_fixture_backup.py` | 10/10 PASS |
| 8–10 bundles | `bundle_rehearsal.py` | 25/25 PASS |
| 12–15 restore, persist, failures | `standin_rehearsal.py` | 19/19 PASS |
| 17–19 endpoints, cutover, rollback | `cutover_dry_run.py` | 23/23 PASS |
| wrapper checks (no container) | `scripts/validation/flh094/test_wrapper.sh` | 92/92 PASS |
| offline tools | `staging/tests/test_staging_tools.py` | 30 tests OK |

Two runs failed first, in the rehearsal's own code, not the product. Both
were kept, renamed, not deleted:
- **the fixture's self-check:** a wrong table name;
- **the bundle run:** an invalid capture body that got a 400.

## 6–7. Pinned revision and reproducibility

`build_bundle.sh` built three bundles:
- **The v9 tree:** it hashes to `86ccae78…`, the batch-5 candidate, with the
  same content digest `291c9e6e…`.
- **Two worktree snapshots,** run as tree-only rehearsals with commit
  `null`: the owner path `--git . <rev>` adds the commit.
- **Shared app bytes:** all three have the same `/app/server` (`2a03f311…`)
  and web digest (`72115066…`).

Two builds of one tree, one cached and one `--no-cache --repro`:

| Artifact | Build A | Build B | |
| --- | --- | --- | --- |
| `MANIFEST.json` | `f4a95d33…` | `f4a95d33…` | **identical** |
| `staging.override.yaml`, `repo/*` | — | — | **identical** |
| server / web | `2a03f311…` / `72115066…` | same, and the `--repro` rebuild too | **identical** |
| image ID | `493a3656…` | `abac86dc…` (repro rebuild `333d7a88…`) | differs (timestamps) |
| `image.tar`, `BUILD.json`, `SHA256SUMS`, transfer tar | — | — | differ |

So two builds are compared by `MANIFEST.json`. The transfer tar's SHA-256
identifies one build and is what the host requires (RUNBOOK §1.2).

## 8. Verification refuses altered bundles before anything changes

`flh-staging-bundle install` on real bundles. Each case below exited 1
before `bundles/` or the service changed (V1–V7):
- **V1:** a wrong SHA-256.
- **V2:** an altered script.
- **V3:** an altered script with `SHA256SUMS` recomputed; `MANIFEST.json`
  pins the files.
- **V4:** an added file.
- **V5:** a missing file.
- **V6:** a renamed bundle (inconsistent identity).
- **V7:** another revision's `image.tar`, with `BUILD.json` and the sums
  rewritten; the image tag and labels disagree.

The unit tests add a forged label, a mismatched config digest, `..` and
symlink members, and the override naming another image.

## 9. Rollback to the previous verified bundle

**Install and upgrade:**
- Install OLD (the v9 tree; 3.8 s), restore the fixture, write W1.
- Install NEW (4.9 s). A pre-install backup is recorded in `deploy.log`.
  Identity OK; then write W2.

**Rollback:**
- `flh-staging-bundle rollback` takes **2.8 s**: it re-verifies OLD from its
  files, checks the ledger, swaps, starts and checks identity (image, labels,
  `/app/server`, `/readyz`).
- W1 and W2 are both present after it.
- Rolling forward again also passes.

## 10. Failed and interrupted installs

| Case | What happened | Result |
| --- | --- | --- |
| F1: SIGKILL while unpacking/verifying | `current`, the running image and identity unchanged; `status` names the interrupted unpack; the next run removes it | PASS |
| F2: a bundle whose migration fails (rehearsal-only tree with a broken `022`) | started, unhealthy, **switched back automatically**, the previous identity verified, ledger and data unchanged (one transaction per migration) | PASS, 70.6 s. **The service is down for about a minute** (the wrapper's 60 s health wait): single instance, no blue-green |
| F3: session dropped right after the switch (output closed + SIGHUP to the group) | the install continued (SIGHUP ignored during install/rollback) and verified the new bundle | PASS |

## 11. Synthetic NAS-shaped backup

`nas-fixture-20261118072610` was made by `flh-daily.sh backup`, on top of the
batch-5 synthetic backup (contract entry, old mistake, script revision 1)
plus API writes.

| Content | Count |
| --- | --- |
| `learning_entries` / `learning_captures` | 3 / 3 |
| `learning_capture_sources` | 1 |
| `listening_transcripts` (script revisions 1 and 2) | 2 |
| `listening_exercises` | 2 |
| `mistake_retry_marks` (mark, unmark, mark) | 3 |
| `speaking_exercises` | 1 |
| `speaking_takes` (metadata only) | 3 |
| `speaking_transcription_requests` / `speaking_transcriptions` (1 provider 500 stored, then retry; 1 lost response = unknown, plain retry 409, confirmed retry) | 5 / 5 |
| `speaking_transcripts` (v1 transcription, v2 corrected) | 2 |
| `speaking_feedback` | 1 |

- **Ledger:** 21.
- **Audio:** no audio bytes anywhere in `app.db`.
- **Sizes:** `app.db` 651,264 B, backup 684,259 B, transfer tar 696,320 B.

## 12–14. Restore, health, first write, persistence, second target, timings

| Step | Result |
| --- | --- |
| 12 | Fixture restored on `stg` (installed by the bundle tool). `DUMP` `bb28b141…` and every table count equal the fixture. Five `/readyz` calls change nothing. The entries, revision 2 (revision 1 kept), the retry mark and Speaking practice read back. `/readyz` and `/healthz` 200. First write `POST /captures` 201, replay 200 |
| 13 | `restart`: the write and the restored data persist. The `stg` backup was copied (tar + SHA-256) and restored into `dr`: snapshot and `DUMP` equal, the write present, `dr` identity OK |

| Timing (local NVMe, no network) | Seconds |
| --- | --- |
| install (verify, load, switch, identity) | 3.95 |
| restore command (fixture) → healthy | 2.39 |
| ready after the restore command returned | 0.02 |
| restart → healthy | 2.34 |
| backup (stop, copy, verify, start) | 2.43 |
| second target: restore → ready | 3.93 |
| rollback (§9) | 2.79 |
| failed install with automatic switch back (§10) | 70.6 |

AWS times will differ: the network transfer, EBS and t3.small are pending
live checks.

## 15. Failures on a running service, and the fix

Rehearsed with the fixed wrapper on `stg`, and with the previous wrapper on a
comparison host.

| Failure | Previous wrapper | Fixed wrapper |
| --- | --- | --- |
| Restore into a read-only destination | the service was **stopped first**, then `mkdir` failed with no guidance (X1-older: gap reproduced) | refused **before** the stop; the service stays up; the message names the cause (X1) |
| Disk fills during the restore copy | the service was stopped, and a **partial staging copy was left** (X2-older) | refused before the stop; the partial copy is removed; the service stays up (X2) |
| Backup interrupted by a session hangup mid-copy | `.incomplete` kept, data intact, the service left stopped (documented); `start` recovers in about 2 s | unchanged (same handling) |

- **The fix:** in `scripts/daily/flh-daily.sh` restore, the checksums, free
  space, staging copy and integrity check now run before the stop. An EXIT
  trap removes a partial staging copy and names the cause.
- **Tests:** the wrapper tests gained six checks. They pass on the fixed
  wrapper (92/92). Four of them fail on the previous wrapper.

## 16. IAM templates and generator

- **Generator agreement:** `make_policies.py` regenerated `iam/out/`
  byte-identically before the change (`preflight.py` checks this every run).
- **Rendering:** `render_policies.py` fills the account ID and AMI, refuses
  output inside the repository, and leaves no placeholder (tests).
- **Review:** `review_permissions.py` maps every Terraform resource type, the
  operator's runbook calls and the host's calls (80 actions) to the
  templates.

| Finding | Severity | Status |
| --- | --- | --- |
| `aws_ebs_volume.data` is created with tags, which needs `ec2:CreateTags` under `ec2:CreateAction=CreateVolume`. The template's tag-on-create list lacked `CreateVolume`. **The first apply would fail with AccessDenied** | missing | **fixed** in `make_policies.py` (Ec2TagOnCreateOnly); the review flags the earlier templates |
| The same list allowed `AllocateAddress` and `AuthorizeSecurityGroupIngress` (demo leftovers; no public path here) | unexpectedly broad | **removed** |
| `iam:DeleteRole` under the `iam:PermissionsBoundary` condition | checked against AWS's service authorization reference: the key is supported | no change |
| Session Manager actions on `*`; `kms:Decrypt` on `*` only via SSM; EC2 management account-wide but only on `Project=flh`/`Component=workbench-staging` tagged resources | broad by design | kept (as in the reviewed demo) |
| Update/start/stop actions allowed but used by no create/destroy step (`ModifyInstance*`, `ReplaceRoute`, `Start/Stop/RebootInstances`, untag) | unused, tag-scoped | kept (Terraform updates, operator stop/start) |
| Host role has no `s3:AbortMultipartUpload` for `backups/` | minor | not added: the bucket lifecycle aborts incomplete uploads after 1 day |

Conditions are not evaluated offline. Every policy stays untested until
used on AWS.

## 17–19. Endpoint checks, cutover and rollback (dry runs)

- **Endpoint checks** (RUNBOOK §7, the rows that need no AWS):
  - E2: identity, including `/app/server`;
  - E3: `/readyz` ready, `/healthz` 200;
  - E4: first write 201;
  - E5: no `request failed:` line and no learning content in the logs;
  - E6: the port is published on 127.0.0.1 only.

  All PASS. E1 and E7–E11 need AWS.
- **Cutover** (CUTOVER_DRY_RUN.md, C1–C8, all PASS):
  - AWS staging data moved aside;
  - T0 after two NAS writes;
  - the settings-file guard refuses `status` and `start`;
  - final backup `DUMP` == T0;
  - verified transfer;
  - AWS restore with `DUMP` and `COUNTS` == T0 and integrity ok;
  - smoke test without new data;
  - T1, then the first AWS write;
  - the NAS stays intact.

  The freeze window was 3.3 s on the stand-in.
- **Rollback** (R0–R2, all PASS):
  - the measurement found the AWS-only write, which a naive NAS restart
    would lose (case B);
  - AWS backup and guard;
  - migration compatibility (21 ≤ 21);
  - NAS restore: `DUMP` == AWS, the AWS-only write present, the T0 data
    kept aside.

  Total: 3.0 s.

## Batch 5 (run 20261117T042813Z), for reference

- **The first stand-in:** run `standin-3`, 25/0, on bundle v6, later re-run
  on v9 (27/0).
- **What it proved:**
  - the bundle's override runs the loaded image with no build on the host;
  - parameter-rendered settings work with the wrapper and never print
    values;
  - a read-only backup restores read-only and the write check refuses to
    start it (27b, still true);
  - backup → restore into a second target gives equal snapshots.
- **What it did not cover:** the bundle tool, pinned revisions, rollback and
  failure handling. The rehearsals above cover those.

## Not covered without AWS

These are pending live checks (RUNBOOK §11):
- EC2, AL2023 and cloud-init;
- the IAM policies against real calls;
- S3 and SSM permissions;
- SSM sessions and port forwarding;
- the power-off timer;
- real transfer and restore times;
- Compose v2.29.7 on the host;
- the Terraform plan.
