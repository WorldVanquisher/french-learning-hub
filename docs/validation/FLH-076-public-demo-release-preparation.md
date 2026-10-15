# FLH-076 validation: public demo release preparation

Date: 2026-10-15 (UTC). Working directory:
`/Users/lowx/projects/FLH/french-learning-hub` (macOS arm64; Go 1.26.5; Node
24.16.0; Google Chrome 155.0.8059.41). Contract:
[plan](../plans/FLH-076-public-demo-release-preparation.md); operator guide:
[PUBLIC_DEMO.md](../PUBLIC_DEMO.md).

**Not used:** Git/GitHub, subagents, Docker, AWS/Titan, model downloads,
Windows changes, service installation, publication or DNS.

**Current outcome (FLH-078, 2026-10-15): CANDIDATE prepared; not deployed.**
- The encoder was restarted with the pinned `singleton_v1` deployment, then the
  same work directory was resumed: 20 positions in 3 POSTs. Accounting is
  20/64 positions, 3/16 POSTs and 2/2 probes; all receipts are complete.
- The artifact is `~/flh076/artifact-e5`: version `d025f217f4d76396`,
  manifest `dfe6e94d…`, `validate -release` exit 0.
- It is packaged as `flh-public-demo-flh078-rc1` (tarball `78fb5495…`) and
  accepted on Linux and in a real browser. Evidence:
  [FLH-078](FLH-078-demo-release-candidate.md).

The two banners below are kept as history.

