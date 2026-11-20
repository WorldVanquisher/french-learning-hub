# Public demo R2: phone comparison, practice and first visit (2026-11-19)

**Rules for this record:**
- **Source:** every number comes from this run, on one machine (lane browser:
  Chromium 156 in a container, loopback only).
- **What they are:** scripted observations, not a user study.
- **Builds compared:**
  - "Before" is the pinned package `d1119-rehearsed` (tree `8a75de57…`).
  - "After" is `d1119-r2` (tree `7935a87c…`, `SHA256SUMS` digest
    `ac02c095…`).
  - Both serve the same public artifact, `97dbe0f215af37e7`.
- **Evidence:** the lane handoff `demo-refresh-20261119-r2-100`.

## Before and after on a phone

| | Before | After |
|---|---|---|
| Distance between the two example sentences, 320 × 640 (en / zh) | 714 / 672 px | 106 / 106 px |
| Both examples in one view, 320 px | never | yes (also tablet 768, 200 % zoom, 24 px default font, a 200-character sentence) |
| T3 "compare two examples", 320 px (en / zh), steps | 4 / 4 | 3 / 3 |
| Swipes after opening the comparison, 320 px | 2–3 | 0 |
| T1 "open a French question", 320 / 1280, steps | 1 / 1 | 1 / 1 |
| T2 "what the evidence supports", 320 px (en / zh), steps | 9 / 7 | 9 / 8 (the evidence card's new controls) |
| Text that ignores a 24 px default font (11 route states) | 580 elements | 0 |
| Controls under 24 × 24 px at 320 px | 14 on the start page | 0 |
| Lowest text contrast | 3.99:1 (a highlight in a hint) | 4.6:1 |

Steps count taps, typed queries, Enter and 80 % swipes; T1–T3 times are
medians of 3 interleaved runs per build (`r2-030-rehearsal-pkg/medians.md`).

## New behaviour, checked in a browser on the package

| Check | Result |
|---|---|
| Comparison layout, 14 configurations (en/zh × 320/768/1280, long sentence, 200 % zoom, 24 px font) | both examples in one view in all; no horizontal overflow |
| Practice: context before the choice, nothing revealed early, reveal announced and focused, both forms linked to their evidence, the valid alternative, Back from the evidence restores the answered example, second example, skip, no cookie/storage/IndexedDB/cache, no write, route sweep after the practice | 52/52 (en, zh × 320, 1280) |
| Accessibility: heading order on 8 screens × 2 languages, highlights underlined, contrast, reduced motion, 24 px targets, keyboard order, focus return, status announcements | 60/60 |
| First-visit paths from a clean profile: example, comparison, practice, search to "Why it matched", the 60-second tour; direct links; broken links one tap from search; every feature from `/` | 51/51 |
| Repository suites | accept_matrix 1381/1381, accept_paths 108/108, accept_guided 244/244, accept_resilience 41/41, accept_a11y 107/107, FLH-076 37/37 |
| Earlier lane probes | walkthrough 22/22, evidence and comparison 72/72, UX 10/10, state 6/6 |

## Bytes and time

First visit, gzip bodies (`bytes_check.py`):

| | Page | Script | Stylesheet | Demo description | Concept list | Total |
|---|---|---|---|---|---|---|
| Before | 3,073 | 95,099 | 8,005 | 2,092 | 10,304 | 118,573 |
| After | 3,066 | 99,412 | 8,694 | 2,093 | 10,304 | 123,569 (+4,996, +4.2 %) |

The practice code is 1,115 bytes of the script (gzip).

**Time** (390 × 844 phone, 150 ms RTT, 1.6 Mbit/s, 4× CPU; medians of 5):

| | Interleaved start | Sequential start | Comparison | Warm visit |
|---|---|---|---|---|
| Before | 1,577 ms | 1,543 ms | 2,085 ms | 553 ms, 12,820 B |
| After | 1,583 ms | 1,549 ms | 2,084 ms | 549 ms, 12,821 B |

The start is measured to the first example card, the comparison to the first
example sentence; the warm visit is the first card from cache. Every sample
names its build and entry script (`check_runs.py`: RUNS CHECK PASS).

**Not split:** a lazily loaded practice saved 192 bytes of the entry script
on a scratch prototype. A failed chunk there showed a retry that worked
without a reload (3/3).

## Package

| | |
|---|---|
| Gate | `check_package.sh --expect-sums … --pinned-manifest …` PASSED: identity, boundary (24), live, writes (14), examples (12/12), stop. A tampered copy fails on the named file |
| Served identity | loopback 7/7; correct proxy 7/7; stale entry, stale page and stale artifact each FAIL on that item; rollback package 7/7 against itself, FAIL against this |
| Host update rehearsal | `flh-release`, local fakes: previous → new, previous kept intact, two rollbacks: 7/7 |
| Public surface | 254 route probes, including the Workbooks lane's `/review-today` and 8 other routes: only allowlisted reads answer. Privacy crawl 8/8; 15 error bodies name nothing local |
