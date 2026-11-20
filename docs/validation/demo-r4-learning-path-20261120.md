# Public demo R4: learning path, browser checks and publication boundary (2026-11-20)

**Rules for this record:**
- **Source:** every result comes from this run on one machine (lane browser: Chromium 156 in a
  container, loopback only).
- **What they are:** scripted observations, not a user study.
- **Builds compared:**
  - "Base" is the merged base `58c0ba8b`, packaged as `r4-base`.
  - "R4" is this tree. Both serve artifact `97dbe0f215af37e7` (public manifest `4c2488b2…`).
- **Evidence:** the lane handoff `demo-refresh-20261120-r4-075`, which also records the final
  candidate's file names and digests.

## Publication boundary

| Check | Result |
|---|---|
| Served identity tied to `RELEASE.json` (page SHA-256, build id, entry, artifact version, manifest) | 5/5 ties; served-identity check 7/7 |
| Two real packages, each checked as the other | refused (4/7); 7/7 as itself; the gate refuses a wrong digest |
| Archive and extracted-file scans (private host, machine paths, tailnet, e-mail) | 0 findings; a private-provenance package fails on exactly its two metadata files |
| Unapproved field in `RELEASE.json` or `artifact/provenance.json` | refused, naming the field path, never its value |
| URLs and paths in the demo bundle | only the boundary's allowlist (the workbench's semantic and hybrid routes removed; `check_bundle.py` now refuses them) |
| 127 server routes × root and `/api` | 17 public reads answer, 145 private reads 404, 92 writes refused |
| Negative controls (`negative_controls.sh`) | identity ×2 and write detected; link not run (needs a pre-fix control package) |
| A whole visit's requests | 141, all same-origin GETs of the page, its assets and the read routes; none off-origin; nothing stored |

## The learning path

| | Base | R4 |
|---|---|---|
| The first suggested action (the tour) opens | the imparfait example (question in English) | the first French example, in 1 tap, at 320, 390 and 1280 px |
| Evidence controls with a name shared by different destinations | yes ("See where this unit came from", "Open the Concept and its evidence") | none (18 controls on 5 screens) |
| A rule not contained in the question | not said | one line: it comes from the stored interpretation |
| The wrong option « je suis cuisinant » | not a French form, with the stored reason | also "Tempting" against "Supported rule (unit #15)" |
| Focus after an immediate Back from evidence | on the opening control in 41 of 60 runs | 60 of 60 |
| A question stored with decomposed accents | its repeated words were not marked | marked as whole words |

## Checked in a browser on the R4 build

| Check | Result |
|---|---|
| Entry: the first example without typing, account or provider; long en/fr/zh strings | 42/42 |
| Guided steps: 32 step links, headings and navigation, Back/Forward, returns to the same step, invalid and retired links | 80/80 |
| Comparisons: all three, the prompt before an answer, a skip | 52/52 |
| Evidence: quote vs rule, destination names, the orphaned Concept | 8/8 |
| Learning clarity, and a three-task walkthrough (2, 3 and 2 steps on a phone) | 8/8 |
| Accessibility: keyboard path (19 keys), focus, live regions, labels and contrast (≥ 4.6:1, light and dark preference) | 9/9; `accept_a11y` 107/107 |
| Localization: switching keeps the screen and answer; 2 languages × 390/1280 px × 6 screens; 600-character French excerpts | 53/53 |
| Merge with the Workbooks lane's catalog edits | clean (`diff3`); typecheck and i18n tests pass on the merged catalogs |

## Bytes and time

| | Base | R4 |
|---|---|---|
| First visit, gzip bodies | 126,988 B | 127,325 B (+0.3 %) |
| Entry script, gzip | 101,926 B | 102,215 B |
| Time to first card / first example, constrained phone and desktop (7 runs each) | | no measurable difference: the ranges overlap |

The constrained profile is 150 ms RTT, 1.6 Mbit/s and a 4× CPU slowdown.

**Not claimed:** warm-visit timings, which were too variable over 2 runs. Returning visits
transfer about 12.8 KB on both builds.

## Not done here

**Owner only:** any stage, DNS, publication, pushes and the PR. The publication checklist is in
`docs/PUBLIC_DEMO.md`.
