# FLH-028 — Independent annotation response-loss verification

Owner: NAS Codex, supplied `flh-nas-codex` working tree; actual pwd reported in
chat. Requested branch label: `test/flh-028-review-response-loss`. Read current
`AGENTS.md`, annotation transport/service/repository/projection code and the
existing isolated native launcher. No Git/GitHub command, production patch or
FLH-027 frontend modification. Date: 2026-10-08. Status: complete, stopped for
review. FLH-027 is not awaited; no claim of its acceptance is made.

## Exact owned and modified paths

Only these new files were created:

- `scripts/validation/flh028/reproduce.py`
- `scripts/validation/flh028/proxy.py`
- `scripts/validation/flh028/test_proxy.py`
- `scripts/validation/flh028/README.md`
- `docs/validation/FLH-028-review-response-loss.md`

The launcher/provider in `scripts/validation/flh026/` are reused read-only.
All response-loss controls and investigation assertions are new and independent
of that harness's workflow assertions. No shared README, AGENTS, configuration,
dependency, frontend or production files are edited. `README.zh-CN.md` exists.
README-owner handoff: if adding a validation link to shared documentation, add
the corresponding English/Simplified Chinese link to this task's usage document.

## Executed commands and results

```sh
python3 -B scripts/validation/flh028/test_proxy.py
python3 -B scripts/validation/flh028/reproduce.py --report /tmp/flh028-response-loss-verified.json
```

Both completed with exit 0. The proxy suite passed **5 tests**: never forward,
drop only after upstream commit, reconciliation GET before delayed POST, refusal
to overwrite an active job, and cleanup of a job armed but never received.
The final application investigation passed **104 cases**:

| Scenario | Cases | Expected | Actual |
| --- | --- | --- | --- |
| Request never forwarded | 22 | Client gets no response; GET/data unchanged | PASS |
| Commit, drop response | 22 | Client gets no response; GET confirms desired state; data changes | PASS |
| Delay original while GET completes | 22 | Client gets no response; GET reports baseline; later write commits | PASS |
| Desired state preexists, new request never forwarded | 22 | GET matches desired state even though this request did not commit | PASS |
| Explicit DISTINCT/relation submissions after response loss | 8 | Three persisted event IDs, one effective pair/type | PASS |
| Existing pair confirmed while duplicate original remains delayed | 8 | GET matches old pair; another event appends after GET completion | PASS |

The 11 operations are SAME, reassign SAME, reject membership, INVALID, restore,
new concept with seed SAME, preferred unit, DISTINCT, BROADER, NARROWER and
RELATED. Each scenario is repeated through root and `/api` routes, using fresh
entry/unit/concept fixtures. All 104 lost requests actually produced
`RemoteDisconnected`, with no client-visible HTTP status, headers or response
body. Successful upstream statuses were 201 for SAME/new concept/DISTINCT/
relations and 200 for reassignment/reject/INVALID/restore/preferred unit.

Full before/reconciliation/final JSON payloads, captured upstream results,
ordering timestamps, event IDs, provider counters, build output, source hashes
and cleanup are retained in the external report. `never` cases compare every
SQLite table unchanged. Annotation outcomes never increment provider counters;
fixture setup accounts for exactly 82 local extractions and zero analyzer calls.
No paid or external provider is contacted. Captures import valid synthetic
analyses; extraction uses the deterministic counted fixture only.

### Concrete persisted-event evidence from the final run

These are actual IDs in the isolated database, not prescribed stable IDs for
future source revisions:

| `/api` explicit-repeat operation | Unit / Concept | Stored IDs after lost response + two explicit submissions | Effective ID | Supersession pointers |
| --- | --- | --- | --- | --- |
| DISTINCT | 75 / 153 | 10, 11, 12 | 12 | No relation back-pointers; independent DISTINCT rows |
| BROADER | 77 / 157 | 72, 73, 74 | 74 | null, 72, 73 |
| NARROWER | 79 / 161 | 77, 78, 79 | 79 | null, 77, 78 |
| RELATED | 81 / 165 | 82, 83, 84 | 84 | null, 82, 83 |

