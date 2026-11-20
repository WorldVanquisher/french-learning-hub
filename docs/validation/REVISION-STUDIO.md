# Revision studio (2026-11-19)

Synthetic fixture packs and disposable databases only. No migration, no provider call.

**Where:** a workbook script lesson → **Revision history** (`web/src/pages/RevisionStudio.tsx`).
Routes are in `docs/ARCHITECTURE.md` §4.3 and A.16; none is on the public demo's allowlist.

| Need | What exists |
|---|---|
| Block-level differences | Every line in order (`AlignListeningBlocks`, the update preview's alignment). A changed line carries word edits (`DiffWords`): `<ins>` and `<del>` with spoken labels "inserted:" and "removed:". Underline and strike-through mean the colour is never the only cue |
| Fold unchanged lines | On by default. A folded run is one button ("3 unchanged lines (s1–s3): show"). The header always names the revision pair ("Revision 2 → revision 3.") |
| What belongs to a revision | Lines (transcript #), questions (exercise #), answer key (authored exercise and generator, fingerprint), audio (always "none": a script is never recorded), and the notebook records saved from it, with how many are in Review Today |
| Restore preview | Shows what changes: the next revision number, the lesson moving to a new exercise, the records on the current revision keeping their wording, and the unsaved-answers warning. Nothing is written until the confirm button |
| Restore as a new revision | `POST …/restore` appends the older content via `ReviseAuthoredScript`. History is never rewritten; records keep their exercise |
| Two editors | A resend replays (200, no second revision). A confirmation against an older current revision is `409 stale_preview` with a fresh preview and nothing written; confirming the fresh preview works |
| Long French text | `DiffWords` pieces rebuild both sides exactly: tested with ` `, ` `, `’`, `« »`, `…`, line breaks and a 40-sentence passage. The UI keeps `white-space: pre-wrap` |
| Empty and one-revision views | One revision: one sentence says what will happen and where, plus its facts; no comparison. A YouTube lesson is `409 not_authored_script` and the panel is not offered |
| Older record beside a current one | A revision stored by an older build (extra key, no evidence) compares and previews a restore without error; every question names `evidence` as changed |

## Tests (this run)

| Command | Cases |
|---|---|
| `go test -count=1 -run 'TestDiffWords\|TestAlignListeningBlocks' ./internal/domain/` | 3 |
| `go test -count=1 -run 'TestRevisionStudio\|TestReviewToday_NeverInThePublicDemo' ./internal/transport/http/` | 4 |
| `cd web && npx vitest run src/pages/RevisionStudio.test.tsx` | 5 |

**Known limit:** after a restore, `pack_status` reports `update_available` whenever the
restored content differs from the pack, so the pack update notice reappears. This is
intended; a restore never hides a correction.
