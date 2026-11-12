# Annotation Workbench

An internal frontend with four views: the **Learning Records** view for importing
captures, browsing learner-authored records and their interpretations, and
explicitly requesting analysis or extraction; the write-capable
**Concept Review** workflow for `KnowledgeUnit → KnowledgeConcept` annotation,
the read-only **Annotation Inspector** for viewing M11-A effective annotation
state over current-extraction units, and the read-only **Experiment Dashboard**
for M11-D dataset quality and M13-A0 retrieval comparison summaries.

It is **not** the Review Engine, mastery, scheduling, or an ML resolver. There is no
authentication in this milestone.

Stack: React + Vite + TypeScript, native `fetch`, plain CSS. No state-management
framework, no component framework.

## Running it (two terminals)

The Go backend is the source of data. The frontend talks to it through a `/api`
prefix that Vite proxies to the backend, so the browser makes same-origin requests
and there is no CORS to weaken on the backend.

**Terminal 1 — Go backend** (from the repository root):

```sh
go run ./cmd/server
# listens on :8080 by default
```

**Terminal 2 — web frontend** (from `web/`):

```sh
npm install      # first time only
npm run dev
# Vite dev server on http://localhost:5173, proxying /api → http://localhost:8080
```

Open the printed Vite URL and use the local view switch to move between
**Learning Records**, **Concept Review**, **Annotation Inspector**, and
**Experiment Dashboard**. Concept Review remains the view shown on load.
In the release image the same workbench is served at `http://127.0.0.1:8080`
without Vite (see `docs/RELEASE.md`). If the backend
is not on `:8080`, point the proxy at it:

```sh
FRENCH_HUB_URL=http://localhost:9000 npm run dev
```

To have units to review, create an entry, analyze it, and run an extraction against
the backend (see the repository `README.md` and `docs/ARCHITECTURE.md`). Units from
the current extraction appear in the queue only when they have no CURRENT SAME
membership and are not effectively INVALID. Absence of CURRENT SAME alone is not
sufficient for reviewability.

## Scripts

