# FLH-153 follow-up: a first visit by search (items 21–40, 2026-11-17)

**Release status: BLOCKED** (mechanical vectors). This follows
`FLH-153-packaged-demo-verification.md` in the same worktree and on the same
baseline. Local fixtures only: long and right-to-left text are injected in the
browser, and the server and its data never change. Nothing was deployed, and
no external service was called. Chromium 156 ran in a disposable container
against packages served by their own binary on loopback.

**Candidate:** `flh-public-demo-flh153-fu-final-BLOCKED`.

| Field | Value |
|---|---|
| Artifact | `77d0502093f78a56` |
| Manifest | `d3e6a6553328d88f0c83810588dd3e96bee2496db0df7a7434b0ed05e3983303` |
| Tarball SHA-256 | `a16ae94846fcf839f82a0c2c47b15215a5fcd6a12e46fb343112fd909c922a29` |
| Revision label | `198b23f14489+flh153-fu` |

Its web build is byte-identical to the package every probe below ran on
(`fu2`).

## Confirmed fixes (two)

| Fix | Before | After |
|---|---|---|
| **A submitted search shows what it found.** In the demo, the explanation of how search works now follows the results instead of sitting inside the form. A submitted search scrolls just far enough to show its first result, the no-match help or the error, and focus stays in the form. Searches opened by a link, a reload, Back or Forward do not scroll. | After Search, the first result was off screen in all 5 configurations (390 en/zh, 320, 1280 en/zh), 1057–1264 px down. Nothing on screen changed. The no-match help was also off screen at 390 px. | The first result is on screen in all 5 configurations, after a scroll of 0–194 px. The search field keeps focus and stays in view. |
| **The learner's text keeps its own direction.** The original question gets `dir="auto"` on the example and the evidence. The context gets `dir="auto"` on the example, and an isolating `<bdi>` in the evidence's context row. | A question starting in Arabic and a context starting in Hebrew were laid out left-to-right. The phrases around the embedded French were shown in the wrong order, and the final punctuation was on the wrong end. | Right-to-left in all 6 configurations checked. French, English and Chinese are unchanged ("auto" resolves to left-to-right). |

- **Code:** `web/src/pages/KnowledgeLibrary.tsx` and
  `web/src/demo/ExampleScreen.tsx`. Every change is demo-gated, adds no text
  and no i18n key, and leaves the private workbench unchanged.
- **Tests:**
  - `web/src/demo/SearchFirst.test.tsx` (4) and
    `web/src/demo/LearnerText.test.tsx` (2). All 6 fail on the FLH-153
    sources.
  - `scripts/validation/demo_ux/accept_matrix.mjs` gains 9 checks per
    configuration (54 in all). The FLH-153 package fails exactly 22 of them;
    the 32 that pass on both are the French left-to-right check and the
    overflow checks on the right-to-left screens.
- **Recorded commands (item 36):** `docs/PUBLIC_DEMO.md` had a private
  network address in the FLH-076 "Continuation" command. It now uses `"$E5"`
  (§36).

Everything else below is an observation.

## 21. A 60-second first visit, from search to the original evidence

A sighted visitor at 390 px who chooses to search. The time budget is a
script estimate; the scroll and on-screen figures are measured (probe
`search_path_probe.mjs`, after the fix).

