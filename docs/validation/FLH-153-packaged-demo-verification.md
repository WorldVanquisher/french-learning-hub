# FLH-153: verify the packaged public demo (2026-11-17)

**Release status: BLOCKED.** Every package built here uses mechanical vectors.
- **Run:** `20261117T042813Z`, branch `overnight/20261117T042813Z/demo-refresh`.
- **Baseline:** `198b23f14489c26cef6ea1c34f96714c843f00db`, as assigned (agents
  run no Git). The demo-candidate lane (`DEMO-CANDIDATE-LANE.md`) is in it.
- **Scope:** the public demo's focus on the way back, its browser gate, and
  this record. The private workbench, the server, the catalog and the
  migration ledger are unchanged.
- **Not run:** Git, AWS, deployment, E5 or any provider. Synthetic fixtures
  and disposable work directories only.
- **Browser:** Chromium 156 (playwright-core 1.49.1) in a disposable
  container, against packages served by their own `linux-amd64` binary on
  loopback. Phones use true emulation (`isMobile`, touch, DPR 2). No screen
  reader, Safari, Firefox or real phone was used.

## Confirmed fix (one)

**Focus was lost when the way back led to the start and its control was
gone.** The start screen (examples, search, results) has no heading of its
own. On a return to it, when neither the control that left it nor the result
or example the visitor came back from was on the page, focus stayed on the
page body:

| Case | Before | After |
|---|---|---|
| `#concept=9999`, then its in-page back | page body | "Start with an example" |
| `#q=il+faut&concept=12` (a search that does not list Concept 12), then its in-page back | page body | "Or search the library" |
| a Concept reloaded while the search fails, then its in-page back | page body | "Or search the library" (the error and its retry follow) |

- **Why the second step:** Back and Forward restore the entry's scroll
  position after the `popstate` handlers run. That is where the control that
  left it was, so the fallback heading was focused but off screen at 390 px.
  It is now brought into view again on the next frame (`focusFallback`).
- **Also:** a remembered control that is on the page but cannot take focus
  now falls back to the screen's heading (`focusControl` reports whether
  focus landed).
- **Code:** `web/src/demo/history.ts`, `web/src/pages/KnowledgeLibrary.tsx`
  and `web/src/demo/ExampleScreen.tsx`, all demo-gated. The two headings
  gained `tabIndex={-1}`, so they can be focused by script but are not tab
  stops (the tab order is unchanged; §10).
- **Tests:** 5 new cases in `web/src/demo/SharedLinks.test.tsx`; the 3
  fallback cases fail on the baseline sources (exact negative control). The
  browser matrix gained 2 checks per configuration (12 in all); the baseline
  package fails exactly those 12 with focus on `BODY`.

Everything else below is an observation, not a change.

## Checkpoints

| # | Item | Result |
|---|---|---|
| 1 | Baseline and package identity | DONE |
| 2 | Landing → original evidence, en + zh-CN | DONE |
| 3 | Valid shared link: direct open, reload, copied link | DONE |
| 4 | Malformed and missing IDs, recovery | DONE (re-verified; covered by the demo-candidate lane) |
| 5 | Back/Forward after switching search and opening a source | DONE |
| 6 | Focus returns to the previous trigger | DONE |
| 7 | Focus falls back when the trigger is gone | DONE: the fix above |
| 8 | 320 / 390 px page and element overflow | DONE |
| 9 | Long identifiers, mixed French and Chinese | DONE |
| 10 | Named controls, keyboard-only first example | DONE (no screen reader run) |
| 11 | Comparable phone and desktop evidence, labelled | DONE (screenshots outside Git) |
| 12 | Read-only boundary checks | DONE |
| 13 | Incorrect artifact identity fails the release check | DONE |
| 14 | A mechanical bundle cannot pass the public release gate | DONE |
| 15 | Build commands, dependencies, disk prerequisites | DONE |
| 16 | Reproducible mechanical candidate | DONE: content-reproducible, not byte-reproducible |
| 17 | Real-vector readiness from existing artifacts | DONE: real vectors for this catalog exist; approval unrecorded |
| 18 | Packaged browser checks, coverage and skips | DONE |
| 19 | Owner-run deployment, public verification, rollback | DONE (written; not run) |
| 20 | Candidate matrix | DONE (§20) |

