# Review Today batch: item counts reconciled with the per-ID table (2026-11-19)

The source of truth is the per-ID table in the sealed `handoff-100/HANDOFF-100.md` (SHA256SUMS
`f73278e9…`), parsed by script: every ID 001–100 appears exactly once.

## The correction

The chat report that closed the batch said "94 implemented and verified; 8 prototypes, 3 blocked,
1 owner-only". That adds to 106, not 100, and it is wrong:
- **Prototypes:** it counted only the scheduler items (011, 012, 015–020) and left out 021, 026
  and 054.
- **Implemented:** "94" was not taken from the table. The report's own range list for
  implemented items (001–010, 022–025, 027–046, 048–053, 055–080, 082–100) counts 85.

`HANDOFF-100.md` itself states no totals, so the sealed handoff needs no change. Only that
summary was wrong.

## Counts from the table

| Category (the four the owner asked for) | Count | IDs |
|---|---|---|
| Implemented or verified (table labels: Implemented 55, Verified 15, Done 13, Measured 1, Implemented (read side) 1) | **85** | 001–010, 022–025, 027–046, 048–053, 055–080, 082–100 |
| Verified prototype (Prototype (verified) 9, Prototype 1, the mixed 054) | **11** | 011, 012, 015–020, 021, 026, 054 |
| Blocked: needs a migration number | **3** | 013, 014, 047 |
| Owner-only | **1** | 081 |
| **Total** | **100** | |

**Edge cases, stated once:**
- **054** is counted as a prototype. Its workbook half ("Done for today") is implemented and
  stored, but its Speaking half ("Hide for this visit") is page-only.
- **023** is counted as implemented: read-side provenance works. Its stored half shares the
  `practice_prompts` decision with 021 and 026.
- **086, 087, 090, 091–100** are documentation or measurement items marked Done or Measured. They
  are counted as implemented because their deliverable exists and was checked in the run.

## Cross-check with Extraction 2.0 HANDOFF-136 (read only; nothing in that lane was changed)

`handoff-136` verifies (`sha256sum -c`: OK). Its per-ID table (`docs/validation/EXTRACTION-2.md`
in that lane's worktree) covers 111–136, **26 items**:

| Label in their table | IDs | Count |
|---|---|---|
| done | 111–114, 115, 116, 131 | 7 |
| implemented (prototype) | 117–118, 119, 120, 121–123, 124, 125–127, 129 | 12 |
| written | 128, 136 | 2 |
| run | 132, 135 | 2 |
| owner-only smoke | 130 | 1 |
| design only | 133 | 1 |
| proposal, owner-review (Workbooks lane) | 134 | 1 |

**Discrepancy (theirs to fix):** the handoff's label line names 130 and 134 as owner-only or
owner-review, but the table also marks **133** (learner trial) as "designed, not run". The label
line does not mention it.

**What reaches this lane:** item 134, the `flh_practice_review_feed_v1` payload. Its Workbooks side
is the slice built after this note (`docs/validation/PRACTICE-FEED-SLICE.md`). It consumes the
documented fixture only, read-only, and changes nothing in their contract.

## Evidence correction found while reconciling: the web typecheck

The "typecheck clean" rows in handoffs 025, 050, 075 and 100, and the `web` step of
`scripts/validation/learning_day/verify.py`, ran `npx tsc --noEmit -p .`. That command checks
**no file**: `web/tsconfig.json` lists none (`"files": []`) and only references the app and node
configs. The project's check is `npm run typecheck` (`tsc -b --noEmit`), which `make verify` runs.

**Re-run on the sealed handoff-100 tree** (from `inc4-start-tree.tar`):
- `tsc -b --noEmit` fails with **1 error**: `NotebookPractice.tsx` uses `notePractice.run.back`,
  which no catalog defines.
- Cause: the `practice.*` → `notePractice.*` rename (handoff 025) stopped one line short, leaving
  a stray `practice.run.back`. At run time the "Back to the approved drafts" button showed its key
  instead of its text. No test or walkthrough clicked it.

| Consequence | Detail |
|---|---|
| Items affected | 021–030 (Make practice): the one button label above. Their status stays "implemented", with this defect now fixed |
| Claim retracted | Every "typecheck clean" line in handoffs 025, 050, 075 and 100. The vitest, Go and browser results in those handoffs are unaffected: they ran real checks |
| `make verify` | Would have failed on the handoff-100 tree, at `npm run typecheck` |

**Fixed in this increment:**
- The key is renamed to `notePractice.run.back` in both catalogs.
- `verify.py` now runs `npm run typecheck`.
- AGENTS.md names the right command.

`npm run typecheck` passes on the current tree.