| Seconds | Action | What is on screen (390 px, en / zh-CN) |
|---|---|---|
| 0–10 | Land; read the title and the intro ("Pick a French learner's question … or search the library yourself") | The first example card at 477 / 380 px. The search field is about one screen down (1207 / 1055 px). |
| 10–20 | Scroll once; type `il faut que`; press Search | The first result appears under the form, at 745 / 677 px, with "1 concept matching “il faut que”". |
| 20–30 | Tap "subjunctive after « il faut que »" | The Concept, focused on its heading. "View source record" is at 630 / 550 px. |
| 30–45 | Read the best explanation; tap "View source record #1 for unit #1" | The evidence screen, focused on its heading. |
| 45–60 | Read the original learning record (the learner's question, its context, when it was recorded), the unit and the extraction | The record is at 530 / 465 px; the return bar stays on top. |

- **Actions:** four, plus one scroll, from landing to the original record.
  At 1280 px no scroll is needed.
- **At 320 px:** the Concept's "View source record" is at 701 px, so one
  more scroll is needed there.

## 22. Where the flow first needs explanation

In order of appearance:

1. **After Search, nothing happened** (FIXED, see above). The results were
   below several paragraphs of explanation in every configuration. This is
   the first point where a visitor would need someone to say "scroll down".
2. **The search is below the examples on a phone** (observation). It is one
   screen down at 390 px and 1.4 screens at 320 px. This is by design: the
   start leads with the examples, and the intro sentence names the search.
3. **Terms in the results** (observation). "2 units filed here, 2 currently
   supporting" uses the demo's vocabulary. Its explanation is now right
   below the results instead of above them.
4. **The Concept screen is long** (observation, carried over). At 320 px the
   source button needs a scroll, because the screen shows the preferred unit
   twice. This was raised by the demo-candidate lane as a design decision.
5. **Identifiers in labels** (observation). "View source record #9 for
   unit #12" is exact but technical.

## 23. The first action in both languages

The first action, opening an example, is on screen at landing in both
languages:
- the first card is at 477 px (en) and 380 px (zh-CN) at 390 px;
- at 320 px its title line is on screen;
- at 1280 px it is at 374 / 329 px.

The gap the audit found was the search's outcome (§22.1). It is fixed
structurally, so it is fixed in both languages without new text.

## 24–35. Results (probe `fu_probe.mjs`: 84/84 on the candidate; the FLH-153 package: 77/84)

| # | Check | Result |
|---|---|---|
| 24 | A search with no match | explains keyword matching and suggests the three examples' searches plus "Show all Concepts"; every suggestion finds at least one Concept; the help is on screen after Search (it was not before the fix); an empty query lists the catalog |
| 25 | An example after a search | the results are hidden; back at the start, the address, form and results agree; a new search shows only its own results; Back and Forward between results and an example never show both. The example's address keeps the search (`#q=il+faut&example=y-en`) as its way back, by design |
| 26 | The way back from the evidence | at 320, 390 and 1280 px the return bar stays at the top at the end of the evidence; its buttons name the destination ("← Back to concept #12", "← Back to the example “…”"); it returns with focus on the control used |
| 27 | A shared link in a clean browser profile | an empty persistent profile opens `#example=y-en&concept=12&unit=12` on the evidence, in English, with no stored state |
| 28 | The same link after a language switch | 简体中文 keeps the address; a reload keeps the screen and the language; a new tab in that profile opens in 简体中文; in-page back, Back and Forward still work |
| 29 | Duplicate parameters | **the first value of each parameter wins**, and the address is rewritten to the screen's own link: `#concept=1&concept=12` → Concept 1, `#q=il+faut&q=pronouns` → `#q=il+faut`, `#concept=12&unit=12&unit=13` → unit 12. If the first value is invalid, the link is malformed (`#example=nope&example=y-en` → the start with the notice). The rewritten address reloads to the same screen |
| 30 | Unicode and percent-encoded queries | `%C3%AAtre` = `être`, `il%20faut` = `il+faut`, encoded = raw Chinese, composed = decomposed `é`: the same results and the same query. A broken escape (`%E0%A4%A`) opens a search without an error. The address keeps the form the link used (observation) |
| 31 | Loading and errors, keyboard only (390, 1280) | a loading Concept says "Loading concept #1…" in a status message, with focus on the heading. A failure is an alert ("Could not load concept #1: (503) …"), "Try again" is the next Tab stop with a visible ring, and Enter recovers without a reload. A search in progress says so in a status message; a failed search is an alert, with focus kept in the field. No screen reader was run |
| 32 | 200% zoom (emulated: 640×450 CSS px at DPR 2) | on the start, example, Concept and evidence, every Tab stop from the top of the document draws a ring, is in view and is not under the return bar; no sideways page scroll |
| 33 | Keyboard walkthroughs | 1280 px and 390 px, 15 presses each: Tab ×2 to the first example, Enter, Tab ×6 to "Open the Concept", Enter, Tab ×2 to "View source record", Enter, Shift+Tab to "← Back to the example", Enter; focus is back on "Open the Concept" |
| 34 | Long evidence | a 1500-character French question, a 330-character unbroken URL-like token and unspaced Chinese in the question, context, statement and example: no sideways scroll and no element past the edge, at 320, 390 and 1280 px, on the evidence and the example |
| 35 | Right-to-left and mixed text (local fixture) | FIXED, see above; no overflow at any size before or after |

## 36. Private endpoints in evidence and recorded commands

- **Change set:** no private address, secret, session link or local path;
  `publish_metadata_check.py` is clean. The one hit was the pre-existing
  address in `docs/PUBLIC_DEMO.md`'s recorded command, now `"$E5"`.
- **Screenshots** (1578 PNGs, outside Git): pages served from `127.0.0.1`,
  page content only. The demo's info payload, which the page renders, holds
  no URL or address.
- **Lane evidence text:** no private address. The working copies of the
  existing real-vector packages, whose provenance names the owner's E5
  address, were deleted after validation; the recorded result omits it.
- **Observation (not changed, outside this lane):** the same private address
  appears in 10 other tracked files:
  - E5 tooling docs: `tools/embedding/e5/README.md`,
    `docs/WINDOWS_EMBEDDING_OPERATIONS.md`, `scripts/demo/flh060/README.md`;
  - validation scripts: `scripts/validation/flh053/*`,
    `scripts/validation/flh058/explore.py`,
    `scripts/validation/flh078/browser_offline.sh`;
  - historical records: `docs/plans/FLH-076-…`,
    `docs/validation/FLH-058-…`, `docs/validation/FLH-076-…`.

## 37. Reviewer script (exact candidate, about 10 minutes, local only)

```sh
# 1. The candidate: verify the tarball against the recorded hash, then the package.
echo "a16ae94846fcf839f82a0c2c47b15215a5fcd6a12e46fb343112fd909c922a29  flh-public-demo-flh153-fu-final-BLOCKED.tar.gz" | sha256sum -c
tar -xzf flh-public-demo-flh153-fu-final-BLOCKED.tar.gz && cd flh-public-demo-flh153-fu-final-BLOCKED
./validate-release.sh; echo "exit=$?"                       # expect 3: BLOCKED (mechanical vectors)
# 2. Serve it on loopback (Linux amd64; arm64: bin/linux-arm64).
env -i PATH=/usr/bin:/bin LISTEN_HOST=127.0.0.1 PORT=18975 ./bin/linux-amd64/flh-server \
  -public-demo-artifact artifact -web-dir web -public-demo-allow-mechanical &
curl -s http://127.0.0.1:18975/knowledge-library/demo | python3 -c 'import json,sys; a=json.load(sys.stdin)["artifact"]; print(a["version"], a["manifest_sha256"], a["real_model"])'
#    expect: 77d0502093f78a56 d3e6a6553328d88f0c83810588dd3e96bee2496db0df7a7434b0ed05e3983303 False
# 3. Open http://127.0.0.1:18975/ in a phone-sized window (390 px) and do the checklist (§40).
# 4. Stop: kill %1
```

## 38. Before/after evidence

Stamped screenshots, outside Git, in the lane handoff (`screenshots/fu-before`
and `screenshots/fu-after`). Each image reads "MECHANICAL BUILD · local package
… · not the live site" and states what it shows.
- **Configurations:** 390 en, 390 zh-CN, 320 en, 1280 en and 1280 zh-CN.
- **Moments:** the screen right after Search ("first result NOT on screen"
  before, "ON screen" after), and the evidence with the right-to-left fixture
  ("direction ltr" before, "rtl" after).

## 39. Packaged gate on the final patch

`scripts/validation/demo_candidate/check_package.sh` on the candidate,
`--expect-version 77d0502093f78a56 --expect-manifest d3e6a655… --expect-status BLOCKED --suites all`:
exit 0.

| Stage | Result |
|---|---|
| identity | PASS |
| boundary | PASS (24 smoke checks) |
| live | PASS: served `77d0502093f78a56` / `d3e6a655…`, `real_model` false |
| writes | PASS: 14 writes refused |
| `demo_ux/accept_matrix.mjs` | 1267/1267 (312 screens; 9 new checks × 6 configurations) |
| `demo_refresh/accept_paths.mjs` | 112/112 |
| `demo_first_visit/accept_guided.mjs` | 208/208 |
| `demo_first_visit/accept_resilience.mjs` | 41/41 |
| `demo_first_visit/accept_a11y.mjs` | 107/107 |
| `flh076/browser/accept.mjs` | 37/37 |
| stop | PASS: package files unchanged |

`fu_probe.mjs` on the same candidate: 84/84.

**Not covered:** real-vector relevance, Safari, Firefox, real phones,
screen readers, real browser zoom (it was emulated), CI and the live site.

## 40. Release note and reviewer checklist

**Release note.** The public demo is easier to use for a visitor who
searches first or arrives by a shared link:
- **Search:** pressing Search now shows the first result, or suggestions
  when nothing matched, right away, instead of leaving it several screens
  below an explanation. That explanation now follows the results.
- **Focus:** keyboard focus no longer falls to the page body when a way back
  leads to the start and the control that left it is gone. It goes to the
  heading of what is shown.
- **Direction:** a learner's question or context written in a right-to-left
  script keeps its own reading order.

The private workbench is unchanged. The demo still uses mechanical vectors
and is not released until real-model vectors are approved.

**Reviewer checklist** (the candidate of §37, Chromium or any browser, a
390 px window; tick each):

- [ ] `validate-release.sh` prints BLOCKED (exit 3); `/knowledge-library/demo` shows `77d0502093f78a56` / `d3e6a655…` / `real_model` false.
- [ ] Landing: the first example card is visible without scrolling; the page says Read-only, Synthetic data and Development build.
- [ ] Scroll to "Or search the library", type `il faut que`, press Search: the result "subjunctive after « il faut que »" appears without further scrolling, and the field keeps focus.
- [ ] Search `zzzq`: "Nothing found? Try one of these" is on screen; "Search “pronouns”" finds a Concept.
- [ ] Open the result, then "View source record …": the original learning record (question, context, when recorded) is shown; the return bar stays on top while scrolling.
- [ ] Copy the address, open it in a private window: the same evidence, in English.
- [ ] Switch to 简体中文 and reload: same screen, Chinese interface; the learner's French is untranslated.
- [ ] Open `…/#concept=9999`, press "← Back …" with the keyboard: "Start with an example" is focused and visible.
- [ ] Open `…/#q=il+faut&concept=12`, press "← Back …": "Or search the library" is focused and visible.
- [ ] Open `…/#concept=abc`: the start shows "That link does not match anything in this demo …".
- [ ] Keyboard only from the start: Tab twice to the first example, then Enter, Tab and Enter through Concept and evidence; Shift+Tab and Enter on "← Back …" returns with focus on the control used.
- [ ] Browser zoom 200%: focus rings visible; no sideways scrolling.
- [ ] Stop the server; nothing was written (`curl -X POST …/api/captures` answers 405 while it runs).

## Validation commands (run here)

| Command | Result |
|---|---|
| `TMPDIR=<home volume> NODE_OPTIONS=--no-experimental-webstorage make verify`, first run | exit 2: 1 of 502 tests failed. It was `Navigation.test.tsx` "never sends the browser's Back forward…", which is unchanged by this work: `findByText` hit its 1 s default timeout (the test took 1.66 s) with the host's load average at 8 on 8 cores, from other lanes |
| The same test alone, 3 times; the full `vitest run`, twice | 13/13 each time; 502/502 each time |
| `make verify`, second run | exit 0: 24 Go packages ok, vitest 46 files / 502 tests, web build |
| `SearchFirst.test.tsx` and `LearnerText.test.tsx` on the FLH-153 sources | 6 of 6 fail (exact negative control) |
| `accept_matrix.mjs` on the FLH-153 package | 1245/1267: exactly 22 new checks fail |
| `check_package.sh` on the candidate, `--suites all` | exit 0 (§39) |

**Observation:** that navigation test relies on default 1 s waits and can time
out on a loaded host. It is not changed here.
