# v1.0 packaged browser smoke — real browser, ownership-gated, in CI

Owner: NAS Claude Code, sole writer, branch `ci/v1-packaged-browser-smoke`.
Date: 2026-11-07 (US Eastern; UTC timestamps in the evidence are 2026-11-08).
Follows [V1-RELEASE-REHEARSAL.md](V1-RELEASE-REHEARSAL.md) §4, where the
smoke was only syntax-checked.

**Status:**
- **Browser smoke: PASS in real Chromium 156.0.8078.79**, run twice on the NAS
  against the packaged RC. Each run had 36 checks and 0 failures.
- **Controlled failure: PASS.** Exit 1, evidence kept, only the run's own
  resources removed.
- **CI workflow: written, NOT YET RUN on GitHub.** The owner checks it on the PR.
- **Daily instance: untouched.** Its container ID, state, start time and image
  were identical before and after every run.

## 1. What changed

| Gap in #124 | Now |
|---|---|
| Ownership inferred from "empty DB + loopback URL" | `rehearse.sh verify` (`ownership.py`) proves from live Docker state that `127.0.0.1:PORT` is the project `serve` created (§2). The smoke refuses to seed without an `owned` file for its exact URL |
| Browser path fixed to macOS Chrome | Discovery: `--chrome`, `$CHROME`, `google-chrome`, `google-chrome-stable`, `chromium` or `chromium-browser` on PATH, then macOS Chrome. `--browser-container` for hosts without one. A fresh temporary profile each run |
| Several manual steps | `browser_check.sh WORK`: browser → driver → serve → verify → smoke → down (always) → bounded diagnostics. Exit 0/1/2/3 (3 = BLOCKED, no browser) |
| No failure proof | `--inject-failure PHASE` and `failure_probe.sh` |
| No CI | `.github/workflows/packaged-browser.yml` (new workflow; existing check names and `public-demo.yml` unchanged) |
| Fake provider image `python:3.12-slim` by tag | Pinned by digest in `rehearse.sh`; CI pulls exactly that reference |

## 2. Ownership verification (fail closed)

`ownership.py` reads `docker ps -a`/`docker inspect` for all containers, plus
three GETs. The verdict is `owned` only if **all** of these hold:
- **Project:** the name is `flh-rehearsal-<14 digits>` and equals
  `WORK/project`. It is never `french-learning-hub`.
- **Containers:** exactly one running `app` and one running `fake-provider`.
  Both were created from `REPO/compose.yaml` + `WORK/compose/upgrade.yaml`,
  with this checkout as the working directory.
- **Port:** the app image is `<project>:app` and publishes exactly
  `127.0.0.1:PORT`. No other container publishes that port.
- **Data:** the app's only mount is `WORK/data` → `/data`, and no daily
  container mounts it.
- **Provider:** the provider URL is `http://fake-provider:19195/v1`. The key
  equals the placeholder (compared only, never written out). All three
  providers are openai.
- **Fake provider:** it runs the fixture script, publishes no port, and shares
  the app's network.
- **HTTP:** `/readyz` reports ready, suggestions are enabled, and there are
  zero entries.

Any collection error is a refusal. There are 15 self-tests without Docker
(`test_ownership.py`), and the live refusals below were run.

## 3. Defects found by the first real-browser runs (all in the harness)

| # | Symptom in Chromium | Cause | Fix |
|---|---|---|---|
| 1 | The container could not read `ownership.json` | `browser_check.sh` passed the host path into the container | The container uses the mounted `/ownership.json` |
| 2 | `getByLabel('Language')` matched 2 elements | "Explanation language" also matches | First tried `exact` (→ 3) |
| 3 | `getByLabel('Language', {exact})` timed out | The `<label>` wraps the `<select>`, so its name includes the option names | Select the visible `<select>` that has a `zh-CN` option, and check its label text separately |
| 4 | "generation is the only write" failed | The packaged UI calls `/api/...` | Record request paths without the `/api` prefix |
| 5 | Clicking stale Confirm timed out; the button was detached | Returning to AI suggestions re-reads the run asynchronously. The outside re-extraction landed first, so the re-read showed "Stale: cannot be confirmed" mid-click | Wait for both re-read GETs before the stale phase. The click now reaches the server, which refuses it (409) |
| 6 | "record stage now complete" failed | The regex was anchored, but the text follows a bold "Next:" | Unanchored match; the stage text goes into the detail on failure |
| 7 | "no console errors" failed | Chrome logs the refused stale confirm as a 409 resource error | Exactly one such 409, in the stale phase, is required; any other error fails |

