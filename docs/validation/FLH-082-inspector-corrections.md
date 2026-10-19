# FLH-082 — Correct reviewed units from the Inspector (handoff)

Owner: Claude Code. Scope: frontend (`web/`) and user documentation only. No
endpoint, migration, Go code or domain semantics changed.

## Result

The unit inspection opened from a record (`UnitInspection`) now renders
`UnitCorrections`, which offers, for a unit of the record's current extraction:

- resolved (CURRENT SAME): Reassign SAME (`PUT /knowledge-units/{id}/concept-membership`)
  and Mark INVALID (`POST /knowledge-units/{id}/invalid`);
- invalid: Restore (`POST /knowledge-units/{id}/invalid/restore`).

Historical, unresolved and no-current-extraction units get no correction. Each
action is explained before confirmation, re-checked against a fresh read
immediately before sending (nothing is sent on any difference), sent once, and
reported as succeeded / rejected / unknown with the existing `ExplicitAction`,
`OutcomeBanner` and `RefreshBanner`. Unknown outcomes are checked read-only, never
resent, and block further corrections until found or explicitly allowed. A
failed post-write re-read keeps corrections disabled until a manual re-read
succeeds. Back to record waits while a write is in flight; return focus is
unchanged.

## Files

- `web/src/pages/unitCorrection.ts` (new): eligibility, basis comparison, send, check.
- `web/src/pages/UnitCorrections.tsx` (new): correction panel and unknown-outcome panel.
- `web/src/pages/UnitInspection.tsx`: stale-safe refresh, catalog load state, panel.
- `web/src/App.tsx`: focused-inspection subtitle and comment.
- `web/src/UnitCorrections.test.tsx` (new): 11 tests through the real App in
  StrictMode against a synthetic stateful fixture.
- `web/README.md`, `docs/QUICKSTART.md`, `docs/ARCHITECTURE.md` §10.4,
  `README.md`, `README.zh-CN.md`.

## Validation

Run in `web/` after `npm ci`:

- `NODE_OPTIONS=--no-experimental-webstorage npm test`: 19 files, 230 tests passed.
- `npm run typecheck`: passed.
- `npm run build`: passed.

The local Node is v26. Without `--no-experimental-webstorage`, Node's built-in
`localStorage` shadows jsdom's and 40 existing tests in
`annotationOperation.test.ts`, `ReviewOutcomes.test.tsx` and `ReviewQueue.test.tsx`
(files this task did not touch) fail. CI pins Node 22, where the flag is not needed. All new
tests pass with or without the flag.

## Known risks / backend gap

- The reassign, INVALID and restore endpoints check only that the unit (and
  Concept) exists, not that the unit belongs to the current extraction, and
  reassign accepts a retired Concept. The workbench enforces both restrictions
  and re-reads right before sending, but a change between that re-read and the
  write is not detected. Enforcing currency server-side would need a
  backend change, which this task did not make.
- These endpoints have no idempotency key; an unknown outcome is reconciled from
  current authority, as Concept Review does for SAME and INVALID.
