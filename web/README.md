# Concept Review UI (milestone 10.6)

An experimental **human annotation / data-collection** frontend for
`KnowledgeUnit → KnowledgeConcept` resolution. It lets a reviewer inspect candidate
units and record high-quality resolution decisions that can later become ML training
data.

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

Open the printed Vite URL. If the backend is not on `:8080`, point the proxy at it:

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

## Current membership vs. history

The UI reads the unit's **current** SAME membership only from
`GET /knowledge-units/{id}/concept-membership`. It never infers current membership
from the append-only resolution events, which may still show a superseded decision
as `accepted`. The current-membership panel is visually distinct from the collapsible
resolution-history panel for exactly this reason.

## Layout

```
web/src/
  api/         fetch client (client.ts) — all request logic lives here
  components/  UnitCard, CandidateConceptCard, IdentityEditor,
               MembershipPanel, HistoryPanel, ResolutionActions
  pages/       ReviewQueue — the single experimental dashboard
  types/       wire types mirroring the Go transport DTOs
  App.tsx
```
