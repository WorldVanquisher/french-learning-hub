# FLH R3: AWS migration and staged rollout (release lane plan)

Release lane, 2026-11-20.
- **Base:** `main` at `b96675f87ac7` (tree `57ec7085dc61`), which includes PRs
  #160–#163.
- **Worktree:** `worker/20261120-postmerge/release`.
- **Status:** this is the plan, and it authorizes nothing. No AWS resource was
  created, changed or deleted.
- **Evidence:** the masked evidence (read-only AWS observations, local runs) lives
  in the lane's private handoff area. It is referenced below by evidence class,
  not copied, and no account, resource, address or host identifier appears in
  this file.

It builds on, and does not repeat, the private-staging design already on main:
- [`deploy/aws/private-staging/AWS_STAGING_PLAN.md`](../../deploy/aws/private-staging/AWS_STAGING_PLAN.md):
  design, storage, IAM derivation, cost;
- [`RUNBOOK.md`](../../deploy/aws/private-staging/RUNBOOK.md): the owner's
  commands;
- [`INVENTORY.md`](../../deploy/aws/private-staging/INVENTORY.md): the 21
  resources and the stop rule;
- [`CUTOVER_DRY_RUN.md`](../../deploy/aws/private-staging/CUTOVER_DRY_RUN.md):
  cutover and rollback;
- [`STANDIN-REHEARSAL.md`](../../deploy/aws/private-staging/STANDIN-REHEARSAL.md):
  local results.

R3 reconciles that work with the new base and adds what a production move
needs: per-environment settings, read-only verification permissions, recovery
objectives, observability and the cutover approvals.

## 1. Lanes and file ownership (one writer per file)

| Lane | Owns | R3 relies on it for |
| --- | --- | --- |
| **Release** (this plan) | infrastructure (`deploy/aws/private-staging/**`), private release bundle, deployment sequencing, rollback, `scripts/release/**`, this file | — |
| **Extraction** | the extraction service and every model runtime (OpenAI extractor configuration, `tools/extraction`, `tools/speaking`, `tools/embedding/e5`, `deploy/aws/sagemaker-extractor`) | the endpoint and model handoff contract, model placement, and model rollback (§8, R3-061–070) |
| **Workbooks** | learner integrity: workbook tables, exports, integrity checks (`tools/workbooks`, learning-history export) | the backup contract and the integrity checks after restore (R3-041, R3-044) |
| **Demo** | the public artifact and the public-demo stack (`deploy/aws/terraform`, `deploy/aws/host`, `scripts/demo/**`) | public provenance (R3-092), and demo identity for monitoring separation (R3-057) |

The release lane changes no file another lane owns. A needed change in
another lane's file is recorded as a dependency with a ready patch, never made
here.

## 2. Evidence classes (what each kind of proof can and cannot show)

| Class | Where | Who runs it | Can prove | Cannot prove |
| --- | --- | --- | --- | --- |
| **L**: local offline | release worktree; no network, no Docker | agent | syntax, policy shape, plan-check rules on fixed plans, documents | anything about a real host or account |
| **S**: stand-in | Docker on loopback, isolated Compose project, synthetic data, this machine | agent | install, verify, rollback, restore, cutover order, measured times on this hardware | AL2023, EBS, S3, SSM, IAM behaviour |
| **R**: AWS read-only | account (masked), us-east-1, Identity Center profiles `flh-staging-release` and `flh-staging-extraction` | agent, describe/list/get only; nothing billed | what exists now, and which read actions a profile has | any staging behaviour |
| **G**: AWS staging | the private-staging root, synthetic data, bounded runtime | **owner** after authorization (§7) | the real host, IAM, S3, SSM, times, cost, teardown | production data and traffic |
| **P**: AWS production | a production instance of the same root, the learner's data | **owner**, separate decision | the move itself | — |

Each R3 item records which class proves it. An item that needs **G** or
**P** is `owner-only`, or `blocked` while the authorization is missing. It is
then rehearsed in **S** or **L** with equivalent inputs, and recorded as
`verified-rehearsal`, never as done on AWS.

## 3. Scope (R3-001 to R3-010)

### 3.1 Source and destination services (R3-001)

| Service | Source today (the NAS host, documented in `docs/RELEASE.md`; the daily instance is not inspected by agents) | Destination, phase 1 | Moves? |
| --- | --- | --- | --- |
| FLH server + workbench (one image) | Compose project `french-learning-hub`, image `french-learning-hub:local`, loopback `127.0.0.1:8080`, `scripts/daily/flh-daily.sh` | the same image built from the release commit, `flh-staging-bundle` + `flh-daily.sh` on one EC2 host (AL2023), loopback port | yes |
| SQLite `app.db` (+WAL), 21 migrations | `FLH_DATA_DIR` on the NAS | encrypted gp3 EBS data volume, `/srv/flh-staging/data` | yes (restore of a verified backup) |
| Backups | `flh-daily.sh backup` (directory + `SHA256SUMS`), on the NAS | the same command on the host, plus an off-host copy in S3 `backups/` (SSE-S3, versioned) | yes |
| Settings and keys | `~/.config/flh/daily.env` (0600) | SSM Parameter Store `/flh/<env>/` (String; SecureString for keys), rendered to a 0600 file by `flh-staging-env` | yes; values are never copied by agents |
| Access path | browser on loopback / private tunnel, `HTTP_ALLOWED_HOSTS` | SSM port forward to the loopback port. No inbound rule, no public name | yes |
| OpenAI-backed providers (analyzer, extractor, suggestions, listening, reading, writing, speaking feedback) | opt-in on the NAS | off in staging; production enables only what the owner lists (egress 443) | owner decision |
| Speaking transcription service (`tools/speaking`, no auth, loopback or private address) | local service | **not moved** (phase 1) | no |
| E5 embedding service (`tools/embedding/e5`, CUDA, no auth) and Qdrant | laptop GPU / optional Qdrant | **not moved**; semantic search off, index rebuildable | no |
| Daily Listening pull, YouTube, Telegram | optional timer / opt-in | not installed; only after cutover, never on two hosts | later |
| Public demo | FLH-084 stack in AWS (Demo lane) | unchanged and separate | no |

### 3.2 Data owners and retention (R3-002)

| Data | Owner | Retention | Migration rule |
| --- | --- | --- | --- |
| Learner records: entries, captures, analyses, feedback, knowledge units and concepts, annotations, workbook rows, speaking metadata, exam sessions | the learner (owner); integrity: Workbooks lane | indefinite; append-only history (CLAUDE.md design priorities) | moved only as a verified whole-database backup; never edited, merged or partially copied |
| Backups | owner; mechanism: release lane | staging (synthetic): 14 days (bucket lifecycle). **Production: proposed 35 daily copies in S3, plus the NAS final backup kept for the rollback window** | `SHA256SUMS` verified before every restore |
| Settings and provider keys | owner | as long as used | never in a backup, image, bundle, Terraform state, log or the repository |
| Release bundles | release lane | current + previous (rollback); staging objects expire after 14 days | pinned by tree ID and SHA-256 |
| Host logs (Docker json-file, journald) | release lane | journald limits (`deploy/aws/host/journald-flh.conf` pattern) | never contain learner content (5xx lines carry route, status and request ID only) |
| Vectors and semantic index | Extraction lane | rebuildable | not migrated |
| Audio | — | **none stored** (Speaking keeps metadata only) | nothing to move |
| Public demo artifact (`demo.db`, synthetic) | Demo lane | per demo release | not part of this migration |

### 3.3 Current topology (R3-003)

- **NAS host:** this machine.
  - The daily Compose project serves the workbench on loopback.
  - The data, backups and settings stay local.
  - Optional model services run on the NAS or the laptop over a private
    network.
  - Agents never start, stop, read or inspect the daily instance, its data or
    its settings.