**No product defect was found.** No product code changed, so `make verify`
was not required (§5).

## 4. Commands run and results

Working directories were under the session scratchpad.

| Command | Result |
|---|---|
| `python3 -B -m unittest discover -s scripts/validation/v1_rehearsal -p 'test_*.py'` | 15 tests OK |
| `browser_check.sh <s>/bc-blocked` (host, no browser) | **exit 3**: BLOCKED before anything was built or started; `diagnostics/results.json` says `browser-missing` |
| `browser_check.sh <s>/bc1 … bc5 --browser-container` | exit 1 each: defects 1–7 above, fixed one by one. Teardown PASS every time |
| `browser_check.sh <s>/bc6 --browser-container` | **exit 0. 36 passed, 0 failed, all 10 phases.** Writes: one `POST /concept-suggestion-runs`, one refused stale confirm (409), one confirm. Six screenshots; diagnostics 2.1 MB; no key in diagnostics |
| `browser_check.sh <s>/bc7 --browser-container` | **exit 0, 36/0** (repeatability) |
| `failure_probe.sh <s>/probe1 sources --browser-container` | **exit 0.** The check exited 1, and the only failure was the injected one in `sources`, after 27 passing checks. Kept: error screenshot, sanitized logs. Removed: every container, tag and network of the project. No browser container left. Daily instance unchanged |
| `rehearse.sh serve <s>/neg-a`, then `verify <s>/neg-a` | `owned` |
| `verify <s>/neg-b` (same project name, other WORK) | **refused** (compose files and `/data` mount do not match) |
| `browser_smoke.mjs` with the refused file / URL `:8080` / `localhost` | **exit 2** each, before any request. The instance stayed empty |
| `browser_smoke.mjs` with an owned file on the host (no browser) | **exit 3** |
| `rehearse.sh down <s>/neg-a` | exit 0; cleanup PASS; daily instance unchanged |
| `bash scripts/validation/flh094/test_wrapper.sh <s>/wrapper4` | `{"failures": 0}` |
| `rehearse.sh run <s>/reh3 sha256:41a35172…4802` (repeated, because the fake-provider image reference changed) | **43 PASS, 0 FAIL, exit 0**. Same result as #124; daily instance unchanged; baseline image still present |
| Workflow YAML parsed with a local PyYAML (all three workflows) | OK; existing job names unchanged |

**The NAS has no usable browser.** Neither Chrome nor Chromium is installed,
and the GUI libraries are missing. The real browser therefore ran in a
disposable container: `--rm`, labelled `org.flh.task=v1-browser-smoke`, from
the local pinned `node:22-bookworm-slim`. Debian's `chromium` was installed
inside it at run time. Nothing was installed on the host.

## 5. Not run / remaining owner checks

1. **CI on the PR.** The job `packaged-browser` must pass. It runs:
   - the self-tests and the wrapper test;
   - a pull of the pinned fake-provider image;
   - `google-chrome --version`;
   - `browser_check.sh` with the runner's Chrome;
   - `failure_probe.sh`.

   That step has not run on GitHub yet, and host-Chrome mode (as opposed to
   the container) has not been run anywhere. On failure, download
   `packaged-browser-diagnostics`.
2. **One real Luna positive SAME** with both sources visible:
   [V1-RELEASE-REHEARSAL.md](V1-RELEASE-REHEARSAL.md) §6 item 4. The fake
   provider proves mechanics, not model judgment.
3. **The baseline image**, unchanged from #124: confirm
   `sha256:41a35172…4802`.
4. `make verify`: not run. No Go, web or migration file changed in this task.
