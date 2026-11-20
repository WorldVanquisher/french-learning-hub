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
| identity | the package's `validate-release.sh` | exit 0 for `CANDIDATE`, 3 for `BLOCKED`, matching `RELEASE.json`; `RELEASE.json`'s artifact version, manifest SHA-256, `real_model` and domain fingerprint equal `artifact/manifest.json` and every `--expect-*` value; with `--expect-sums`, the package's `SHA256SUMS` digest equals the one `package.sh` printed, so no file (another server binary with a regenerated `SHA256SUMS`, for example) differs from the package built; with `--pinned-manifest FILE` (R2), a copy of `SHA256SUMS` kept outside the package, every package file matches it and a difference names the file (with `--expect-sums` too, FILE's own digest must equal it) |
| boundary | `scripts/demo/flh076/smoke_package.sh` | allowed GETs 200, private routes 404, writes 405 (root and `/api`), preset counters as expected, package files unchanged |
| live | the package's `deploy/ctl.sh start` | `/healthz` and `/readyz` 200; `/knowledge-library/demo` serves `RELEASE.json`'s artifact identity, read-only and synthetic; `/` is this package's page (`RELEASE.json` `web`: build id, entry script, `index.html` SHA-256), so a package sharing the artifact cannot pass in its place |
| writes | `write_probe.sh` | 14 well-formed writes (capture, entry, Concept, pin, clear; root and `/api`) all answered 405, the demo's identity and counters unchanged |
| examples | `check_examples.py` | every guided example, comparison and suggested search in `web/src/demo/discovery.json` (or `--examples SPEC`) resolves against the served artifact the way the page resolves it; a stale entry fails with one readable reason. Writes the support matrix `WORK/examples/examples-matrix.md` |
| browser | `demo_ux/accept_matrix.mjs`; with `--suites all` also `demo_refresh/accept_paths.mjs`, `demo_first_visit/*.mjs`, `flh076/browser/accept.mjs` | every suite exits 0 (vectors `mechanical` for a `BLOCKED` package, else `model`) |
| stop | `deploy/ctl.sh stop` | no demo process left for this package; package files unchanged |

- **Low-memory path:** `--skip-browser` runs identity, boundary, live, writes,
  examples and stop, about 1 minute and no browser. `summary.json` `omitted`
  lists the browser suites left out (`accept_matrix` only, or all six with
  `--suites all`). Run those suites one at a time where at least 2 GB is
  free, or the whole stage with `--suites all` where 3 GB is.
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

**Is what is served this package?** `python3 -I check_served.py BASE_URL
PKG_DIR` compares a served demo with the package directory the operator
holds. It works for loopback, a staging host, or the published address
behind a proxy, and uses GETs only. It checks:
- the page's build id, entry script and `index.html` SHA-256 against
  `RELEASE.json` `web`;
- the entry script's and stylesheet's served bytes against `SHA256SUMS`, so
  a proxy serving a stale copy fails;
- the artifact identity against `RELEASE.json` `artifact`;
- `no-cache` on the page and `immutable` on assets.

Use it for the staged smoke, after a deployment, and after a rollback
(against the package rolled back to). Exit 0 only when everything matches.

`write_probe.sh BASE_URL OUT_FILE` can also be run on its own against any
loopback demo, and so can
`python3 -I check_examples.py BASE_URL web/src/demo/discovery.json OUT_DIR`
(GETs only; exit 1 names each stale entry, for example "“pronouns” matches
Concepts [12], whose supporting units include 0 with “y remplacé” in their
wording (the page needs exactly 1)").

## Build assertion (R2)

`python3 -I check_bundle.py WEB_DIR [--private-host-file FILE]` checks a public
demo web build before it ships; `package.sh` runs it on its own build and
refuses a build that fails. It passes when the directory holds only
`index.html` and `assets/*.js|*.css`, `index.html` names exactly one entry
script and only files that are there, no script is named like a workbench
chunk, and no script or page names a private route (the server's routes other
than health, the knowledge library and static assets, plus the Workbooks
lane's `/review-today`, `/practice-feed`), a private content pack or fixture,
a workbench-only storage key, a machine-local path or a tailnet value. With
`--private-host-file`, the private host that file names must be absent too
(compared, never printed). The stylesheet is shared with the workbench, so it
is checked for private values and paths only. Tests:
`python3 -I -B test_check_bundle.py`; a workbench build (no
`VITE_FLH_PUBLIC_DEMO`) is its negative control and fails.

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
