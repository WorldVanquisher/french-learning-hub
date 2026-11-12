# Public demo UX lane: overflow, walkthrough, navigation, matrix (2026-11-12)

**Release status: BLOCKED. Every package in this lane uses mechanical vectors.**
- The UI work is ready for integration.
- **Baseline:** main `c53b42c`, with the public-demo first-visit patches P1–P5
  already in it.
- **Scope:** public-demo components, demo-scoped styling and demo browser
  checks.
- **Unchanged:** private workbench navigation, provider behaviour, backend
  code, catalog and artifact.
- **Not run:** Git, AWS, deployment, model or provider calls.
- **Data:** synthetic fixtures only.

## Checkpoint 1: the 421 px source-detail overflow

**Result: current main already fixes it. The regression check it relied on
was blind; it is now fixed and fails for the old layout.**

How it was tested:
- **Browser:** Chromium 156 with true phone emulation (`isMobile`, touch,
  DPR 2).
- **Builds:** the packaged baseline, and the same package with only the two
  P2 evidence-row rules removed (the "old layout").
- **Screens:** every source, Concept and example screen, at 390 and 320 px,
  in English and 简体中文.

| Build | Screens over the device width | Widest | Element | Old `innerWidth` check |
|---|---|---|---|---|
| main (baseline) | 0 / 144 | 390 / 320 | — | — |
| old layout | 68 / 144 (all 16 sources × 4) | 421 (390 px) / 422 (320 px) | `dd` “fixture:flh073:fr_l2_taxonomy_v1”, plus the nanosecond timestamp at 320 px | passes 68 / 68 |

Why the old check was blind:
- Under phone emulation `innerWidth` grows with the content, while
  `clientWidth` stays 390.
- So `scrollWidth <= innerWidth` could not fail.

Fixed checks:
- **`demo_refresh/accept_paths.mjs`** now compares with the device width and
  names the element.
  - Old layout: 104/112, six evidence failures at 421 px naming the `dd`.
  - Baseline main: 110/112. It found a second, previously hidden overflow:
    the semantic preset `<select>` made the page **594 px** wide on a 390 px
    phone, in both languages. Checkpoint 4 fixes it.
- **`web/src/demo/demoStyles.test.ts`** (CI) fails when either evidence-row
  rule is removed. It proves this against the old layout inside the test.
- **`demo_ux/accept_matrix.mjs`** injects the old layout into a running page
  and requires the check to catch it (below).

## Checkpoint 2: first-visit walkthrough

- **Example screen:** shows four numbered steps. Step 4, "The source
  evidence", names the learning record, the extraction and the
  interpretation, and opens the evidence.
- **Step labels:** a Concept or evidence screen opened from an example says
  "Step 3 of 4 · Concept" (with what to do next) or "Step 4 of 4 · Source
  evidence".
- **Empty state:** a search that finds nothing explains keyword matching and
  offers the examples' own queries plus "Show all Concepts". An empty catalog
  is described as the demo build's.
- **Loading, unavailable and failed states:** these already existed. They
  are now tested in both languages.
- **Evidence screen:** the recorded time shows as a localized UTC date.
- **Accessible names:** two units from one record get distinct names for
  their source buttons.
- **Tests:** `web/src/demo/Walkthrough.test.tsx` covers the walkthrough and
  the loading, empty, no-match, unavailable and failed states, 14 tests in
  English and 简体中文.

## Checkpoint 3: navigation contract

This is defined in `web/src/demo/history.ts` and documented in
`docs/PUBLIC_DEMO.md`.

| Action | Before (measured, baseline package) | After |
|---|---|---|
| In-page "← Back to concept", then browser Back | added an entry; Back returned to the evidence just left | no entry added; Back goes to the example; Forward keeps the evidence |
| Reload on search results | query lost (1 → 14 results) | `#q=…` keeps the search |
| Reload on a Concept opened from a search | back label became "all concepts" | `#q=…&concept=N` keeps "results for …" |
| Browser Back after a search | searches were not entries, so Back skipped them (from the start it left the demo) | returns to the previous results, form restored |
| Direct link, then in-page back | added entries | replaces the entry: no loop |
| Focus | heading / opened result / example card | unchanged rules, now tested on every path |

Links use stable fixture identifiers: example keys, preset ids and Concept/unit
IDs. Two independent builds of the artifact gave identical IDs for all 14
Concepts, 16 units and 11 entries, under the same domain fingerprint.