Every historical event's full response payload remains unchanged, and all IDs
are present in its physical table. Inspector and Dataset identify the newest
one. Relation repeats append superseding events rather than mutating old rows;
all three relation event IDs remain in history. DISTINCT repeats append new
negative-pair rows; effective projection selects the latest per concept.
Neither operation grants SAME membership or changes INVALID state.

For the delayed existing DISTINCT pair, unit 76 already had event 13. The
reconciliation GETs completed at monotonic nanosecond `3425874323740275` while
the original duplicate had not been forwarded. Forwarding began only after
release at `3425874326058546`; event 14 then committed. Thus a matching pair
read is compatible with an unresolved original request that will later append
another event. Timestamps are only ordering evidence within this run.

The first exploration passed 74 cases, and the expanded exploration passed 104.
The final 104-case rerun additionally asserts unchanged historical payloads,
exact relation supersession chains and newest Dataset event IDs. No failing
application behavior was silently patched to obtain a pass.

## Authoritative reconciliation reads

All paths also work under `/api` in packaged HTTP wiring.

| Operation | Reads establishing current state | What they cannot establish |
| --- | --- | --- |
| SAME / reassignment | `GET /knowledge-units/{id}/concept-membership`: current concept and link ID; effective annotation confirms authority | Whether this client request produced that link; old accepted SAME history is not current authority |
| Membership rejection | Membership GET confirms null; concept detail provides rejection/supersession history | Null membership alone cannot distinguish never having membership from this request clearing it |
| INVALID / restore | `GET /knowledge-units/{id}/invalid`: effective boolean plus append-only judgment history; membership/effective annotation confirm resulting authority | Boolean alone does not identify a request; restore does not reinstate a previous SAME |
| New concept + seed SAME | `GET /concepts` matches full normalized identity; detail and seed-unit membership confirm durable concept and current seed link | Signature/identity existence does not attribute creation to this request or guarantee a past seed link is still current |
| Preferred unit | `GET /concepts/{id}` exposes `preferred_unit_id` | No client request receipt or distinct preferred-selection event ID |
| DISTINCT | `GET /knowledge-units/{id}/concept-distinctions`: full negative-pair history; effective annotation confirms the latest effective pair | Pair presence, even with a new event ID, is not a general request receipt without a causal client token |
| BROADER / NARROWER / RELATED | `GET /concepts/{id}` supplies historical links filtered by unit/type; effective annotation establishes current unsuperseded relation | History includes accepted but superseded events; there is no dedicated unit relation-history GET or client operation identifier |

`GET /knowledge-units/{id}/effective-annotation` is the existing authoritative
effective annotation projection. Dataset is derived/current-extraction-only:
it is suitable for current-label projection checks, not general historical
request reconciliation. The harness verifies it for repeated current-unit
annotations without treating history reconstruction as current authority.

GETs are snapshots, not ordering fences for pending mutations. Separate GETs
are not one atomic multi-endpoint snapshot. A read which does not yet show a
change cannot prove the request failed, was canceled or will never commit.
A read matching desired state can justify saying **state confirmed**; it cannot
justify saying **this request committed**. The 22 preexisting-state counterexamples
prove this distinction directly, without needing another live writer.

Event IDs and prior baselines can support inference under a known single writer,
but concurrent writers or later corrections defeat general attribution. In
this experiment causality is established by the proxy's captured response and
controlled forwarding, an oracle the response-losing client does not have.
Request headers resembling a browser exercise the real backend boundary;
no browser cancellation or DOM behavior is inferred from them.

## Backend gap and smallest proposed contract — not implemented

Affected locations in the tested source:

- `internal/transport/http/concept.go:309` and `:314`: relation/DISTINCT request
  bodies contain only target/type, without a client operation token. Their
  handlers at `:726` and `:644` expose no durable operation receipt.
- `internal/storage/sqlite/concept_repository.go:924` (`RecordDistinction`): each
  successful submission inserts another DISTINCT row.
- `internal/storage/sqlite/concept_repository.go:1029` (`LinkRelation`): each
  successful repeat inserts another immutable event and supersedes its prior
  pair/type event.
