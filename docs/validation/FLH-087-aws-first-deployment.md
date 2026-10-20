# FLH-087 — First AWS deployment record and updated demo package

Owner: NAS Claude Code. Builds on FLH-084, FLH-085 and FLH-086.

**Not done in this task:**
- AWS calls, uploads, SSM sessions, Terraform operations, deployments;
- VPS, DNS, nginx or xray changes;
- Git commands, subagents, installations, model calls.

**Current state (closing summary):**
- **Deployed:** the verified-source candidate `flh-public-demo-flh087-rc1`
  (§3), installed over rc1 by the operator (§4). rc1 is the recorded rollback
  target.
- **Historical:** the earlier `flh087-local-unverified` package (§2) was
  superseded and never deployed.
- **AWS and browser results are operator-reported.** The agent observed none
  of them; it ran only the local package build and checks.
- **Outstanding:** see §5.

## 1. First deployment evidence (OPERATOR-REPORTED)

The human supplied everything in this section. None of it was independently
observed by the agent. Account, bucket and instance identifiers are
deliberately omitted.

| Stage | Operator-reported result |
|---|---|
| Infrastructure | `terraform apply flh086r2.tfplan`: **19 added, 0 changed, 0 destroyed**. us-east-1, arm64, `t4g.micro`, AMI `ami-04048e843b318bc37` |
| Systems Manager | SSM agent 3.3.5390.0, `Online` |
| Host configuration | cloud-init 22.2.2, `status: done`. `/usr/local/sbin/flh-release` and `/etc/systemd/system/flh-public-demo.service` present |
| User-data schema | `cloud-init schema --system` rejected the compressed input header; `/var/lib/cloud/instance/user-data.txt` begins with gzip magic bytes. `sudo cloud-init schema -c /var/lib/cloud/instance/cloud-config.txt` returned **Valid cloud-config** |
| Release install | `flh-release` downloaded rc1 from the private bucket, passed CANDIDATE validation, installed it and verified the live artifact identity |
| Runtime | service `active`; `GET http://127.0.0.1:18970/readyz` returned `{"status":"ready"}` |
| Browser access | demo opened on a Mac through an SSM port forward (instance 18970 → local 18971). The tunnel was then closed, which does not stop the instance |
| Interactive acceptance | Not reported for rc1. For the later upgrade, see §4 |
| Deploy-policy detachment | **PENDING CONFIRMATION.** Removal of the `flh-demo-deploy` attachment is not explicitly verified (still open, §5) |

**First deployed release (rc1; now the previous release and rollback target):**

| Item | Value |
|---|---|
| Package | `flh-public-demo-flh081-rc1.tar.gz` |
| SHA-256 | `536966c46cc3ed70d201fbd2439cd0e1eb3c047151af86de011d8580bb3981df` |
| Source revision | `145983623fd83f71fbb968769ab767c2e3efc5a1` |
| Artifact version | `d025f217f4d76396` |
| Artifact manifest SHA-256 | `dfe6e94de6664c18be2ae65a27ad9b6c107e7ceefb56a1627fe3f54d4788bcab` |

**Runbook corrections** (`docs/AWS_DEMO.md`, narrow):
- **Installer path:** `/usr/local/sbin/flh-release` everywhere, because
  `sudo`'s `secure_path` may omit `/usr/local/sbin`.
- **Schema check:** the observed gzip limitation and the decoded-config check.
  It is stated for cloud-init 22.2.2 only, not claimed for all versions.
- **Five deployment stages:** infrastructure, host configuration, runtime
  readiness, browser access and interactive acceptance, each with its own
  evidence.
- **Acceptance checklist and tunnel scope:** an explicit stage-5 checklist,
  and the fact that closing the tunnel leaves the instance billing.
- **Status line:** updated with this deployment.
- **Unchanged:** the permissions-boundary design and the `flh086.tfplan`
  obsolete-plan warning.

## 2. Earlier package (historical): LOCAL CANDIDATE / SOURCE UNVERIFIED

**Superseded and never deployed.** This section records the first rebuild,
made before a source revision was available. It was replaced by the
verified-source candidate in §3, which is the deployed package. The
"source unverified" label applies only to this earlier package.

**Source provenance.** The exact source revision and clean committed state
**could not be established**:
- this task forbids Git, and no packaging metadata records the current
  revision;
- the working tree holds uncommitted FLH-084 to FLH-087 work.

So:
- **Revision label:** the package carries the explicit label
  `UNVERIFIED-local-worktree-flh087`. rc1's revision was not reused and no
  revision was invented.
