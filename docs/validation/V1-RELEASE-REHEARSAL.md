# v1.0 release rehearsal — packaged upgrade, recovery and browser smoke

Owner: NAS Claude Code, sole implementation owner, working tree
`~/workspace/flh-nas-claude`. Date: 2026-11-07 (US Eastern; UTC timestamps in
the evidence are 2026-11-08).

**Status at a glance:**
- **Docker upgrade and recovery: rehearsed with real Docker Compose. PASS.**
- **Browser smoke: NOT RUN.** No Chrome or Chromium exists on this host. The
  script and the owner's command are in §4.
- **Real-model positive SAME: NOT RUN** (owner checklist, §6).
- **Daily NAS instance and database: not touched.** Their fingerprints were
  unchanged after every run.

## 1. Boundaries and the baseline

| Item | Value |
|---|---|
| Daily instance (never targeted) | project `french-learning-hub`, container `french-learning-hub-app-1`, image `french-learning-hub:local` = `sha256:41a35172…4802`, `127.0.0.1:8080` |
| Rehearsal | project `flh-rehearsal-<UTC run>`, images `flh-rehearsal-<run>:{app,before-upgrade}`, `127.0.0.1:18995`, settings/data/evidence in a scratch directory, fake provider as a second service (local `python:3.12-slim`, no published port, placeholder key) |
| **Baseline image** | `sha256:41a3517252348c06024bd8d03470af9ac7f179acfe1b55c9598c075b3bfe4802`, created 2026-10-22: the image the daily container runs. **The owner did not designate a baseline.** I chose this image because it exists locally and predates #123; it was only read, started in the isolated project, and tagged. **Owner: confirm or supply another** (§6) |
| Proof it predates #123 | Its served workbench bundle lacks "Where this record stands"; the RC bundle has it (checked over HTTP) |
| RC | Built from this working tree (PR #123 content plus this task's ops changes) by the wrapper's own `up` |
| **Migrations** | **Identical in both images**: `001`–`013`. This rehearsal proves an **image upgrade and recovery, not a database migration.** No migration was fabricated |

**A finding that made a code change necessary.** The wrapper hard-codes the
daily project, and `compose.yaml` hard-codes the image `french-learning-hub:local`.
So `flh-daily.sh up` from any settings file would rebuild the daily image tag
and recreate the daily project. The smallest change:
- an opt-in isolated mode in `scripts/daily/flh-daily.sh`, which needs both
  `FLH_COMPOSE_PROJECT` and `FLH_COMPOSE_OVERRIDE`;
- it refuses the daily project name and any `french-learning-hub` image;
- the resolved configuration is re-checked.

With neither variable set, the invocation is byte-identical to before. Tested
in §3.

## 2. Docker upgrade and recovery (run, real Docker)

```bash
bash scripts/validation/v1_rehearsal/rehearse.sh run <scratch>/reh2 sha256:41a3517252348c06024bd8d03470af9ac7f179acfe1b55c9598c075b3bfe4802
```

Docker 29.9.3, Compose 5.7.0. **Result: 43 PASS, 0 FAIL, exit 0.** Each step
uses the operator path (`flh-daily.sh` in isolated mode):

| Step | Evidence |
|---|---|
| 0. Preflight (read-only) | **Before any mutating command**, each override's resolved config checks project, image, port and `/data`. The project had no containers and port 18995 was free. The daily container ID, state, start time and image, and the `:local` ID, were recorded |
| 1. Baseline | `up` → healthy; `/readyz` `{"status":"ready"}`, `/healthz` `{"status":"ok"}`; running image = baseline ID. **Seeded with the #123 RC fixture against the baseline: 43 passed, 0 failed.** Snapshot: 4 records, 5 units, Concept #1 supported by unit 1 (record 1) and unit 2 (record 2), y unit and stale units unfiled, 1 suggestion run. It records exact questions, analysis/feedback/extraction IDs and versions, current-extraction selection, CURRENT SAME (concept + link) and source links |
| 2. Backup | `flh-daily.sh backup`: `SHA256SUMS` verify, `integrity_check` = `ok`, service ready again. Known-good image kept as `:before-upgrade` |
| 3. Upgrade | `flh-daily.sh up` built the RC (different image ID) → healthy. RC bundle has the stage summary. **Snapshot byte-identical to the baseline.** Then one record (#5) was written after the backup |
| 4. Failed upgrade | Induced startup failure (`entrypoint` with an unknown server flag). `up` returned non-zero after 60 s ("did not become healthy … state: unhealthy"); `/readyz` unreachable; the app log names `flag provided but not defined: -rehearsal-induced-startup-failure` (10 restarts) |
| 4. Recovery, documented order | (1) `flh-daily.sh stop`, (2) retag `:before-upgrade` → `:app`, (3) `flh-daily.sh restore <backup>` → healthy. The running image is the baseline ID again; live `integrity_check` = `ok`; migrations equal the baseline. **Snapshot byte-identical to the baseline** (questions, versions, CURRENT SAME, sources). Record #5 → `404`, but present in `data.before-restore-*` |
| Cleanup | No container, tag or network of the project remains. The untagged RC image was removed too. **Daily fingerprint identical before/after.** Baseline image still present |

**Failure path:**
```bash
rehearse.sh run <scratch>/reh-inject <same baseline> --inject-failure after-seed
```
- **Result:** exit 1 with `FAIL injected failure after seeding`.
- **Evidence kept:** Compose `ps`, logs and container state at exit, configs,
  the seed journey and the snapshot.
- **Cleanup and daily instance:** the same cleanup PASS lines; daily instance
  unchanged.

**Earlier invalid run (kept for honesty).** The first run (`reh1`) exited 1:
- **Seeding failed** because the harness did not create the provider call log.
- **Snapshots were empty**, so its comparisons proved nothing.
- **I then edited the script while bash was still reading it**, which caused a
  syntax error mid-run.

Fixes: the harness now creates the log, aborts if seeding fails, and requires a
non-empty baseline. That run's cleanup still removed everything and left the
daily instance unchanged.

**Packaged `serve`/`down`** (for the browser smoke): see §3.

## 3. Commands actually run

| Command | Result |
|---|---|
| `rehearse.sh run …/reh2 <baseline>` | 43 PASS, 0 FAIL, exit 0 |
| `rehearse.sh run …/reh-inject <baseline> --inject-failure after-seed` | exit 1 as intended; evidence kept; cleanup PASS; daily unchanged |
| `rehearse.sh serve …/reh-serve2` then `rehearse.sh down …/reh-serve2` | serve exit 0: preflight PASS, RC built and healthy through the wrapper, `/readyz` ready, bundle has the stage summary, suggestions enabled, empty database. down exit 0: no container, tag or network left; daily instance unchanged |
| `bash scripts/validation/flh094/test_wrapper.sh <scratch>/wrapper2` | **43 PASS, 0 failures** (32 existing + 11 new). Normal invocation unchanged (`docker compose --env-file <settings> up -d --build`, no `-p/-f`). Isolated mode passes `-p <project> -f compose.yaml -f <override>`. It refuses a missing half, the daily project name, an invalid name, and an override that keeps the daily image, before any start |
| `bash scripts/validation/daily_v1_rc/run.sh <scratch>/rc3` | 43 passed, 0 failed (fake provider's default loopback bind unchanged) |
| `unshare -rn bash -c 'ip link set lo up; GOPROXY=off GOFLAGS=-mod=readonly GOTOOLCHAIN=local NODE_OPTIONS=--no-experimental-webstorage make verify'` | exit 0; frontend 322 tests in 25 files; production build |

The only harness change after `reh2` is that `down` now also compares the
daily fingerprint recorded by `serve`. The earlier `reh-serve` run, made
before that change, passed without this comparison. `run` is unchanged since
`reh2` (checked by `diff` against a copy taken before the run).

## 4. Browser smoke — NOT RUN

There is no Chrome or Chromium on the NAS, and I did not install one. I did
not substitute jsdom or the Docker shim.

**The script.** `scripts/validation/v1_rehearsal/browser_smoke.mjs` uses the
same playwright-core 1.49.1 + installed Chrome pattern as the FLH-076 demo
acceptance. It was checked with `node --check` only and **has never been
executed**, so expect possible selector fixes on its first run.

**What it covers:**
- record stage → reviewable unit;
- AI suggestion of the existing Concept;
- stale confirmation refused after an outside re-extraction;
- explicit Confirm SAME;
- both distinct source records;
- return to the original views;
- focus on the filed unit after **← Back to record**;
- English ↔ 简体中文.

**No-write checks.** It asserts **no write request** while browsing a record,
switching language, opening a suggestion's record, browsing sources and
returning. It asserts exactly one write each for generation and confirmation.

**Owner command** (details in `scripts/validation/v1_rehearsal/README.md`):

1. On the NAS:
   ```bash
   bash scripts/validation/v1_rehearsal/rehearse.sh serve ~/flh-rehearsal-browser
   ```
2. On the Mac:
   ```bash
   ssh -N -L 18995:127.0.0.1:18995 <NAS_SSH_HOST>
   mkdir -p /tmp/flh-browser-tools && cd /tmp/flh-browser-tools && npm init -y > /dev/null && npm install --no-audit --no-fund --ignore-scripts playwright-core@1.49.1
   cd <checkout>/scripts/validation/v1_rehearsal
   PLAYWRIGHT_CORE_DIR=/tmp/flh-browser-tools/node_modules/playwright-core node browser_smoke.mjs --url http://127.0.0.1:18995 --out /tmp/flh-browser-smoke
   ```
3. On the NAS:
   ```bash
   bash scripts/validation/v1_rehearsal/rehearse.sh down ~/flh-rehearsal-browser
   ```

## 5. Release blockers

**Found and fixed in this rehearsal:**
1. **The wrapper could not target an isolated project.** It now has a guarded,
   opt-in isolated mode; daily behaviour is unchanged (§1, §3).
2. **The documented rollback rebuilt from an older checkout.** It now keeps and
   restores the known-good image tag: stop → `docker image tag
   french-learning-hub:before-upgrade french-learning-hub:local` →
   `restore`. Updated in `docs/DAILY_USE.md` and `docs/RELEASE.md`. Rebuilding
   from the previous checkout is kept as a fallback. This is the order the
   rehearsal exercised.

**Not a defect, now documented:** after a failed `up` the container stays in a
`restart: unless-stopped` loop until `stop`, which is the first recovery step.

**Remaining before `v1.0.0`:**
1. **Browser smoke** (§4) on the owner's machine.
2. **The real-model positive SAME path** (§6).
3. **Owner confirmation of the baseline image** (§1). A **database-migration**
   upgrade is not covered, because both images have migrations `001`–`013`. It
   needs a future release with a new migration.

## 6. Owner checklist: final Luna positive SAME and release decision

1. **Confirm the baseline.** Confirm that `sha256:41a35172…4802` (the current
   daily image) is the right pre-#123 baseline, or rerun §2 with the image you
   supply.
2. **Browser smoke.** Run §4; attach `/tmp/flh-browser-smoke/results.json`.
   Fix-ups to selectors are expected on the first run.
3. **Before upgrading the daily instance:**
   - `bash scripts/daily/flh-daily.sh backup`;
   - `docker image tag french-learning-hub:local french-learning-hub:before-upgrade`;
   - update the checkout;
   - `bash scripts/daily/flh-daily.sh up`;
   - `curl -fsS http://127.0.0.1:8080/readyz`.
4. **Luna positive SAME.** Follow `docs/validation/DAILY-V1-RC.md` §5:
   1. a first `en` question → NEW CONCEPT;
   2. a second question on the same use of `en`;
   3. **AI suggestions** → expect a recommendation of that Concept;
   4. **Confirm SAME**;
   5. **Open Concept** → both units supporting → **View source record** for
      each: the two original questions are distinct and exactly as typed;
   6. **← Back** returns to each view.

   Record the model's choice and reason as given, even if it differs.
5. **Rollback**, only if something fails: `stop` → `docker image tag
   french-learning-hub:before-upgrade french-learning-hub:local` →
   `restore <backup>` → `/readyz`.
6. **Decide.** Release `v1.0.0` only if items 2 and 4 pass. Otherwise list the
   failing step and keep the backup and the `before-upgrade` tag.