Tests: `web/src/demo/Navigation.test.tsx` (13 tests). They include the
workbench library leaving the address and history untouched.

## Checkpoint 4: packaged Chromium matrix

**Package:** a mechanical, BLOCKED build of this tree, using its own
`linux-amd64` binary. **Browser:** Chromium 156 in a disposable container.

| Suite | Result |
|---|---|
| `demo_ux/accept_matrix.mjs` (320 / 390 / 1280 px × en / zh-CN) | **797 / 797**; 282 screens measured, none wider than the device |
| …self-test: the old layout injected at 320 and 390 px, en and zh | caught 4 / 4 (409 px; the old `innerWidth` check would pass) |
| `demo_refresh/accept_paths.mjs` (device-width check) | 112 / 112 |
| `demo_first_visit/accept_guided.mjs` · `accept_resilience.mjs` · `accept_a11y.mjs` | 208 / 208 · 41 / 41 · 89 / 89 (keyboard round trip 20 presses, was 21) |
| FLH-076 `browser/accept.mjs` | 37 / 37 |
| FLH-073 `smoke.sh` | PASSED |
| Private-route probe, packaged binary (root and `/api`) | 58 probes, 0 failures; artifact private tables empty |
| `make verify` | exit 0: 24 Go packages, vet, builds, vitest 42 files / 469 tests, web build |

Further notes:
- **First example on a phone:** the first card now starts at 477 px (was 602)
  on a 390 px phone and at 545 px (was 694) on a 320 px phone, in English.
  The narrow-screen spacing in `demo.css` does this.
- **Keyboard:** the walk start → evidence → start takes 17 key presses at
  every size, with visible focus at each stop.
- **Temporary directory:** `make verify` needs `TMPDIR` on a volume with
  space. On this host the shared `/tmp` quota made SQLite and the linker fail
  until `TMPDIR` was moved.

## Checkpoint 5: walkthrough, recording script, release status

The before/after screenshots and their numbers are kept with the lane handoff,
not in Git.

### 90-second recording script

On a mechanical (BLOCKED) build, say the Development-build line and skip
semantic results, or show them only to read their notice.

| Time | Do | Say |
|---|---|---|
| 0:00–0:10 | Open the demo; point at *Read-only · Synthetic data*. | "A read-only demo of my French-learning knowledge service. Everything is synthetic; nothing is saved; no AI is called." |
| 0:10–0:25 | Click **One question, two pronouns**. | "Start from a learner's question, kept exactly as written in French." |
| 0:25–0:45 | Scroll steps 1 → 4 on the example. | "Two short rules were taken from it, filed under one Concept, and step 4 names the record, extraction and interpretation they came from." |
| 0:45–1:00 | **Open the Concept and its evidence**; point at *Step 3 of 4*. | "A Concept is the durable idea a learner studies; every unit says which question it came from." |
| 1:00–1:10 | **View source record #9**; point at *Step 4 of 4* and the question. | "One click back to the original question, with the full provenance." |
| 1:10–1:20 | Press **← Back to concept**, then the browser's **Back**. | "In-page back and the browser's Back are the same move, so Back keeps going backwards and never loops." |
| 1:20–1:30 | Search `subjonctiff`, then click **Search “viennes”**. | "A search that finds nothing explains itself and offers searches that work. Copy the address and the search comes with it." |

### Release status (three separate states)

| State | Status | Evidence |
|---|---|---|
| Mechanical vectors | **BLOCKED** (not releasable) | `validate-release.sh` exit 3 on this lane's package; `RELEASE.json` `BLOCKED`, `real_model: false`, artifact `77d0502093f78a56` |
| Real vectors | **Not built in this lane**; no real-vector artifact for domain fingerprint `8c06d3098991cb00…` was found | this lane changes no catalog or artifact; the fingerprint is identical before and after |
| Deployment | **Not performed; frozen** | public deployment is frozen by the owner; agents run no AWS or Terraform |

**Remaining owner step (unchanged by this lane):**
1. Build the real-E5 CANDIDATE from the integrated tree. Run the
   `prepare embed` / `import` / `validate -release` / `package.sh
   --expected-deployment` sequence from the D1 release gate, against the
   owner's E5 service.
2. Run §C acceptance in `model` mode, adding `demo_ux/accept_matrix.mjs …
   model`.

Deployment stays a separate, owner-only decision.
