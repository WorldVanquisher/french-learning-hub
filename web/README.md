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
| `npm test` | run the Vitest unit tests once |
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

When the backend rejects a decision with `409 Conflict`, the banner shows the
backend's own message (for example, an identity that already exists versus an
existing membership) and the UI re-reads the unit's current membership before
the reviewer tries again. If that re-read fails, the banner keeps the backend
message and says the membership could not be refreshed, so the membership shown
must not be treated as confirmed. Nothing is recorded by the rejected request.

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
  `corrected`, `rejected`) is sent to the backend as `state`; **Load older
  records** passes the returned `next_before_entry_id` cursor back as
  `before_entry_id` and appends the next page. "End of records." appears when the
  cursor is null.
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
interpretation for a version that is no longer selected. Returning from a detail
keeps the loaded pages and filter and moves focus back to the record's **Open**
button. Switching to another workbench tab still resets the view.

## Capture import, analysis, and extraction (FLH-014)

The daily path capture → record → analysis → extraction runs in the Learning
Records view through existing endpoints only. The browser never decides
interpretation or eligibility.

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
- The extraction panel shows the stored versions, the version the backend reports
  as current, and its units with their admission state. Zero units is shown as a
  valid result, distinct from "No extraction stored." It is re-read after every
  extraction request.
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

Feedback (accept, correct, reject) is not yet available in the workbench; use
`POST /analyses/{id}/feedback`. The browser cannot tell which analyzer or
extractor the server is configured with, so the explanations describe both the
local default and the provider-backed case.

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
               ExperimentDashboard — read-only quality/comparison summary
  types/       wire types mirroring the Go transport DTOs
  App.tsx
```
