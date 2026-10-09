# FLH-030 — Browser acceptance of annotation idempotency and recovery

- Branch under review: `test/flh-030-idempotency-browser-acceptance`
- Date: 2026-10-09
- Reviewer: Claude Code (verification only; no production file or shared document changed)
- Subject: the delivered FLH-029 contract (`docs/plans/FLH-029-annotation-idempotency.md`)
  and its implementation in the working tree. Delivery is not treated as merge
  or acceptance.
- Result: **24 / 24 scripted checks passed in both Vite dev (StrictMode) and the
  production build (`-web-dir`); persisted receipts and events reconcile exactly;
  no automatic resubmission observed. Three defects found (one Medium, two Low),
  none of which sends or duplicates a write, plus four observations.**

## Prerequisite check

Working directory reported: `/Users/lowx/projects/FLH` (repository at
`french-learning-hub/`). AGENTS.md read. No Git command was run.

| FLH-029 artifact | Present |
| --- | --- |
| Contract `docs/plans/FLH-029-annotation-idempotency.md` | yes |
| Validation `docs/validation/FLH-029-annotation-idempotency.md` (states real-browser verification NOT RUN) | yes |
| `migrations/009_annotation_operations.sql` | yes |
| `internal/{domain,application,storage/sqlite,transport/http}/annotation_operation.go` | yes |
| `web/src/pages/annotationOperation.ts`, keyed paths in `ReviewQueue.tsx`, `reviewOutcome.ts`, `api/client.ts` | yes |

The implementation is present, so all dependent checks were run.

## Environment and method

| Item | Value |
| --- | --- |
| DEV | Vite 5.4.21 dev server (`/src/main.tsx` loaded, `<StrictMode>` active) on `localhost:5330`, proxying `/api` to a backend on `:18931` with `HTTP_TRUSTED_ORIGINS=http://localhost:5330` |
| PROD | `cmd/server -web-dir <built dist>` on `:18932`; workbench at `/`, API at `/api` |
| Builds | `go build ./cmd/server` (go1.24.5); `npm run build` of a scratch copy of current `web/` (sources and lockfile verified identical with `diff -rq`) |
| Data | Fresh scratch SQLite per environment, seeded through the public API: 4 synthetic records, rule-based analyses, one extraction each from a local stub provider (12 units), 3 concepts `alpha`=1, `beta`=2, `gamma`=3 |
| Provider | Local stub on `127.0.0.1:18930`; `OPENAI_API_KEY=sk-fake-local`. No paid call. |
| `.env` / daily DB | Not read / not touched; servers ran with a scratch working directory |
| Browser | Google Chrome 154.0.8037.98 headless, fresh profile, `playwright-core` 1.49.1 in a scratch directory (not a project dependency) |
| Harness | `scripts/validation/flh030/` (see its README); the suite was run twice from fresh databases, the second time from the committed copies |

Fault injection is browser-level and labelled `[inj]`:

- **Lost response:** the request is forwarded and commits, then the browser connection is reset.
- **Never arrives:** the browser connection is reset before forwarding.
- **Delay-drop:** the browser connection is reset immediately. The harness later delivers the identical captured request (same URL, Origin, `Idempotency-Key` and body), standing in for an original write that commits late.
- **Hold:** the request is kept inside the browser until the step releases it.

Storage failure is a synthetic override of `Storage.prototype.setItem` for the operation key only.

**Evidence types.** UI evidence is DOM text, roles and button states observed in Chrome. Persisted evidence comes from backend reads: `GET /knowledge-units/{id}/concept-distinctions`, `GET /concepts/{id}` links, `GET /knowledge-units/{id}/effective-annotation` and `GET /annotation-operations/{key}`, plus read-only `sqlite3` queries. Request evidence is the method, `Idempotency-Key`, body and response headers of every browser POST. Step H1 is **HTTP-only** and labelled as such.

## Coverage matrix (DEV and PROD results identical)