## 1. Baseline and package identity

- **Baseline manifest:** 1088 files, captured before any edit (outside Git).
- **Baseline package:** `flh-public-demo-flh153-base-BLOCKED`, built offline
  from the baseline: artifact `77d0502093f78a56`, domain fingerprint
  `8c06d3098991…`, `mechanical-test` vectors, 64 dimensions, `real_model`
  false. `validate-release.sh` exit 3 (BLOCKED).
- **Final candidate:** `flh-public-demo-flh153-cand-a-BLOCKED`, revision label
  `198b23f14489+flh153`: same artifact version and fingerprint, manifest
  `3afaa051…`, tarball SHA-256
  `74d85b949aad1422b86624d838bc93588949e5bd9c23a889c4a713e0d1395048`.

## 2–6. Walk, shared links, history and focus

- **Walk** (320, 390 and 1280 px; en and zh-CN): landing → example →
  Concept (step 3) → evidence (step 4, the original learning record #9) in
  three moves. Focus is on each new screen's heading. The fixed build walks
  identically to the baseline.
- **Copied links** (a fresh browser context with no history or storage):
  - the evidence link opens the same screen, focused on its heading;
  - a reload keeps it;
  - its in-page back replaces the entry rather than adding one, and the next
    Back leaves the demo;
  - searches for `être`, `il faut que` and `虚拟式 subjonctif « que »`, and a
    hybrid preset link, restore the query, mode, preset and results.
- **Observation (not changed):** the interface language is a per-browser
  choice, not part of a link. A link copied from the 简体中文 interface opens
  in English in a fresh browser (FLH-083: English on first use).
- **Malformed and missing IDs:** a malformed link opens the start with a
  notice. `#concept=9999` and `#concept=12&unit=9999` say this build lacks
  the ID, offer no retry, and open a working example without a reload.
- **Back/Forward after switching search** (keyword `il faut` → hybrid preset
  `subjunctive` → a Concept → its source): every Back and Forward restores
  the screen, address, mode, query and preset.
- **Focus on return:** focus lands on the control used. That is the source
  button, the hybrid result, "Search" (`#library-search-submit`) and the
  search field. Forward to the source focuses its heading. 64/64 probe checks
  pass after the fix; the baseline passes 58/64, failing the 3 fallback cases
  × 2 sizes.

## 8–9. Phone layout, long and bilingual text

`demo_ux/accept_matrix.mjs` on the final candidate measured 300 screens: 100
each at 320 px, 390 px and 1280 px, in en and zh-CN.

| Width | Screens | Document wider than device | Element past the edge |
|---|---|---|---|
| 320 px | 100 | 0 | 0 |
| 390 px | 100 | 0 | 0 |
| 1280 px | 100 | 0 | 0 |

- **Long-text screens:** the example, Concept (details open) and evidence
  screens, with long identifiers, a long Concept title and scope, English +
  中文 + French explanations, a long French question and a nanosecond
  timestamp. Each configuration has them.
- **Clipped self-test:** the old layout under `overflow-x: hidden` passes
  the document check (390 px) but the element check still names the 409 px
  `dd`.

## 10. Names and keyboard

On 6 screens × 3 configurations, the probe checked every tab stop:
- each has a name and draws a focus ring;
- tab order equals DOM order and visual order;
- Chromium's accessibility tree has no unnamed interactive nodes.

Results before and after the fix are identical, so no tab stop was added.
- **First example from the keyboard:** it is the second Tab stop, after the
  language selector.
- **Observation:** at some sizes one card is only partly on screen when it
  is focused. Chromium scrolls focus only "if needed". This is unchanged from
  the baseline.

## 11. Evidence

Stamped screenshots, outside Git, in the lane handoff (`screenshots/before`
and `screenshots/after`). Each stamp reads "MECHANICAL BUILD · local package
… · not the live site · focus: …".
- **Sizes:** phone 390 (en and zh-CN), phone 320 (en), desktop 1280 (en and
  zh-CN).
- **Moments:** landing, example, Concept, evidence, and the two fixed
  returns.

## 12–14. Boundary, identity and release gate (final candidate)

- **`check_package.sh`** (identity, boundary, live, writes, browser, stop):
  exit 0.
  - **Boundary:** 24 smoke checks pass.
  - **Live:** it served `77d0502093f78a56` / `3afaa051…`, with `real_model`
    false.
  - **Writes:** all 14 well-formed writes were refused with 405.
  - **Files:** the package files were unchanged.
- **`negative_controls.sh`** on the final candidate:

  | Control | Result |
  |---|---|
  | wrong `--expect-version` | DETECTED: "identity mismatch" |
  | wrong `--expect-manifest` | DETECTED: "identity mismatch" |
  | the same binary without the demo boundary | DETECTED: 12 of 14 writes accepted, 2 probe entries in its throwaway database |
  | link (`democand-before`, a build without the malformed-link notice) | DETECTED: only the browser stage failed; the malformed-link check failed in all 6 configurations |

- **Tamper tests on copies** (lane tool; 10/10 as expected):

  | Fed to the gate | Result |
  |---|---|
  | `RELEASE.json` identity edited | `validate-release.sh` exit 1, checksums differ |
  | another build's `demo.db` (same artifact version) | exit 1, checksums differ |
  | `RELEASE.json` forged to CANDIDATE, checksums rewritten | exit 1, "says CANDIDATE but the artifact is mechanical" |
  | the mechanical candidate as built | exit 3, BLOCKED |
  | host installer `flh-release install` (fake `aws` and `systemctl`, temporary root): the BLOCKED tarball, the same package renamed without `-BLOCKED`, and the forged one | each refused (by name, `validate-release.sh` exit 3, exit 1); nothing switched, no restart |
  | another build's artifact with rewritten checksums, `RELEASE.json` unchanged | `validate-release.sh` exit 3: **not noticed** (it does not compare `RELEASE.json`'s identity with `artifact/manifest.json`); `check_package.sh`'s identity stage refuses it: "RELEASE.json manifest_sha256 … != artifact …" |

