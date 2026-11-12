# Public demo package check (demo-candidate lane)

One local entry point for a packaged public demo (`scripts/demo/flh076/package.sh`
output): identity, health, the read-only boundary, attempted writes and the
browser suites. Each stage runs the maintained tool for it; nothing here
re-implements their checks.

```sh
CHROME=/usr/bin/chromium bash scripts/validation/demo_candidate/check_package.sh \
  /abs/flh-public-demo-<label>[-BLOCKED] /abs/new/work/dir \
  --expect-version <artifact version> [--expect-manifest <manifest sha256>] [--expect-status BLOCKED|CANDIDATE] \
  --node-modules /abs/dir/node_modules --suites all
```

| Stage | Tool | Passes when |
|---|---|---|
| identity | the package's `validate-release.sh` | exit 0 for `CANDIDATE`, 3 for `BLOCKED`, matching `RELEASE.json`; `RELEASE.json`'s artifact version, manifest SHA-256, `real_model` and domain fingerprint equal `artifact/manifest.json` and every `--expect-*` value |
| boundary | `scripts/demo/flh076/smoke_package.sh` | allowed GETs 200, private routes 404, writes 405 (root and `/api`), preset counters as expected, package files unchanged |
| live | the package's `deploy/ctl.sh start` | `/healthz` and `/readyz` 200; `/knowledge-library/demo` serves `RELEASE.json`'s identity, read-only and synthetic |
| writes | `write_probe.sh` | 14 well-formed writes (capture, entry, Concept, pin, clear; root and `/api`) all answered 405, the demo's identity and counters unchanged |
| browser | `demo_ux/accept_matrix.mjs`; with `--suites all` also `demo_refresh/accept_paths.mjs`, `demo_first_visit/*.mjs`, `flh076/browser/accept.mjs` | every suite exits 0 (vectors `mechanical` for a `BLOCKED` package, else `model`) |
| stop | `deploy/ctl.sh stop` | no demo process left for this package; package files unchanged |

- **Exit:** 0 passed; 1 a check failed; 2 usage or refused (existing work
  directory, busy port, not Linux); 4 the browser could not run and
  `--skip-browser` was not given.
- **Evidence:** `WORK/summary.json` (stage results and identity),
  `WORK/check.txt`, each tool's own output under `WORK/`.
- **Needs:** Linux (the package's own binary), Python 3, `curl`,
  `sha256sum`, and for the browser stage Node, `playwright-core` (no browser
  download) and Chromium or Chrome. Ports `--port` (default 18986) and the
  next one, loopback only.
- **Never:** installs, uploads, deploys, contacts an encoder or provider, or
  runs Git.
- **A pass does not make a release.** A `BLOCKED` (mechanical-vector) package
  that passes is still not releasable; only a `CANDIDATE` built from real-model
  vectors can be (docs/PUBLIC_DEMO.md, "Real-E5 candidate (owner only)").

`write_probe.sh BASE_URL OUT_FILE` can also be run on its own against any
loopback demo.

## Negative controls

```sh
CHROME=/usr/bin/chromium bash scripts/validation/demo_candidate/negative_controls.sh \
  /abs/flh-public-demo-<label>[-BLOCKED] /abs/new/work/dir \
  --control-package /abs/<package built from a tree without the malformed-link notice> \
  --node-modules /abs/dir/node_modules
```

Each control feeds the gate something it must reject and passes only when the
failure is actually detected (`DETECTED`; `MISSED` exits 1):

| Control | What is fed | Detected when |
|---|---|---|
| identity-version, identity-manifest | `check_package.sh` with a wrong `--expect-version`, then a wrong `--expect-manifest` | exit 1, with "identity mismatch" in both the offline identity and the served identity |
| write | the package's own server started **without** `-public-demo-artifact` (a normal server, providers off, on a throwaway database in WORK) | `write_probe.sh` exits 1 naming the accepted writes, and the database holds the probe's entries, so the writes really happened |
| link | `check_package.sh` on a package built from a tree without the malformed-link handling (for example main at `521279a`) | exit 1 with identity, boundary, live and writes passing and only the browser stage failing, on "a malformed link opens the start with a notice" |

The link control is `NOT RUN` without `--control-package`, `CHROME` and
`--node-modules`. It uses ports `--port`..`--port`+4 (default 18986).
