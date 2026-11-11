# Sections v1 — learning home and source honesty: validation

Owner: Claude Code (overnight stack, 2026-11-10 UTC). Built on the Mistake
Notebook v1 tree; no schema change. Contract: `docs/ARCHITECTURE.md` §4.8
("Sections v1") and A.20; walkthrough: `docs/DAILY_USE.md` §14.

## What was checked in the save paths

| Path | Explicit save or review | Exact source and version | Gap found | Fix |
|---|---|---|---|---|
| Listening | Save learning record (unchanged) | exercise + transcript version + question | Open source opened the lesson at its current transcript, not the item | the lesson now marks the saved question, or says the lesson shows another version or exercise; the notebook says when a newer version exists |
| Reading | Save learning record (unchanged) | lesson + passage version + exercise + question | same as Listening (a learner passage can get new versions) | same as Listening |
| Writing | Save this mistake (unchanged) | task + draft version + feedback + correction | none (opens the exact draft version) | — |
| Speaking | Save this mistake (unchanged) | exercise + take + transcript version + feedback + improvement | none (opens the exact transcript version) | — |
| Any | — | a stored reference that no longer resolves | one unreadable source made the whole notebook list fail | the item is listed with its stored reference only (`missing` / `unusable`), nothing guessed; the list, the record and its retry mark still work |
| Any | — | who wrote the reference | authored answers and model suggestions looked the same | `reference_origin` (authored / generated) + `generator`, shown apart from "What I got wrong" |

Grammar and Vocabulary were reachable only inside the notebook; the **Home**
tab now names the seven sections and opens Grammar and Vocabulary directly.

## Automated checks

| Check | Result |
|---|---|
| `TestSections_ReferenceOriginSeparatesAuthoredAnswersFromSuggestions` | pass |
| `TestSections_ItemsStayOnTheExactVersionTheyCameFrom` (a newer listening transcript and a newer learner reading passage after the save) | pass |
| `TestSections_AnUnreadableSourceDegradesOneItemOnly` (a deleted listening exercise row) | pass |
| `TestSections_RepeatPracticeAppendsOnlyExplicitDecisions` (mark, unmark, mark; two retry reads write nothing) | pass |
| jsdom: `MistakeNotebook.test.tsx` (mine vs suggested, unreadable source and retry exclusion, newer version, home → Grammar/Vocabulary, zh-CN) and `Reading.test.tsx` (open on the exact question; newer version notice) | pass |
| `NODE_OPTIONS=--no-experimental-webstorage make verify` | exit 0 |

Packaged Chromium: run on the assembled overnight stack; the results are in
the overnight handoff's `START-HERE.md`.

## Not covered

- Listening and Reading still cannot show an older transcript or passage
  version itself; they say so instead.
- The default view is still Concept Review (owner decision).