| command | what it does |
| --- | --- |
| `npm run dev` | Vite dev server with the `/api` proxy |
| `npm run build` | typecheck (`tsc -b`) then production build (`vite build`) |
| `npm run typecheck` | typecheck only |
| `npm test` | run the Vitest unit tests once (Node 25+: `NODE_OPTIONS=--no-experimental-webstorage npm test`, so jsdom supplies `localStorage`; CI's Node 22 needs no flag) |
| `npm run preview` | serve the built `dist/` locally |

## What the reviewer can do

Seven decisions, all recorded as backend data:

- **SAME** — resolve an unresolved unit SAME to a selected existing concept. If the
  unit already has a current SAME membership and a different concept is chosen, the
  UI uses the explicit **ReassignSame** correction (`PUT
  /knowledge-units/{id}/concept-membership`) — never create+seed as a hidden
  reassignment path.
- **NEW CONCEPT** — create a concept from the edited identity, atomically seeding
  SAME when the unit is unresolved.
- **BROADER / NARROWER / RELATED** — record a non-membership relation. These do not
  make the unit a SAME member.
- **DISTINCT** — `DISTINCT(U, Concept A)` records that the reviewer explicitly
  judged Unit U to be **not** the same pedagogical identity as Concept A. It is an
  explicit negative pair: it creates no membership, does not resolve the unit, and
  keeps the unit reviewable. It is separate from BROADER / NARROWER / RELATED and
  from INVALID. It cannot contradict a CURRENT SAME membership to the same concept.
- **INVALID** — the primary INVALID action is a unit-level judgment that the
  `KnowledgeUnit` candidate itself should not participate in concept resolution.
  It works even when the unit never had a SAME membership. If CURRENT SAME exists,
  INVALID clears it atomically; the unit then leaves the normal review queue. The
  append-only unit-level judgment can later be restored. This is separate from
  membership-level `RejectSame`, which corrects a SAME membership without declaring
  the unit itself invalid.

## Review state within and across units

The reviewed identity draft (target, intent, scope, identity features) and the
search query belong to the unit being reviewed:

- **Switching units** (skip, previous, or advancing after a resolving decision)
  resets them to the new unit's backend candidate identity. Feature rows from one
  unit never carry over to another.
- **Staying on the same unit** after DISTINCT or BROADER / NARROWER / RELATED
  re-reads the unit's current membership and exact matches from the backend but
  keeps the draft and search query, so a reviewer can record DISTINCT against
  one concept and then create a NEW CONCEPT from the edited identity. The
  selection is cleared so the concept just judged is not reused by accident.

**Bounded loading (FLH-090).** Concept Review reads the queue in pages through the
paged `GET /reviewable-units` contract:
- **Page sizes:** 50 units for the general queue; up to 200 for a record's queue.
- **The next page:** it is read only when you skip past the last loaded unit,
  or when you decide it. One request, never a loop over the whole queue.
- **Duplicates:** a unit already loaded is never added twice.
- **Position text:** "unit 3 of 12" only when the whole queue is loaded.
  Otherwise it says how many units are loaded and that more follow, or that
  earlier units are not loaded. A page is never presented as the queue total.
- **A failed next-page read:** it is shown as its own error, apart from the
  decision's outcome. **skip →** (or **Load the next units**) reads it again on
  request. Nothing is retried automatically, and no decision is ever resent.
- **No snapshot:** pages are separate reads. A unit decided elsewhere between
  pages is simply absent.

**Leaving and returning (FLH-089, paged in FLH-090).** The general queue unmounts
when another view is shown. App keeps where it was left, and the queue resumes
there:
- **What is kept:** the unit shown (by unit ID) and the search text typed for that
  unit.
- **On return, and on reload queue:** one page is read from that unit
  (`from_unit_id`, a bounded locator), and the same unit is shown again. Earlier
  units are not loaded, and **Start from the beginning of the queue** reads the
  first page.
- **If that unit left the queue meanwhile:** for example, it was decided from a
  record. The page starts at the next unit in queue order, and the queue says
  which unit is no longer awaiting review. The old unit's search text is not
  carried over to another unit.
- **What is not kept:** the identity draft and the selected Concept stay
  per-unit and are re-seeded from the backend.
- **Pending decisions:** their saved-operation and unknown-outcome protections are
  unchanged.

### Reading a candidate before deciding (FLH-093)

Concept Review makes the content of a membership decision readable. Every view
below is a read of the existing Knowledge Library endpoints, started only when
the reviewer asks; nothing is written and no provider is called.
- **The unit:** the card leads with the knowledge statement and example, then
  kind and record. **Show the original question for unit #N** opens the
  original input and context inline (`GET /knowledge-library/units/{id}/source`),
  so the position, search text, selection and identity draft are kept. Unit ID,
  confidence, identity features and signature are under **Technical details**.
- **A candidate:** each card leads with the Concept's target, type and scope.
  **Show what concept #N contains** reads `GET /knowledge-library/concepts/{id}`
  and shows the preferred explanation (only when a person chose one), then the
  backend-derived current supporting units, three at a time with
  **Show all N**, each with its own original question. Filed-but-not-supporting
  and historical units (older extraction, INVALID, moved away) are only counted,
  never shown as support. A Concept without current support says so; a missing
  Concept, a loading read and a failed read (with **Retry**) are each stated.
- **Compare before deciding:** the selected Concept's content is shown at the
  top of the right column, beside the unit card, with what SAME does (adds a
  membership; the unit and its record are unchanged, nothing is merged or
  deleted), what it does when the unit already belongs to another Concept, and
  what NEW CONCEPT does. A late answer for an earlier selection is discarded.
- **Reassignment:** selecting a target in a unit's **Corrections** shows
  "What concept #N currently contains" the same way. Confirmation, eligibility
  and unknown-outcome handling are unchanged.
- **Limits:** the Concept detail response is complete but not paginated; the
  view renders a bounded number and states how many are shown. There is no
  generated summary of a Concept.

### Explanation languages (FLH-095)

- **Two separate choices in the header:** **Language** is the application UI
  language; **Explanation language** (Both stored languages / English / 中文,
  default Both, stored as `flh.explanation-language.v1`) chooses which stored
  variants of generated explanations and unit statements are shown. Neither
  changes the other, and switching sends no request.
- **Honest labels:** a missing variant reads "No Chinese explanation is stored
  for this version." (never the other language's text); text without a
  recorded language is labelled "language not recorded". Learner text, French
  examples and IDs are never translated or relabelled.
- **Effective interpretation:** each language shows its basis (not yet
  reviewed, reviewed by a person in this language, not reviewed in this
  language, corrected by a person, or generated before a correction in another
  language).
- **Feedback:** every decision on a bilingual analysis records the explanation
  languages shown (the panel says which). **Correct** offers one field per
  language; an analysis without recorded languages keeps the single
  **Corrected explanation** field.
- **Where:** the record's analysis and effective interpretation, extracted
  units, the Concept Review unit card, Concept contents and the Annotation
  Inspector. The Knowledge Library and public demo still show the primary
  statement only, except the recall-practice reveal (see *Recall practice*).

### AI suggestions (FLH-097)

- **Where:** Concept Review has two modes, **Unit queue** and **AI
  suggestions**. Switching modes sends nothing.
- **Generate:** select at most the server's `max_units` reviewable units, then
  **Generate suggestions**. This is the only control that may call the model.
  The key and unit ids are saved in browser storage
  (`flh.concept-suggestion-requests.v1`) before sending; if storage fails,
  nothing is sent. A lost answer shows an unknown outcome with **Check for a
  stored result**, **Send the same request again** (same key) and **Forget**.
  A same-key answer that is a stored failed run is shown as a failure; retrying
  it is the explicit **Generate again as a new request** (new key, a new and
  possibly billed model call).
- **Review:** each item shows the unit, the model outcome and reason, the
  supplied candidates, the proposed Concept's current content (FLH-093) and
  the derived state (open, confirmed, stale with reasons, nothing to confirm).
  The page states that candidates were limited.
- **History:** a confirmation whose SAME was later corrected is shown as
  historical ("no longer the unit's CURRENT SAME"), never as current.
- **Decide:** **Confirm SAME to Concept #n** sends one confirmation; the
  backend revalidates and refuses stale state. **Leave unused** records
  nothing. There is no bulk acceptance. Correcting an already-resolved unit
  stays in the unit queue.
- **Advisory, stated on the run:** a completed run says that generating
  recorded nothing and that only one explicit confirmation records a human
  SAME. A confirmed, still-current item adds that a later correction can make
  it history. A left item says it is not DISTINCT or any other judgment.

### Decision outcomes (FLH-027)

Every Concept Review decision (SAME or REASSIGN SAME, NEW CONCEPT,
BROADER/NARROWER/RELATED, DISTINCT, INVALID) is sent once and reported by what
the server actually answered. The decision outcome and any re-read that follows
are shown separately.

- **Confirmed.** A resolving decision (SAME, NEW CONCEPT with SAME, INVALID)
  removes that unit, by ID, from the in-memory queue. A non-resolving one
  (DISTINCT, relations) keeps the unit, re-reads its membership and exact
  matches, keeps the identity draft and search, and clears the selection.
- **Rejected by the server** (any HTTP error, e.g. `409` or `422`): "The server
  did not record …" with the backend's message. A `409` also re-reads the unit's
  current membership; that re-read is reported on its own line ("… re-read from
  the server" or "Could not re-read …").
- **No response** (the request may never have arrived, or may have been stored
  with its answer lost): **Outcome unknown**, never "could not be recorded", and
  nothing is resent. The workbench then checks the authority or history the
  decision would have changed:
  - SAME / REASSIGN: the unit's current membership is the requested concept.
  - NEW CONCEPT with SAME: the unit belongs to a concept whose identity matches
    the draft (a different identity does not count).
  - DISTINCT and relations: an event newer than the newest one read just before
    sending exists (they append events, so older events never count).
  - INVALID: the unit is INVALID.
  When the check finds the decision, a resolving one removes the unit from the
  queue with a note; otherwise decisions continue. When it does not, the
  workbench says the decision is not visible yet, that the original request may
  still be in progress on the server or may never have arrived, and keeps every
  decision for that unit blocked. **Check again** repeats the check; **Allow
  another decision for unit #N…** is an explicit confirmation that explains the
  duplicate risk (DISTINCT and relations would be recorded twice).
- While a decision is being sent, other decisions, previous/skip, and reload
  wait. An unknown outcome stays with its unit: other units can be reviewed, and
  a check that finishes later never changes the unit being shown.
- DISTINCT and relation decisions first read the existing events; if that read
  fails, nothing is sent and the reason is shown.

## Candidate sources and authority

The page keeps two candidate sources visibly and semantically separate:

- **Exact identity matches** come from the existing deterministic
  `resolveUnit()` exact-signature resolver. Its behavior is unchanged.
- **Search existing concepts** reads the existing `GET /concepts` catalog and
  performs transparent client-side token matching over `target`,
  `pedagogical_intent`, `scope`, and `identity_features`. Search is
  case-insensitive, ignores French accents for retrieval convenience, excludes
  retired concepts, and keeps orphaned durable identities discoverable. Concepts
  already shown as exact matches are deduplicated by Concept ID.

**A large catalog (FLH-089).**
- **One normalization per load:** the catalog is normalized once when it loads,
  not on every keystroke.
- **Fifty at a time:** matches render 50 at a time, in catalog order. "Showing
  50 of 500 matching concepts" states the total, and **Show 50 more** adds the
  next page, so every match stays reachable.
- **When it restarts:** a new search or a new unit starts again at one page.
- **Selection stays visible:** a selected Concept further down the list is
  always shown.
- **Unchanged:** matching rules, order and exact-match deduplication.

Catalog discovery is retrieval evidence only, never annotation authority. Showing,
searching, selecting, or skipping a candidate writes nothing and does not imply
SAME or DISTINCT. Both sections share one selected Concept; only an explicit human
action uses that selection to call the existing SAME, DISTINCT, or relation
endpoint. Search normalization never changes stored identities or signatures.

## Current membership vs. history

The UI reads the unit's **current** SAME membership only from
`GET /knowledge-units/{id}/concept-membership`. It never infers current membership
from the append-only resolution events, which may still show a superseded decision
as `accepted`. The current-membership panel is visually distinct from the collapsible
resolution-history panel for exactly this reason.

## Learning Records

Browsing the Learning Records view uses only GET requests to existing endpoints.
Writes happen only through the explicit actions described in the next section.

- `GET /learning-records` supplies the list, newest first, 20 records per
  request. The **Record state** filter (`unanalyzed`, `unreviewed`, `accepted`,
  `corrected`, `rejected`) is sent to the backend as `state`. The **Effective
  category** filter (`fr_l2_taxonomy_v1`) is sent as `category`; the backend
  matches the effective interpretation, so rejected and unanalyzed records never
  match a category. **Load older records** passes the returned
  `next_before_entry_id` cursor back as `before_entry_id` and appends the next
  page. "End of records." appears when the cursor is null.
- **Go to record #** (FLH-089) starts the list at a record ID with one request.
  - **How it works:** it uses the same exclusive cursor (`before_entry_id = ID + 1`)
    under the current filters.
  - **What it shows:** a banner says that the list starts at #ID and that newer
    records are not shown, and **Show newest records** returns to the top.
  - **Absent or filtered-out ID:** the list says so and starts at the next older
    matching record. Older pages stay reachable with **Load older records**.
  - **Invalid input:** it is refused without a request.
- **Search text** (FLH-090) is applied with **Search** and sent as `q`.
  - **What it matches:** the backend matches a literal substring of the
    learner's original input or context. Letter case is ignored and accents
    must match; `%` and `_` are ordinary characters. Generated interpretations
    are never searched.
  - **Combination:** it combines with the state and category filters and with
    **Go to record #**.
  - **Pagination:** applying or clearing a search restarts from its first page,
    and **Load older records** pages through all matches. A response for an
    earlier search is discarded.
  - **Limits:** a blank search means no search. Over 200 characters is refused
    in the browser, before any request.
  - **Messages:** "no records", "no search matches" and "jump target excluded by
    the filters" are three different messages.
- Opening a record reads `GET /entries/{id}` for the original input and context
  and `GET /entries/{id}/analyses` for every immutable analysis version. The
  latest version is selected by default; choosing another version only changes
  what is displayed.
- The selected version's interpretation comes from `GET /analyses/{id}/effective`
  exactly as the backend resolves it. The browser never recomputes state or
  effective values.

States stay distinct: loading; request failure (with the backend status and
message, and a retry); an empty inventory versus a filter with no matches; a
record with **no analysis**; an **unreviewed** interpretation that no human has
confirmed; a **corrected** interpretation shown beside its original values; and a
**rejected** interpretation, which has no effective values and shows the original
only as rejected evidence. Each detail read is independent, so one failure does
not hide another section.

Responses that arrive after the reader has moved on are discarded: a list
response for a superseded filter, an older page requested under a previous
filter, a detail read for a record that is no longer open, and an effective
interpretation for a version that is no longer selected. A list requested under
an earlier jump is discarded the same way.
- **Returning from a detail:** the loaded pages, filters and jump position are
  kept, and focus moves back to the record's **Open** button.
- **Switching to another workbench tab and back:** the Learning Records view
  stays mounted, so it keeps them too.

## Capture import, analysis, and extraction (FLH-014)

The daily path capture → record → analysis → extraction runs in the Learning
Records view through existing endpoints only. The browser never decides
interpretation or eligibility.

- **Add a learning question** (FLH-091) opens one intake panel with two modes.
  **Question** is the default; **Capture JSON** is the import described in the
  next item. Both modes stay mounted, so switching keeps each draft and sends
  nothing.
  - **What Question saves:** your question and optional context, exactly as
    typed. The server trims only the ends; interior spaces and line breaks are
    kept.
  - **How it is sent:** through the same `POST /captures` as a
    `learning_capture_v1` with `source: "manual"`, a fresh
    `capture_id = question-<uuid>`, and no `analysis` or `discussion_summary`.
  - **What it creates:** an `unanalyzed` record. There is no analysis,
    extraction, provider request or human acceptance; request those later in
    the record.
  - **Same attempt, same identity:** one submission keeps one `capture_id` and
    one byte-identical body. Repeated clicks send one request, and a write is
    never retried automatically.
  - **Lost response or `5xx`:** the outcome is *unknown*, not failed, and the
    text is kept. **Check whether it was saved** reads the receipt
    (`GET /captures/{id}`), and **Send the same question again** resends the
    identical attempt, which the server replays (`200`) and cannot store twice.
  - **Text edited while unknown:** **Save** is blocked until you check or
    explicitly **Stop tracking the earlier attempt**. Edited text never reuses
    the earlier identity.
  - **Outcomes:** new save (`201`), replay (`200`), validation rejection
    (`400`/`422`, text kept, the next save gets a new identity) and conflict
    (`409`) are reported separately.
  - **After a confirmed save:** the list is reloaded, and **Open saved record
    #N** opens the record directly, even when the current search, filters or
    jump would not list it. A failed list refresh is shown separately and does
    not undo or hide the confirmed save.
  - **Browser storage:** none of the learner's text is written there.
- **Import a capture** (`POST /captures`) sends one pasted or loaded
  `learning_capture_v1` JSON document unchanged, like the capture CLI. The browser
  checks only JSON syntax (invalid JSON is never sent); the server validates
  content and its `400`/`422` message is shown. A new import (`201`) reloads the
  list and offers **Open imported record #N**. An identical replay (`200`,
  `created: false`) is reported as the existing record, with nothing new stored.
  A conflicting replay (`409`) states that nothing changed and looks up the
  existing receipt (`GET /captures/{capture_id}`) to offer **Open existing
  record #N**. Import makes no AI call.
- **Request analysis** (`POST /entries/{id}/analysis`) and **Request extraction**
  (`POST /entries/{id}/extractions`) live in a record's detail. Each is a
  two-step control: the first button explains what the request does, whether a
  provider may be called and billed, and that it is never retried; only the
  confirm button sends it, once. While a request is pending the control is
  disabled.
- The **request outcome** and the **refresh** that follows are reported
  separately. The outcome says only what the server answered. The refresh line
  says "Re-reading … from the server…", then "… re-read from the server." only
  after the GET succeeded, or "Could not re-read …; what is shown may be out of
  date" if it failed. Retry (analysis) and Reload extractions settle a failed
  refresh.
- After a confirmed or unknown analysis the record is re-read; on success the
  new latest version is selected. The list row is re-read from the backend
  (`GET /learning-records?before_entry_id=<id+1>&limit=1`). A row that no longer
  matches the active state filter says so instead of disappearing, and a row
  whose re-read failed is marked as possibly out of date.
- The extraction panel lists every stored version and is re-read after every
  write; see **Extraction history and current selection** below.
- Error answers show the backend status and message, and claim only what the
  backend contract supports. Every error response means nothing was stored.
  Only extraction `503` (not enabled) is returned before any provider call. A
  `409` can come from the eligibility check before the provider runs or from the
  source-changed check after it returns (a newer analysis or feedback, or a
  rejected analysis), so it says the provider may have been called. `422`,
  `502`/`504` and other errors also say the provider (or configured analyzer)
  may have been called.
- **No response** (a network failure) is reported as **Outcome unknown**, never
  as a failure, and nothing is resubmitted. The same action stays unavailable,
  with the reason shown, until the stored state has been re-read successfully,
  so a duplicate request cannot be sent before the reader can check. Capture
  import offers **Check import status**, which reads the receipt (`GET` only);
  re-importing identical content is idempotent.
- A result that arrives after the reader has opened another record is not shown
  on that record.

Buttons keep readable labels in every state: colored and selected buttons keep
their color on hover, disabled buttons use a grey fill with a dashed border
instead of reduced opacity, and keyboard focus shows a dark ring with a gap.

The browser cannot tell which analyzer or
extractor the server is configured with, so the explanations describe both the
local default and the provider-backed case.

## Extraction history and current selection (FLH-022, FLH-025)

The extraction panel reads `GET /entries/{id}/extractions` and
`GET /entries/{id}/current-extraction`, whose `selection_mode` is `automatic`
(the latest stored version is current) or `pinned` (an explicitly selected
version stays current).

- **Viewed, current, mode, latest.** A summary line shows the current version and
  selection mode (as the backend reports them), the latest stored version
  (highest number), and how many versions exist. A mode line explains automatic
  selection, a pin to an older version, and a pin to the version that is also the
  latest. Version buttons are labelled "current" (with "pinned" when pinned)
  and/or "latest", and the viewed one is pressed. The current version is viewed by default; a version the
  reader picks stays viewed through the record's own re-reads, and another record
  starts fresh.
- **Browsing is read-only.** Viewing a version sends nothing. Each version shows
  its units with admission state, or "Zero units." for an empty successful
  result, plus its provenance (extractor, source analysis, feedback, time) and
  whether it is current.
- **Pin a version.** "Pin vN as the current extraction…" (offered for any viewed
  version except one that is already the pinned current version, so the latest
  can be pinned too) explains the effect before anything is sent: its units
  become the ones offered in Concept Review and counted as concept support;
  other versions' units stay stored but give no support while it is current;
  nothing is deleted or rewritten (units, SAME memberships, DISTINCT and
  relation labels, INVALID judgments); no extraction is run; a pinned version
  stays current when the record is extracted again. Confirming sends
  `PUT /entries/{id}/current-extraction` with only `extraction_id`, once.
- **Resume automatic latest selection.** Shown only while pinned. It explains
  that the latest stored version becomes current and later extractions are
  followed again, that nothing is deleted or rewritten, and that no extraction
  runs and no provider is called. Confirming sends
  `DELETE /entries/{id}/current-extraction` once. Pinning and resuming share one
  pending state, so they never overlap.
- **Backend state, not local state.** The `PUT` response is built from the
  request and the `DELETE` response is the server's report, so both are shown
  only as the server's answer. The re-read then either confirms the requested
  version and mode ("Confirmed by re-read: … v3 (automatic) …") or reports what
  the server actually stores, for example a pin applied again elsewhere. A `422`
  (version missing or from another entry), `404`, and other errors say the
  selection was not changed. No response is reported as
  **Outcome unknown**, the version list is hidden until the re-read, and nothing
  is resubmitted. An older re-read that finishes after a newer one is ignored.

When the dev server runs on a port other than `:5173`, start the backend with
that origin in `HTTP_TRUSTED_ORIGINS`; otherwise its browser boundary refuses
the workbench's writes with `403`, which the panel reports as not changed.

## From a record to Concept Review and the Inspector (FLH-025)

Each unit of the viewed extraction can be opened elsewhere without losing the
record. There is no router: App keeps the Learning Records view mounted (hidden)
while another view is shown.

- **Eligibility comes from the backend.** For the current extraction the panel
  reads `GET /reviewable-units?entry_id=…`. Only units listed there get
  "Review unit #N in Concept Review"; others say "Not awaiting review (already
  resolved or marked INVALID)". Units of other versions are labelled historical
  and can only be inspected. If the status cannot be read, the panel says so and
  offers "Recheck review status"; no review link is shown meanwhile.