- **AWS (observed read-only, class R, 2026-11-20).** In us-east-1 the account
  holds:
  - **one EC2 instance:** `t4g.micro`, arm64, running, IMDSv2 required. It is
    tagged `Project=flh`, `Component=public-demo`, `Task=FLH-084`,
    `ManagedBy=terraform`, `Name=flh-demo-host`, uses the `flh-demo-host`
    instance profile, and sits in the demo VPC (`flh-demo-vpc`, a /24).
  - **its security group:** inbound TCP 80 and 443 from anywhere, outbound TCP
    443 only. The FLH-088 public HTTPS rules are therefore in effect. The
    instance has a public address.
  - **the default VPC:** present and unused.
  - **SageMaker:** no endpoints and no training jobs.

  Everything else (volumes, addresses, buckets, IAM, SSM, alarms, budgets,
  quotas, pricing) was **refused** to both profiles (§9).
- **Conclusion on reuse:** the existing ARM64 instance **is the public demo**,
  so it is **not reused**:
  - it is public (80/443 open);
  - its instance role and stack belong to the Demo lane;
  - the private workbench has no authentication and must never share a host,
    role or security group with a public service.

  This keeps the prior decision ("a separate host, never the public-demo
  instance").

### 3.4 Regions and environments (R3-004)

| Environment | Region | State | Authorized? |
| --- | --- | --- | --- |
| local (L, S) | — | available | yes (this lane) |
| AWS read-only (R) | us-east-1 | available: two Identity Center profiles, same account | yes, read-only only |
| AWS staging (G) | us-east-1 (proposed; same region as the demo, FLH-087) | **not created** | **no**: budget cap, runtime window, account confirmation and data scope (synthetic only) are missing |
| AWS production (P) | us-east-1 (proposed) | not designed into Terraform until R3-022; never applied | **no**: separate owner decision |

No other region is in use or proposed: one region keeps the IAM policies
(region-scoped ARNs), the AMI pin and the cost model simple.

### 3.5 Release and image identity (R3-005)

| Item | Identity |
| --- | --- |
| Release commit | `b96675f87ac77bb139bf71926c69434033f0c202` (`main`, merge of #163) |
| Tree | `57ec7085dc613fa32236f04f3c48150a8e1ab9be`. It is identical to the stacked trial tree verified during the #161/#163 repair: Go 25 packages, web 739/739, every hermetic Python suite |
| Staging bundle | `flh-staging-57ec7085dc61` (built from the commit by `build_bundle.sh --git`; image, archive and bundle digests recorded at R3-032) |
| Daily image | **unknown to agents** (`french-learning-hub:local` is not inspected). The owner records its ID and commit label at cutover precondition P2 |
| Public demo release | Demo lane's; it is not changed by R3 |

### 3.6 Components that stay put initially (R3-006)

- **E5 embedding and Qdrant:** semantic search stays off on AWS; the index is
  rebuilt later from SQLite, never copied.
- **Speaking transcription service:** local, no authentication. AWS reaching it
  needs a private path that does not exist yet.
- **Daily Listening timer and Telegram notifications:** installed on AWS only
  after cutover, and never on two hosts.
- **OpenAI providers:** off in staging. Production enables only the providers
  the owner lists.
- **The public demo stack and its DNS (Namecheap):** untouched.
- **Model training and SageMaker jobs:** deferred (the repository roadmap).

### 3.7 Uptime and restore objectives (R3-007, proposed; owner decision)

This is a single-user personal service: no SLA and no multi-host
availability.

| Objective | Proposal | Basis |
| --- | --- | --- |
| Availability | best effort, ≥ 99% per month, measured by the readiness alarm (R3-054) | one host; restart-on-failure through Compose `restart: unless-stopped` |
| RPO, normal operation | ≤ 24 h: a daily `backup` copied to S3. Hourly is possible at a few cents a month, but each backup stops the service briefly | `flh-daily.sh backup` stops the service, copies, verifies and starts it again: 2.43 s on the stand-in (STANDIN-REHEARSAL.md §12–14) |
| RPO, cutover | 0. The write freeze from T0 to T1 makes the NAS final backup equal the AWS start state (`DUMP` equal) | CUTOVER_DRY_RUN.md |
| RTO, bad release | ≤ 15 min: `flh-staging-bundle rollback` to the previous verified bundle | stand-in rollback timings (R3-040) |
| RTO, lost host or volume | ≤ 2 h: re-apply the root, then restore the newest S3 backup | stand-in restore in seconds; host provisioning dominates (to be measured in G) |
| RTO, failed cutover | ≤ 30 min: rollback A (no AWS write) or B (AWS writes carried back) | CUTOVER_DRY_RUN.md, R1–R2 |

### 3.8 Success and failure criteria (R3-008)

**A staging pass succeeds** when:
- the RUNBOOK E-rows all pass;
- `plan_check.py` shows no STOP on create, update and destroy;
- `flh-staging-bundle status` reports `IDENTITY OK` for the exact bundle;
- the synthetic restore's `DUMP` and `COUNTS` equal the source;
- the deliberately broken deploy rolls back;
- the post-teardown listings show nothing billable;
- the spend stays under the authorized cap.

**A cutover succeeds** when:
- P1–P5 hold;
- every step before T1 passes `cutover_check.py`;
- the first AWS write returns 201;
- the first S3 backup verifies and restores on a disposable volume;
- no abort criterion fires within the observation window.

**Failure:** any STOP, DO-NOT-SWITCH, ROLLBACK or DIVERGED verdict, an
`IDENTITY` mismatch, a readiness failure longer than the agreed window, or
spend over the cap. Each failure has its rollback in CUTOVER_DRY_RUN.md or
RUNBOOK §8.

### 3.9 Owner authorizations for each live step (R3-009)

| # | Live step | Inputs the owner must supply | Run by | Evidence |
| --- | --- | --- | --- | --- |
| A1 | Grant the read-only verify policy (§9) to the `FLHStagingRelease` permission set | approve the actions in §9 | IAM administrator | R: the refused reads succeed |
| A2 | Staging authorization | account (confirm), us-east-1, budget cap (proposed $5 per pass), runtime window (proposed 4 h, maximum 12 h), data scope = synthetic only | owner | written approval in the handoff |
| A3 | Create the four `flh-stg-*` IAM policies | the rendered policies (`render_policies.py`, outside Git) | IAM administrator | RUNBOOK §2 |
| A4 | `terraform plan` and `apply` of the staging root | A2 + A3, a fresh `run_id` and `expires_at` | owner | plan JSON passes `plan_check.py`; apply output |
| A5 | SSM parameters, bundle and backup upload | A4 | owner | RUNBOOK §4–6 |
| A6 | Staging checks, a broken deploy, rollback, teardown | A4 | owner | RUNBOOK §7–9 |
| A7 | Production design approval (R3-022 settings, retention, alarms, the providers to enable) | owner | owner | approved diff |
| A8 | Production apply | A7 + a production budget | owner | plan check `--env production` |
| A9 | **Real learner data migration** (cutover T0–T1) | A8, a rollback window, the abort time limit, the decider | owner | `cutover_check.py` evidence |
| A10 | **Production DNS** (only if a public name is ever wanted) | separate decision; not needed for SSM access | owner | — |
| A11 | **Production model promotion** (any runtime the Extraction lane hands off) | Extraction lane's sealed contract + the owner | owner | R3-066 |

A9, A10 and A11 are separate decisions. None follows from approving staging.

### 3.10 Dependency map (R3-010)

```
L/S (agent, now)                         R (agent, read-only)        G (owner)              P (owner)
────────────────────────────────────     ───────────────────────     ────────────────────   ─────────────────────
R3-011..020 design ───────────────────┐  R3-004/003 inventory ─┐
R3-021..026 Terraform + IAM (L) ──────┼──────────────────────────┼─▶ A1 verify policy
R3-027..030 plan check / teardown (L) ┤                          │   A2 authorization ─▶ A3 IAM ─▶ A4 apply
R3-031..040 bundle + rollback (S) ────┤                          │                        │
R3-041..050 backup/restore (S) ◀── Workbooks: backup contract,    │                        ▼
             integrity checks ────────┤                          │   A5 upload ─▶ A6 checks/broken deploy/teardown
R3-051..060 observability (L/S) ◀── Demo: identity labels ───────┤                        │
R3-061..070 model path (L/S) ◀── Extraction: endpoint + model contract                    ▼
R3-071..080 staging verdict ──────────────────────────────────────────────▶ go/no-go ─▶ A7 design ─▶ A8 apply
R3-081..090 cutover runbook (S dry run) ──────────────────────────────────────────────────────────▶ A9 data move
R3-091..100 release seal ◀── Demo: public provenance fix (R3-092)                                 (A10 DNS, A11 model: separate)
```

**Blocking edges today:**
- A2 is missing, so every G and P step waits.
- Extraction has no endpoint or model handoff contract for an AWS-placed
  runtime: HANDOFF-2.2 defines none, and its R3 queue has not sealed.
- Workbooks' R3 queue has not sealed a backup contract; R3-041 uses the
  integrity rules already on main until then.
- Demo has not landed the public provenance fix: `scripts/demo/flh076/package.sh`
  on `main` still copies `base_url` into `RELEASE.json`.

Each lane continues independently; release-lane work proceeds in L, S and R
classes.

## 4. Architecture (R3-011 to R3-020)

### 4.1 Existing AWS scripts against the service's needs (R3-011)

| Script set | Built for | Fit for the private workbench | Gaps on the new base |
| --- | --- | --- | --- |
| `deploy/aws/terraform` + `deploy/aws/host/flh-release` (FLH-084/088) | the read-only public demo package; providers refused at startup; optional public HTTPS | **no**: no data volume, no backups, no secrets path, and a public entry point by design | none; it stays the Demo lane's |
| `deploy/aws/private-staging/staging/*` (release lane) | the full workbench image; durable data volume; S3 backups; SSM settings; SSM access; bounded lifecycle | **yes**, for staging | **(a)** the lifecycle is staging-only by construction: `expires_at`/`run_id` required, power-off timer, shutdown → terminate, bucket `force_destroy`, 14-day expiry. Production cannot use it unchanged (R3-022). **(b)** No scheduled backup: backups and S3 copies are operator commands (production needs a host timer, R3-042). **(c)** No alarms or counters (R3-053/054). **(d)** x86_64 only (R3-018). The settings renderer forwards any well-formed name, so the providers added since (Speaking transcription, Review Today zone, …) need no renderer change. Readiness (`/readyz` write probe, `storage_read_only`) and `restore_write_check.py` already match the runbook |
| `deploy/aws/sagemaker-extractor/*` (Extraction lane) | training and batch prediction jobs | **not a serving runtime** (no endpoint, and none exists in the account) | the serving contract belongs to Extraction (§8) |

### 4.2 Options for one containerized app with persistent SQLite (R3-012)

| Option | SQLite durability | Moving parts | Verdict |
| --- | --- | --- | --- |
| **EC2 + Docker Compose + separate EBS gp3 data volume** (current staging root) | block storage; WAL works (one host, local shared memory); the volume survives instance replacement | one instance, one volume, one bucket | **chosen** |
| ECS on EC2 with the same EBS volume | same | adds a cluster, task definitions and an agent for one container | no benefit at one container |
| ECS Fargate + EFS | **unsafe**: SQLite over NFS (locking, WAL shared memory) | — | rejected |
| ECS Fargate + task-attached EBS | the volume lives with the task; persistence through snapshot restore on each launch | snapshot pipeline | rejected (complex, slow rollback) |
| App Runner / Lambda | no persistent disk | — | rejected |
| Lightsail instance | block storage, fixed price | outside the Terraform, IAM and tag conventions already reviewed | viable alternative; not chosen |
| EC2 + SQLite replication to S3 (e.g. Litestream) | continuous RPO | a new dependency and process | deferred; would need its own decision (Scope Discipline) |

### 4.3 Staging topology (R3-013)

The staging topology is the existing private-staging root, unchanged in shape:
- **Network:** its own VPC (10.85.0.0/24), one subnet, an internet gateway for
  outbound traffic only, and an S3 gateway endpoint.
- **Host:** one `t3.small` (AL2023 x86_64, standard credits, IMDSv2 with hop
  limit 2), with a 16 GiB encrypted root and an 8 GiB encrypted gp3 data
  volume.
- **Storage and access:** one private bucket (`releases/`, `backups/`), SSM
  parameters, and SSM access.

**Rationale:**
- it reuses the shape FLH-087 actually applied for the demo (same AMI family,
  SSM-only access, egress 443);
- it keeps the demo's state, role and network separate;
- the image built on this machine is linux/amd64;
- the whole pass costs about $0.11 for 4 hours.

### 4.4 Public and private boundaries (R3-014)

- **Public:** only the demo stack. It is the Demo lane's, inbound 80/443
  (observed).
- **Private:** the workbench host.
  - **Network:** no inbound rule, no Elastic IP, no load balancer, DNS name,
    CloudFront or API gateway (`plan_check.py` STOPs on each).
  - **Service binding:** the service binds loopback on the host, and
    `HTTP_ALLOWED_HOSTS` stays loopback-only.
  - **Who can reach it:** only an IAM principal holding `flh-stg-operate`,
    through `ssm:StartSession` port forwarding to an instance tagged
    `Component=workbench-staging`.
- **Separation of stacks:** separate VPCs (10.84/24 demo, 10.85/24 staging,
  10.86/24 reserved for production), separate roles, buckets and parameter
  paths, and IAM conditions keyed on the `Component` tag.
- **Model services:** they have no authentication, so they are never put on a
  public address.

### 4.5 Minimum network paths (R3-015)

| Direction | Path | Phase 1 |
| --- | --- | --- |
| Inbound to the host | none | — |
| Operator → app | SSM Session Manager port forward → `127.0.0.1:<FLH_HOST_PORT>` | required |
| Host → SSM, SSM messages, EC2 messages | TCP 443, public regional endpoints through the internet gateway | required |
| Host → S3 (bundles, backups, AL2023 package repositories) | S3 gateway endpoint (no charge) | required |
| Host → GitHub releases (Compose plugin, pinned SHA-256, cloud-init only) | TCP 443 | first boot only |
| Host → OpenAI, YouTube, Telegram | TCP 443 | only for providers the owner enables (production) |
| Host → model services (Speaking, E5) | **none**: not reachable, and no private link exists | later, §8 |
| DNS, time | VPC resolver, Amazon Time Sync (link-local; not filtered by the security group) | implicit |

### 4.6 Capacity and storage assumptions (R3-016)

| Item | Staging | Production proposal | Basis |
| --- | --- | --- | --- |
| Instance | t3.small, 2 vCPU burstable, 2 GiB | t3.small; t4g.small after an arm64 build is tested | 46 MB image; single user; a Go server plus SQLite |
| Root volume | 16 GiB gp3 | 16 GiB gp3 | OS, Docker, two bundles |
| Data volume | 8 GiB gp3 | 20 GiB gp3, grow-only | the database (real size **unknown**: the owner measures `du -sh` of the data directory) + 2 restore copies + ~10 local backups |
| S3 backups | synthetic, 14 days | 35 daily copies; old versions 7 days | RPO ≤ 24 h |
| Throughput | gp3 baseline 3,000 IOPS / 125 MB/s | same | far above a single-user SQLite load |

### 4.7 Cost (R3-017)

These are list prices, not quotes. The Pricing API and Cost Explorer are
unavailable to the read-only profiles, and Cost Explorer is billed per
request. Every figure is to be confirmed in the AWS calculator before A2, A7
or A8.

| Scenario | Components | Estimate |
| --- | --- | --- |
| Staging pass, 4 h (A2) | t3.small $0.0208/h, public IPv4 $0.005/h, 24 GiB gp3, S3 cents | **≈ $0.11** (12 h maximum ≈ $0.33) |
| Staging left running until expiry | impossible past `max_runtime_hours` (≤ 12): the host powers off and terminates; volume and bucket cost cents until destroy | **< $0.50** |
| Production, normal (always on) | t3.small $15.18 + IPv4 $3.65 + 36 GiB gp3 $2.88 + S3 35 × ~100 MB ≈ $0.08 + 2 alarms $0.20 | **≈ $22 / month** (t4g.small: ≈ $19) |
| Production, peak | t3.medium $30.37 + IPv4 $3.65 + 66 GiB gp3 $5.28 + hourly backups for 7 days (168 copies) + more S3 + alarms | **≈ $42 / month** |
| Existing public demo (Demo lane, for the total) | t4g.micro $6.13 + IPv4 $3.65 (+ the Elastic IP when in use) + gp3 root + S3 | **≈ $11 / month** |

Not included:
- **OpenAI usage:** billed by the provider, not AWS. It is unchanged by the
  move.
- **Data transfer out:** the port-forward traffic and backups downloaded to
  the NAS stay inside the free tier at a single user's volume.

### 4.8 Region and instance restrictions (R3-018)

- **us-east-1 only:**
  - the IAM ARNs are region-scoped;
  - the AMI pin is regional;
  - the demo runs there.
- **Instance shape:** `t3.small` only, which the deploy IAM enforces.
  - A different type is AccessDenied by design, and needs an IAM edit.
- **x86_64 only:** this machine has no buildx or QEMU, so no arm64 image can
  be built here. `t4g` needs an arm64 build and test elsewhere first.
- **Unverified (the read-only profiles are refused the calls):**
  - the account's on-demand vCPU and Elastic IP quotas;
  - t3.small availability in the subnet's zone;
  - the AMI ID.

  The owner reads these at A2 with the runbook's §0 commands. The quota check
  is in §9's verify policy.

### 4.9 Rollback time per topology (R3-019)

| Failure | EC2 + Compose (chosen) | ECS/Fargate | NAS (today) |
| --- | --- | --- | --- |
| Bad release | `flh-staging-bundle rollback`: **2.8 s** on the stand-in, plus the session (~1 min) | new task-definition revision, minutes | re-tag the previous image + restart, minutes |
| Failed install | automatic switch back: **70.6 s** on the stand-in | deployment circuit breaker, minutes | manual |
| Lost host | `terraform apply` (instance only; the data volume is kept) + reinstall: **≈ 10–15 min** (estimate; measured in G) | task restart; the data volume problem remains | hardware dependent |
| Lost data volume | restore the newest S3 backup: seconds on the stand-in + transfer; **≤ 2 h** with provisioning | snapshot restore | restore the latest local backup |
| Failed cutover | rollback A (no AWS write): minutes; B (carry the AWS writes back): **3.0 s** restore on the stand-in + transfer | — | — |

### 4.10 Expected changes against today's production (R3-020)

"Production" today means two things:
- **the daily NAS instance:** the learner's data;
- **the public demo stack:** the public service.

| Area | Expected change | Guard |
| --- | --- | --- |
| Public demo stack | **none** | separate root and state; `plan_check.py` STOPs on any demo address; separate IAM (`flh-demo-*` vs `flh-stg-*`) |
| NAS daily instance | **none** until A9 | agents never touch it; the cutover is an owner step with T0/T1 evidence |
| AWS account | staging adds 21 resources plus four IAM policies (A3) and ~17 parameters, all tagged `Component=workbench-staging` | tag-conditioned IAM; the `ExpiresAt` and `Run` tags |
| DNS | **none** | no public name is needed (SSM access) |
| Cost | staging cents per pass; production ≈ $22 / month (owner decision A7/A8) | budget alert proposed at A2 |

## 5. Infrastructure changes (R3-021 to R3-030)

### 5.1 One root, two environments (R3-021, R3-022)

The existing private-staging root (`deploy/aws/private-staging/staging/terraform`) gains `var.environment`
(`staging` by default, or `production`) instead of a second copy. One `locals.environments` table holds:
- names (`flh-stg` / `flh-prd`) and the `Component` tag;
- the parameter path and the VPC range;
- the data-volume size and the shutdown behaviour;
- termination protection, bucket `force_destroy`, and the power-off timer verb.

The staging values are unchanged, so the staging user data renders byte for byte as before. Production also
gets its own S3 lifecycle: `backups/` are kept `backup_retention_days` (35) days, and `releases/` never
expire. Full table: `deploy/aws/private-staging/INVENTORY.md` §5.

### 5.2 State (R3-023)

The existing convention is local state on the operator's machine (no backend block; `.gitignore` covers
`*.tfstate*`, and the demo root does the same). R3 keeps it: production uses the Terraform workspace
`production` (`terraform.tfstate.d/production/`, ignored).

A precondition on `aws_vpc.stg` refuses:
- `environment = "production"` outside that workspace;
- `staging` inside it;
- a staging run without an expiry time, or a production run with one.

A remote backend (S3 + lock) is **not** introduced. It would be new shared infrastructure; the owner can
choose it at A7.

### 5.3 Tags (R3-024)

Every resource carries these tags through the provider's `default_tags`:
- `Project=flh`;
- `Component=workbench-staging|workbench-production`;
- `Environment=staging|production` (new);
- `Run`, `ExpiresAt` (`never` in production) and `ManagedBy=terraform`.

`plan_check.py --env` requires all of them.

### 5.4 Least-privilege permissions (R3-025)

`make_policies.py` derives the policies from the reviewed demo policies, and `review_permissions.py`
checks them against the Terraform and the runbook:
- **staging (`staging/iam/out`):** the four reviewed policies, unchanged;
- **production (`--env production`, `staging/iam/out-production`):** the same four as `flh-prd-*`, with
  every delete of data or settings withheld (`ec2:DeleteVolume`, `s3:DeleteBucket`, `s3:DeleteObject*`,
  `ssm:DeleteParameter*`). The review lists those as ADMIN-ONLY;
- **both:** a `*-verify-readonly` policy (§9). It allows only describe, list, get and view, and explicitly
  denies parameter values, KMS decrypt and `backups/*` objects.

`render_policies.py` fills either set outside the repository.

### 5.5 Checks (R3-026 to R3-030)

- **Syntax and behaviour without AWS:**
  - `terraform fmt -check`, `init -backend=false` against the demo root's committed lock
    (hashicorp/aws 6.69.1) and `validate`;
  - `terraform test` with a **mocked** AWS provider: `tests/staging.tftest.hcl` in the default workspace and
    `tests/production.tftest.hcl` in a `production` workspace. They cover the settings, the user data, and
    the refusals (wrong workspace, wrong expiry, unknown environment).
- **Plan checks on fixed fixtures:**
  - `plan_check.py --env staging|production` (production fixtures added);
  - `plan_review.py checklist` follows the environment recorded in the plan (`var.environment`).
- **Safety against silently replacing production data:**
  - separate workspace and state;
  - separate names, tags, VPC range, parameter path and IAM (staging IAM only touches
    `Component=workbench-staging` resources);
  - the data volume and the bucket are never replaced;
  - production is never destroyed through `plan_check.py`;
  - auto-loaded tfvars are refused for a production run.
- **A real plan:** only after A2 (staging) or A8 (production). Owner commands: RUNBOOK §3 plus `--env`.

## 6. Release pipeline (R3-031 to R3-040)

### 6.1 Build from the intended commit, pinned (R3-031, R3-032, R3-039)

**Commands (operator machine; Docker; no registry, no AWS):**

```bash
S=deploy/aws/private-staging/staging
bash $S/build_bundle.sh --git . b96675f87ac77bb139bf71926c69434033f0c202 "$OUT" --repro   # the release
git archive f9e4dd865c16 | tar -x -C "$OLD"                                               # the previous release,
bash "$OLD/$S/build_bundle.sh" --git . f9e4dd865c16bc3ed31a8b93976ba90d85f1124f "$OUT"    #   with ITS OWN builder
```

**Identities (stand-in build of 2026-11-20; the owner's build must reproduce the tree, content, server and
web digests):**

| Bundle | Commit | Tree | Transfer tar SHA-256 | Image ID | Server / web | Migrations |
| --- | --- | --- | --- | --- | --- | --- |
| `flh-staging-57ec7085dc61` (release) | `b96675f87ac7` | `57ec7085dc61` | `d53d71b76f1f…d7988` | `ca1de4877b28` | `e061f974616e` / `ab465f9c9e91` | 21 |
| `flh-staging-2bf1d9f6aea3` (rollback: previous `main`) | `f9e4dd865c16` | `2bf1d9f6aea3` | `4ae965c1d9bc…a9799` | `ca755385bbc5` | `48004f0376d2` / `ca9a34ce8aae` | 21 |

What `--repro` shows:
- a no-cache rebuild of the release gives a byte-identical server binary and web files;
- the image ID differs, as expected from layer metadata, so the tree, content, server and web digests
  are the stable identity (RUNBOOK §1.2).

### 6.2 Artifact store layout (R3-033)

One private bucket per environment (`flh-stg-…` / `flh-prd-…`): SSE-S3, versioned, all public access
blocked, TLS-only policy.

| Prefix | Object | Writer | Reader | Retention |
| --- | --- | --- | --- | --- |
| `releases/` | `flh-staging-<tree12>.tar` + `.sha256` | operator (`flh-*-operate`) | host role (`releases/*` get); verify role (`*.sha256` only) | staging 14 d; production kept (old versions 30 d) |
| `backups/` | `<backup>.tar` + `.sha256` (a `flh-daily.sh backup` directory) | host role and operator | host role and operator; **never** the verify role | staging 14 d; production 35 d + 7 d as old versions |

Nothing else lives there:
- **no Terraform state:** it stays local;
- **no settings:** they are in SSM;
- **no database outside a backup tar.**

The release SHA-256 the operator types at install comes from the build machine, never from S3 or the host
(RUNBOOK §5).

### 6.3 Endpoints and credentials (R3-034)

**Flow:** SSM Parameter Store `/flh/<env>/<NAME>` (String; SecureString for any key) → `flh-staging-env`
renders `NAME='value'` lines to a 0600 file atomically. It prints only names and set/empty → the file is
`flh-daily.sh`'s settings file.

**Covered settings:** the providers' base URLs, models and timeouts (`OPENAI_*`, `SPEAKING_TRANSCRIPTION_*`,
`EMBEDDING_*`) use this same path. The renderer accepts any well-formed name.

