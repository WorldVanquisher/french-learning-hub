# FLH-032 annotation recovery validation

Validates the fixes for FLH-030 defects F1, F2 and F3
([FLH-030 report](FLH-030-idempotency-browser-acceptance.md),
[plan](../plans/FLH-032-annotation-recovery.md)).

- Working directory: `french-learning-hub/`.
- No Git commands, `.env`, secrets, daily database, paid provider or permanent dependency were used.
- Frontend checks ran in a temporary copy of `web/`, reusing a previously installed `node_modules`.
- Browser runs used isolated temporary databases with the synthetic FLH-030 fixtures (units 1–12, concepts alpha=1, beta=2, gamma=3) and a local stub provider.

## Evidence types

| Type | What it proves |
| --- | --- |
| **Mocked (vitest/jsdom)** | Component and storage logic against a stateful fixture backend, rendered in StrictMode. No real browser or HTTP server. |
| **Real browser** | Headless Chrome 154 driven by playwright-core 1.49.1 against the real Go server and SQLite. Each probe ran twice: against the Vite DEV server (StrictMode) and against the PROD build served by `-web-dir`. Faults were injected at the browser level. |
| **DB reconciliation** | Read-only `sqlite3` queries on the temporary databases after the browser runs. |

## Automated checks (final sources)

| Command (in temporary `web/` copy) | Result |
| --- | --- |
| `npm run typecheck` | pass |
| `npm test` | 16 files, **207 tests passed** (198 before; 9 added) |
| `npm run build` | pass (`index-Bn7_bwfR.js`, the same bundle used by the browser runs) |
| `go test ./...` / `go vet ./...` (repository) | pass / pass (backend unchanged) |

### Regression tests added (mocked)

- **`annotationOperation.test.ts`:**
  - A conflict is `OperationConflictError` (not a storage error) carrying the existing operation; other units are unaffected.
  - Clearing removes only the exact key and payload. A newer operation for the same unit survives, without a storage write.
  - Access and format failures are `OperationStorageError`, including a `getItem` exception.
  - `recheckStorage` fails while storage fails and succeeds after.
- **`ReviewOutcomes.test.tsx` → "FLH-032 recovery fixes":**
  - **F1:**
    - Another tab's saved operation makes RELATED send nothing.
    - The unit-specific panel names the existing DISTINCT and its key, with no storage alert.
    - Only that unit is blocked; unit 6 DISTINCT is sent with a fresh key.
    - An explicit retry on unit 5 sends the existing key and payload.
  - **F2:**
    - A 422 after unmount clears the saved operation, and a remount shows nothing unresolved.
    - A late 422 for an old key leaves a newer operation intact.
    - An unknown outcome after unmount keeps the operation; the restored retry uses the same key.
  - **F3:**
    - Keyed buttons are disabled and unkeyed ones stay enabled. A recheck while failing says "still unavailable"; after recovery it re-enables with 0 POSTs. An explicit DISTINCT then sends once.
    - An unreadable value on load: the recheck says reloading does not repair it and leaves the value untouched.
    - A failed cleanup after commit is retried by the recheck.

**Mutation check.** Each regression test was confirmed to fail on a scratch copy with its fix reverted:
- F1 → the F1 test fails;
- F2 (mounted check moved first) → the 422-after-unmount test fails;
- F3 (`keyedUnavailable` not passed) → both F3 UI tests fail.

## Real-browser results

### FLH-032 probes (`scripts/validation/flh032/probes.mjs`): DEV 7/7, PROD 7/7

| Step | Expected | Actual (identical in DEV and PROD) |
| --- | --- | --- |
| G1 F1 two tabs | Tab B: accurate per-unit conflict, nothing sent; other units keyed | Panel: `Nothing was sent: this browser already has an unresolved DISTINCT from concept #2 saved for unit #5, probably from another tab. It is kept unchanged; check its receipt or retry it explicitly…`, with tab A's key. 0 POSTs, no "Browser storage" text, storage kept A's op. Unit 6 NARROWER sent 1 and committed. B's explicit retry used A's key → committed. A's Check receipt → found, storage empty. Unit 5 DISTINCT beta 1, RELATED gamma 0. |
| G2 F2 [inj 422] while away | Exact op cleared; unit not unresolved | Storage during send: 1 op; after the 422 arrived while on Annotation Inspector: `[]`. On return unit 9 has no panel and decisions are enabled. Receipt 404, 0 events, 1 POST. |
| G3 F2 newer op survives | Late rejection of the old key does not touch the newer op | Storage after the 422: only the newer `0f32aaaa…`. Reload restored it; explicit retry committed BROADER beta (receipt 200). Old key: receipt 404, 0 events. |
| G4 F2 [inj reset] while away | Unknown kept for recovery with the original key and payload | Storage kept the DISTINCT alpha op. Reload restored it. A retry with gamma selected still sent alpha under the same key: 1 event, receipt 200, storage empty. |
| G5 F3 save failure | Keyed disabled visibly; explicit recheck; no automatic POST | Alert `Browser storage failed. Nothing was sent; reload recovery cannot be guaranteed. Keyed decisions (BROADER, NARROWER, RELATED, DISTINCT) are disabled until browser storage is rechecked.` plus a **Recheck browser storage** button. DISTINCT/BROADER/NARROWER/RELATED disabled; SAME/NEW/INVALID enabled. A recheck while failing says "still unavailable". After storage recovered the buttons stayed disabled until the recheck (0 POSTs), then were enabled (0 POSTs). An explicit DISTINCT sent 1 and committed. |
| G6 F3 cleanup failure | Recheck retries the exact cleanup | The committed op stayed saved; the recheck cleared it; after reload unit 7 has no panel. 1 POST, receipt 200. |
| G7 F3 unreadable value | Honest recheck text; recovery once the value is removed | RELATED disabled. The recheck left `{not json` untouched and said reloading does not repair it. After the value was removed, a recheck re-enabled RELATED without a reload. |