- `internal/domain/effective_annotation.go:147` and `:177`: latest-DISTINCT
  selection and relation supersession hide older repeats from current projections
  while correctly retaining history. Projection presence is not deduplication
  of HTTP submissions.

Concrete failure scenario: an annotation POST commits but its response is lost;
the client explicitly submits the same unresolved action again. DISTINCT or a
relation produces another immutable event. Alternatively, a reconciliation GET
completes before a delayed original mutation; treating the old read as a failed
write and submitting again can produce multiple events. Current APIs cannot
resolve whether a particular client operation committed, nor guarantee a
single append for that operation. This is a receipt/idempotency contract gap,
not evidence that append-only history or its current projections are incorrect.

Smallest proposed backend addition for the two append-every-time endpoints:

1. Accept an optional client-generated UUID `Idempotency-Key` for DISTINCT and
   non-SAME relation POSTs. Existing requests without it preserve current
   append-per-submission behavior. A new deliberate human annotation uses a new
   key; repeating the same unresolved operation reuses its original key.
2. Store a durable unique receipt, validated-payload fingerprint and original
   event/result **atomically with the event**. Fingerprint method, canonical
   route/unit, target and relation. Same key/same fingerprint returns the original
   status/body/event ID without an additional write, optionally with
   `Idempotency-Replayed: true`. Reusing a key for different semantics returns
   409 with no event. Concurrent arrivals with the same key must append at most
   one event, enforced transactionally, not by a client-side check.
3. Expose `GET /annotation-operations/{operation_id}` returning 200 with a durable
   committed receipt (operation ID and event ID). Unknown key is 404 **unknown**,
   not proof the original request cannot still arrive. That uncertainty is safe
   only because another submission with the **same** key cannot create a second
   event. A mere `X-Request-ID` in logs is insufficient.

This proposal does not add authentication, automatic retries, provider behavior
or label rewriting. A terminal *not committed/canceled* guarantee would require
an additional reservation/cancellation fence and is not claimed by this minimal
contract. Existing state-idempotent SAME/reassign/INVALID/restore/rejection APIs
can continue using state confirmation with honest wording; universal attribution
would require extending receipts to those operations too.

Suggested contract verification if separately authorized: commit-and-drop then
same-key submission preserves one event/ID; delayed concurrent same-key arrivals
produce one append; same-key/different payload conflicts without a write; a new
key creates a new explicit event; receipts survive process replacement. No part
of that proposal was implemented in this task.

## Source scope, cleanup and limits

The final report records 145 backend source/module/migration files. Canonical
source inventory digest (SHA-256 of sorted-key JSON) is
`e16352269dadabeda4b187a87149e12563c94681d676eb8cfd4edc7d3ddefe9a`.
Every FLH-028 Python file and reused FLH-026 Python file matches its report hash.
Native compiler was `go1.27.1-X:nodwarf5 linux/amd64`; `go.mod` requires `1.26.5`.
`go mod verify` and the isolated server build passed. A Go-1.26.5-specific rerun,
container mode, full Go unit/vet suite and real-browser/DOM checks were **NOT RUN
for FLH-028**. No prerequisite prevented the native investigation or proxy tests.

Final resources belonged to `/tmp/flh026-y98b03cz` (inherited launcher naming).
Cleanup released/drained jobs, closed the proxy/thread, stopped the owned
server/provider, and removed the entire private run; evidence reports
`cleanup_errors=[]`, `temporary_directory_removed=true`. The retained report
is external to the repository. No existing service, daily database, secret or
paid API was used. SIGKILL/power loss cannot promise cleanup.

When integrated FLH-027 code is supplied, this harness can be rerun against its
backend snapshot and its proxy controls reused by frontend acceptance. It does
not execute FLH-027 client code and cannot establish UI handling of unknown
outcomes, disablement, notices, retries or DOM reconciliation. The frontend owner
must supply that evidence independently. No shared file ownership is transferred.

Usage: [`scripts/validation/flh028/README.md`](../../scripts/validation/flh028/README.md).
Investigation complete; editing stopped for human review.
