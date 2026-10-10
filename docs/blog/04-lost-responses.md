# When the response never arrives: idempotent annotation writes

> Retrospective draft, prepared 2026-10-10. Not yet published. The reports cited
> here are dated 2026-10-08 and 2026-10-09, except where noted as undated.

Every decision in the Concept Review workbench is an HTTP POST. Usually the
browser sends it, the server commits it, and the response comes back. The
interesting case is when the response does not come back: the connection drops,
the laptop sleeps, a proxy times out. Did the write happen?

## Why "just read the current state" is not enough

The obvious recovery is to re-read the unit and see whether the decision is
there. An independent investigation (FLH-028, 2026-10-08) tested that idea
before anything was built. A small controllable proxy produced three kinds of
loss across all eleven annotation operations, on both root and `/api` routes:

- requests that were never forwarded;
- responses dropped after the server had committed;
- original requests held back while a reconciliation read went through first.

That made 104 cases, and the application behaved as its code implied in all of
them.

The useful output was a table of what each read can and cannot prove:

- A membership read shows which Concept a unit currently belongs to. It cannot
  show whether *this* request put it there.
- A null membership cannot distinguish "never had one" from "this request
  cleared it".
- For DISTINCT and BROADER/NARROWER/RELATED, each submission appends an event.
  A read can show that the desired pair exists while the delayed original is
  still in flight, and that original will then append another event after the
  read.

So for the appending operations, reading state cannot safely decide whether to
retry.

## The design: a key, a receipt, and no automatic retry

The fix (FLH-029) is narrow on purpose. It covers only DISTINCT and
BROADER/NARROWER/RELATED, the operations whose repeats append.

- The client may send an `Idempotency-Key`: one canonical UUID, scoped globally
  to the database.
- The server stores a **receipt** in the same SQLite transaction as the
  annotation event (migration 009). A writer lock is taken before the receipt
  lookup.
- An equivalent replay returns the original `201` result without re-evaluating
  current state. The same key with a different payload or action is a `409`
  with no write.
- `GET /annotation-operations/{id}` returns the committed receipt. A `404` means
  *unknown*: it does not mean "cancelled", and it does not make it safe to
  resend under a new key.
- Requests without a key behave exactly as before.

In the browser, Concept Review saves a minimal, versioned description of the
operation (key, action, target ids, relation) *before* sending. After a reload,
unresolved operations reappear without anything being written. The reviewer
can check the receipt or explicitly retry the saved operation with the same key
and payload, even if they have since changed the selection. Nothing retries
automatically. Receipt attribution and the refresh of current state are kept
separate, so a commit that is confirmed but followed by a failed refresh is
reported as exactly that.

## Verification, and what it caught

The author's checks passed: targeted and full Go tests, `make verify`, and the
frontend suite. No real browser was available in that environment, and the
report says so.

A browser acceptance run (FLH-030, 2026-10-09) followed in both the development
server and the production build. All 24 scripted checks passed, persisted
receipts matched events exactly, and nothing was resubmitted automatically. It
still found three defects, none of which sent or duplicated a write:

- an unresolved operation saved by *another tab* was reported as "browser
  storage failed", and keyed decisions were blocked on every unit;
- a rejection that arrived after the reviewer had left the page left the
  operation marked unresolved;
- after a storage failure, keyed buttons stayed enabled but silently did
  nothing, even once storage had recovered.

A frontend-only follow-up (FLH-032, undated) fixed all three:

- a per-unit "another unresolved operation" message;
- rejection cleanup that runs even after unmount;
- an explicit **Recheck browser storage** action.

New tests were shown to fail without the fixes, and the browser runs passed
again in both builds.

Separately, the original author re-verified the contract (FLH-031,
2026-10-09). The report labels itself as author verification, not independent
review. It found problems in the *evidence* rather than the product: an
inaccurate toolchain attribution in an earlier report, a Compose image name
that could be invalid, and a test proxy that collapsed duplicate headers. These
were corrected in the harnesses (FLH-033).

## Limits that remain

There is no multi-tab locking, no receipt expiry or cancellation, and no keys
for SAME, reassignment, INVALID, concept creation or preferred-unit changes;
the investigation documents how far reads can reconcile those. Receipts live in
the database, so restoring an older backup can lose newer receipts. Clearing
browser storage loses the saved recovery identity.

## Sources in the repository

- `docs/ARCHITECTURE.md` §7.5, `docs/plans/FLH-029-annotation-idempotency.md`
- `docs/history/05-annotation-idempotency.md`
- `docs/validation/FLH-028-review-response-loss.md`,
  `docs/validation/FLH-029-annotation-idempotency.md`,
  `docs/validation/FLH-030-idempotency-browser-acceptance.md`,
  `docs/validation/FLH-031-idempotency-contract-verification.md`,
  `docs/validation/FLH-032-annotation-recovery.md`,
  `docs/validation/FLH-033-validation-harness.md`
