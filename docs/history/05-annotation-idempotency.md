# 5. Lost responses and annotation idempotency

Covers FLH-027 to FLH-033, dated 2026-10-08 to 2026-10-09 where a date is
recorded. Current behaviour:
[ARCHITECTURE §7.5](../ARCHITECTURE.md#75-annotation-request-idempotency) and the
exact [FLH-029 contract](../plans/FLH-029-annotation-idempotency.md).

## The problem

A Concept Review decision is an HTTP POST. If the browser never receives the
response — a dropped connection, a closed tab, a proxy timeout — the reviewer
cannot tell whether the write happened. Re-reading current state does not
settle it either, because the state may already have matched, or the original
request may still be in flight.

## Investigation before the fix

- **FLH-027 (no report in the repository).** Concept Review began reporting each
  decision by what the server actually answered, separately from any re-read
  ([web/README.md](../../web/README.md)). FLH-028 states that it did not wait for
  or claim acceptance of FLH-027.
- **FLH-028, 2026-10-08 (Codex).** An independent investigation used a
  controllable proxy to drop requests, drop responses after commit, and delay
  originals behind reconciliation reads, across all eleven annotation operations
  on root and `/api` routes: 104 cases, all behaving as the code implies. Its
  key result is a table of what each read can and cannot establish. For
  example, a membership read shows the current concept but cannot show whether
  *this* request produced it, and a delayed duplicate DISTINCT or relation POST
  can append another event after the read
  ([report](../validation/FLH-028-review-response-loss.md)).

## Initial implementation

**FLH-029 (Codex; validation report dated 2026-10-08).** Optional
`Idempotency-Key` UUIDs for the operations whose repeats append new events:
DISTINCT and BROADER/NARROWER/RELATED. Migration 009 stores a receipt in the
same transaction as the event. An equivalent replay returns the original
`201` result, and a conflicting payload returns `409` with no write.
`GET /annotation-operations/{id}` returns committed attribution, and `404`
means unknown, never "safe to resend with a new key". The browser saves a
minimal operation identity before sending, restores it on reload, and offers an
explicit same-key retry; there is no automatic retry. Author checks passed:
targeted and full Go tests, `make verify`, and 198 frontend tests. A real
browser was **NOT RUN**
([plan](../plans/FLH-029-annotation-idempotency.md),
[report](../validation/FLH-029-annotation-idempotency.md)).

## Verification and corrections

- **FLH-030, 2026-10-09 (Claude Code, browser acceptance).** 24/24 scripted
  checks in both the Vite development server and the production build, with
  persisted receipts and events reconciling exactly and no automatic
  resubmission. Three defects, none of which sent or duplicated a write:
  - F1 (Medium): another tab's unresolved operation was reported as a browser
    storage failure and blocked keyed decisions on every unit.
  - F2 (Low): a rejection arriving after leaving the page left the operation
    "unresolved".
  - F3 (Low): keyed buttons stayed silently disabled after storage recovered.

  ([report](../validation/FLH-030-idempotency-browser-acceptance.md))
- **FLH-031, 2026-10-09 (Codex, author verification — explicitly not
  independent review).** The contract held. It found three defects in the
  evidence and harnesses rather than in the product: an inaccurate toolchain
  claim in the FLH-029 response-loss evidence, an invalid generated Compose image
  name, and a proxy that dropped duplicate header multiplicity
  ([report](../validation/FLH-031-idempotency-contract-verification.md)).
- **FLH-032 (Claude Code; undated, worked in parallel with FLH-033 per that
  report).** A frontend-only fix of F1–F3:
  - F1: a per-unit "another operation" message instead of a page-wide storage
    failure;
  - F2: rejection cleanup that runs even after leaving the page;
  - F3: an explicit **Recheck browser storage** action.

  207 frontend tests passed (nine added), with mutation checks showing the
  tests fail without the fixes, and real-browser runs passed in development and
  production builds ([plan](../plans/FLH-032-annotation-recovery.md),
  [report](../validation/FLH-032-annotation-recovery.md)).
- **FLH-033, 2026-10-09 (Codex).** Corrected the FLH-031 findings in the
  harnesses and evidence (compiler attribution, Compose names, header
  multiplicity) without production changes
  ([plan](../plans/FLH-033-validation-harness.md),
  [report](../validation/FLH-033-validation-harness.md)).

## Current behaviour and limits

Keyed DISTINCT and relation writes are idempotent per database; unkeyed
requests behave as before. Not provided: multi-tab locking, receipt expiry or
cancellation, and keys for the other annotation operations (SAME, reassignment,
INVALID and restore, concept creation, preferred unit), which FLH-029 left out
of scope; FLH-028 documents how far reads can reconcile those. Restoring an older
backup can lose newer receipts.