**Never there:** a secret in user data, Terraform state, the bundle, logs or the repository. The host role
reads only its own environment's path.

### 6.4 Startup gates (R3-035)

`flh-staging-bundle install` runs these steps in order (`cmd_install`):
1. **Target:** the optional `--expect-target` check, then the settings file must exist.
2. **Verify:** the SHA-256, every file and the identity; refused before anything is unpacked.
3. **Load:** load the image.
4. **Ledger check:** the bundle must know every migration in the database.
5. **Back up:** a pre-install backup when a service is running.
6. **Switch:** `current` → the new bundle (`previous` → the old).
7. **Start and check:** `up`, then the identity check: running image ID and labels, `/app/server`
   SHA-256, `/readyz` 200.
8. **Fall back:** if the identity check fails, switch back automatically and write redacted diagnostics.

`/healthz` is liveness only. `/readyz` includes a write probe that writes nothing; a read-only database is
`503 storage_read_only`.

### 6.5 Explicit rollback target (R3-036)

`flh-staging-bundle rollback` used to take no argument and switch to `ROOT/previous`. It now:
- prints the target, its commit, tree, image and migration count, and why it was chosen;
- accepts `--to flh-staging-<tree12>` for any **installed** bundle;
- refuses a target that is not installed, is the current bundle, or is not a bundle name.

