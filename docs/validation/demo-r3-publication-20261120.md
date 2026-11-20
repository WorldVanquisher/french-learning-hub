# Public demo R3: public packaging, staging plan and a beginner contrast (2026-11-20)

**Rules for this record:**
- **Source:** every number comes from this run on one machine (lane browser: Chromium 156 in a
  container, loopback only).
- **What they are:** scripted observations, not a user study.
- **Builds compared:**
  - "Base" is the base UI with public provenance (`b96675f8` + the public-provenance patch).
  - "R3" is this tree. Both serve artifact `97dbe0f215af37e7` (manifest `4c2488b2…`).
- **Evidence:** the lane handoff `demo-refresh-20261120-r3-100`, which also records the final
  candidate's file names and digests.

## Public packaging

| Check | Result |
|---|---|
| `RELEASE.json` and `artifact/provenance.json` | only allowlisted public fields; the private embedding host is gone. The input artifact is unchanged (5 files hash the same) |
| Gate on a package built before this change | refused at identity (`release.model_provenance.base_url`, `provenance.base_url`) |
| Gate on a package with an unapproved field | refused (`release.build_host`, `release.web.cdn_origin`) |
| Tarball scan, every member including binaries | 0 matches. A package built before this change fails on exactly the two metadata files |
| Route sweep, 127 routes × root and `/api` | 9 public reads; 72 private reads 404; 46 writes 405 |
| Hostile requests (token, Authorization, cookie, traversal) | 0 echo a secret or a path; 0 serve a package file |
| Stale entry in front of the served-identity check | refused (6/7, names the entry script) |
| Local TLS stand-in (the rendered `flh-public-https` nginx files) | 22/22 proxy checks; served identity 7/7 |

## The beginner contrast and its question

| | Base | R3 |
|---|---|---|
| Ways to the *je cuisine* / *je suis en train de cuisiner* contrast | none | under the first example, "Common mix-up: is « je suis cuisinant » French?" |
| Steps from `/` to the answer (P6), 1280 / zh-320 / en-320 | (none) | 2 / 2 / 3 |
| Link to one question | none (a link named the comparison only) | `#compare=…&practice=N`; the answer is never in a link |
| A wrong option and why | none | the stored interpretation of the learner's record, quoted, with its evidence link |
| Hint | none | on request, under the choices; it names no form |
| First example card at 320 px (en / zh) | 504 / 414 px | unchanged |
| Imparfait question from its card (P3), 1280 / en-320 / zh-320 | 2 / 4 / 4 | 3 / 5 / 4 (the new comparison is listed first) |

## Checked in a browser on the R3 package

| Check | Result |
|---|---|
| R3 probe: way in, nothing revealed early, hint, distractor, alternative, copied link, fresh profile, keyboard, Back/Forward, learner's-question panel, storage and requests | 104/104 (en, zh × 320, 1280) |
| Evidence labels open the unit and record they name | 14/14 |
| Layout at 320 px, 200 % zoom and a 24 px default font (verified in effect), 4 screens × 2 languages | 24/24: no overflow, text scales, targets ≥ 24 px, lowest contrast 4.97:1 |
| Chromium accessibility tree: names, states, polite status region | 20/20 |
| Links the demo writes, on 11 screens | 14 distinct, documented parameters only |
| Repository suites | accept_matrix 1381/1381, accept_paths 108/108, accept_guided 244/244, accept_resilience 41/41, accept_a11y 107/107, FLH-076 37/37 |
| Earlier lane probes | practice 52/52, paths 55/55 |

## Bytes and time

**First visit** (gzip bodies):

| | Page | Script | Stylesheet | Demo description | Concept list | Total |
|---|---|---|---|---|---|---|
| Base | 3,064 | 99,556 | 9,434 | 2,092 | 10,304 | 124,450 |
| R3 | 3,064 | 101,926 | 9,576 | 2,092 | 10,304 | 126,962 (+2.0 %) |

**Time:** under a constrained profile (150 ms RTT, 1.6 Mbit/s, 4× CPU; medians of 5 interleaved
cold runs), the start, the comparison and the new question are ready at the same time as the base,
within run spread: about 1.54 s for the first card and 2.04 s for the comparison, on phone and
desktop.

## The Navigation.test.tsx CI failure

| Code | Test | Failed runs (40 each, 2 CPUs under contention) |
|---|---|---|
| CI tree before the history fix | original | 3: the CI failure (the start screen after Back) |
| current | original | 3: all 5 s test timeouts from the load |
| CI tree before the history fix | hardened | 1: the defect (address empty where the example was expected) |
| current | hardened | 0 at moderate load, 0 at heavy load |

**The hardened test:**
- **Waits:** it waits for the observed route state (address and history entry) after every move
  and keeps every Back/Forward assertion.
- **Rejected version:** one that first waited for the start's history entry hid the race, and
  it was replaced.
- **The defect itself:** `HistoryAdoption.test.tsx` covers it deterministically: it fails 3/3
  before the fix and passes 3/3 after.

## Not done here

**Owner only:** the stage on AWS (cloud writes need approval), DNS and public HTTPS. See
`docs/plans/R3-demo-stage-plan.md`.
