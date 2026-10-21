# FLH-091 — Unified question intake

Owner: NAS Claude Code. Continues FLH-089/090 in the same working tree; their
uncommitted changes are preserved.

**Status: implemented and validated on synthetic data only.**
- **No backend change:** no endpoint, migration or dependency changed.
- **No browser:** no browser is installed on the NAS, so browser behaviour is
  **unverified**. UI results come from jsdom component tests.
- **Not daily-use acceptance.**

## 1. Contract choice

**Endpoint:** the existing `POST /captures`, for both modes.
- **Question payload:** a plain question is sent as
  ```json
  {"schema_version":"learning_capture_v1","capture_id":"question-<uuid v4>",
   "source":"manual","original_input":"<as typed>","original_context":"<as typed>"}
  ```
  It has no `analysis` and no `discussion_summary`.
- **Why not `POST /entries`:** it has no idempotency. After a lost response it
  cannot tell "stored" from "not stored", so a retry could duplicate the
  record.
- **What the capture contract already provides:**
  - a client `capture_id` and a content fingerprint: an identical resend
    replays (`200`), different content with the same ID is refused (`409`);
  - a read-only receipt, `GET /captures/{id}` (`200` stored, `404` not stored);
  - an `unanalyzed` record when no analysis is supplied;
  - `source: "manual"`, which truthfully says the text was entered by hand.
- **Text:** both endpoints validate original input and context with the same
  entry rules. Leading and trailing whitespace is trimmed; interior spaces,
  tabs and line breaks are kept. The browser sends the text exactly as typed.
- **ID generator:** `crypto.getRandomValues` (works on plain-HTTP LAN origins,
  where `randomUUID` needs a secure context), the same approach as the FLH-029
  idempotency keys.
- **Capture JSON mode:** the existing `CaptureImport` component, unchanged.
  Imported candidate Analyses stay `unreviewed`; import never records
  acceptance.

## 2. Behaviour

| Situation | Behaviour |
|---|---|
| Default mode | **Question**. Labels are user-facing: "Your question", "Where it came from (optional)", "Save question" |
| Blank question (whitespace only), or context only | **Save** disabled; nothing sent |
| Repeated clicks | One in-flight request; the button reads "Saving…" and is disabled |
| `201` | "Saved as new record #N, not yet analyzed", **Open saved record #N**, list reload, fresh empty form |
| `200` replay | "Already saved as record #N; nothing new was stored" |
| `400`/`422` | "Rejected, nothing was stored" with the server message; text kept; a corrected save gets a new identity |
| `409` | Conflict: nothing stored or overwritten; text kept; no retry |
| No response, or `5xx` | **Unknown**, never "failed"; text and attempt kept. **Check whether it was saved** (GET receipt): found = saved, `404` = "not saved", other error = still unknown. **Send the same question again** resends the byte-identical attempt (same `capture_id`). Nothing is automatic |
| Text edited while unknown | **Save** is disabled with an explanation, until the reader checks status or chooses **Stop tracking the earlier attempt** (sends nothing; warns that it may still have been saved). Edited text never reuses the earlier identity |
| Mode switching | Both modes stay mounted: each draft is kept; nothing is sent |
| Browser storage | Not used for learner text (asserted with a `Storage.prototype.setItem` spy) |
| List refresh fails after a confirmed save | The success and **Open saved record #N** remain; the list error is separate |
| Saved record excluded by search, filters or jump | **Open saved record #N** opens the detail directly |

The intake panel stays mounted when hidden, as the capture import did. A
pending save and its outcome therefore survive hiding the panel or switching
workbench views.

## 3. Validation (agent-run)

**Frontend:**

| Command | Result |
|---|---|
| `NODE_OPTIONS=--no-experimental-webstorage web/node_modules/.bin/vitest run src/components/QuestionIntake.test.tsx` | **13 passed** |
| `… vitest run src/pages/RecordsBrowser.test.tsx` | 31 passed (2 new) |
| `… vitest run src/components/RecordWorkflow.test.tsx src/components/CaptureImport.test.tsx src/i18n` | 46 passed (existing JSON-import tests retained; the workflow test now selects the **Capture JSON** mode) |
| full `vitest run` | **21 files, 280 passed** (265 after FLH-090) |