- **Concept Review for one record.** The queue shows "Concept Review for record
  #N" and only that record's reviewable units, starting at the chosen unit. If
  the unit stopped awaiting review in the meantime, it is not shown as a
  candidate; the view explains why and offers "Inspect unit #N". All decisions
  are the existing explicit human actions.
- **Unit inspection.** A view of one unit's effective annotation
  (`GET /knowledge-units/{id}/effective-annotation`) with the record's current
  selection. Opening it records nothing. It states whether the unit belongs to
  the current extraction; a historical unit's stored labels are shown for
  reference only, never as a review or correction candidate. A current unit
  that is unresolved links to Concept Review, which checks eligibility again. A
  current unit that was already reviewed can be corrected there (see below). A
  unit that no longer exists is reported.
- **Back to record #N** returns to the same record, viewed extraction version,
  list filter, loaded pages, feedback drafts, and moves keyboard focus to the
  unit (or the record heading). Review status is read again on return. Choosing
  a tab directly leaves the record-scoped mode.

## Record stage and cross-view links (Daily workflow v1.0 RC)

A record detail starts with **Where this record stands**: three steps and one
**Next:** line. It is derived on every render from reads the detail already
makes; nothing is stored and there is no second workflow state.

| Step | Says | Source |
|---|---|---|
| 1. Analysis | describes and classifies the question; not knowledge yet | latest analysis version and its effective resolution (`GET /analyses/{id}/effective`) |
| 2. Extraction | produces the knowledge statements (units) | stored extractions and `GET /entries/{id}/current-extraction` |
| 3. Concept decisions | units awaiting a decision vs. decided (filed / INVALID) | `GET /reviewable-units?entry_id=…` plus `GET /knowledge-units/{id}/effective-annotation` for each decided current unit |