- **Observation (not changed; release tooling):** the last row. The tarball
  SHA-256 the operator supplies, and `check_package.sh`, are what catch a
  relabelled package. On the host, `flh-release` compares the live identity
  with `artifact/manifest.json`, not with `RELEASE.json`. A follow-up for the
  release tooling's owner: have `validate-release.sh` compare `RELEASE.json`'s
  artifact version and manifest SHA-256 with the artifact.

## 15. Build commands, dependencies, disk

```sh
cd web && npm ci --offline            # from the npm cache; no network (unshare -rn)
TMPDIR=<dir with room> GOPROXY=off GOFLAGS=-mod=readonly \
  go build -o <work>/flh-prepare ./scripts/demo/flh073/prepare
<work>/flh-prepare build -out <work>/artifact -fixtures scripts/demo/flh073/fixtures/catalog.json
bash scripts/demo/flh076/package.sh --artifact <work>/artifact --revision <label> --label <name> --out <work>/packages
```

- **Toolchain observed:** Go 1.27.3 (`go.mod`: 1.26.5), Node 26.13 /
  npm 12.2, Python 3.14, GNU tar 1.35, gzip 1.15, coreutils `sha256sum`,
  vite 5.4.21, esbuild 0.21.5.
- **npm install script:** `npm ci` blocks esbuild's postinstall
  (`allowScripts`); the build and tests work without it.
- **Browser checks:** Chromium or Chrome, plus a `node_modules` holding only
  `playwright-core` 1.49.1 (8.5 MB).
