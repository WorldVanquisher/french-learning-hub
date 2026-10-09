# FLH-032 browser annotation recovery fixes

Fixes the three defects in
[FLH-030](../validation/FLH-030-idempotency-browser-acceptance.md) on top of the
integrated FLH-029/030/031 baseline. This is a frontend-only change. It does
not change the backend, migrations, HTTP contract, dependencies or annotation
semantics, and it adds no multi-tab locking.

## Defects and causes

| ID | Defect | Cause |
| --- | --- | --- |
| F1 | Another tab's unresolved operation is reported as a browser storage failure and blocks keyed decisions on every unit | Every `saveOperation` error mapped to the page-wide `storageFailure` |
| F2 | A definite rejection received after leaving Concept Review leaves the rejected operation saved and the unit falsely unresolved | `if (!mounted.current) return;` ran before the rejection cleanup |
| F3 | After a save-time storage failure, keyed buttons look enabled but do nothing, even after storage recovers | A silent `return` in `act`; `ResolutionActions` did not know about the failure |

## Changes

### `web/src/pages/annotationOperation.ts`

- Two typed errors:
  - `OperationStorageError`: storage access or format failure. `getItem`/`setItem` exceptions, unparsable JSON and invalid shape all raise it.
  - `OperationConflictError`: carries the existing saved operation. It is raised when the unit already has a different unresolved operation, or when the payload saved under the same key differs.
- `clearOperation(decision)` removes only the saved operation whose key **and** payload match exactly. If nothing matches it writes nothing, so a newer operation (another key) is never removed.
- `recheckStorage()` reads and validates the saved operations and rewrites the same content. It proves read and write access and sends nothing.

### `web/src/pages/ReviewQueue.tsx`

**F1: conflict with another tab's operation**

- `OperationConflictError` is handled per unit by `adoptConflict`.
- The existing saved operation is kept unchanged and shown in that unit's keyed reconciliation panel, with its key, "Check receipt" and "Retry saved operation". The panel explains that nothing was sent and that the operation probably comes from another tab.
- Only that unit is blocked. Nothing is sent.

**F2: cleanup after leaving the page**

- `cleanUp(decision, failureText)` clears the exact operation. A failed cleanup is remembered for the recheck and is reported only while the page is mounted.
- On a definite (non-uncertain) rejection of a non-retry keyed send, the cleanup now runs **before** the mounted check.
- Uncertain outcomes still keep the operation for recovery with the original key and payload. A rejected retry still does not cancel the original.

**F3: storage failure**

- While `storageFailure` is set, the keyed buttons (BROADER, NARROWER, RELATED, DISTINCT) and "Retry saved operation" are disabled, with an explanation. SAME, NEW CONCEPT, INVALID and "Check receipt" stay available.
- The alert has a **Recheck browser storage** button. It:
  - retries any failed exact cleanups;
  - calls `recheckStorage()`;
  - restores saved operations for units that have no in-memory recovery state;
  - clears the failure and says that nothing was sent.
- If storage still fails, the recheck says so. It also says that reloading does not repair an unreadable saved value.
- The former silent `return` in `act` now shows an error notice. It is not reachable through the disabled controls.

### `web/src/components/ResolutionActions.tsx`

Adds an optional `keyedUnavailable` prop. It disables the relation and DISTINCT buttons and appends an explanation to the hint.

## Unchanged

- Historical receipts stay separate from current authority.
- Reload recovery, stale-response isolation, and the unkeyed SAME/NEW/INVALID behavior and its "allow another decision" path are unchanged.
- There is no automatic POST retry. The storage recheck only reads and rewrites local storage.

## Known limits

- **Adopting another tab's operation.** If the other tab later definitely rejects that operation and clears it, this tab still shows it until reload. Its receipt check returns 404 (unknown). Releasing it automatically would need cross-tab coordination, which is out of scope.
- **Newer operations saved after load.** A newer operation that another tab saves after this page loaded only appears here after a recheck or reload, or when this tab tries to decide on that unit.

## Validation

See [FLH-032 validation](../validation/FLH-032-annotation-recovery.md).