The target is always re-verified from its files and its ledger checked before the switch.

**Browser cache after a rollback (demo lane finding, 2026-11-20):**
- **Cause:** `GET /` sends `Last-Modified` from `index.html`'s file time
  (`internal/transport/http/workbench.go`). After a rollback, a browser holding the newer page can be
  answered `304` and keep it, while its hashed assets are 404 on the older build.
- **Mitigation now:** RUNBOOK §8 adds a cache-bypassing reload, then a check that the page's entry
  script equals the one an uncached `curl` of `/` returns. The private build carries no `flh-build`
  meta tag (checked in both images).
- **Fix proposed:** the Demo lane's `0002-page-etag.patch` (a strong ETag, no Last-Modified). It applies
  cleanly to this base, but it changes shared application code, so it needs the owner's assignment. It
  protects only rollbacks *from* a patched build.

**Older releases:** the current builder cannot package a release from before its bundle file list (it lacks
`backup_tool.py` and friends). The previous release is built with its **own** builder, and the current host
tool verifies that bundle.

### 6.6 Missing artifacts and persistent data (R3-037, R3-038)

- **Builder:** `build_bundle.sh` now refuses a tree missing any bundle file before the image build: in
  0.4 s, naming the files, with nothing written. Before, it failed after a 73 s build with
  `install: invalid mode ''` and left a partial bundle directory behind.