- **Misleading note:** `package.sh` writes a fixed `source_revision_note`
  ("supplied by the human owner"). For this package that note is inaccurate:
  the agent chose the unverified label. The builder was not weakened to change
  it.
- **Source-input digest (traceability without Git):** SHA-256 of 268 input
  files is recorded in `~/flh087/source-inputs.sha256` (local, not committed;
  its own SHA-256 is `12e1a622…d2478e0`). It covers `cmd`, `internal`,
  `migrations`, `scripts/demo/flh073/prepare`, `scripts/demo/flh076`,
  `web/src` plus the web config and lockfile, `go.mod` and `go.sum`.
  `web/package-lock.json` (`6e56a2b7…`) and `validate-release.sh`
  (`2c72fd14…`) are byte-identical to FLH-081's recorded inputs.
- **Web dependencies:** the build used the existing `web/node_modules` (no
  `npm ci`, no installation). Whether it matches the lockfile was not
  re-verified.

**Build (existing workflow, network-isolated):**
```sh
unshare -rn env GOPROXY=off GOFLAGS=-mod=readonly GOTOOLCHAIN=local \
  bash scripts/demo/flh076/package.sh --artifact ~/flh081/artifact \
  --revision UNVERIFIED-local-worktree-flh087 --label flh087-local-unverified --out ~/flh087/release \
  --expected-deployment 'multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/flh_e5_role_prefix_v1/float16/singleton_v1/5a3e23f28a05baff'
```
- **Artifact input:** `~/flh081/artifact`. Its five files are byte-identical
  to rc1's packaged artifact. No embeddings were regenerated; model
  provenance, annotations and the demo database are unchanged.
- **Result:** exit 0, CANDIDATE. Built 2026-10-20T19:21:48Z with Go 1.27.1.

| Item | Value |
|---|---|
| Tarball | `~/flh087/release/flh-public-demo-flh087-local-unverified.tar.gz` (41,365,221 bytes) |
| SHA-256 | **`6035fe8b5e49649ff2e249cc129c2ce90c229677c1ecc2a00d7e47a6253c7521`** |
| Unpacked | `~/flh087/release/flh-public-demo-flh087-local-unverified/` |
| Binaries | `bin/linux-amd64/` (x86-64) and `bin/linux-arm64/` (AArch64), statically linked |
| `RELEASE.json` | label `flh087-local-unverified`, `source_revision` `UNVERIFIED-local-worktree-flh087`, CANDIDATE; artifact `d025f217f4d76396`, manifest `dfe6e94d…bcab`, `real_model: true`, pinned E5 deployment unchanged |

**Compared with rc1:** 18 files each.
- **Byte-identical:** the artifact (5 files), deploy templates,
  `validate-release.sh` and `README.md`.
- **Different:** the four binaries, `RELEASE.json`, `web/index.html` and the
  web assets (new hashed names).
- **rc1 itself:** unchanged (SHA-256 still `536966c4…`).

**Validation:**

| Command | Result |
|---|---|
| `unshare -rn python3 -B scripts/validation/flh081/candidate_check.py --tarball ~/flh087/release/flh-public-demo-flh087-local-unverified.tar.gz --work ~/flh087/check --revision UNVERIFIED-local-worktree-flh087 --artifact-version d025f217f4d76396` | **93 PASS, 0 FAIL** (details below) |
| `python3 -B scripts/validation/flh084/release_tool_test.py --tarball <new tarball> --work <scratch> --port 18996` | **26 passed, 0 failed** (details below) |
| Archive inspection (Python `tarfile`) | 27 members under one top directory; files and directories only; no absolute paths, `..`, links, setuid or world-writable entries |
| `NODE_OPTIONS=--no-experimental-webstorage web/node_modules/.bin/vitest run src/i18n/i18n.test.tsx` | **13 passed** (details below) |
| Bundle inspection | public-demo build, with the language selector and catalogs present. The editing workbench code is tree-shaken out |

**Candidate check details:**
- **Isolation:** no network namespace route.
- **Identity:** tarball `.sha256`; `validate-release.sh` CANDIDATE;
  `RELEASE.json` revision label, artifact version and real model.
- **Smoke test and served identity:** the FLH-076 smoke test passes, and the
  server reports the expected version, manifest SHA-256 and model.
- **Search:** keyword, semantic and hybrid presets.
- **Read-only boundary:** POST, PUT, PATCH and DELETE return 405 on write
  routes; non-demo and free-text routes return 404/400.