**Earlier outcome (2026-10-15): still BLOCKED, now on deployment identity.**
E5 is reachable and ready, but it serves `…/float16/dd0889c6f1869f7f` (default
dynamic batching), not the pinned `…/float16/singleton_v1/5a3e23f28a05baff`.
Nothing was sent, so no real artifact, package or real-artifact browser run
exists yet ([continuation](#continuation-real-artifact-attempts-2026-10-15)).
The original outcome below is kept as history.

**Earlier outcome: release candidate BLOCKED (no real-model vectors).** The other
work packages are delivered: the pipeline, browser acceptance, a BLOCKED
package, and the deployment handoff.

| Work package | Status |
| --- | --- |
| 1. Real-vector artifact pipeline | **PASS** (deterministic fake-service tests; no real model) |
| 2. Bounded real E5 preparation | **BLOCKED**: E5 offline. 1 of 2 probes used; 0 positions and 0 POSTs sent |
| 3. Actual browser acceptance | **PASS**, real Chrome. Mechanical artifact: 37/37. Fake-service model-path artifact: 37/37 (UI mechanics only) |
| 4. Portable release package | **PASS as a BLOCKED package**. `CANDIDATE` packaging is NOT RUN: no real artifact |
| 5. Deployment handoff | **PASS** (templates and documentation). Installation, publication and DNS: NOT RUN (not authorized) |

## Work package 2: E5 availability (BLOCKED)

- **`tailscale status`:** `worldvanquisher 100.118.109.6 windows offline,
  last seen 6h ago`.
- **Probe 1 of max 2:** `curl --max-time 5 http://100.118.109.6:8765/readyz`
  at 2026-10-15T00:20:50Z gave `http=000 time=5.001967s` (timeout).
- **Probe 2:** not used. The host was offline at the coordination level, so a
  second probe could not succeed.
- **Sent:** 0 embedding positions and 0 POSTs. No retry or waiting.
- **Continuation:** a single command, in
  [PUBLIC_DEMO.md](../PUBLIC_DEMO.md#real-model-vectors-flh-076)
  (embed → import → package). It is bounded to 20 positions in 3 POSTs, within
  the task's 64/16 caps.

## Work package 1: real-vector pipeline (PASS, fake service)

**Production-text plan** (`prepare plan`):
- 20 positions: 12 `document/concept_embedding_text_v1/passage` and 8
  `preset/concept_search_query_v2/query`;
- plan SHA-256 `083a35ef…6adb2f`;
- 3 POSTs at batch 8.

**Tests** (`internal/publicdemo/realvectors_test.go`, 7 tests). Each uses an
in-process fake E5 that enforces the service's model id, the 1–32 input bound
and the representation/type role contract:
- **Exact texts:** documents are `concept_embedding_text_v1`/`concept`
  (passage), presets are the exact `ConceptSearchQueryEmbeddingText` envelope
  (query), and the plan is reproducible.
- **Full pipeline:**
  - embed sends 3 POSTs, 20 positions and 1 probe;
  - a repeat sends nothing and does not probe;
  - import produces a `model` artifact with `real_model: true`,
    `model_vectors`, 4 files and `provenance.json`;
  - its domain fingerprint equals the mechanical artifact's (same domain);
  - serving the artifact makes 0 further service calls, and the preset-only
    provider refuses free text;
  - no `.partial-` directory is left behind.
- **Failure and resume:**
  - POST 2 fails (HTTP 500), so the run stops with 8 receipts;
  - the resume sends exactly the 12 missing positions in 2 POSTs, and each
    first-batch text was received exactly **once**;
  - final accounting: 4 POSTs (1 failed), 28 positions, 2 probes;
  - the failed POST is recorded with its error.
- **Budget and probes:**
  - a 2-POST or 19-position limit gives `ErrBudget` with **zero** requests,
    not even a probe;
  - limits above 64/16/8, a base URL without `/v1`, and a missing deployment
    are refused;
  - a `503` readiness answer, or a manifest reporting another deployment,
    charges the probe and sends no POST;
  - a third probe is refused with no request;
  - changing the dimensions of a started work directory is refused.
- **Invalid vectors:** wrong dimensions mark the POST failed and write no
  receipt, so import is refused.
- **Import refusals** (8 cases; no output directory is ever published):
  - a missing receipt;
  - a vector changed with its hash kept;
  - a receipt for another text, or from another deployment;
  - an extra receipt;
  - a POST marked failed;
  - a plan from other fixtures;
  - a corrupt state file.

  An existing (even empty) output directory is also refused.
- **Provenance binding** (8 cases, each giving `ErrArtifact`):
  - provenance missing;
  - a vector hash mismatch, a swapped role, a dropped position;
  - another deployment;
  - no successful probe;
  - a budget over 16 POSTs;
  - a vector changed with `vectors.json` re-hashed.
- **No relabelling:** a mechanical artifact relabelled `model`, even with
  copied provenance, is refused.

**CLI** (`scripts/demo/flh073/prepare/main_test.go`):
- **Refusals:** `embed` without `-allow-live` exits 2 with 0 POSTs; with
  `-max-posts 2` it exits 3 with 0 POSTs.
- **Success:** a full run sends 3 POSTs. `status` shows 0 pending. `import`
  reports `real_model: true`, and `validate -release` exits 0 (fake
  deployment, test only).
- **Other paths:** a repeated import into an existing directory exits 1. A
  mechanical `validate -release` exits **3** (`RELEASE BLOCKED`).

**Fingerprint v3** (a defect found and fixed in this task):
- **Symptom:** the FLH-075 v2 fingerprint gave equal `created_at` instants
  equal ranks. Two builds of the same fixtures produced different
  fingerprints and artifact versions, because recommendations 2 and 3 had
  been written in the same microsecond in one build.
- **Fix:** v3 records each row's position in the order the reads use. Within a
  table that is `(created_at, id)`. SAME links and DISTINCT decisions share a
  merged order, with ties placing the distinction first: effective annotation
  lets a SAME at an equal instant win.
- **Evidence:** 15 consecutive builds produced the identical artifact version
  `e4ee51c6dffcabe3`, fingerprint `c92c71c4…` and `vectors.json` hash. A new
  test shows the following leave the fingerprint unchanged: tied
  recommendations, and recommendations one tick apart in id order. Reversing
  their order changes it.
- **Compatibility:** v1 and v2 artifacts are refused with rebuild guidance.
  The FLH-075 tests still pass.

## Work package 3: real-browser acceptance (PASS)

- **Tooling:** `scripts/demo/flh076/browser/run.sh` installs
  `playwright-core@1.49.1` (8.3 MB, no browser download) into the run
  directory. It drives the installed Chrome 155, headless, with a fresh
  temporary profile, against a loopback demo server, then stops the server.
- **First run (mechanical): 27 PASS / 8 FAIL.** Triage:
  - **5 bugs in my test:** reads during loading states, an over-strict keyword
    assertion, and a hybrid regex.
  - **3 real browser defects, fixed with minimal UI changes:**
    1. Every page load logged a console error: the browser's automatic
       `/favicon.ico` request was correctly refused (404) by the allowlist.
       `web/index.html` now declares `<link rel="icon" href="data:,">`. The
       normal workbench had the same 404.
    2. In demo mode, the semantic hint claimed it "needs that index and an
       embedding service". The demo now has its own description.
    3. The demo note referred to "the example queries above" in keyword mode,
       where no list is shown. Reworded.
- **Final runs:**

  | Artifact | Result | Requests | Console |
  | --- | --- | --- | --- |
  | Mechanical (`/tmp/flh076-browser-mech2/browser/`) | **37 PASS / 0 FAIL** | 14 | only the two deliberate HTTP errors |
  | Fake-service model-path (`/tmp/flh076-browser-fakemodel/browser/`) | **37 PASS / 0 FAIL** | 14 | only the two deliberate HTTP errors |

  The fake-service artifact checks the model-mode UI only (no mechanical
  banner, the model identity line). It is not release evidence, and the
  packager refuses it.
- **What the checks cover:**
  - title, `lang="en"`, the synthetic, read-only and no-AI notices, and the
    free-text restriction;
  - the mechanical banner, shown or absent as expected;
  - the artifact identity line;
  - no workbench tabs and no editing, import or review controls;
  - keyword free text, with identity and unit-wording evidence;
  - the empty keyword result;
  - a real server 400 shown as an explicit error with retry;
  - the semantic preset selector (8 exact texts) and the restriction note;
  - semantic results with similarity evidence;
  - hybrid with the status filter: the policy line and per-result evidence;
  - Concept detail, then the source with the original question and
    interpretation, then back to the Concept, then back to the results with
    focus restored;
  - a client-injected hybrid 503 shown explicitly, with no keyword
    substitute.
- **Network:** every request is same-origin, GET, on the allowlist, with no
  free-text semantic or hybrid request. The preset requests carried
  `preset=no-longer` and `preset=subjunctive&state=active`.
- **Evidence:** `results.json` holds every console message and request, and
  there are 8 screenshots per run.

## Work packages 4–5: package and handoff

- **BLOCKED package:**
  `/tmp/flh076-release/packages/flh-public-demo-rc1-BLOCKED/` (63 MB), with
  tarball SHA-256 `6dbf8cd757337ff6…0b37e4`.
- **Its contents:**
  - `RELEASE.json`: `release_status: BLOCKED`, artifact `e4ee51c6dffcabe3`,
    `mechanical-test`, `real_model: false`, fingerprint v3, and source
    revision **`unlabelled-human-must-supply`**. No label was supplied, so
    the human must provide one for a release.
  - Static ELF binaries for linux/amd64 and linux/arm64 (`flh-server`,
    `flh-prepare`), 17 checksummed files.
  - No symlinks, no AppleDouble files in the tarball, and exactly one
    database (`artifact/demo.db`).
- **`smoke_package.sh`** (host builds; this Mac cannot run the Linux
  binaries): **24 PASS, `PACKAGE SMOKE PASSED`**.
  - `validate-release.sh` exits **3** (BLOCKED);
  - `ctl.sh` start, status and stop work;
  - allowed paths return 200; `/favicon.ico`, free-text semantic,
    write-surface, `artifact/demo.db`, `RELEASE.json` and `/assets/` return
    404; writes return 405; `q=` on a preset route returns 400;
  - the counters are unchanged by denied requests, and two preset searches
    use two lookups;
  - the package files are unchanged by the run, and the server stopped.
- **Tampering** (copies of the package, each giving `validate-release.sh`
  exit 1): an edited web file, an added symlink, an extra file, and
  `RELEASE.json` relabelled `CANDIDATE`.
- **Fake-model artifact:** refused by `package.sh` ("not a pinned E5
  deployment").
- **Packaging bugs found and fixed during the run:** `SHA256SUMS` listed
  itself (the redirect created it before `find` ran), and a locale-dependent
  `sort` broke the top-level layout check.
- **Deployment templates** (examples, not installed):
  - **systemd:** a dedicated user, `ProtectSystem=strict`, read-only paths, no
    capabilities, memory and task limits, a loopback listener, every provider
    disabled, and `HTTP_ALLOWED_HOSTS`;
  - **nginx:** TLS, GET/HEAD only (405), 1 KB body cap, timeouts, per-client
    request and connection limits, `Host` passed through, client forwarding
    headers cleared, and request bodies not forwarded;
  - **`ctl.sh`:** stops only the pid it recorded, after checking its command
    line.
  - nginx and systemd syntax were **not** checked on a target host; neither
    is installed on this Mac.

## Regressions and checks

| Command | Result |
| --- | --- |
| FLH-074 `accept.py` (fresh binaries, v3 artifact, demo build) | **exit 0, 868 PASS / 0 FAIL**, 775 requests |
| FLH-074 `followup.py` | **exit 0, 7 PASS / 0 FAIL** |
| `TMPDIR=/private/tmp/flh076-gotmp make verify` | **exit 0**: gofmt; `go test ./...` all 16 packages ok (including `scripts/demo/flh073/prepare`); `go vet`; server and capture builds; frontend 18 files / **219 tests**; normal production build |
| `VITE_FLH_PUBLIC_DEMO=1 vite build` | built (in the browser runs and the package) |
| `scripts/demo/flh073/smoke.sh` | **exit 0, 93 PASS** |
| `go test ./internal/publicdemo/ -count=1 -v` | 18 top-level tests, 43 subtests, PASS |

**`TMPDIR`:** this is the documented macOS workaround (FLH-071) for the
pre-existing `scripts/validation/flh053` symlinked-temp refusal.

## NOT RUN / limits

- **Real-model artifact, CANDIDATE package and release validation exit 0:**
  BLOCKED (E5 offline).
- **The packaged Linux binaries were not executed:** no Linux host or Docker
  here. The package smoke used host builds of the same source.
- **nginx/systemd validation on a target host:** not run.
- **Installation, ports, publication and DNS:** not performed and not
  authorized.
- **Provenance is local evidence,** not cryptographic proof of the producing
  model.
- **Not claimed:** relevance and complete security assurance. Mechanical
  rankings show mechanics only.

## Evidence (outside the repository)

- **Browser runs:** `/tmp/flh076-browser-mech2/` (also the failed first run,
  `/tmp/flh076-browser-mech/`) and `/tmp/flh076-browser-fakemodel/`.
- **Fake-model work:** `/tmp/flh076-fakemodel/`, and the fake service in
  `/tmp/flh076-fake-e5/`.
- **Release:** `/tmp/flh076-release/`: the mechanical artifact, the package,
  the tarball and the smoke run.
- **FLH-074 rerun:** `/tmp/flh076-flh074/`.
- **Logs and probe:** `/tmp/flh076-verify.log`,
  `/tmp/flh076-flh073-smoke.out`, and the probe output
  `/tmp/flh076-probe1.json` (empty: the probe timed out).

## Continuation: real-artifact attempts (2026-10-15)

**Prior state, inspected before sending:**
- no work directory existed (`~/flh076` absent), so 0/64 positions and 0/16
  POSTs had been used;
- the fresh plan is **20 positions** (12 `document/concept_embedding_text_v1/passage`,
  8 `preset/concept_search_query_v2/query`) in **3 POSTs**, plan SHA-256
  `083a35ef51a9580e…`, as expected.

**Attempt 1 at 02:58:22Z** (Mac; one invocation, no retry):

```sh
prepare embed -work ~/flh076/e5-work -base-url http://100.118.109.6:8765/v1 \
  -deployment 'multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/flh_e5_role_prefix_v1/float16/singleton_v1/5a3e23f28a05baff' \
  -dimensions 768 -allow-live
```

- **Built-in probe:** `/readyz` 200, but `/manifest` reported a **different
  deployment**, so the result was `deployment_mismatch`, exit 1, nothing sent.
- **Accounting** (`~/flh076/e5-work/state.json`): **1/2 probes, 0/16 POSTs,
  0/64 positions**, 0 receipts.
- **Hashes:** `plan.json` `239b159a…`, `state.json` `2b12c7b3…`.

**Attempt 2 at 03:15:08Z** (after PR #104): a single plain `GET /manifest`
and `GET /readyz`, so as not to spend the work directory's last probe on a
known mismatch. Both returned 200, still with deployment
`…/float16/dd0889c6f1869f7f`, so `embed` was **not** run. A final identical check at
03:17:22Z, just before handoff, returned the same identity.

| | Deployment id |
| --- | --- |
| Pinned (FLH-060, singleton batching) | `multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/flh_e5_role_prefix_v1/float16/singleton_v1/5a3e23f28a05baff` |
| Served | `multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/flh_e5_role_prefix_v1/float16/dd0889c6f1869f7f` (`manifest_sha256` `dd0889c6f1869f7fe3bc…`) |

The served identity has no `singleton_v1` segment. That is the shape of the
default `dynamic_v1` batching (FLH-059): a different vector identity.

**Therefore NOT RUN:**
- import and real-artifact release validation;
- packaging with source label `86b06f461e64203192ebc3a54e4d1f749681aceb`;
- browser checks against a real artifact.

No AWS or paid fallback; no Windows changes.

**To unblock, choose one (human decision):**
1. **Serve the pinned deployment.** Start the encoder with `singleton_v1`
   batching (FLH-065 `flh-e5.ps1 start` uses `singleton_v1` with the pinned
   identity). Then rerun the **same** `embed` command: the work directory
   keeps its accounting (1 probe left, 64/16 untouched).
2. **Adopt the served `…/float16/dd0889c6f1869f7f` identity** (an explicit
   decision: a new vector identity). Use it as `-deployment` and
   `--expected-deployment` in a **new** work directory. The started one is
   bound to the pinned id.

**Then:**

```sh
prepare import -work ~/flh076/e5-work -out ~/flh076/artifact-e5
prepare validate -artifact ~/flh076/artifact-e5 -release            # expect 0
bash scripts/demo/flh076/package.sh --artifact ~/flh076/artifact-e5 --revision 86b06f461e64203192ebc3a54e4d1f749681aceb \
  --label rc2 --out ~/flh076/packages --expected-deployment '<deployment id>'
bash scripts/demo/flh076/browser/run.sh /abs/new/browser-dir ~/flh076/artifact-e5
```

Package on a host that has `shasum` (such as this Mac) until FLH-077 D2 is
fixed.

