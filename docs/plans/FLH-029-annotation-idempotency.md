# FLH-029 annotation request idempotency

NAS Codex is the single implementation writer in the supplied working directory.
Scope is DISTINCT and BROADER/NARROWER/RELATED POSTs only. Existing SAME,
INVALID, extraction, provider and batch behavior is unchanged. See the integrated
FLH-028 response-loss evidence and FLH-027 review outcome implementation.

## Exact HTTP contract

Optional `Idempotency-Key` is exactly one canonical hyphenated UUID text
(8-4-4-4-12 hexadecimal digits, case-insensitive, normalized to lowercase).
No surrounding whitespace, alternate UUID encodings or multiple values are
accepted. An explicitly empty header is invalid. Invalid keys return secret-safe
400. UUID version/variant bits are not restricted; clients generate random v4.

The key scope is global to this service database, shared across both annotation
POST endpoints, every unit/concept and root/workbench `/api` aliases. There is no
user, session or method-specific namespace, expiration or receipt deletion API.
The operation ID is the normalized key.

Normalized payload equivalence is exact typed equality of:

- action `distinct` or `relation` (derived from the endpoint);
- positive integer path unit ID and body `concept_id`;
- for relation only, exact lowercase `relation`: `broader`, `narrower`, `related`.

Those are all accepted semantic fields. DISTINCT accepts only `concept_id`;
relation accepts only `concept_id` and `relation`. No caller evidence, reason,
source, score or resolver field is accepted. JSON whitespace/object field order,
UUID case and decimal path leading zeros do not change equivalence. Relation
case/whitespace is not normalized. Unknown JSON fields and trailing documents
are rejected for keyed requests. Equivalence uses deterministic canonical typed
JSON stored in the receipt, not a probabilistic hash. Server-generated evidence
is stored in the original event/result and is never recomputed on replay.

The first successful keyed request returns the existing event DTO and HTTP 201,
plus normalized `Idempotency-Key`. Equivalent replay returns that original 201
and result, with `Idempotency-Replayed: true`, without executing the annotation
again or checking whether its historical result is still current. Different
valid operation/payload under a committed key returns 409 without writes.
Invalid semantic input returns 400, missing targets 404, annotation contradiction
409 and storage failure 500, all without receipt/event. Unkeyed callers keep
existing status/body behavior and append once per successful submission.

`GET /annotation-operations/{id}` (also `/api/...`) returns HTTP 200:

```json
{
  "schema_version": "annotation_operation_v1",
  "id": "01234567-89ab-cdef-0123-456789abcdef",
  "state": "committed",
  "request": {"action": "distinct", "unit_id": 5, "concept_id": 42},
  "status": 201,
  "result": {"id": 17, "unit_id": 5, "concept_id": 42}
}
```

`result` above is abbreviated; actual result is the full unchanged DISTINCT or
relation event DTO. The receipt attributes a historical committed request, never
current membership, effective DISTINCT or relation authority. Malformed lookup
ID is 400. Lookup 404 means **unknown**, never canceled, failed or safe to
submit with a new key: a delayed original request may still commit. Explicit
same-key/same-payload retry is safe against a second append. No cancellation,
pending reservation or terminal non-commit fence is claimed.

## Persistence and implementation

Migration allocation was inspected: 008 was latest; additive migration 009
creates `annotation_operations` with unique UUID key, canonical semantic payload,
original immutable domain result and commit timestamp. It changes no old table,
event, projection or migration. Receipt and event INSERTs share one SQLite
transaction using transaction-local existing annotation helpers. A no-row UPDATE
acquires SQLite's writer lock before receipt lookup, including independent
connections; the unique key is a second invariant. No external work occurs in
that transaction. Rollback leaves neither record. Replays perform no annotation
writes. Receipts survive process replacement and belong in normal SQLite backups.
Existing global browser Host/read and origin/write protection covers both aliases.

## Browser recovery

Each explicit in-scope decision gets a fresh key. Before sending, the workbench
stores version 1 `flh.annotation-operations.v1` in origin-local browser storage:
only key, action, unit ID, concept ID and optional relation. No credentials,
learning text, identity drafts or unrelated data. Reload restores unresolved
operations and never automatically writes. Explicit retry uses the original
saved decision, ignoring edits to current selection. Unknown keyed operations
block a new decision for that unit until receipt or response confirms commit;
other units remain independently usable. A later deliberate decision gets a new
key. Pending writes block switches; asynchronous receipt reads are scoped to unit
and request generation. A committed receipt is followed by fresh backend
effective annotation, membership and resolver reads, separately from attribution.

Storage failure/corruption blocks new keyed submissions and is reported honestly;
no claim of reload persistence is made. A write already confirmed committed stays
committed even when authority refresh fails. Cleanup failure can leave a saved
committed operation which is safely checked again on reload. Storage is not a
multi-tab locking protocol, and deleting storage/changing origin loses recovery
identity. Receipts do not authenticate callers. Operations for units no longer
reviewable remain stored; the current workbench recovery controls are available
when the unit is in the review queue.

## Verification

Targeted tests cover equivalence, cross-action/target conflicts, 12 same-key
requests, two independent SQLite pools, restart, receipt INSERT rollback,
malformed keys, lookup and historical replay. Frontend tests cover storage,
reload, explicit retry, fresh decisions, receipt attribution, unknown lookup,
stale reads, unit switching and storage errors. FLH-028 retains the unkeyed
104-case matrix and adds keyed loss/replay/concurrency/boundary/history checks.
All databases/output are temporary; all providers are local fakes. See
`docs/validation/FLH-029-annotation-idempotency.md` for actual results and limits.