- **Host:** the host tool refuses a bundle with a missing, added or altered file, a wrong SHA-256, an
  inconsistent identity or a swapped image, before anything changes.
- **Data:** installs and rollbacks change only `current`/`previous` and the containers. `FLH_DATA_DIR` sits
  on the separate data volume, which Terraform never replaces (`plan_check.py`). Writes made before an
  update and before a rollback survive both (§6.7).

### 6.7 Update and rollback on the stand-in (R3-040)

See the results in [§6.8](#68-stand-in-results), recorded after the runs.

### 6.8 Stand-in results

All runs were on 2026-11-20, class S:
- **Hosts:** Docker on loopback, each in its own `flh-stg-<run>-*` Compose project.
- **Data:** the synthetic fixture `nas-fixture-20261118072610`, whose checksums verify.
- **Daily instance:** container and image unchanged in every run (C2).

| Run | Result | Key measurements |
| --- | --- | --- |
| `e2e_rehearsal.py` (release report, deploy controls, aborted and rolled-back cutover, recovery, first run) | **7/7 parts passed**, 334 s | cutover freeze window (T1 − T0) **7 s**; ROLLBACK-B carried 3 + 3 AWS-only rows back; restore of a 70 MB / +200,000-row database **3.06 s**, backup 2.54 s, transfer 0.28 s |
| `bundle_rehearsal.py` (old = previous main, new = the release, broken = failing `022`) | **25/25 PASS** | 7 tampered or missing artifacts refused before install. First install 3.7 s; update 5.3 s; rollback 2.9 s (target line printed); roll forward again 3.3 s. A killed install leaves `current` intact. A failed migration switched back automatically in 73.4 s with the ledger unchanged (21 → 21) |
| `r3_platform_probes.py` (new) | **14/14 PASS** | the model is unreachable at startup, yet ready; analysis 502 with a generic message, readiness still 200; one `request failed:` line, no key or text in the log. A stale running deployment fails `identity`. Teardown leaves no container, network or volume |

### 6.9 Data protection (R3-041 to R3-050)

- **Contract (R3-041), agreed with the Workbooks lane on 2026-11-20:**
  - **Unit:** the whole database (`flh-daily.sh backup`: stop, copy app.db + WAL/SHM, `SHA256SUMS`, start).
  - **COUNTS:** every table except the ledger and the semantic caches (46/53), compared by `max(rowid)`.
  - **Restore acceptance:** sums, `integrity_check`, ledger, `restore_write_check.py`, `DUMP`, COUNTS,
    plus Workbooks' read-only `inventory.py` (from their sealed handoff-075) on both sides.
  - **At cutover:** the learning-history export compared NAS ↔ AWS, then an import-preview showing 0 new
    and 0 conflicts. The export is learner data: never in evidence.

  The full text is in `deploy/aws/private-staging/CUTOVER_DRY_RUN.md`.
- **Storage (R3-042):**
  - S3 (SSE-S3, versioned, private, TLS-only);
  - an encrypted gp3 data volume, never replaced (Terraform tests and `plan_check.py`);
  - production keeps 35 days of backups. A KMS key of its own is not needed (no cross-account access).
- **Before and after a restore:**
  - **Digests (R3-043):** `sha256sum -c` before anything stops, and a damaged backup is refused before
    any stop.
  - **Checks after the restore (R3-044):** ledger, file permissions (`restore_write_check.py` judges a
    read-only or foreign-owned database) and the first write.
- **Credentials (R3-045):** a backup holds only `app.db`, its WAL/SHM and `SHA256SUMS`. The settings
  file lives outside `FLH_DATA_DIR`. 18 rehearsal backups showed 0 credential patterns, including two taken
  while a placeholder key was configured.
- **Disposable restore and timing (R3-046, R3-047):**
  - the restore rehearsals use disposable stand-in volumes (`recovery`, `dr`);
  - measured: 0.68 MB → 2.8 s, 70 MB → 3.06 s on local NVMe.

  EBS and S3 times are pending G.
- **Interrupted restore (R3-048):** a damaged backup records `PREPARE-INTERRUPTED`, names the staging
  copy, then resumes with a good backup. A failed prepare leaves the service and its data untouched.
- **Write freeze and loss bounds (R3-049):**
  - from T0 (NAS stopped, settings moved aside) to T1 nobody can write; 7 s on the stand-in, plus the
    real transfer;
  - data loss at cutover: **0** (the backup equals T0);
  - normal operation: ≤ 24 h (daily backup);
  - after T1, a rollback carries AWS writes back (procedure B), never a naive NAS restart.
- **Rollback inputs (R3-050):**
  - the rollback bundle `flh-staging-2bf1d9f6aea3` (§6.1);
  - the NAS final backup, the moved settings file and the NAS image tag `:before-cutover`;
  - the AWS backups;
  - the measured times above.

## 7. Observability (R3-051 to R3-060)

### 7.1 Readiness and errors (R3-051, R3-052)

| Check | How | Expected | Depends on providers? |
| --- | --- | --- | --- |
| API ready | `GET /readyz` (bounded; ping + a write probe that writes nothing) | 200 `ready`; 503 `not_ready` (+ `reason`, e.g. `storage_read_only`) | **no**: a provider outage must not make the service unready |
| Process alive | `GET /healthz` | 200 | no |
| Web | `GET /` serves the workbench; `/assets/*` immutable | 200 | no |
| Running identity | `flh-staging-bundle status` / `identity` (image, labels, server SHA-256, `/readyz`) | `IDENTITY OK` | no |
| Model services (only when enabled) | the service's own `/readyz` (Speaking: `ready` only after a warm-up; E5: model on GPU) | 200 | they are the dependency; FLH maps their failure per request |

**Errors already recorded without content:**
- Every 5xx response writes one `request failed:` line: status, method, route **pattern**, duration and
  `request_id`. The same ID is the `X-Request-Id` on every response.
- A failed install writes redacted diagnostics, and `diagnose.py` names the cause (for example
  `db-readonly`).
- Provider failures are stored as failed attempts with non-secret codes (`provider_unavailable`,
  `provider_timeout`, `invalid_output`). Unknown outcomes need `confirm_unknown_retry`.

### 7.2 Counters (R3-053: proposal, needs approval)

The service exposes no counters today. Adding them is an application change, so it is **owner-only**.

**Proposed** (loopback only, no labels holding learner text):
- `http_requests_total{route_pattern, status_class}`;
- `http_request_duration_ms{route_pattern}` as fixed buckets;
- `readyz_failures_total{reason}`;
- `provider_calls_total{provider, outcome}`, where `outcome` is `ok | timeout | unavailable | invalid_output | unknown`.

**Until approved:** the `request failed:` lines can be counted from the journal on the host
(`flh-daily.sh logs`).

### 7.3 Alarms (R3-054, R3-059: thresholds proposed for A7)

| Alarm | Metric (free EC2 metrics unless noted) | Threshold | Assumption |
| --- | --- | --- | --- |
| Host down | `StatusCheckFailed` | ≥ 1 for 2 × 5 min | single host; a restart is the first remedy |
| CPU starved | `CPUCreditBalance` (t3 standard credits) | < 20 for 3 × 5 min | single user. A sustained drain means a runaway process, not load |
| Not ready | a host timer probing `/readyz` every minute and logging failures to the journal; optional custom metric (≈ $0.30/month and `cloudwatch:PutMetricData`) | 3 consecutive failures | readiness, not provider health |
| Spend | AWS Budgets on `Component=workbench-production` | 80% of the A7 budget | the alert notifies; it does not stop spend |

**Alarm destinations** are configuration, not secrets: an SNS topic ARN or an e-mail address as a
Terraform variable or `/flh/<env>/ALERT_*` String parameter. A webhook with a token would be a
SecureString. Two EC2 alarms cost about $0.20 / month.

**None of these resources is in the Terraform yet.** Adding them changes the expected-resources list and
the IAM policies, which is a decision for A7.

### 7.4 Correlation (R3-055)

**Today:**
- Inbound requests carry `X-Request-Id`; providers do not receive it.
- Speaking and the OpenAI calls keep their own idempotency keys.
- No prompt, learner text or provider body is logged.

**Proposal**, an application change gated by the Extraction contract and the owner:
- forward the inbound `X-Request-Id` as a header on provider calls;
- record the provider's echoed request ID next to the stored attempt.

Both are identifiers only. Blocked on Extraction (§8).

### 7.5 Tests and separation (R3-056 to R3-058, R3-060)

| Item | Evidence class | What ran |
| --- | --- | --- |
| Startup failure | S | the broken-`022` bundle install: the new bundle fails readiness, the tool switches back automatically, identity is verified, the data is unchanged (§6.8) |
| Dependency timeout | L | `TestExtractor_Timeout`, `TestSpeakingDeadlineCoversTheLocalTranscriptionTimeout`, and three local Speaking service tests, including a stop, restart and recovery. 5/5 pass |
| Demo vs private | R + L | the demo instance is tagged `Component=public-demo` (observed), while the private stack is `workbench-*`. `plan_check.py` STOPs on any demo address. Alarm names carry `flh-stg` / `flh-prd` |
| Old deployment identity | S | the identity check compares the **running** image and server binary with the bundle `current` names. A stale container fails it (§6.8) |
| Operator view | L | `OPERATOR-VIEW.md` in the lane's handoff area: status per item with links to evidence |

## 8. Extraction and model lanes (R3-061 to R3-070)

### 8.1 Contracts read (R3-061)

The Extraction lane answered on 2026-11-20 (cross-session). Its handoff will be sealed at
`~/flh-handoff/extraction3-20261120/`; until then the files below are cited from its worktree, unsealed.

| Service | Contract | Identity | Auth | Timeouts | Health | Request ID | Rollback |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Speech recognition (`flh_speaking`) | `tools/speaking/CONTRACT.md` (main) | `GET /manifest` `deployment_id`, pinned as `SPEAKING_TRANSCRIPTION_MODEL`; another answer is refused | none; loopback or private only | service 50 s < client 60 s < `HTTP_WRITE_TIMEOUT` 75 s | `/healthz`, `/readyz` (warm), `/metrics` | **not implemented** (neither read nor echoed) | the previous image + weights, then reset the model setting; a half switch fails closed |
| Extraction rules service (new) | `tools/extraction/SERVICE.md` (Extraction worktree) | `flh-extraction-rules@<code12>/flh_extraction_service_v1/…`, header `X-FLH-Contract` | none; private only | 5 s per request, 4 in flight, 256 KiB body | `/healthz`, `/readyz` (self-check), `/metrics` | echoes a well-formed `X-Request-Id` | redeploy the previous image; `expect_deployment` pin |

**The app does not call the extraction service:** there is no Go provider for it. Wiring one in is a
shared-contract change for the owner.

**No model runtime is placed on AWS.** The Extraction lane's `deploy/aws/model-runtime/STAGING-PLAN.md` (prepared,
not run) proposes both services as **sidecars on the private host's Compose network**.

