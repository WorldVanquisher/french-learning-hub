# v1.0 release rehearsal

A repeatable rehearsal of the packaged application with real Docker Compose.
It goes through the daily wrapper, in an isolated project, and never touches
the daily instance. Report:
[docs/validation/V1-RELEASE-REHEARSAL.md](../../../docs/validation/V1-RELEASE-REHEARSAL.md).

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

## Browser smoke (a machine with Chrome)

1. **On the NAS, start an empty RC instance with the fake provider:**

   ```bash
   bash scripts/validation/v1_rehearsal/rehearse.sh serve <empty dir outside the repo>
   ```

2. **On the Mac, open the tunnel, install the browser driver once, and run the
   smoke:**

   ```bash
   ssh -N -L 18995:127.0.0.1:18995 <NAS_SSH_HOST>          # keep open
   mkdir -p /tmp/flh-browser-tools && cd /tmp/flh-browser-tools \
     && npm init -y > /dev/null && npm install --no-audit --no-fund --ignore-scripts playwright-core@1.49.1
   cd <checkout>/scripts/validation/v1_rehearsal
   PLAYWRIGHT_CORE_DIR=/tmp/flh-browser-tools/node_modules/playwright-core \
     node browser_smoke.mjs --url http://127.0.0.1:18995 --out /tmp/flh-browser-smoke
   ```

   The driver installs into a temporary directory and downloads no browser; it
   drives the installed Chrome (`--chrome PATH` to choose another).

3. **On the NAS, remove what `serve` started:**

   ```bash
   bash scripts/validation/v1_rehearsal/rehearse.sh down <same dir>
   ```

**What the smoke does.** It seeds four authored records over the API, then
drives this journey in the browser:
1. record stage → reviewable unit;
2. AI suggestion of the existing Concept (the only write in that phase);
3. a stale confirmation refused after an outside re-extraction;
4. an explicit Confirm SAME (exactly one write);
5. both source records;
6. return navigation with focus on the filed unit.

It also checks English ↔ 简体中文. Every other phase must send no write
request. Results go to `results.json` and screenshots.

`serve` uses the RC built from the checkout. Run the smoke once per fresh
`serve`: it refuses a non-empty instance.