All 10 annotation POSTs per run carried an `Idempotency-Key`. There were no automatic resubmissions: the only repeated keys were the dropped/reset originals followed by explicit retries.

### FLH-030 regression: DEV 24/24, PROD 24/24 (adapted S1/S2)

- **Unmodified FLH-030 harness (run 2).**
  - N1–V3, H1, R1, K1 and C1 passed.
  - **S1 and S2 failed by design**: they assert the old alert text and click keyed buttons that FLH-032 now disables.
  - S2 then left a corrupt saved value, so S3 and X1–X3 failed as a cascade (seen texts show the storage alert carried over).
- **Run 3** used the harness copy written by `adapt030.py`, with only S1/S2 rewritten for the new behavior. All 24 passed in both environments, including:
  - **V3:** the 422 while away now leaves storage `[]`, no panel and enabled decisions. FLH-030 recorded the op left behind.
  - **S3:** the original cleanup-failure text is still a prefix of the new one.
  - **K1:** every DISTINCT/relation POST was keyed.
- **FLH-030 probes P1/P2 (unchanged).**
  - **P1:** the historical receipt still reads `This historical result is separate from current authority` after a later INVALID.
  - **P2:** tab B now shows the conflict panel (not "Browser storage failed"), and NARROWER on another unit sends **1** POST (FLH-030: 0). Tab A's retry committed and storage ended empty.

### Database reconciliation (read-only `sqlite3`)

| Run | DB | Receipts | DISTINCT | Relations | Notes |
| --- | --- | --- | --- | --- | --- |
| FLH-032 probes | dev, prod | 6 | 4 | 2 | receipts = keyed events; no duplicate (unit, concept[, relation]) |
| FLH-030 adapted + P1/P2 | dev, prod | 20 | 8 | 13 | 0 orphan receipts; 1 relation is the FLH-030 harness's deliberate unkeyed HTTP request; +1 receipt vs FLH-030 is P2's now-permitted NARROWER |

## Acceptance criteria

| Criterion | Evidence |
| --- | --- |
| Storage access/format failure distinguished from an existing unresolved operation | Typed errors (unit tests); G1, P2 (browser) |
| Existing operation preserved, conflict explained accurately | G1: storage kept A's op; panel names it and its key |
| Per-unit conflict never becomes page-wide | G1 and the F1 mocked test: other unit keyed, sent and committed |
| Definite rejection cleans up the exact op even when unmounted; never clears a newer one | G2, G3; F2 mocked tests; exact-match unit test |
| Unknown outcomes stay recoverable with the original key and payload | G4 and the F2 unknown mocked test; FLH-030 U1–U4, D1–D3 |
| Consistent visible controls and actionable recovery; no silent enabled controls; no automatic POST | G5–G7 and the F3 mocked tests; 0 POSTs from rechecks |
| Receipt/current separation, reload recovery, stale isolation, unkeyed behavior preserved | FLH-030 P1, U3, V1/V2, L-*, R1 and the existing 198 tests |
| No multi-tab locking, backend change or new semantics | Only frontend files changed; Go tests unchanged and passing |

## Limitations

- Headless Chrome on macOS only.
- Faults are injected at the browser level: a synthetic 422 the server never saw, connection resets, and a `setItem` override. A real quota or private-mode failure was not reproduced.
- In G3 the "other tab" is simulated by writing to `localStorage` directly. G1 and P2 use two real tabs in one browser context.
- **Known limit (by design, documented in the plan).** An operation adopted from another tab that the other tab later definitely rejects (and clears) stays displayed in this tab until reload. Its receipt check returns 404 (unknown). No automatic release was added.
- The FLH-030 S1/S2 expectations were replaced in a temporary copy, not in the FLH-030 harness, which is unchanged. Updating that harness belongs to its owner.