- **Disk:**

  | Item | Size |
  |---|---|
  | `web/node_modules` | 102 MB |
  | Go module cache | 528 MB |
  | Go build cache | 1.7 GB |
  | Artifact | 0.7 MB |
  | Package (directory) | 76 MB |
  | Package (tarball) | 42 MB |
  | Browser container (Chromium and CJK fonts) | 835 MB |

- **`/tmp`:** it is a tmpfs with a per-user quota. On this host
  `scripts/release/disk_preflight.sh` reported it BLOCKED: "Disk quota
  exceeded" at a 32 MiB probe, while `df` showed free space. Set `TMPDIR`
  to a directory on a disk with room. The preflight passes for the work
  directory, `TMPDIR` and the Go build cache.
- **Offline:** every build ran in a namespace with no network (`unshare -rn`,
  `GOPROXY=off`).

## 16. Reproducibility

Two builds of the final tree were made, each from a fresh `prepare build`
artifact.

**Identical:**
- every file in the package except `RELEASE.json`, `artifact/demo.db` and
  `artifact/manifest.json`;
- that includes both architectures' binaries, the web build, the vectors and
  the fixtures;
- the artifact version and the domain fingerprint;
- an earlier build of the same tree was also identical apart from those
  three files.

**Different, and why:**
- **`demo.db`:** only build-time columns differ: `created_at`, `updated_at`
  and `applied_at`, in 9 of 54 tables.
- **`manifest.json`:** it hashes `demo.db`, so it differs too.
- **`RELEASE.json`:** the label and `built_utc` differ.
- **Tarball:** therefore it differs as well.

**Verdict:** content-reproducible, not byte-reproducible. The identity a
release is checked by (artifact version and domain fingerprint) is stable;
the manifest SHA-256 is per build. Not changed here: pinning seed timestamps
would change `prepare`, outside this lane.

## 17. Real-vector readiness (existing artifacts only; E5 not contacted)

| Package (existing) | Status | Catalog | Usable for this tree? |
|---|---|---|---|
| `flh-public-demo-flh087-rc1` (deployed, FLH-087) | CANDIDATE; `validate-release.sh` exit 0 on a copy | fixtures `0e3d1912…`, fingerprint `c92c71c4…`, 20 positions | No: an older catalog |
| owner-built 2026-11-12 package from `521279a` | CANDIDATE; `validate-release.sh` exit 0 on a copy | fixtures `d7b97b56…`, fingerprint `8c06d309…`, 23 positions, plan `536021a4…` | Yes, the same catalog. This tree's `flh-prepare validate -release` accepts its artifact (exit 0), and `migrations/` is identical |

- **What is missing:** the 2026-11-12 artifact (version `97dbe0f215af37e7`)
  matches the documented "Real-E5 candidate (owner only)" plan, but no record
  in the repository says it was approved.
- **Not done by this lane:** no CANDIDATE was built. Approving the artifact
  and packaging the integrated tree with it is the owner's decision (§19).

## 18. Packaged browser coverage and skips (final candidate)

| Suite | Result |
|---|---|
| `demo_ux/accept_matrix.mjs` | 1213/1213 (300 screens) |
| `demo_refresh/accept_paths.mjs` | 112/112 |
| `demo_first_visit/accept_guided.mjs` | 208/208 |
| `demo_first_visit/accept_resilience.mjs` | 41/41 |
| `demo_first_visit/accept_a11y.mjs` | 107/107 |
| `flh076/browser/accept.mjs` | 37/37 (expects mechanical vectors) |

- **Covered:** Chromium 156 only, at 320, 390 and 1280 px, in en and zh-CN.
- **Skipped:**
  - real-vector relevance, because no CANDIDATE was built;
  - Safari, Firefox and WebKit, real phones and screen readers;
  - zoom and text-spacing overrides;
  - CI (`public-demo.yml` runs FLH-079, not these suites);
  - the live site.

## 19. Owner-run steps (not run by any agent)