### 8.2 Placement and authentication (R3-062, R3-063)

| Option | Network path | Auth gap | Verdict |
| --- | --- | --- | --- |
| Phase 1: not moved, providers disabled | none | none | **current** (agreed by Extraction) |
| Sidecars on the same host's Compose network (`flh-staging_default`), no published port | the container network only | none needed: no route from outside the host | **proposed** (owner decision A11; t3.medium ≈ +$15/month; IAM shape change) |
| A separate private instance, security group from the app's group only | VPC-internal | unauthenticated service reachable by anything in the VPC | not proposed |
| SageMaker endpoint | AWS API (SigV4) | the app has no SigV4 client | rejected for interactive use |
| Back to the NAS over a tailnet | VPN | new component, home uplink | not approved |

The approved AWS resources today are none beyond the read-only profiles. Nothing here needs a new AWS
resource type.

### 8.3 Configuration, failure and rollback (R3-064 to R3-067)

- **Configuration per environment (R3-064):** endpoint, model and timeout come from `/flh/<env>/`
  parameters.
  - **New guard:** `scripts/release/test_compose_forwarding.py` checks that every setting the server
    reads is forwarded by `compose.yaml`, fixed by it, or excluded with a reason.
  - **Found:** `SPEAKING_TRANSCRIPTION_BASE_URL`/`_TIMEOUT` are not forwarded, **and** `flh-daily.sh
    check` refuses `SPEAKING_TRANSCRIPTION_PROVIDER=local`. Local transcription is therefore not packaged.
    The test pins the two together.
  - **Enabling it** is one release-lane change set (the wrapper, Compose, `RELEASE.md`, `test_wrapper.sh`),
    after A11.
