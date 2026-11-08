# v1.0.0 release evidence index

Written 2026-11-08 (UTC) on `ops/v1-release-prep`, after #126 merged. This
index points to evidence that already exists. It does not rewrite any
validation document. A check counts as **verified** only if a command was
executed and its result is recorded in the cited document or run. Syntax
checks, jsdom tests and shimmed Docker runs are listed as what they are.

Like every validation document, this index is a historical record. The
remaining checks are tracked in the go/no-go checklist of
[the v1.0.0 release plan](../plans/v1.0.0-release.md). Their results go into a
new validation note after the release decision (§9 of that plan); this index
is not edited to add them.

Legend:
- **VERIFIED**: executed; the result is recorded in the cited document or run.
- **PENDING**: not run yet, or no result has been provided.
- **NOT COVERED**: a known gap, stated as a limitation. It is not claimed.

## A. Verified

| # | Claim | Evidence (document → section) | Command and result | Origin |
|---|---|---|---|---|
| A1 | Release check passes on the RC tree | [DAILY-V1-RC.md](DAILY-V1-RC.md) §3, [V1-RELEASE-REHEARSAL.md](V1-RELEASE-REHEARSAL.md) §3 | `make verify` (offline, `unshare -rn`): **exit 0**; gofmt, Go tests, vet, builds, typecheck, **322 frontend tests**, production build | #123, #124 |
| A2 | The daily journey works end to end over the API with the fake provider | DAILY-V1-RC.md §2–3 | `daily_v1_rc/run.sh`: **43 passed, 0 failed** (rc1, and rc3 again in #124) | #123, #124 |
| A3 | The UI journeys send no writes while browsing (jsdom) | DAILY-V1-RC.md §3 | `DailyJourney.test.tsx`: 10 passed. *jsdom only; superseded for real-browser purposes by A8* | #123 |
| A4 | The public-demo acceptance still passes after the bundle change | DAILY-V1-RC.md §3 | `flh079/run.py`: **210 checks, 0 failed**. Its browser stage was **NOT RUN** (no browser) | #123 |
| A5 | The wrapper's commands, refusals and isolated mode behave as documented | V1-RELEASE-REHEARSAL.md §3, [V1-PACKAGED-BROWSER-SMOKE.md](V1-PACKAGED-BROWSER-SMOKE.md) §4 | `flh094/test_wrapper.sh`: **43 PASS, 0 failures** (docker shim; only `docker compose config` was real); rerun on the packaged-browser branch: `{"failures": 0}` | #124, #125–#126 |
| A6 | Packaged image upgrade, failed upgrade and recovery work with real Docker | V1-RELEASE-REHEARSAL.md §2 | `rehearse.sh run …/reh2 sha256:41a35172…4802`: **43 PASS, 0 FAIL, exit 0** (Docker 29.9.3, Compose 5.7.0). Baseline → backup → RC upgrade (snapshot byte-identical) → induced startup failure → stop / retag `before-upgrade` / restore → snapshot byte-identical; the record written after the backup is gone from the live data and kept in `before-restore-*` | #124 |
| A6′ | The rehearsal still passes with the fake-provider image pinned by digest | V1-PACKAGED-BROWSER-SMOKE.md §4 | `rehearse.sh run …/reh3`: **43 PASS, 0 FAIL, exit 0** | #125–#126 |
| A7 | The rehearsal harness fails loudly and cleans up after itself | V1-RELEASE-REHEARSAL.md §2 | `--inject-failure after-seed`: exit 1, evidence kept, cleanup PASS, daily instance unchanged | #124 |
| A8 | **Real browser:** the packaged RC passes the daily journey in real Chromium | V1-PACKAGED-BROWSER-SMOKE.md §4 | `browser_check.sh …/bc6` and `…/bc7 --browser-container`: **exit 0, 36 passed / 0 failed, all 10 phases**, Chromium 156.0.8078.79 on the NAS (disposable container). Writes were exactly: one suggestion run, one refused stale confirm (409), one confirm | #125–#126 |
| A9 | A failing smoke is reported and contained | V1-PACKAGED-BROWSER-SMOKE.md §4 | `failure_probe.sh …/probe1 sources`: **exit 0** (the inner check exited 1 with only the injected failure; screenshot and sanitized logs kept; only the run's own containers, tags and network removed) | #125–#126 |
| A10 | Seeding happens only on a verified-owned rehearsal instance | V1-PACKAGED-BROWSER-SMOKE.md §2, §4 | `test_ownership.py`: 15 OK. Live: foreign WORK refused; smoke exit 2 for a refused file, `:8080` and `localhost` before any request; exit 3 with no browser | #125–#126 |
| A11 | The daily NAS instance was never touched by any of the above | V1-RELEASE-REHEARSAL.md §2, V1-PACKAGED-BROWSER-SMOKE.md status | Daily container ID, state, start time and image identical before and after every run | #124, #125–#126 |
| A12 | Health and readiness endpoints answer as documented | DAILY-V1-RC.md §4, V1-RELEASE-REHEARSAL.md §2 | `/healthz` → `{"status":"ok"}`, `/readyz` → `{"status":"ready"}` (real binary in the fixture; real container in the rehearsal) | #123, #124 |
| A13 | No paid provider and no real key were used by any automated check | all three documents | Fake OpenAI-compatible provider with the key `placeholder-not-a-real-key`; diagnostics scanned for key-like values | all |
| A14 | **GitHub-hosted runner:** the `packaged-browser` job of the *Packaged browser smoke* workflow passes on the **pull-request commit of #126** | GitHub Actions run `42530700573` (reported by the owner, 2026-11-08) | Workflow **passed**. #126 then merged into `main`. This is **not** a run on the release commit (see B1). Recorded from the owner's report; the agent did not open the run, because Git and GitHub commands are owner-only, so step-level details such as the printed Chrome version are not copied here | #126 |

**About the schema in A6 and A6′.** Both sides of the upgrade ran the same
schema. The baseline image and the RC both contain migrations `001`–`013`, so
the rehearsal proved an image upgrade and recovery. It did **not** prove a
database migration. See C1.

**About the RC image identity.** The RC was built from the working tree at
rehearsal time. The release image is built locally from the `v1.0.0` tag by
`flh-daily.sh up`. No image is published and no byte-identical build is
claimed.

## B. Pending (each blocks GO unless the owner waives it in writing)

The go/no-go IDs refer to §2 of the release plan.

| # | Check | Why it is pending | How to close it | Status |
|---|---|---|---|---|
| B1 | **`packaged-browser` job on the release commit** on `main` | Run `42530700573` (A14) covered the #126 pull-request commit only. The release commit, including these documents, is a new tree | A green *Packaged browser smoke* run whose head SHA is the release commit. A documentation-only merge does not match the workflow's path filter, so dispatch it by hand (release plan §5). If it fails, download `packaged-browser-diagnostics` | PENDING (G2) |
| B2 | **Existing CI** (`CI` → `ci`, `qdrant-integration`, `web`; `Public demo` when its paths change) green on the release commit | The release commit does not exist yet | Check the runs for the release commit (release plan §5) | PENDING (G2) |
| B3 | **Real Luna positive SAME** with both sources visible | Needs the real model and billed calls; out of scope for agents | DAILY-V1-RC.md §5 steps 2–10, as listed in V1-RELEASE-REHEARSAL.md §6 item 4. Record the model's choice and reason verbatim, even if it differs | PENDING (G4) |
| B4 | **Baseline confirmation:** `sha256:41a3517252348c06024bd8d03470af9ac7f179acfe1b55c9598c075b3bfe4802` is the correct pre-#123 baseline | The owner never designated one; the agent chose the image the daily container runs | Confirm, or supply another image and rerun `rehearse.sh run` with it | PENDING (G5) |
| B5 | `make verify` on the release commit | A1 ran on the RC tree before the packaged-browser work merged. That work changed no product code, but the merged tree is new | `make verify` on the release commit (after `cd web && npm ci`) | PENDING (G3) |

## C. Not covered (accepted limitations, stated in the release notes)

| # | Gap |
|---|---|
| C1 | **A database-migration upgrade** (old schema → new schema) was not rehearsed, because no migration was added between the baseline and the RC. It needs a future release that adds one |
| C2 | **Browsers.** Only Chromium was tested (on the NAS, and as Google Chrome on the GitHub runner); no other browser and no narrow-screen layout |
| C3 | **The public-demo browser stage** (FLH-079) was not run in #123. The public demo is not part of this release and is not deployed by it |
| C4 | **Real-model judgment** beyond the single B3 walkthrough is not evaluated. The fake provider proves mechanics only |
| C5 | **The documented daily upgrade on the real NAS instance** has not been performed yet. It is the owner's deployment step after GO (release plan §7) |

## D. Sources

- [DAILY-V1-RC.md](DAILY-V1-RC.md): PR #123 (`04125e9`)
- [V1-RELEASE-REHEARSAL.md](V1-RELEASE-REHEARSAL.md): PR #124 (`621ac81`)
- [V1-PACKAGED-BROWSER-SMOKE.md](V1-PACKAGED-BROWSER-SMOKE.md): written on
  `ci/v1-packaged-browser-smoke`, merged through #125 (`4c55dca`) and #126
  (`1c4af7d`). Its §5 lists the runner check as not yet run; A14 records that
  run, and that document is left as written
- GitHub Actions run `42530700573`: *Packaged browser smoke* on the #126
  pull-request commit, **passed** (reported by the owner)
- [DAILY_USE.md](../DAILY_USE.md) §6 and [RELEASE.md](../RELEASE.md)
  (*Upgrades and migration rollback limits*): the operator procedures that were
  exercised