- **Restart and integrity:** byte-identical responses after restart, package
  bytes unchanged.

**Installer test details:** `flh-release` installs the new package, refuses bad
hashes, BLOCKED and unsafe tarballs, rolls back automatically and manually,
and logs the identity. It used the amd64 binary, a fake `aws` and a fake
`systemctl`.

**Language test details:** English default regardless of browser locale,
optional 简体中文, persistence, catalog parity.

**Bundle inspection details:**
- **Selector present:** the `flh.ui-locale.v1` storage key and `zh-CN`/简体中文
  are in the bundle.
- **No write code:** no `/captures`, `Idempotency-Key`, `annotation-operations`
  or POST/PUT/DELETE method literals.
- **Why the bundle grew** (174 KB → 301 KB): it now carries the full
  English and Chinese message catalogs. These include text-only workbench
  labels, such as "PUT concept-membership" in an explanation string. That is
  text, not capability; the server boundary refuses those routes.

**Not run or not verified:**
- **arm64 execution:** not run. This NAS is x86_64; the arm64 binary was built
  and its ELF type checked only.
- **Real-browser rendering of the language selector:** not run, no browser on
  the NAS. English default and Chinese switching are proven by the jsdom tests
  of the same source, not by a browser against the packaged bundle.
- **Source revision and clean committed state:** unverified for this package
  (see above); resolved by the verified rebuild in §3.
- **`<html lang="fr">`:** the static `index.html` still declares it until the
  app sets the language on mount. This predates the task (FLH-083).

## 3. Verified-source candidate: `flh087-rc1` (DEPLOYED)

**Source identity.** The human owner fetched `origin/main`, created the
branch at the revision below and confirmed no tracked changes. The source
identity rests on that Git verification. The agent ran no Git and did not
check the revision itself. That is a task boundary, not a defect of the
package, so the package is **not** labelled source-unverified.

| Item | Value |
|---|---|
| Package | `flh-public-demo-flh087-rc1.tar.gz` (41,365,127 bytes) |
| SHA-256 | **`725a367aa545ecdaf723cfd43f571e96b783195f699e6bc6be44d81ad36f4a6d`** |
| Source revision | `dc82235a85b01497957f571ef6870f514ea0cb27` |
| Status | CANDIDATE, built 2026-10-20T19:35:37Z with Go 1.27.1 |
| Targets | `linux/amd64` (x86-64) and `linux/arm64` (AArch64), statically linked |
| Artifact | version `d025f217f4d76396`, manifest `dfe6e94d…bcab`, `real_model: true` |

**Build (existing workflow, network-isolated):**
```sh
unshare -rn env GOPROXY=off GOFLAGS=-mod=readonly GOTOOLCHAIN=local \
  bash scripts/demo/flh076/package.sh --artifact ~/flh081/artifact \
  --revision dc82235a85b01497957f571ef6870f514ea0cb27 --label flh087-rc1 --out ~/flh087/verified-release \
  --expected-deployment 'multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/flh_e5_role_prefix_v1/float16/singleton_v1/5a3e23f28a05baff'
```
- **Output collision:** the output directory did not exist beforehand, and
  the builder refuses an existing package name.
- **Dependencies:** existing Go modules and `web/node_modules`; nothing
  installed or downloaded.

**Unchanged artifact and model provenance:**
- All five artifact files are byte-identical to `~/flh081/artifact`, which
  matches its recorded checksums. No embeddings were regenerated.
- The pinned E5 deployment id and the model provenance are the same as in
  rc1.
- The 268 source inputs recorded for the §2 package are byte-identical in
  the verified tree.

**Validation (run by the agent):**

| Command | Result |
|---|---|
| `unshare -rn python3 -B scripts/validation/flh081/candidate_check.py --tarball <flh087-rc1 tarball> --work ~/flh087/check-rc1 --revision dc82235a85b01497957f571ef6870f514ea0cb27 --artifact-version d025f217f4d76396` | **93 PASS, 0 FAIL**. Includes loopback-only namespace and `RELEASE.json` `source_revision` equal to the supplied revision |
| `python3 -B scripts/validation/flh084/release_tool_test.py --tarball <flh087-rc1 tarball> --work <scratch> --port 18996` | **26 passed, 0 failed** (amd64 binary, fake `aws` and `systemctl`) |

**Preserved:** rc1 (`536966c4…81df`) and the §2 package (`6035fe8b…7521`)
are unchanged.