| # | Requirement | Steps | DEV | PROD |
| --- | --- | --- | --- | --- |
| 1 | Normal submission; history/current projections | N1, N2 | PASS | PASS |
| 2 | Server commits, response lost | L-DISTINCT, L-BROADER | PASS | PASS |
| 3 | Request never reaches server | U1, X1 (`[inj 500]`) | PASS | PASS |
| 4 | Receipt lookup before delayed original commits | D1, D2, D3 | PASS | PASS |
| 5 | Explicit retry preserves key and payload | U4, D2, D3, X1 | PASS | PASS |
| 6 | Reload preserves unresolved identity and recovery | U3, S3 | PASS | PASS |
| 7 | Deliberate new operation gets new identity | N1, X2 | PASS | PASS |
| 8 | Editing payload / changing units cannot reuse a key | U2, X2 | PASS | PASS |
| 9 | Browser storage failure reported honestly | S1, S2, S3; probe P2 | PASS (S1-S3); **F1, F3** | same |
| 10 | Navigating away prevents stale results changing another unit | V1, V2, V3 | PASS; **F2** | same |
| 11 | Historical receipt distinct from current state | D1; probe P1 | PASS | PASS |
| 12 | Record/history/pin/reset/review/inspector navigation | R1, N2 | PASS | PASS |
| — | Every browser DISTINCT/relation POST keyed | K1 | PASS (24 POSTs, 18 keys) | PASS |
| — | Console errors only from injected faults | C1 | PASS (22) | PASS (22) |
| — | Contract probes over HTTP | H1 (HTTP-only) | PASS | PASS |

## Results by requirement

### 1. Normal submission (N1, N2)

Unit 1 received DISTINCT→alpha, BROADER→beta, NARROWER→gamma and RELATED→alpha.

**Requests.**
- Each click produced exactly one POST.
- Each POST carried a fresh UUIDv4 `Idempotency-Key`.
- Each response was 201, echoed the key, and had no `Idempotency-Replayed` header.
- The four keys were distinct.

**UI.**
- The success text was `Recorded <ACTION> event #n for concept #c (historical request result; current authority refreshed separately).`
- It was followed by `Unit #1's membership and exact matches re-read from the server.`

**Persisted state.**
- Each key's receipt is `state: committed`, `status: 201`, with `result.id` equal to the UI event number.
- Counts were DISTINCT/BROADER/NARROWER/RELATED = 1/1/1/1.
- The effective annotation was `status unresolved, distinctions [1], relations [related:1, broader:2, narrower:3]`.
- Saved operations were empty.

**History panel.** It listed `related status=accepted src=human link #3 unit 1 concept 1`.

### 2. Committed, response lost (L-DISTINCT, L-BROADER)

| | Expected | Actual |
| --- | --- | --- |
| UI first | Unknown outcome, not "failed" | `Outcome unknown. No committed result was confirmed for DISTINCT from concept #2 on unit #2, so its outcome is unknown. It was not sent again.` |
| Reconciliation | Read-only receipt lookup finds it | `Found on the server: This request committed event #2. This historical result is separate from current authority. DISTINCT from concept #2 is stored.` |
| Writes | 1 POST, 1 event, receipt 200 | 1 POST, 1 event, receipt 200, saved operation cleared, decisions re-enabled |