- **Model unavailable at startup (R3-065):** `r3_platform_probes.py` M1–M7:
  - the app installs and becomes ready with its model endpoint refusing connections;
  - the request fails fast with a generic 502, and readiness is unaffected;
  - no key or text reaches the log.
  - The Go tests cover the Speaking local service stopping, restarting and recovering.
- **Model rollback is independent of the app (R3-066):** the app pins `deployment_id`, and a model
  rollback changes only the model service and `SPEAKING_TRANSCRIPTION_MODEL`. The app bundle and its
  identity stay as they are. The model side is rehearsed by the Extraction lane (its seal); the app side
  holds by construction (identity covers image and server only).
- **No accidental public route (R3-067):**
  - `plan_check.py` STOPs on any ingress, EIP, LB, DNS or CloudFront;
  - `compose.yaml` publishes on `127.0.0.1` only (preflight);
  - the sidecars publish no port (Extraction check 1);
  - in the observed account, no security group but the demo's allows ingress from anywhere. The two
    default groups allow only their own members (the AWS default).

### 8.4 Staged request, identities, findings (R3-068 to R3-070)

- **Staged request with a synthetic fixture (R3-068):** **blocked**. There is no approved staging and no
  approved sidecar.
- **Component identities (R3-069):** every stand-in run records:
  - the bundles' commit, tree, image, server and web digests;
  - the fixture's `SHA256SUMS`;
  - Terraform 1.15.9 with hashicorp/aws 6.69.1;
  - the Docker server version (`BUILD.json`).

  Model `deployment_id`s come from the Extraction seal.
- **Findings sent to the Extraction lane (R3-070):**
  - the wrapper refuses `local`;
  - the IAM shape is t3.small only;
  - the existing IAM covers `releases/model-runtime/*`;
  - the Compose network name;
  - the sidecar lifecycle versus the bundle tool and the power-off;
  - root disk room;
  - the request-ID gap.

## 9. Read-only verification permissions (exact actions, for later staging)

The `FLHStagingRelease` permission set today answers only:
- `sts:GetCallerIdentity`;
- `ec2:DescribeInstances`, `ec2:DescribeSecurityGroups`, `ec2:DescribeVpcs`
  and `ec2:DescribeSubnets` (observed; not an exhaustive listing).

It is refused `ec2:DescribeVolumes`, `DescribeAddresses`, `DescribeImages`,
`DescribeSnapshots`, `DescribeVpcEndpoints`, `DescribeRouteTables`,
`DescribeInternetGateways`, `DescribeInstanceTypes`, `DescribeInstanceAttribute`,
`s3:ListAllMyBuckets`, IAM reads, SSM reads, CloudWatch, Budgets, Service Quotas
and Pricing.

The read-only verification of a staging pass needs the policy
`staging/iam/out/flh-stg-verify-readonly-policy.json` (R3-025). It has no
write action and no `ssm:GetParameter`, so no value is ever readable.

Write permissions for the staging run itself stay the four reviewed
`flh-stg-*` policies (AWS_STAGING_PLAN.md §20):
- **`flh-stg-deploy-ec2`:** tag-conditioned EC2 creates in us-east-1,
  `t3.small`, the pinned AMI, the required `ExpiresAt`/`Run` tags, and an
  encrypted gp3 data volume;
- **`flh-stg-deploy`:** host role only under the `flh-stg-host-boundary`, and
  buckets `flh-stg-*`;
- **`flh-stg-host-boundary`:** SSM minimum, `releases/*` read, `backups/*`
  read and write, `/flh/staging/*` read, and KMS decrypt only through SSM;
- **`flh-stg-operate`:** uploads, sessions only to tagged instances, and
  `/flh/staging` parameters.

## 10. Controlled staging (R3-071 to R3-080)

No staging was applied: A2 is missing. Every live step was dry-run with equivalent inputs instead:

| Live step | Owner command (RUNBOOK) | Equivalent rehearsal (class L/S) | Result |
| --- | --- | --- | --- |
| Approval, account, region before apply (R3-071) | §0 inputs. `aws sts get-caller-identity` must name the **approved** account; region us-east-1; `terraform workspace show` matches the environment | read-only identity check of both profiles (masked); the workspace/environment precondition (terraform test) | identity OK; precondition refuses a mismatch |
| Hostname and artifact (R3-072) | no hostname by design: the SSM target is the instance ID (Terraform output) | release transfer tar `flh-staging-57ec7085dc61.tar`, SHA-256 `d53d71b76f1fae8716400c2ddf2adb33197c455b7c9fcc453d65f0be8ab7d988` | pinned |
| IAM, plan, apply (R3-073) | §2–§3 | `render_policies.py` (both sets), `plan_check.py` and `plan_review.py` on fixtures, mocked `terraform test` | all pass; **apply blocked** |
| Parameters, upload, install, restore (R3-074, R3-075) | §4–§6 | `e2e_rehearsal.py` (first run: 10 typed steps, 7 owner-only sections), `restore_acceptance.py` with Workbooks' sealed `inventory.py` | 7/7 parts; acceptance READY on both sides |
| Browser and API smoke on the exact release (R3-076) | §7 | `scripts/release/smoke.sh`: 12 stages PASS; its `/app/server` SHA-256 equals the bundle's `e061f974616e…`. `browser_check.sh --browser-container` (§10.1) | PASS |
| Broken deploy and rollback (R3-077) | §8 | `bundle_rehearsal.py` F2a (failing migration → automatic switch back), R1 (rollback) | PASS |
| Costs and labels (R3-078) | §9 billable checks; Budgets | every stand-in object is named `flh-stg-<run>-*` / `flh-smoke-*`. The AWS inventory re-run at the end is **unchanged** (one demo instance, 3 security groups, 2 VPCs, 0 SageMaker endpoints) | AWS spend from R3: **$0** (read-only calls only; Cost Explorer not called) |
| Teardown and residuals (R3-079) | §9 | probes T1/C1; bundle and e2e C1; smoke teardown | no stand-in container, network or volume left. The images `flh-staging:{57ec7085dc61,2bf1d9f6aea3,b66ad94c9034}` and `flh-smoke:20261120t083013-34d0cf` remain local (removable with `docker image rm`) |

**Go / no-go (R3-080):**
- **NO-GO for any live AWS step today:** A2 (budget, runtime window, account confirmation, synthetic-only
  scope) and A3 (IAM policies) are missing.
- **GO to run the staging pass** as soon as A2 and A3 are given. Every local gate on the exact release
  `b96675f8` passes (§6.8, §10), and no blocking defect is open in the release lane.
- **Production (A7–A9) stays a separate decision** after a passed staging pass.

### 10.1 Browser check

`scripts/validation/v1_rehearsal/browser_check.sh --browser-container`, run on the release working tree (2026-11-20): every stage PASS (disk, browser, driver, serve, ownership, smoke, teardown). 36 browser checks passed and 0 failed, in a disposable Chromium container, and the daily instance was unchanged. Evidence: `standin/browser-check/` in the lane's handoff.

## 11. Production cutover and release close (R3-081 to R3-100)

- **Owner decisions and approval points (R3-081):** A1–A11 (§3.9), plus where the `/` ETag fix
  lands (shared `workbench.go`, §6.5). Production DNS (A10), the real data
  move (A9) and model promotion (A11) are separate.
- **Pre-cutover inventory (R3-082):** the release and rollback bundle identities (§6.1), the fixture-free
  `cutover_check.py` records (C1–C8), and the Workbooks `inventory.py` receipt on the NAS backup. The NAS
  daily image ID and commit label are read by the owner at P2. Agents never read them.
- **Order (R3-083):** CUTOVER_DRY_RUN.md steps 1 → 2a → 2 → 2b → 2c → 3 → 3b → 4 → 5 → 5b → 6 → 7 → 8 → 9.
- **Rollback thresholds (R3-084)**, written down at P4. Proposed:
  - the freeze window (now − T0) passes **30 min**;
  - any DO-NOT-SWITCH check fails;
  - after T1, `/readyz` is not 200 for **5 min**;
  - `flh-staging-bundle status` is not `IDENTITY OK`;
  - an `inventory.py` mismatch.

  Each threshold leads to ROLLBACK-A or ROLLBACK-B.
- **Downtime measured on the stand-in with the same order (R3-085):** 7 s (T1 − T0) plus the real transfer.
- **URLs (R3-086):** access is an SSM port forward to `127.0.0.1`. There is no staging or production
  DNS, and A10 is not requested.
- **Writes during the transition (R3-087):**
  - nobody writes between T0 and T1 (settings moved aside on the NAS);
  - after T1, AWS is the only writer;
  - a rollback after AWS writes uses procedure B;
  - both sides written gives DIVERGED and the owner chooses;
  - captures re-enter by `capture_id` (create once, replay 200, conflict 409; confirmed by Workbooks).
- **Restore credentials and access (R3-088):** **owner-only**. The operator needs `flh-*-operate` (S3
  `backups/*` read and write, sessions) and NAS shell access; the host role reads `backups/*`. Confirm both
  before T0.
- **Rollback before and after the switch (R3-089):** case A (before T1, or no AWS write) and case B (AWS
  writes carried back). Rehearsed in the e2e cutover part (ROLLBACK-B, then ROLLED-BACK).
- **Walkthrough without production mutation (R3-090):** `first_run.py` types the RUNBOOK on a fresh
  stand-in, and `ACCEPTANCE.md` in the lane's handoff lists every command with its approval point.
- **Seals and PR heads (R3-091):** main's tree `57ec7085dc61` equals the tree assembled from the
  #160/#161/#162/#163 heads plus the shared demo fix (the PR-repair stacked check). The PRs were
  squash-merged, so their head commits are not ancestors. The shared fix landed with an equal patch ID
  (`0e3863e3`).
- **Public provenance fix (R3-092):** **included in the intended public release, not yet on main.**
  The Demo lane's sealed source (`demo-refresh-20261120-r3-source`, base `b96675f8`, SHA256SUMS
  `a525d082…`) carries:
  - `public_provenance.py`, byte-identical to the reviewed packaging patch 0001;
  - `package.sh` calling it;
  - one more test (7/7 pass).

  Its final candidate `flh-public-demo-r3-final.tar.gz` (SHA-256 `f204e88969ea…`) passes:
  - the release lane's member scan: no private host, labels, user or host names, and no pattern class
    beyond the synthetic `demo.db`;
  - `public_provenance.check`: 0 problems.

  Until the Demo PR lands, a public package must not be built from `main`. The private release builds no
  demo package.
- **Integrated checks on the final tree (R3-093):**
  - Go: gofmt, vet, 25 packages, 5 commands;
  - Python: every hermetic suite;
  - staging tools: 76 tests;
  - release: 126 tests;
  - Terraform: mocked tests;
  - web: unchanged from main's verified 739/739.
- **Pins (R3-094):** `RELEASE-PINS.txt` in the lane's handoff: the bundle tars and their `.sha256`, the
  host tools, the builder, and the Terraform and IAM files.
- **Evidence classes (R3-095):** §2. Every row in the lane's `status.tsv` names its class.
- **Commands and location (R3-096):** §6.1 (build), RUNBOOK.md (staging), CUTOVER_DRY_RUN.md (cutover),
  `ACCEPTANCE.md` (the lane's handoff).
- **AWS cost and quota unknowns (R3-097):**
  - the Pricing API and Cost Explorer are unavailable;
  - the vCPU and EIP quotas and the AZ offering are unread (the verify policy, §9, grants these reads);
  - the real database size is unknown.
- **Rollback artifacts and access (R3-098):**

  | Artifact | Where | Access |
  | --- | --- | --- |
  | `flh-staging-2bf1d9f6aea3.tar` (previous release) | the release lane's handoff area; later S3 `releases/` | owner; host role (read) |
  | NAS final backup, moved settings file, `:before-cutover` image | the NAS | owner only |
  | AWS backups | S3 `backups/`, the data volume | operator, host role |
  | Public demo rollback | `pkg-ba2ff1b23210` | Demo lane / owner |