1. **Real vectors.** Either:
   - re-run "Real-E5 candidate (owner only)" in `docs/PUBLIC_DEMO.md`, steps
     1–9, on the integrated commit; or
   - approve the existing 2026-11-12 artifact (version `97dbe0f215af37e7`,
     plan `536021a4…`) and run only steps 5–9 with it as `$R/artifact-e5`.
     This is valid because this tree's catalog and migration ledger equal the
     ones it was built from (§17).

   Either way, step 8 must print `PACKAGE CHECK PASSED (CANDIDATE package)`.
   Record the version and manifest from step 7.
2. **Deploy:** follow `docs/AWS_DEMO.md` §5 (upload) and §6 (`flh-release
   install <s3 uri> <sha256 from the .sha256 file>`). `install` refuses a
   BLOCKED or invalid package (§13 tested this with fakes). After the switch
   it must report the release's own version and manifest with
   `real_model: true`.
3. **Private verification** (`AWS_DEMO.md` §7, through the SSM port forward):
   - `/readyz`;
   - `/knowledge-library/demo` against the step 7 identity;
   - the interactive acceptance: search, Concept, source and the language;
   - and for FLH-153: open `#concept=9999`, press its "← Back" with the
     keyboard, and confirm "Start with an example" is focused and visible.
4. **Public verification** (only if `AWS_DEMO.md` §11 public HTTPS is
   enabled):
   - `curl -fsS https://<public host>/api/knowledge-library/demo` returns the
     step 7 version and manifest with `real_model: true`;
   - `https://<public host>/` loads and the walk of §2 completes;
   - a write such as `curl -X POST https://<public host>/api/captures` is
     refused with 405.

   Record the results in a validation note. Until then, "publicly verified"
   stays NO.
5. **Rollback:** `sudo /usr/local/sbin/flh-release rollback`. That switches
   back to the previous release (the deployed `flh087-rc1` as of FLH-087)
   and re-verifies its identity. Then confirm `flh-release status` and
   `/knowledge-library/demo` report `d025f217f4d76396`.

## 20. Candidate matrix

| Candidate | Built | UX checked | Real vectors present | Deployed | Publicly verified |
|---|---|---|---|---|---|
| `flh153-cand-a` (this tree, mechanical) | YES (offline, content-reproducible) | YES (Chromium, local; §2–§11, §18) | NO (mechanical; BLOCKED) | NO | NO |
| this tree + the 2026-11-12 real-E5 artifact | NOT BUILT (owner decision) | NOT RUN | YES on disk, validated; approval UNRECORDED | NO | NO |
| `flh087-rc1` (deployed per FLH-087) | YES | older demo; not checked by this lane | YES (older catalog) | YES, per FLH-087 (not verified by this lane) | UNVERIFIED by this lane |

**Single next owner action:** step 1 of §19.

## Validation commands (run here)

| Command | Result |
|---|---|
| `TMPDIR=<home volume> NODE_OPTIONS=--no-experimental-webstorage make verify` | exit 0: 24 Go packages ok, vet, builds, vitest 44 files / 496 tests, web build |
| `npx vitest run src/demo src/i18n` (web/) | 8 files, 83/83 |
| `SharedLinks.test.tsx` on the baseline sources | 3 of 20 fail: exactly the 3 new fallback cases |
| `scripts/validation/demo_ux/accept_matrix.mjs` on the baseline package | 1201/1213: exactly the 12 new checks fail (focus on `BODY`) |
| `scripts/validation/demo_candidate/check_package.sh <cand-a> <work> --expect-version 77d0502093f78a56 --expect-manifest 3afaa051… --expect-status BLOCKED --suites all` | exit 0, every stage PASS (§12, §18) |
| `scripts/validation/demo_candidate/negative_controls.sh <cand-a> <work> --control-package <democand-before>` | exit 0, 4 of 4 DETECTED |
| `scripts/release/disk_preflight.sh work=…:2048 tmpdir=…:1024 gocache=…:1024` | exit 0 (with `/tmp` added: exit 3, quota) |
