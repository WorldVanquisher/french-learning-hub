# v1.0 release rehearsal

A repeatable rehearsal of the packaged application with real Docker Compose.
It goes through the daily wrapper, in an isolated project, and never touches
the daily instance. Reports:
[V1-RELEASE-REHEARSAL.md](../../../docs/validation/V1-RELEASE-REHEARSAL.md)
(upgrade and recovery) and
[V1-PACKAGED-BROWSER-SMOKE.md](../../../docs/validation/V1-PACKAGED-BROWSER-SMOKE.md)
(browser smoke).

## Upgrade and recovery (NAS, Docker)

```bash
bash scripts/validation/v1_rehearsal/rehearse.sh run <empty dir outside the repo> <BASELINE_IMAGE_ID>
```

`BASELINE_IMAGE_ID` is the known-good image to upgrade from, given as
`sha256:…`. It must already be present: it is never pulled, rebuilt, retagged
or removed. The release candidate (RC) is built from this working tree by the
wrapper's `up`.

**Steps** (each recorded in `evidence/results.tsv`):

0. **Preflight** (read-only). Every resolved Compose configuration must use
   project `flh-rehearsal-<run>`, images `flh-rehearsal-<run>:*`,
   `127.0.0.1:18995` (override with `REHEARSAL_PORT`), and `/data` inside the
   work directory. The daily container and the `french-learning-hub:local`
   image are fingerprinted.
1. **Baseline.** Start the baseline through the wrapper and check readiness.
   Seed it with `scripts/validation/daily_v1_rc/journey.py`, then record a
   snapshot with `snapshot.py`.
2. **Backup.** `flh-daily.sh backup`, then verify the checksums and integrity.
   Keep the known-good image as `:before-upgrade`.
3. **Upgrade.** `flh-daily.sh up` builds and starts the RC. Readiness and the
   snapshot must be unchanged; the applied migrations are compared. One record
   is then written after the backup.
4. **Failed upgrade.** An induced startup failure (unknown server flag)
   follows. Recovery runs in the documented order: `stop`, retag the
   known-good image, `restore <backup>`. Then check readiness, integrity, the
   snapshot (it must equal the baseline), and that the post-backup record is
   gone but kept in the replaced data directory.

**On exit**, even after a failure:
- Compose `ps`, logs and container state are saved to `evidence/`.
- Only this run's containers, network and image tags are removed.
- The daily fingerprint must be unchanged.

`--inject-failure after-seed` aborts after step 1 to show this. `--keep`
leaves the project running.

## Packaged browser smoke (one command)

```bash
bash scripts/validation/v1_rehearsal/browser_check.sh <empty dir outside the repo>                       # host Chrome/Chromium
bash scripts/validation/v1_rehearsal/browser_check.sh <empty dir outside the repo> --browser-container   # NAS (no browser)
```

It runs these steps, and tears down on every exit path:
1. **Find the browser first.** If none is found, it exits **3 (BLOCKED)**
   before building anything. A missing browser never counts as a pass.
   - Host order: `--chrome PATH`, `$CHROME`, then `google-chrome`,
     `google-chrome-stable`, `chromium` and `chromium-browser` on `PATH`, then
     the macOS Google Chrome.
   - `--browser-container` uses a disposable container instead. It starts from
     the local `node:22-bookworm-slim` image (pinned and never pulled; Debian's
     `chromium` is installed inside it at run time). It runs on the host
     network, as your uid.
2. **Install the driver:** `playwright-core@1.49.1` into `WORK/tools`. No
   browser is downloaded.
3. **`rehearse.sh serve WORK/instance`.** This builds the RC through the
   wrapper, in an isolated project with the fake provider and an empty
   database.
4. **`rehearse.sh verify WORK/instance`** (read-only, `ownership.py`) proves
   that `127.0.0.1:PORT` belongs to that project, using the live Docker state:
   - project name and the compose files it was created from;
   - the single loopback port binding, with no other container publishing that
     port;
   - the `/data` mount;
   - the fake-provider settings and the placeholder key (compared, never
     printed);
   - the fake-provider container;
   - readiness, suggestions enabled, and an empty database.

   Any doubt is a refusal. `browser_smoke.mjs` seeds nothing unless
   `ownership.json` says `owned` for its exact URL, a `flh-rehearsal-*`
   project, and was verified within the last 30 minutes.
5. **`browser_smoke.mjs`** drives the journey in headless Chrome with a fresh
   temporary profile.
6. **`rehearse.sh down WORK/instance`** removes only that project's
   containers, network and tags, and checks the daily fingerprint.
7. **Bounded diagnostics** go to `WORK/diagnostics/`: `results.json`,
   screenshots, and sanitized log tails (no database, no settings file).

Exit codes: **0** PASS; **1** FAIL; **2** refused; **3** BLOCKED (no browser).
PASS needs:
- a passing smoke with every phase run and at least 30 checks;
- a clean teardown.

**Controlled failure.**
`bash scripts/validation/v1_rehearsal/failure_probe.sh <empty dir> [PHASE] [options]`
runs the same check with `--inject-failure PHASE` (default `sources`). It
passes only if:
- the check exits 1;
- the injected check is the only failure;
- the error screenshot and the sanitized logs are kept;
- teardown removed every resource of the project.

**Self-tests (no Docker):**
`python3 -B -m unittest discover -s scripts/validation/v1_rehearsal -p 'test_*.py'`.

**CI:** `.github/workflows/packaged-browser.yml` runs both on ubuntu-latest
with the runner's Google Chrome. It uploads `diagnostics/` only on failure.

### What the smoke checks

It seeds four authored records over the API, then drives this journey in the
browser:
1. record stage → reviewable unit;
2. AI suggestion of the existing Concept (the only write in that phase);
3. a stale confirmation refused by the server after an outside re-extraction;
4. an explicit Confirm SAME (exactly one write);
5. both source records;
6. return navigation with focus on the filed unit.

It also checks English ↔ 简体中文. Every other phase must send no write
request, and the only console error allowed is the browser's log of that 409.

### Mac entry point (Chrome on the Mac, package on the NAS)

1. **On the NAS:**
   ```bash
   bash scripts/validation/v1_rehearsal/rehearse.sh serve <dir>
   bash scripts/validation/v1_rehearsal/rehearse.sh verify <dir>
   ```
   Then copy `<dir>/evidence/ownership.json` to the Mac. It is valid for
   30 minutes.
2. **On the Mac:**
   ```bash
   ssh -N -L 18995:127.0.0.1:18995 <NAS_SSH_HOST>          # keep open
   mkdir -p /tmp/flh-browser-tools && cd /tmp/flh-browser-tools \
     && npm init -y > /dev/null && PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install --no-audit --no-fund --ignore-scripts playwright-core@1.49.1
   cd <checkout>/scripts/validation/v1_rehearsal
   PLAYWRIGHT_CORE_DIR=/tmp/flh-browser-tools/node_modules/playwright-core \
     node browser_smoke.mjs --url http://127.0.0.1:18995 --out /tmp/flh-browser-smoke --ownership /path/to/ownership.json
   ```
3. **On the NAS:**
   ```bash
   bash scripts/validation/v1_rehearsal/rehearse.sh down <dir>
   ```

Run the smoke once per fresh `serve`: it refuses a non-empty instance.