- **Next action, in order:** request analysis → request a new analysis after a
  rejected one → review an unreviewed analysis (extraction is allowed, but
  uses an unchecked interpretation) → request extraction → nothing to file
  (zero units) → "N of M units await a decision" with **Open unit #N in
  Concept Review** → nothing left to decide. A failed read says "unknown";
  counts are never guessed from unread data.
- **Decided units say where they are.** A current unit that is no longer
  awaiting review shows "Filed under Concept #N (CURRENT SAME, event #L,
  source)" and that a later correction can make this history, or "Marked
  INVALID". **Open Concept #N in Knowledge Library** opens that Concept.
- **Links, all read-only:** a record's filed unit or a reviewed unit's
  inspection → its Concept; a Concept's source screen → **Open record #N in
  Learning Records**; an AI suggestion → **Open record #N** and, for a filed
  unit, its current Concept. The view that was left stays mounted, and a
  **← Back to …** banner returns to it (the record, AI suggestions or the
  Knowledge Library). Choosing a tab directly drops the banner.
- **AI suggestions stay mounted** once opened. Returning re-reads the run
  list, the open run and the queue (keeping only still-reviewable selected
  units); "left unused" stays a local, unrecorded choice.

## Recall practice (Recall Practice v1)

A private Concept detail in the Knowledge Library has a **Recall practice**
section with **Start recall practice…**. It is a short, session-only practice
over the learner's own original questions. It is never offered in the public
demo.