## 4. AWS upgrade and browser review (OPERATOR-REPORTED)

The human supplied everything in this section. None of it was independently
observed by the agent. Account, bucket and instance identifiers are omitted.

| Item | Operator-reported result |
|---|---|
| `flh-release status`: current | `flh-public-demo-flh087-rc1` |
| `flh-release status`: previous | `flh-public-demo-flh081-rc1` |
| Tarball hash and source revision | match §3 |
| Service | `active` |
| Artifact version | `d025f217f4d76396` |
| Artifact manifest SHA-256 | `dfe6e94de6664c18be2ae65a27ad9b6c107e7ceefb56a1627fe3f54d4788bcab` |
| Live identity | match; `real_model=True` |
| `GET /readyz` | `{"status":"ready"}` |

**What this establishes:**
- **arm64:** the new arm64 server starts and becomes ready on the AWS
  instance, with the expected live identity. This is not comprehensive arm64
  functional testing.
- **Rollback:** rc1 stays the recorded rollback target. No production
  rollback was exercised during this upgrade. Rollback is covered only by the
  local installer test (§3).

**Browser review (operator-reported):**
- **Reported:** "页面几乎没有问题" ("The page has almost no issues.").
- **Recorded as:** an overall browser review with no reported blocking issue.
- **Not claimed from this statement:** separate acceptance of search, Concept
  detail, source records, language switching or English-default behaviour.
- **Preview tunnel:** its current open/closed state is unknown. Closing it
  does not stop the instance.

## 5. Outstanding items

1. **Deploy-policy detachment:** removal of the `flh-demo-deploy` attachment
   is still unconfirmed.
2. **Private encoder address in `RELEASE.json`:**
   `model_provenance.base_url` records the private address of the encoder
   that produced the vectors. rc1 carries the same field. It must be resolved
   before public artifact distribution. The address is deliberately not
   reproduced here.
3. **Bilingual English/Chinese concept explanations: FROZEN** until the
   multilingual model choice is settled. No implementation or model research
   is authorized by this task.
4. **Not verified:** individual browser features (§4) and arm64 behaviour
   beyond startup and readiness.

## 6. Upgrade procedure (reference; run by the operator)

The operator ran these steps for the §4 upgrade. They are kept for the next
upgrade. From the operator workstation, profile with `flh-demo-operate`; no
Terraform:

```sh
# 1. upload (cents); hash comes from the local .sha256 file, never from the bucket
aws s3 cp --profile flh-plan <package-dir>/<package>.tar.gz s3://<artifact-bucket>/releases/
cat <package-dir>/<package>.tar.gz.sha256
# 2. session
aws ssm start-session --profile flh-plan --region us-east-1 --target <instance-id>
```

In the session:

```sh
sudo /usr/local/sbin/flh-release status          # before: current release, identity match
sudo /usr/local/sbin/flh-release install s3://<artifact-bucket>/releases/<package>.tar.gz <sha256>
sudo /usr/local/sbin/flh-release status          # after: new package, previous = old release, "(match)"
systemctl is-active flh-public-demo
curl -s http://127.0.0.1:18970/readyz            # {"status":"ready"}
curl -s http://127.0.0.1:18970/knowledge-library/demo | python3 -m json.tool | grep -E '"version"|"manifest_sha256"|"real_model"'
exit
```

**Failure handling:**
- **Automatic:** if the post-switch identity or readiness check fails,
  `flh-release` restores the previous release by itself.
- **Manual rollback:** `sudo /usr/local/sbin/flh-release rollback`, then
  `status` and `/readyz` again. Previous releases stay in
  `/srv/flh-demo/releases/`.

**Then:** browser access (stage 4) and interactive acceptance (stage 5)
through the tunnel, as in `docs/AWS_DEMO.md` §7. Record the results.

## 7. Self-handoff

- **Implementation:**
  - this report;
  - narrow corrections to `docs/AWS_DEMO.md`;
  - two local packages outside the repository (§2 historical, §3 deployed).
    No code changed.
- **Validation (agent-run):**
  - §3 package: candidate check 93/0, installer test 26/0;
  - §2 package: candidate check 93/0, installer test 26/0, i18n 13/13,
    archive structure clean.
- **Commit and merge status:** nothing committed by the agent (no Git).
- **Deployment status (operator-reported):**
  - AWS runs `flh-public-demo-flh087-rc1`, active and ready, identity match;
  - rc1 is the previous release and rollback target.
- **Open:** see §5.