**What the 13 intake tests cover:**
- **Payload:** an exact manual capture without analysis, with tabs, newlines
  and spaces kept, and IDs in UUID v4 form.
- **Default save:** question and context are saved, and the only request is
  `POST /api/captures` (no analysis, extraction or provider endpoint).
- **Input and clicks:** blank or context-only input is refused; repeated
  clicks send one request.
- **Rejection:** after a rejection the text is kept, and the corrected save
  gets a new identity.
- **Lost response:** it is unknown, with no automatic retry; an explicit
  resend is byte-identical, and the server's replay is reported.
- **`503`:** it is unknown. A failed check stays unknown; a found receipt
  reports it as saved.
- **Not stored:** confirmed through the receipt, with the text kept.
- **Edited while unknown:** blocked until a status check or an explicit stop;
  the new save then gets a new identity.
- **Conflict:** reported, with the text kept.
- **Modes and storage:** mode switching keeps both drafts and sends nothing;
  no browser storage is written.
- **Capture JSON:** the document is sent byte-for-byte and reported as
  imported.

**What the 2 integration tests cover:**
- a confirmed save survives a failed list refresh and opens;
- a saved record excluded by the state filter and the search opens directly.

**Fixture:** `bash scripts/validation/flh089/run.sh <scratch>`, the existing
harness, extended. `workflow.py`: **30 passed, 0 failed**, 7 of them new:
- the exact Question payload gives `201` with `analysis_id: null`;
- `GET /entries/{id}/analyses` and `/extractions` are empty;
- the record is listed as `unanalyzed`, interior whitespace and the newline
  are kept, and the ends are trimmed;
- an identical resend is a `200` replay of the same record;
- the same `capture_id` with changed text is a `409`;
- the receipt confirms the record with `source: manual`;
- an unknown ID is a `404`.

The existing check that an imported candidate Analysis is `unreviewed` until
explicit acceptance still passes.

**Repository checks:**
- `web/node_modules/.bin/tsc -b --noEmit`: ok.
- `unshare -rn bash -c 'ip link set lo up; GOPROXY=off GOFLAGS=-mod=readonly GOTOOLCHAIN=local NODE_OPTIONS=--no-experimental-webstorage make verify'`: **exit 0**
  (Go fmt, tests, vet, builds; frontend typecheck, 280 tests, production build).

**Not run:**
- Go backend tests beyond `make verify`: no backend file changed.
- Real-browser checks: no browser is installed.

## 4. Limitations

- **Drafts live in memory only, by design** (no storage authorization). A page
  reload or closed tab loses an unsaved draft and the identity of an unknown
  attempt. Recovery then means looking for the record in the list, for
  example with text search.
- **The receipt does not return the text**, only references. "It was saved"
  confirms the identity, and the server's fingerprint guarantees the content
  matched the attempt.
- **Trimmed ends:** leading and trailing whitespace is trimmed by the existing
  backend contract, so a learner's deliberate outer spacing is not kept.
- **Length bounds:** they are the server's. An over-long question is rejected
  with the server message; there is no client-side counter.
- **Receipt source:** the saved record's capture receipt reads
  `source: manual`. The workbench does not separate "typed in the workbench"
  from other manual captures.

## 5. Owner walkthrough (owner-run; not yet done)

1. **Save a question:** in **Learning Records**, choose **Add a learning
   question**. Type a question with a line break and an optional context, and
   choose **Save question**.
2. **Check the record:** **Open saved record #N**. It shows your text, "No
   analysis", and no extraction. Request analysis and review, then extraction,
   then Concept Review, as before.
3. **Switch modes:** switch to **Capture JSON** and back; both drafts remain.
   Import a capture with a candidate analysis and confirm that it is shown as
   not yet reviewed.
4. **Optional, unknown outcome:** stop the server, save, and check that the
   question is reported as unconfirmed rather than failed. Restart the server,
   then use **Check whether it was saved** or **Send the same question again**.
5. **Record your observations** on your own browser and data. These are the
   daily-use acceptance this report does not provide.
