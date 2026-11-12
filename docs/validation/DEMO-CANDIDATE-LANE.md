# Public demo candidate lane: shared links, the way back, package check (2026-11-12)

**Release status: BLOCKED.** Every package built here uses mechanical vectors.
- **Baseline:** main `521279a` (the demo-ux lane, PR #146, is in it).
- **Scope:** public-demo components, demo-scoped CSS and i18n, and demo
  validation. The private workbench's navigation, the server, the catalog and
  the migration ledger are unchanged.
- **Not run:** Git, AWS, deployment, E5 or any provider. Synthetic fixtures
  only.
- **Browser:** Chromium 156 in a disposable container, against packages
  served by their own `linux-amd64` binary on loopback. Phones use true
  emulation (`isMobile`, touch, DPR 2).

| # | Checkpoint | Result |
|---|---|---|
| 1 | First-time walk, both languages | DONE |
| 2 | Shared links | DONE: malformed links now say so |
| 3 | History and focus | DONE: coming back focuses the control used |
| 4 | Phone layout regression | DONE: document and elements measured separately |
| 5 | Invalid-link screen | DONE: "not in this demo", with a working example |
| 6 | Keyboard only | DONE (no screen reader run) |
| 7 | Mechanical candidate, offline | DONE: packaged, BLOCKED |
| 8 | Package entry point | DONE: `scripts/validation/demo_candidate/check_package.sh` |
| 9 | Negative controls | DONE: 4 of 4 detected |
| 10 | Real-E5 owner procedure | DONE (prepared, not run) |
| 11 | Phone evidence, recording script | DONE (screenshots outside Git) |
| 12 | Matrix, smoke, status table | DONE |

## 1. First-time walk (baseline package)

The path a first-time visitor takes, at 390 px, in English and 简体中文. Scroll
is how far the next control was below the screen.

| Move | Scroll (en / zh) | Address after | Focus after | Label shown |
|---|---|---|---|---|
| Land | first card at 477 / 380 px | `/` | page | — |
| Click "One question, two pronouns" | 0 / 0 | `#example=y-en` | example heading | Guided example |
| "Open the Concept and its evidence" (step 3) | 499 / 426 | `#example=y-en&concept=12` | Concept heading | Step 3 of 4 · Concept |
| "View source record #9" | 0 / 0 | `…&concept=12&unit=12` | evidence heading | Step 4 of 4 · Source evidence |

That is three clicks from example to evidence, and the same in both
languages. At 320 px, step 3 is 817 px down (en) and 728 px (zh). The
example's own step 4 button reaches the evidence directly, 740 px down at
390 px.

**The three largest remaining problems, ranked:**
1. **Broken shared links are dead ends.** A link to an ID the build lacks
   (`#concept=999`) showed "(404) concept not found" with a "Try again" that
   can never succeed. A malformed link (`#concept=abc`, `#example=nope`, a link
   cut short) silently opened the start and erased the address, with no word
   that the link was wrong. Fixed (2, 5).
2. **The keyboard way back was inconsistent.** Back from the evidence to its
   Concept, and from the Concept to its example, focused the heading, not the
   control used. Back past a submitted search left focus on the page body.
   Back to the results and to the start already restored focus. Fixed (3).
3. **The Concept step is long on a phone and repeats itself.** The preferred
   unit is shown twice, once as "Best explanation" and again first under
   "Currently supporting". On a 390 px phone the second unit starts about
   1,050 px down a 1,370 px page, and the hint says "any unit" without
   pointing at one. Not
   changed here: it is the Concept screen's data presentation, which the
   workbench shares.

## 2. Shared links

Rechecked on the baseline package at 390 px:

| Action | Baseline |
|---|---|
| Open an evidence link directly, then reload | stays on the evidence |
| …in-page back to the Concept, browser Back, Forward | no loop; Back leaves the demo (the link was the visit's first entry); Forward returns |
| Switch language on `#q=il+faut&concept=1`, reload, Back, Forward | address and history length unchanged; the language is kept by a reload |
| `#concept=9999`, `#concept=12&unit=9999` | "(404) … not found" with "Try again" |
| `#concept=1&unit=12` (unit filed elsewhere) | opens the evidence; the back action names Concept #1 |
| `#example=nope`, `#concept=abc`, `#concept=12&unit=`, `#mode=semantic&preset=nope`, `#q=` + 201 characters, `#unit=12` | the start, silently; address rewritten to `/` |

**Fix (highest impact):** a malformed link now opens the start with a notice
in both languages: "That link does not match anything in this demo. Start
with an example below or search the library." The notice also appears for a
malformed fragment typed during a visit, and goes at the next move. The
private workbench reads no fragment and is unchanged.

## 3. History and focus: search → Concept card → source

Keyboard only, at 390 and 1280 px.

| Step | Baseline focus | Now |
|---|---|---|
| Enter in the search field | the field; `#q=il+faut`, one entry | same |
| Enter on the Concept card | Concept heading | same |
| Enter on "View source record" | evidence heading | same |
| In-page "← Back to concept" | Concept heading | **the "View source record" button used** |
| Browser Back from the evidence | Concept heading | **the same button** |
| In-page or browser back to the results | the Concept card | same |
| Browser Back past the search | page body, not in view | **the search field** |

**Rule** (`web/src/demo/history.ts`): opening a screen focuses its heading.
Coming back focuses the control that left it when that control is on the page
again; otherwise the heading. The focused control is scrolled to the middle of
the screen, clear of the sticky return bar.

**Cost:** back on the example, focus is now on "Open the Concept", below the
"← Back to examples and search" button, not on the heading above it. The
keyboard round trip to the start therefore uses Shift+Tab for its last leg.
- **Now:** 21 key presses in the matrix and 25 in `accept_a11y`.
- **Before:** the earlier procedure tabbed forward from the example's heading,
  in 17 and 20 presses.
- **Not comparable:** the baseline build, run with the new procedure, takes
  28, because focus starts on the heading and Shift+Tab wraps around the page.

## 4. Phone layout at 320 and 390 px

- **Result:** in the matrix on the final package, 300 screens (every Concept
  and evidence screen, both broken-link screens, long injected identifiers,
  French and bilingual text, both languages) have no document overflow and no
  element past the device edge.
- **Regression, two measures:** `accept_matrix.mjs` now measures each screen
  twice:
  - **document:** root `scrollWidth` against the device width;
  - **elements:** the right edge of every rendered leaf element, named.
- **Self-test:** the old evidence-row layout is injected at 320 and 390 px in
  both languages. The document check catches it at 409 px. With
  `html, body { overflow-x: hidden }` added, the document is 320 or 390 px
  wide (it would pass), and the element check still names the `dd` at 409 px.
  Before, the element list was only a detail of the document check, so it
  could not fail a clipped page.

## 5. The invalid-link screen

A well-formed link to a Concept or unit the build lacks now says so: "This
link names Concept #999, which this demo build does not have. The link may be
mistyped, cut short or from another build."
- **Action:** a button opens the link's own example, or the first one.
- **No retry:** the 404 will not change. A failure that may pass, such as a
  503, keeps "Try again".
- **No reload, verified:** in the browser, a marker set on the page survives
  the click, the history grows by one entry, and Back returns to the link's
  screen. Covered by `web/src/demo/SharedLinks.test.tsx` and the matrix
  (12 runs).

## 6. Keyboard only: what was checked

- **Walk:** landing → example → Concept → evidence → example → start, in the
  matrix (6 size and language runs) and `accept_a11y` (2 runs). Focus is drawn
  (outline or shadow) at every stop and never under the sticky return bar.
  Opening a screen focuses its heading; coming back focuses the control used.
- **Every stop, 6 screens:** start, example, Concept, evidence, not in this
  demo and malformed link, at 390 px (en, zh-CN) and 1280 px (en). On each:
  - every focus stop has a non-empty computed name (`aria-label`,
    `aria-labelledby`, `<label>`, else text);
  - every stop draws a focus ring;
  - the Tab order equals the DOM order, and no stop starts above the one
    before it;
  - Chromium's accessibility tree has no unnamed button, link, combobox,
    textbox or radio.
- **Not run:** a screen reader (VoiceOver, NVDA, TalkBack), Safari, Firefox,
  real phones, zoom or text-spacing overrides. No screen-reader coverage is
  claimed.

## 7. Mechanical candidate

`flh-public-demo-democand-mech1-BLOCKED` was built offline. Both the
artifact and the package were built in a network namespace with only
loopback, with `GOPROXY=off`; there was no npm install.

| | Result |
|---|---|
| **Packaging** | success: linux amd64 and arm64 binaries, the demo web build, `RELEASE.json`, `SHA256SUMS`, tarball |
| Artifact | version `77d0502093f78a56`, domain fingerprint `8c06d309…`, the same as the baseline build (the catalog is unchanged); manifest `8be47a9f…` (per build) |
| `validate-release.sh` | exit 3, `BLOCKED: … mechanical test fixtures (not releasable)` |
| `prepare validate` / `-release` | 0 / 3 |
| **Real-vector readiness** | **none.** `real_model: false`, no `provenance.json`; no real-vector artifact exists for this fingerprint |

## 8. Package entry point

`scripts/validation/demo_candidate/check_package.sh PKG WORK` takes a
packaged demo and runs the maintained tools in order:
- **identity:** `validate-release.sh`, with `RELEASE.json` equal to the
  artifact's manifest and the expectations;
- **boundary:** `smoke_package.sh`;
- **live:** `deploy/ctl.sh` start, `/healthz`, `/readyz` and the served
  identity;
- **writes:** `write_probe.sh`;
- **browser:** the matrix and, with `--suites all`, the other demo suites;
- **stop:** `ctl.sh stop`, with the package unchanged.

On the mechanical candidate every stage passed in 95 s:

| Stage | Result |
|---|---|
| identity | `BLOCKED` with exit 3, as `RELEASE.json` says; identity equals the manifest and `--expect-version` |
| boundary | 24 smoke checks |
| live | serves `77d0502093f78a56`, `8be47a9f…`, `real_model=False` |
| writes | 14 well-formed writes refused (405); identity and counters unchanged |
| browser | matrix 1201/1201, `accept_paths` 112/112, guided 208/208, resilience 41/41, a11y 107/107, FLH-076 37/37 |
| stop | stopped; package files unchanged |

## 9. Negative controls

`negative_controls.sh` runs all four; each must be detected:

| Control | Result |
|---|---|
| wrong `--expect-version` | DETECTED: exit 1, "identity mismatch" offline and served |
| wrong `--expect-manifest` | DETECTED, as above |
| attempted write: the same binary without `-public-demo-artifact`, on a throwaway database | DETECTED: the probe exits 1; 12 of 14 writes were accepted (e.g. `POST /captures` → 201) and 2 probe entries were in that database |
| malformed shared link: the baseline package (no notice) | DETECTED: exit 1; identity, boundary, live and writes pass, and only the browser stage fails, on "a malformed link opens the start with a notice" in all 6 runs |

## 10. Real-E5 candidate procedure (owner only)

See [PUBLIC_DEMO.md](../PUBLIC_DEMO.md), "Real-E5 candidate (owner only)".
- **Covers:** the inputs, nine commands, the expected output of each and
  when to stop.
- **Recorded offline:** the plan values, 23 positions in 3 POSTs, plan
  `536021a4…`, fixtures `d7b97b56…`.
- **Not exercised here:** `embed`, `status` and `import`, because E5 was not
  contacted. Their expected output is from the tool's documented behaviour.

## 11. Phone evidence and the 90-second recording script

The before and after screenshots stay with the lane handoff, not in Git:
- **Builds:** baseline package versus the final mechanical package;
- **Sizes:** 390 px (en, zh-CN) and 320 px (en);
- **Screens:** a malformed link, a link to a missing Concept, and the
  browser Back from the evidence.
- **Labels:** each image carries a stamp, "MECHANICAL BUILD · local
  package … · not the live site".

The live site is unchanged; nothing was deployed.

Record from a mechanical build only to show the mechanics:
- keep the *Development build* label in view and say what it means;
- skip semantic results.

| Time | Do | Say |
|---|---|---|
| 0:00–0:08 | Open the demo; point at *Read-only · Synthetic data · Development build*. | "A read-only demo of my French-learning knowledge service. Synthetic data, nothing is saved, no AI is called. This is a local development build." |
| 0:08–0:18 | Click **One question, two pronouns**. | "It starts from a learner's question, kept exactly as written in French." |
| 0:18–0:32 | Scroll through steps 1 → 4. | "Two short rules were taken from it and filed under one Concept. Step 4 names the record, the extraction and the interpretation they came from." |
| 0:32–0:44 | **Open the Concept and its evidence**; point at *Step 3 of 4*. | "A Concept is the durable idea a learner studies. Every unit says which question it came from." |
| 0:44–0:54 | **View source record #9** on the second unit; point at *Step 4 of 4*. | "One click back to the original question, with its full provenance." |
| 0:54–1:04 | Press the browser's **Back**; point at the focused button. | "Back is one step back, and focus lands on the button I used, so keyboard users carry on where they were." |
| 1:04–1:16 | Copy the address, open it in a new tab, switch to **简体中文**. | "The address is a shared link to this exact screen. The interface changes language; the French stays as written." |
| 1:16–1:30 | Open a link to Concept **#999**; click **Open the example …**. | "A link to something this build does not have says so, and leads straight back to a working example." |

## 12. Candidate status for Release

| | Status | Evidence |
|---|---|---|
| **Packaged** | Yes, mechanical: `flh-public-demo-democand-mech1-BLOCKED` | built offline; tarball SHA-256 `d2979aca9bae07dcb2460886a32fcd54d21d53d9c20cb262180493d2eae9a6ac`; `validate-release.sh` exit 3 |
| **Real vectors** | **No**: not built; E5 not contacted | `real_model: false`; no real-vector artifact for fingerprint `8c06d309…` |
| **Deployed** | **No**: public deployment is frozen; nothing was attempted | — |
| **Verified** | Mechanics only, locally | `check_package.sh` every stage PASS; negative controls 4/4 DETECTED; matrix 1201/1201 (300 screens); FLH-073 `smoke.sh` SMOKE PASSED (94 checks); `make verify` exit 0 (vitest 43 files / 486 tests). Not verified: relevance with real vectors, the live site |

**The single next owner action:** on the integrated tree, run "Real-E5
candidate (owner only)" in [PUBLIC_DEMO.md](../PUBLIC_DEMO.md), steps 1–9.
Deployment remains a separate, frozen decision.