- **Choosing questions:** the candidates are the Concept's backend-derived
  current supporting units (at most the first 10), and practice re-reads each
  one's source (`GET /knowledge-library/units/{id}/source`). A unit is offered
  only if that read still shows it in the current extraction, active, not
  INVALID and filed under this Concept. Each candidate shows the original
  question as written; nothing is preselected, and at most 5 can be chosen.
  A failed read (with **Retry**), a missing source, a record without question
  text and a unit that no longer supports the Concept are each listed with the
  reason and cannot be chosen. Older-extraction members, relations and
  historical or reassigned units are never read or offered. A retired Concept
  or one without support says so instead of offering practice.
- **Answering:** each card shows only the question. The Concept title,
  statements, examples and the recorded context stay hidden. The optional
  attempt field is plain component state: it is never sent, logged or written
  to browser storage, and it is cleared on the next card.
- **Reveal:** **Reveal stored explanation** shows the unit's stored statement
  in the languages chosen by **Explanation language**, its French example if
  one is stored, and **Open the original source (record #N)**. It is labelled a
  stored reference, not a grading rubric. The source screen opened from
  practice has **← Back to practice**, which returns to the same card.
- **Self-check:** **Recalled**, **Try again** or **Skip**. After the first
  pass, a summary offers one second pass over the items marked **Try again**.
  Self-checks are not judged against the attempt and are kept only in the
  session; leaving practice discards them. No score is stored.
- **Reads only:** the session sends only the two GETs above. It writes nothing
  to records, analyses, admission, annotations, suggestions or retrieval
  evaluation, and calls no provider.

## Listening (Exam Listening Lesson v1)

A private **Listening** view (never in the public demo) for exam-style listening
practice. Contract: [ARCHITECTURE.md §4.3](../docs/ARCHITECTURE.md#43-listening-lessons-exam-listening-lesson-v1).

- **Add a video:** a YouTube link, a title and, optionally, the French transcript
  you have (one line per segment; a leading `[mm:ss]` only when your source
  gives one, on every line). Saved without a transcript, the lesson reads
  **Waiting for a transcript** and offers only a transcript form; no exercise
  can be prepared.
- **Open the video on YouTube ↗** opens YouTube's own player in a new tab
  (`noopener noreferrer`); timestamp links add `&t=<s>s`. Nothing is embedded,
  downloaded or fetched, and no request is sent to FLH.
- **Prepare exercise** (only when `LISTENING_PROVIDER=openai`) is the one
  provider call, sent with a fresh `Idempotency-Key`. A stored failure reads
  "The last preparation failed: …; your link and transcript are kept, and
  nothing was retried". If no response arrives, the page first looks the key up
  (`GET /listening/preparations/{key}`); only if nothing is recorded does it
  offer **Send the same request again** (same key, so it cannot prepare twice).
  An attempt still running shows "still in progress" with **Check again**. An
  attempt whose outcome is unknown (timeout, dropped connection) replaces the
  button with **Retry preparation (may be billed again)**, which sends
  `confirm_unknown_retry`. Disabled reads "Exercise preparation is off".
- **Attempt, then reveal:** the exercise shows only the French questions and an
  answer field per question. **Reveal answers and evidence** shows the
  reference answer (French), its reason (English / Chinese through
  **Explanation language**), the cited transcript lines with their source
  timestamps, the vocabulary and grammar notes, and **Show the full
  transcript**. **I got it** / **I missed it** are session-only; answers and
  self-checks are never sent, logged or stored, and there is no score or level.
  Revealing moves focus to **Your answers and the reference** at the top of the
  exercise: one row per question with your answer beside the reference, a
  chosen option tagged **Same as the reference** or **Different from the
  reference**, a typed answer tagged **Short answer: compare it yourself** with
  its own **I got it** / **I missed it** (the same page-only self-check as
  under the question, so marking one marks both), and **Go to question N**
  (each revealed question has **Back to the answer overview**). Nothing is
  totalled or sent. The exercise shown is the lesson's
  `current_exercise_id`, chosen by the server.
- **Save as a learning question…** opens a form showing the context that will
  be attached (title, video link at the cited time, question, cited lines).
  Nothing is sent until **Save learning record**, which posts one
  `learning_capture_v1` with `source: manual` and a capture ID fixed for that
  form, so **Send the same record again** after a lost response replays it
  instead of duplicating it. **Open record #N in Learning Records** opens it,
  with **← Back to Listening**; the lesson stays mounted meanwhile.
- **Workbook listening scripts** (after **Your listening material**, so your
  own lessons stay near the top) lists the 12 written scripts of the synthetic,
  unreviewed workbook by title (`GET /listening/scripts`; no line or key), with
  "N of 12 scripts imported" and two lists: **Imported (N)** (each row tagged
  **Imported**, with **Open …**) and **Available to import (N)**.
  **Import …** (`POST /listening/scripts/{id}`, no model call) opens a
  script-only lesson labelled **Script only · no audio** with a "No audio: …"
  note: no video link, no timestamp, no transcript form and no Prepare button. A lost response reads
  "unknown whether this script was imported"; importing again is safe (the
  server replays), and an imported script offers **Open …** instead. Single-
  choice questions show their choices as radio buttons. **Show the script to
  the person reading it aloud** shows the lines with their speakers, still
  without any answer or note; **End of the script: hide it** at the bottom hides
  it again and returns focus to that button. After reveal, each question also shows the
  accepted alternatives, **Why not « … »** for every wrong choice and the exact
  words in the cited line. A saved missed point names `Source: authored script,
  no audio or video (<pack id>)` instead of a video link. A script's exercise is
  fixed: the server refuses model preparation on it (`409 authored_script`) and
  always names its authored exercise as current (ARCHITECTURE.md §4.3).
- **Script revisions:** an imported script whose pack version was corrected is
  tagged **Revision N** and **Update available** in the list; its lesson keeps
  the stored wording and shows a notice with **Review the changes** (never an
  update button on load). The preview (`GET …/script-update`) lists the lines
  and questions that differ, says in one sentence that earlier practice stays
  with the current revision, and keeps the exact before/after (which shows
  the key) behind a disclosure. Only **Update this lesson to revision N**
  writes (`POST …/script-update` with `from_revision` and `pack_fingerprint`).
  A lost response offers **Confirm the update again** (the server replays, so
  no second revision); a stale preview is replaced by the fresh one; **Not
  now** closes it. Types: `ListeningScriptUpdatePreview` and friends in
  `types/listening.ts`; tests: `ListeningRevisions.test.tsx`.
- **Reopening from the Mistake Notebook** (**Open source**) brings the saved
  question to the top of the screen and marks it, also after a reload. An item
  saved from an earlier revision opens **Revision N: the version you saved
  from** (`GET …/revisions/{n}`) above the current lesson, with the question
  marked.
- **Every lesson:** "Answered N of M" (then "Self-checked N of M") counts on the
  page only. **Lesson navigation** at the end offers **Back to all listening
  material** and, for a script, **Next workbook script: …** (secondary, so
  **Reveal answers and evidence** stays the one primary action). If a save gets
  no response, the question and **Cancel** are locked until **Send the same
  record again**, which replays the identical record.

### Daily Listening

Contract: [ARCHITECTURE.md §4.4](../docs/ARCHITECTURE.md#44-daily-listening-pull-prepare-notify);
owner guide: [DAILY_USE.md §10](../docs/DAILY_USE.md#10-daily-listening-pull-prepare-notify).

- **Daily listening** (top of the list, `ListeningDaily.tsx`) shows the
  settings from `GET /listening/daily` (playlist, at most one lesson per day in
  the configured zone with today's use, notification channel) and the **Last
  pull**: who started it (button or timer), its status and one line per step.
  When nothing is configured it says so and offers no button.
- **Pull now** posts `POST /listening/pull` with a fresh key and no body: the
  same operation as the operator command. "Another pull is running … Nothing
  was started" answers a `409`. A lost response is looked up by key first; a
  running pull offers **Check again**, and only an unrecorded one offers
  **Send the same request again** with the same key.
- List rows show the backend `state` (Waiting for a transcript, Transcript
  saved; no exercise yet, Preparing, Exercise ready, Last preparation failed,
  Outcome unknown) and **From your playlist**.
- **Notifications** on a lesson list each send (by a pull or by you) with
  sent / not delivered / delivery unknown. Only the latest one, when it failed
  or is unknown, offers a retry: **Send the notification again**, or **Send
  again anyway (it may arrive twice)** with `confirm_unknown_retry` after an
  unknown delivery. Lost responses follow the same key lookup.

## Reading (Exam Reading v1)

A private **Reading** view (never in the public demo). Contract:
[ARCHITECTURE.md §4.5](../docs/ARCHITECTURE.md#45-exam-reading-v1).

- **Authored examples** lists the embedded pack (`GET /reading/examples`).
  **Use this example** imports one with its reviewed exercise (no provider
  call); **Open** opens one already imported. They are labelled as original
  practice material, not official exam items.
- **Add a passage:** a title, an optional `https` source link (stored, never
  fetched) and the French passage; blank lines separate paragraphs `p1…`.
- **Lesson:** the passage stays visible (beside the exercise on wide screens)
  with its paragraph IDs.
  - Before reveal: only the French questions and an answer field each.
  - **Reveal answers and evidence** shows the reference answer, **Also
    accepted**, **Plausible but wrong** with reasons (authored), and **Why:**
    through `StoredText` (Explanation language).
  - **Show in the passage (pN)** scrolls there and marks the excerpt with
    `<mark>`. Inference items read "Inference — not stated directly in the
    text".
  - Self-checks are session-only.
- **Prepare exercise** (own passages, `READING_PROVIDER=openai`) follows the
  Listening flow: a fresh key; a lost response is looked up at
  `GET /reading/preparations/{key}` before **Send the same request again**; an
  unknown outcome needs **Retry preparation (may be billed again)**.
- **Save as a learning question…** posts one `learning_capture_v1` only on
  **Save learning record**, with the lesson, passage version, question and
  excerpts as context and a capture ID fixed for the form; **Open record #N**
  comes back with **← Back to Reading**.

## Writing (Exam Writing v1)

A private **Writing** view (never in the public demo). Contract:
[ARCHITECTURE.md §4.6](../docs/ARCHITECTURE.md#46-exam-writing-v1).

- **Practice tasks** lists the embedded prompts (`GET /writing/prompts`).
  **Start this task** creates the task (no draft, no provider call); **Open**
  opens one already started. **Your own task** saves a title, prompt and
  content points.
- **Task:** the prompt, content points, word range and word convention.
  - **Versions** selects a version (`aria-pressed`) and shows its text and
    word count. The editor starts from the latest version and saves the next
    one; the live count uses the backend's word pattern. On a new authored
    task, **Use the example draft** fills it with the prompt's example (with
    deliberate mistakes).
  - **Compare** is a word-level LCS diff (`<del>`/`<ins>`), always from the
    older version to the newer.
  - Reloads keep the last data on screen, so an unsaved revision survives a
    feedback request.
- **Feedback on version N** shows only reports whose `draft_id` is that
  version, and names the other versions that have their own.
  - **Request feedback on version N** follows the Listening flow: a fresh key;
    a lost response is looked up at `GET /writing/feedback-requests/{key}`
    before **Send the same request again**; an unknown outcome needs
    **Request again anyway (it may be charged twice)**.
  - The rating is shown as a label, not a score. Hints come first; **Show
    suggested wording** reveals the suggestion and **Why:** (`StoredText`).
  - **Show in version N** marks a `located` quote with `<mark>`. An
    `ambiguous` quote says it has no position. A `not_found` quote, or any quote
    whose grounding the text contradicts (`shownAsGrounded`), is listed under
    **Not found in this version**, with no hint, suggestion or save action.
- **Save this mistake…** posts one `learning_capture_v1` only on **Save
  learning record**: `« phrase » → « revised wording »` and the stored reason as
  input, and the task, version, feedback and generator as context. The capture
  ID is fixed for the form. **Open record #N** comes back with **← Back to
  Writing**.

## Speaking (Speaking v1)

A private **Speaking** view (never in the public demo). Contract:
[ARCHITECTURE.md §4.7](../docs/ARCHITECTURE.md#47-speaking-v1).

- **Practice prompts** lists the embedded prompts (`GET /speaking/prompts`);
  **Start** creates the exercise; **Open** reopens it.
- **New take** (`speakingRecorder.ts`):
  - `getUserMedia` + `MediaRecorder` (webm/opus preferred), a live timer, and an
    automatic stop at the backend's `max_duration_ms`. The take is a `Blob` in
    memory, played back from an object URL. Nothing is requested while
    recording or playing back, and nothing goes to browser storage.
  - A refused permission (`NotAllowedError`), a missing device and a browser
    without recording each have their own message. **Upload an audio file**
    (type, size and duration checked in the browser) and **Type what you said
    instead** remain available.
  - **Use as take N** posts only metadata: type, size, SHA-256 (WebCrypto) and
    duration.
- **Take N:**
  - local playback while the audio is in memory (`Speaking` stays mounted;
    an honest note once it is gone);
  - **Send audio of take N for transcription…** opens a panel naming the take,
    length, size, type and provider. Only **Send audio** posts the base64 audio
    under a fresh key, with the Listening/Writing recovery flow;
  - the transcript editor is prefilled with the machine transcript, then with
    the latest confirmed version. **Confirm as version N** saves a version;
  - version tabs (`aria-pressed`) show the origin of each version.
- **Feedback on take N, version M** shows only reports for that transcript.
  Hints come first; **Show suggested wording** reveals the rest. **Show in
  version M** marks a `located` quote. Quotes not found in the text
  (`shownAsGrounded`) are listed apart.
- **Compare** diffs any two confirmed transcripts (`diffWords` from Writing),
  from the earlier take and version to the later one.
- **Save this mistake…** posts one `learning_capture_v1` only on **Save
  learning record**. The context names the exercise, take, transcript version
  and feedback. **Open record #N** comes back with **← Back to Speaking**.

## Mistake Notebook (Mistake Notebook v1)

A private **Mistake Notebook** view (never in the public demo). Contract:
[ARCHITECTURE.md §4.8](../docs/ARCHITECTURE.md#48-mistake-notebook-v1).

- **Save paths:** `notebookLink.ts`'s `sourceRef(type, recordId, index,
  attempt)` adds `source_ref` to the four existing capture saves:
  - Listening and Reading send the exercise and question. The typed answer is
    included only behind an unticked **Include my answer** box.
  - Writing and Speaking send the report and correction or improvement.

  `alreadySaved(e)` turns `409 source_already_saved` into "already saved as
  learning record #N".
- **Mistakes:** `GET /mistake-notebook/items` with skill and marked filters.
  Each item shows the prompt, your words or answer, your record, and the
  source line from its `link`.
  - **Show reference** reveals the reference.
  - **Open source** uses `sourceOpen(item)` and the skill view's
    `openRequest` prop: the listening or reading lesson, the writing task with
    `initialVersion`, or the speaking exercise with `initialTake` and
    `initialVersion`.
  - **Mark for retry** sends an explicit `PUT …/retry`.
- **Retry session:** marked items from any skill. The reference stays hidden
  until **Reveal reference**; the self-check uses `aria-pressed`. Typed
  answers and checks stay in component state. The only write is an explicit
  removal from the retry list.
- **Grammar / Vocabulary / Unclassified:** `GET /mistake-notebook/concepts`,
  shown with their kinds and reasons. A row opens the Concept in the
  Knowledge Library.
- **Record view:** `RecordSource` (in `RecordDetail`, when the App passes
  `onOpenSource`) shows "Saved from …" with **Open source**, or the honest
  "no structured source link" notice.


### Learning home and source honesty (sections v1)

- `LearningHome.tsx` (tab **Home**) lists the seven sections; Grammar and
  Vocabulary open `MistakeNotebook` with `modeRequest`. It makes no request.
- Notebook items: **What I got wrong** groups the learner's words or included
  answer and record; the reference heading comes from `reference_origin`
  (authored / generated with `generator`). `latest_version` adds a note;
  `source_status` other than `resolved` shows the stored reference only, and
  the retry session leaves such items out.
- `NotebookOrigin.tsx`: Listening and Reading `openRequest` carry `target`
  {`exerciseId`, `item`, `version`}; the lesson marks that question
  (`notebook-target`) or says it now shows another version or exercise.

## Correcting a reviewed unit from the inspection (FLH-082)

The unit inspection opened from a record offers corrections for a unit of the
record's **current** extraction that already has a CURRENT SAME membership or an
INVALID judgment. It uses only existing endpoints and adds no semantics:

| Backend state | Offered correction | Endpoint |
| --- | --- | --- |
| resolved (CURRENT SAME) | **Reassign SAME** to another non-retired Concept, chosen with the same retrieval-only catalog search as Concept Review (the current Concept is not offered) | `PUT /knowledge-units/{id}/concept-membership` |
| resolved (CURRENT SAME) | **Mark INVALID**, which also clears the membership in the same transaction | `POST /knowledge-units/{id}/invalid` |
| invalid | **Restore**, which withdraws the INVALID judgment; the unit becomes unresolved and no membership is recreated | `POST /knowledge-units/{id}/invalid/restore` |

- **Historical units stay read-only.** The correction endpoints accept any unit,
  so the workbench applies the current-extraction restriction itself, from the
  backend's effective annotation and current-extraction selection. Unresolved
  units are sent to Concept Review instead.
- **Explained, then confirmed.** Each action first shows the current backend
  state and what the request appends, clears or leaves unchanged (prior events
  stay in history; a preferred-unit reference to the unit is cleared; RESTORE
  does not bring a cleared membership back). Selecting or searching a target
  records nothing.
- **Re-checked before sending.** Immediately before the write the unit and the
  record's current extraction are read again. If the current extraction, the
  unit's status, its in-force SAME event or its latest judgment differ from what
  was confirmed, nothing is sent and the new state is shown.
- **Outcomes** follow Concept Review: a confirmed write, a server rejection
  ("The server did not record …"; a `404` or `409` also re-reads the unit), or
  **Outcome unknown** when no response arrived. An unknown outcome is checked
  read-only against current authority (membership is the requested Concept; the
  unit is INVALID; a judgment newer than the withdrawn INVALID one leaves it
  valid), never resent, and blocks further corrections until it is found or
  **Allow another correction for unit #N…** is confirmed. Only the newest check's
  answer is used.
- **Re-read after a write** is reported on its own line. If it fails, the shown
  state is not treated as current: corrections stay disabled until **Re-read
  unit #N** succeeds.
- While a correction is in flight, other corrections and **Back to record #N**
  wait. Returning moves focus to the unit and re-reads its review status.

## Mock Exam (Mock Exam v1)

A private **Mock Exam** view (`pages/MockExam.tsx`, never in the public demo).
Contract: [ARCHITECTURE.md §4.9](../docs/ARCHITECTURE.md#49-mock-exam-v1).

- **Home:** `GET /exam/forms` and `GET /exam/sessions`; **Start** sends
  `POST /exam/sessions` with a fresh `randomOperationId()` key, resent unchanged
  after a lost response; in-progress sessions offer **Resume**.
- **Session:** the countdown follows `deadline_at` with the server clock
  offset from `server_now`; each choice is a `PUT …/answers/{position}` with a
  per-question saved / failed state. Submit asks for confirmation; a
  `NetworkError` offers **Check status** (re-read) or **Submit the same answers
  again** (replayed by the server). At zero the page submits once. A `409` with
  an `exam` body shows that closed view.
- **Results:** score, per-question explanation (Explanation-language
  preference), authored reason, **Show evidence** (highlight in the document),
  and the frozen source line. **Save this missed point…** imports the authored
  passage (`importReadingExample`) and posts a capture with a `reading_item`
  `source_ref`; **Practise a related question** posts `…/retries`.

## Human feedback (FLH-018)

A record's detail records explicit feedback through `POST /analyses/{id}/feedback`
and shows each version's history from `GET /analyses/{id}/feedback`.

- **Target.** Feedback applies to the selected analysis version. Headings say
  whether it is the latest version or a historical one ("historical version;
  latest is vN"). The record's inventory state and any new extraction use the
  latest analysis and its latest feedback, as the server resolves them; feedback
  on a historical version does not change them, and the outcome says so.
- **Decisions.** Accept, Correct, or Reject, chosen explicitly; nothing is
  preselected. Only contract fields are sent: `status`, an optional `user_note`,
  and for Correct only, `corrected_category` and/or `corrected_explanation`.
  Corrected fields left in a draft are dropped if the decision changes to
  Accept or Reject. Category choices mirror `fr_l2_taxonomy_v1` because the
  backend exposes no taxonomy endpoint; the server still validates them, and its
  `422` message is shown with the draft kept.
- **History and effect.** History is listed oldest first, as the backend returns
  it; the entry the backend's effective interpretation names is marked "in
  effect". The original entry, the analysis, and stored extractions are never
  changed: extractions remain visible as historical evidence and are never
  regenerated by feedback.
- **After a write.** A stored decision clears its draft and re-reads that
  version's feedback history and effective interpretation, plus the list row;
  each re-read is reported separately and may fail independently ("Could not
  re-read …"). A rejected write keeps the draft. **No response** is reported as
  **Outcome unknown**; the draft is kept and the submit stays unavailable until
  that version's history has been re-read, so the reader can check before
  submitting again. Nothing is resubmitted automatically.
- **Isolation.** Drafts, pending requests, outcomes, and history are kept per
  analysis version for the open record. They survive the record's own read
  refreshes and version switches, a late response is stored only for the version
  it was sent for, a version with a pending request cannot submit again, and
  opening another record starts empty.

## Effective Annotation Inspector (milestone 11-B)

The Inspector calls `GET /effective-annotations` and loads `GET /concepts` once to
show human-readable Concept targets. It displays the M11-A projection exactly as
returned: status, CURRENT SAME and its source, effective DISTINCT evidence,
effective relations, and INVALID provenance. Filters for status and CURRENT SAME
source run only in the browser.

The Inspector is read-only. Opening, browsing, and filtering it perform only GET
requests and do not define annotation authority; M11-A and CURRENT SAME remain the
backend sources of truth. Missing catalog references stay visible as `Concept #ID`.
This view exists to inspect and debug collected annotations before dataset work; it
does not export the ML dataset.

## Experiment Dashboard (milestone 13-A1)

The dashboard uses two existing GET endpoints and performs no writes:

- `GET /annotation-dataset/v1/quality` supplies M11-D validity, error/warning
  counts, record/entry totals, human SAME/DISTINCT/INVALID inventory, unlabeled
  unresolved records, and human/automatic SAME authority counts.
- `GET /retrieval-comparison/v1` supplies the backend-ordered exact signature,
  weighted lexical, BM25, and embedding rows with state, Recall@1/3/5, and MRR.

The browser does not calculate validity, sample eligibility, Recall, or MRR.
Metrics are displayed as percentages, while null stays distinct as `—`.
`unavailable` embedding and `blocked_invalid_dataset` states remain visible as
reported. The sections load independently, so a failure in one does not discard
the other report.

This view does not load detailed per-sample evaluations, run or select retrievers,
configure providers, create annotations, or change Concept resolution. It is a
compact presentation of backend-owned experiment state.

## Interface language (FLH-083)

The header of the workbench and of the public demo has an **English / 简体中文**
selector.

- **Default:** English on first use, whatever the browser language. An explicit
  choice is stored in `localStorage` (`flh.ui-locale.v1`); a missing,
  unreadable or invalid value means English. If the choice cannot be saved, it
  still applies and the selector says it is not saved.
- **Switching** re-renders in place (`<html lang>` follows): drafts,
  navigation, selections, pending writes and unknown outcomes are kept.
  Outcome banners and notices hold message references, so text shown before a
  switch is shown again in the new language; nothing is re-sent.
- **Translated:** application text only — navigation, controls, labels,
  confirmations, empty/loading states, outcome banners, accessibility labels
  and explanations. Known status values get a display label; the raw value
  still drives logic, filters, CSS and requests.
- **Never translated:** learner input and context, French examples, unit text,
  analyzer/AI explanations and categories, Concept targets and identity fields,
  human notes, IDs, wire values and API fields, provider/retriever/model names,
  provenance (`analysis #`, `event #`, decision sources), the decision
  vocabulary (SAME, NEW CONCEPT, BROADER, NARROWER, RELATED, DISTINCT,
  INVALID, RESTORE, CURRENT SAME) and raw server error details, which appear
  verbatim inside the translated message.
- **Mechanism:** `src/i18n/` — a typed English catalog (`en.ts`, the
  reference), `zh-CN.ts` typed to exactly the same keys, `{name}`
  interpolation, `.one`/`.other` plural pairs, and whole-sentence templates
  whose placeholders take React nodes (no markup inside messages). No
  translation service, model call or network request is involved;
  `i18n.test.tsx` checks key and placeholder parity.

## Theme (Endfield preview)

`theme.tsx` adds a **Theme** selector to the workbench header (Standard, the
default, or Endfield preview), stored as `flh.ui-theme.v1` with the same
fallbacks as the language choice. `theme-endfield.css` holds every rule under
`:root[data-theme="endfield"]`: a dark command bar with the current view as a
yellow block, square panels with an ink tab, cut-corner actions (gradient
corners, so focus outlines are never clipped), wide upper-case labels, calm
reading surfaces and highlighter-style marks, and no transitions under
reduced motion. `theme.test.tsx` checks the default, persistence, fallbacks,
the public demo and the stylesheet's scoping.

## Layout

```
web/src/
  api/         fetch client (client.ts) — all request logic lives here
  components/  UnitCard, CandidateConceptCard, IdentityEditor,
               MembershipPanel, HistoryPanel, ResolutionActions,
               RecordDetail, CaptureImport, AnalysisRequest,
               ExtractionPanel, ExplicitAction
  conceptSearch.ts  deterministic retrieval-only catalog filtering
  pages/       RecordsBrowser — learning-record list, detail, capture import,
               explicit analysis and extraction requests
               ReviewQueue — write-capable annotation workflow
               AnnotationInspector — read-only effective-state view
               UnitInspection, UnitCorrections — one unit opened from a
               record, with explicit corrections of a reviewed current unit
               ExperimentDashboard — read-only quality/comparison summary
  i18n/        UI localization: catalogs (en, zh-CN), provider, selector
  types/       wire types mirroring the Go transport DTOs
  App.tsx
```