BROADER behaved the same way (event #4).

### 3. Never arrives (U1) and keyed 5xx (X1)

**U1 (RELATED→alpha on unit 3).** The keyed panel read `Receipt unknown. The original request may still commit; retry only with its saved key and payload. Saved operation <key>. Editing the selection does not change this saved payload.`, with `Check receipt` and `Retry saved operation`.
- There was **no** "Allow another decision" control.
- SAME, NEW CONCEPT, all relations, DISTINCT and INVALID were disabled.
- After waiting 3 s there was still exactly one POST with the key: no automatic resubmission.
- Receipt 404, 0 events.
- Saved operation: `{"kind":"relation","unitId":3,"conceptId":1,"relation":"related","operationId":<key>}`.

**X1 (`[inj 500]` NARROWER).** The 500 was classified as unknown, not rejected (`...so its outcome is unknown. It was not sent again.`). An explicit retry with the same key committed one event.

### 4. Receipt lookup before the delayed original commits (D1-D3)

| Step | Expected | Actual |
| --- | --- | --- |
| D1, before commit | Lookup says unknown, never canceled | Two lookups → 404 → `Receipt unknown. The original request may still commit…`; backend 0 events |
| D1, after delayed original (201) | Lookup finds it | `Found on the server: This request committed event #6…`; 1 browser POST in total |
| D2: original commits, then user retries | Replay, no second event | Retry → 201 with `Idempotency-Replayed: true`. The UI shows the original event #8. 1 BROADER event. |
| D3: retry commits, then the late original arrives | Late original replayed | Late original → 201 replayed=true, same event #9. 1 NARROWER event. |

### 5. Explicit retry preserves key and payload (U4)

After a reload, beta was selected in place of the original alpha, then `Retry saved operation` was clicked.

**Request.**
- One POST with the original key and body `{"concept_id":1,"relation":"related"}` → 201 (first commit, not replayed).

**Persisted state.**
- RELATED→alpha 1, RELATED→beta 0.
- Saved operation cleared.

### 6. Reload (U3, S3)

After `page.reload()`, unit 1 showed no panel. Unit 3 showed `Restored unresolved operation. Check its receipt or explicitly retry the saved payload.` with the **same** key, and all decisions blocked.

`Check receipt` → 404 → unknown. The reload sent no POST.

### 7. New deliberate operation, new key (N1, X2)

All four N1 keys were distinct.

In X2, unit 12 was left unresolved under key A. A deliberate RELATED on unit 2 then used a new key B ≠ A, and storage still held only unit 12's operation. Keys are random per run; for example `ff44ca2f…` and `2e2501d8…`.

### 8. Editing payload or changing units (U2, X2)

With unit 3 unresolved, selecting gamma left every relation/DISTINCT button disabled, and a forced click on BROADER sent nothing.

Unit 4 showed no recovery panel. Back on unit 3, the panel named the original key, and storage still held concept #1 / related. Retry used the saved payload (U4), never the current selection.

### 9. Browser storage failure

| Case | Expected | Actual |
| --- | --- | --- |
| S1 `setItem` throws before send | Honest alert, nothing sent | `Browser storage failed. Nothing was sent; reload persistence cannot be guaranteed. Restore storage before submitting an annotation.`; 0 POSTs, 0 events. See **F3** for the state after storage recovers. |
| S2 corrupt `{not json` on load | Honest alert, keyed writes blocked | `Browser storage is unavailable or invalid. Unresolved identity cannot be recovered across reload; new keyed annotations are blocked.`; RELATED click sent 0; value left untouched; clearing it and reloading removed the alert |
| S3 cleanup fails after commit | Honest message, safe recovery | `Request committed, but browser storage cleanup failed. Reload may show it again; check the receipt.`; after reload the restored panel → `Check receipt` → found → cleared; 1 POST, 1 event |
| P2 two tabs, same unit | Accurate reason, nothing sent | Nothing sent, but the reason given was **`Browser storage failed…`** although storage worked. See **F1**. |

### 10. Navigating away (V1-V3)

- **V1:** DISTINCT on unit 7 was held in flight, the user switched to Annotation Inspector, and the request was released and committed.
  - Backend: 1 event; the finished request cleared storage.
  - Back on Concept Review, unit 1 was shown with no outcome or panel for unit 7.
- **V2:** the user switched away and back while the request was still held, then it committed.
  - Unit 1 showed nothing leaked.
  - Unit 8 later showed a restored "unresolved" panel. That is stale but safe: `Check receipt` → found → cleared, with 1 event.
- **V3** (`[inj 422]` rejection delivered while away): see **F2**.

### 11. Historical receipt vs current state (D1, P1)

**D1.** After the delayed RELATED→gamma committed, the harness posted an unkeyed BROADER→gamma (current relations for gamma `[broader, related]`). The receipt still returned the historical RELATED event #6, and the UI said `This historical result is separate from current authority.`

**P1** (stronger: current state really differs). After the delayed RELATED commit, the harness marked unit 6 INVALID over HTTP:
- **Current state:** effective status `invalid`, relations `[]`, not reviewable.
- **Receipt:** still `relation/related result #12`.
- **UI wording:** the receipt was reported only as historical: `This request committed event #12. This historical result is separate from current authority.` It never claimed a current relation. Observation **O2** notes a pre-existing limitation.

### 12. Navigation regression (R1, N2)

On record #4, the pin went to v1 (backend `pinned`), and `Resume automatic latest selection` restored `automatic`.

Record-scoped review opened unit #10, and `← Back to record #4` worked. `Inspect unit #11` worked, and so did the return. The Annotation Inspector, Experiment Dashboard and Concept Review tabs all worked. The history panel was covered in N2.

### HTTP-only contract probes (H1, not UI evidence)

Against unit 1's committed DISTINCT key:
- The same key with a different payload → 409.
- The same payload with the key upper-cased → 201 with `Idempotency-Replayed: true`, and the response key normalized to lowercase.
- `not-a-uuid` → 400.

The DISTINCT count was unchanged (1→1).

## Persisted reconciliation (final databases, second run)

| | DEV | PROD |
| --- | --- | --- |
| Receipts (`annotation_operations`) | 19 | 19 |
| DISTINCT events | 8 | 8 |
| BROADER/NARROWER/RELATED events | 12 (11 keyed + 1 deliberate unkeyed in D1) | 12 |
| Receipts without a matching event (`result` ID, unit, concept, relation) | 0 | 0 |
| Keyed events without a receipt | 0 | 0 |
| Duplicate (unit, concept) DISTINCT or (unit, concept, relation) events | 0 | 0 |
| Unit 9 (rejected in V3) events / receipt | 0 / 404 | 0 / 404 |

How the 19 receipts break down:
- **17 from the suite.** There were 18 browser keys; the key rejected in V3 never reached the server.
- **2 from the probes:** P1 and P2's tab A.

There were no automatic resubmissions. Every key had one POST, plus one per explicit `Retry saved operation` click (U4, D2, D3, X1, X2, X3; P2 cleanup).

## Defects

### F1 (Medium, honesty; no data risk): an unresolved operation in another tab is reported as "Browser storage failed"

**Reproduce** (probe P2, both environments):
1. Open the workbench in tabs A and B.
2. In A, on unit 5, select beta and click DISTINCT with the request dropped. A shows the keyed unknown panel.
3. In B (loaded before step 2), go to unit 5, select gamma and click RELATED.

**Expected.** Nothing is sent, and B says another unresolved operation exists for this unit (or offers to reload).

**Actual.**
- B shows `Browser storage failed. Nothing was sent; reload persistence cannot be guaranteed. Restore storage before submitting an annotation.` while storage is working.
- 0 POSTs, and storage keeps only A's operation.
- B then also refuses keyed decisions on **other** units (NARROWER on another unit sent 0) until reload. A's retry later committed normally.

**Cause (reading only).**
- `saveOperation` throws distinct errors: `Saved operation payload changed…` and `Another operation for this unit is unresolved…` (`web/src/pages/annotationOperation.ts:34,36`).
- The caller maps every `saveOperation` error to the storage-failure text and sets the page-wide `storageFailure` (`web/src/pages/ReviewQueue.tsx:384-388`).

FLH-029 lists "no multi-tab lock" as a limit. The safety holds, but the reported cause is wrong.

### F2 (Low): a definite rejection that arrives after leaving Concept Review leaves the operation "unresolved"

**Reproduce** (V3):
1. On unit 9, select gamma and click DISTINCT, holding the request in flight.
2. Click Annotation Inspector.
3. Let the request receive a definite rejection (`[inj 422]`; the server never saw it).
4. Return to Concept Review and go to unit 9.

**Expected.** As when the page is mounted, a definite rejection clears the saved operation, and the unit is not presented as unresolved.

**Actual.**
- Storage keeps `{"kind":"distinct","unitId":9,"conceptId":3,…}`.
- Unit 9 shows `Restored unresolved operation…` with all decisions blocked and no "allow another decision" path.
- `Check receipt` can only ever return 404.
- The only exit is `Retry saved operation`, which resends a payload the server rejected.
- If the rejection is genuine (for example a 409 contradiction from a concurrent change), the retry is rejected again and the unit stays blocked in this browser.

**Cause (reading only).**
- In the error path, `if (!mounted.current) return;` (`ReviewQueue.tsx:428`) runs before the definite-rejection `clearOperation` (`ReviewQueue.tsx:448-450`).
- The success path clears storage before its mounted check (`ReviewQueue.tsx:414-419`).

Not reproduced with a real server rejection: the reachable real case (DISTINCT against the unit's current SAME concept) also removes the unit from the queue. The record then sits invisibly in storage, which is the documented "units no longer reviewable" limit.

### F3 (Low): after a save-time storage failure, keyed buttons stay enabled but do nothing, even after storage recovers

**Reproduce** (S1):
1. Make `localStorage.setItem` throw for the operation key, then click DISTINCT. The honest alert appears and nothing is sent.
2. Restore storage, then click BROADER.

**Expected.** Either the keyed buttons are disabled, or the page says a reload is required. The alert says "Restore storage before submitting", which implies restoring is enough.

**Actual.**
- BROADER looks enabled.
- The click sends nothing and shows no new message.
- Keyed writes stay blocked until reload. SAME/INVALID/NEW CONCEPT (unkeyed) stay usable.

**Cause (reading only).** A silent `return` when `storageFailure` is set (`ReviewQueue.tsx:377`). `ResolutionActions` does not receive the flag.

## Observations (not defects)

- **O1:** A failed receipt lookup (X3, `[inj]` reset on `GET /annotation-operations/*`) shows the raw `no response from the server (network error)` inside the keyed panel. The heading still says the outcome is unknown and decisions stay blocked, but there is no "Could not check the server…" framing like the unkeyed panel has. The next lookup and the retry worked (1 event).
- **O2:** In P1 the unit was made INVALID by another client. Concept Review kept showing it, and the membership panel only says `unresolved (or was explicitly marked invalid)` until the queue is reloaded. This is pre-existing queue staleness, not FLH-029. The receipt wording itself stayed historical.
- **O3:** A corrupt saved-operations value (S2) has no in-UI reset. The user must clear site storage. This matches the FLH-029 design.
- **O4 (storage, not browser-visible):** `annotation_operations.result` is persisted as Go-default JSON field names (`{"ID":…,"Input":…,"Distinction":{"ID":…,"UnitID":…},"Link":…}`), so the stored receipt format is coupled to untagged Go struct field names. The HTTP receipt DTO is correct.

## Limitations

- Headless Chrome on macOS only. Not tested in Firefox, Safari, a visible window or on mobile.
- Faults are injected in the browser layer and are not real network partitions. The delay-drop "late original" is delivered by the harness with the browser's exact URL, Origin, key and body; it is not a request the browser itself held open.
- Storage failure is simulated by overriding `setItem`. A real quota or private-mode failure, or a `getItem` exception, was not reproduced, except that S2 covers an unreadable value on load.
- Two-tab behavior was probed once (P2). Concurrent multi-tab races beyond that were not explored.
- The servers inherited the shell environment, with every provider variable set explicitly. `.env` was not loaded because the working directory was a scratch directory.
- Supporting automated checks: `go test ./...` passed (9 packages ok). In the scratch copy, `vitest --run` passed 16 files and 198 tests. These are not part of the browser evidence.

## Commands executed

```sh
go -C <repo> build -o <scratch>/server ./cmd/server
npm --prefix <scratch>/web run build          # scratch copy of web/, lockfile identical
sh scripts/validation/flh030/up.sh <scratch-work> <scratch>/web
python3 -B scripts/validation/flh030/seed.py http://127.0.0.1:18931
python3 -B scripts/validation/flh030/seed.py http://127.0.0.1:18932
node <pw>/acceptance.mjs http://localhost:5330  http://127.0.0.1:18931 <shots> dev
node <pw>/acceptance.mjs http://localhost:18932 http://127.0.0.1:18932 <shots> prod
SHOTS=<shots> LABEL=dev  node <pw>/probes.mjs http://localhost:5330  http://127.0.0.1:18931 6 5
SHOTS=<shots> LABEL=prod node <pw>/probes.mjs http://localhost:18932 http://127.0.0.1:18932 6 5
sqlite3 -readonly <scratch-work>/{dev,prod}.db '<reconciliation queries>'
sh scripts/validation/flh030/down.sh
go -C <repo> test ./...
npm --prefix <scratch>/web test -- --run
```

The screenshots are in the scratch directory, not committed:
- `{dev,prod}-never-arrived-keyed-panel`
- `-restored-after-reload`
- `-lost-response-found`
- `-delayed-commit-found`
- `-rejected-while-away`
- `-storage-failed`
- `-historical-vs-invalid`
- `-two-tabs`

## Files created

- `docs/validation/FLH-030-idempotency-browser-acceptance.md`
- `scripts/validation/flh030/README.md`
- `scripts/validation/flh030/up.sh`, `down.sh`, `stub.py`, `seed.py`
- `scripts/validation/flh030/acceptance.mjs`, `probes.mjs`
