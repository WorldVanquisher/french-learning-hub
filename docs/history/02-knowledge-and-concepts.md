# 2. Knowledge units, concepts and human annotation

Covers milestones 10 to 11-B, the annotation-semantics patch, and the workbench
tasks FLH-014, 018, 022, 023, 025 and 027. Milestone dates are **unknown**.
FLH-023 is dated 2026-10-08; FLH-014, 018, 022, 025 and 027 are known only from
the workbench guide and other reports. Current behaviour:
[ARCHITECTURE §5–7](../ARCHITECTURE.md#5-knowledge-extraction-and-admission).

## Initial implementation

**Milestone 10 — knowledge extraction.** An explicit request turns one record,
together with its current effective interpretation, into zero or more atomic
knowledge units. Extraction never runs as a side effect, is refused for
unanalysed or rejected records, and records the exact analysis and feedback it
used. The only extractor is an opt-in OpenAI adapter; when it is disabled the
endpoint returns `503`. A fixed admission ruleset recommends
`active`/`suppressed`/`needs_review` per unit, and humans append overrides that
win.

**Milestone 10.5 — durable concepts.** A unit belongs to one extraction, so
re-extracting creates new units for the same idea. A separate
`KnowledgeConcept` became the durable identity, with a versioned identity
schema and a deterministic signature. The resolver is deliberately
conservative: automatic SAME only on an exact single signature match; ambiguous
cases go to a human.

**Milestone 10.6 — Concept Review.** The first human-review workbench recorded
SAME, NEW CONCEPT, BROADER, NARROWER, RELATED and INVALID decisions, framed as
a data-collection instrument for later resolver experiments rather than a
review scheduler.

**Milestone 10.7 — catalog discovery.** The review UI added transparent
client-side search over the existing Concept catalog, kept separate from exact
resolver matches; showing or selecting a candidate records nothing.

**Milestones 11-A and 11-B — effective annotation.** A read-only resolver
composes append-only judgments, distinctions and link events with the current
membership projection into one effective snapshot per unit; the Inspector shows
it.

## Later corrections

- **Milestone 10.5.1 (migration 007).** The first concept model could drift
  from its own principles. The correction made resolution history strictly
  append-only (supersession is a new row with a back-pointer, never an
  `UPDATE`), moved current SAME membership into a small mutable projection
  (`unit_concept_memberships`), allowed a human to move a wrong SAME
  (`ReassignSame`), derived support at read time instead of storing it, kept a
  Concept's identity reserved while it is orphaned, and made create-plus-seed
  atomic.
- **Annotation-semantics patch (migration 008).** The first 10.6 release
  exposed two labelling gaps: INVALID only worked when a unit already had a
  membership, and a reviewer's "this is not concept A" was lost. Dedicated
  append-only tables added a reversible unit-level INVALID judgment and explicit
  DISTINCT pairs.
- **Workbench daily path (FLH-014, FLH-018).** The Learning Records view gained
  capture import, explicit analysis and extraction requests, and explicit
  feedback with its history, all through existing endpoints.
- **Extraction selection (FLH-022, FLH-023, FLH-025).** Current extraction had
  been "latest successful, or a human pin". FLH-023 (2026-10-08, NAS Codex,
  [plan](../plans/FLH-023-extraction-selection-mode.md)) added an explicit
  `selection_mode` (`automatic`/`pinned`) and a `DELETE` that returns to
  automatic selection without rewriting any history. The workbench then showed
  version history and current selection and linked each unit to Concept Review
  or the Inspector.
- **Decision outcomes (FLH-027).** Concept Review began reporting each decision
  by what the server actually answered, separating the decision outcome from any
  re-read; see [theme 5](05-annotation-idempotency.md).

## Current behaviour

Units are immutable evidence; Concepts are durable identities; CURRENT SAME is
read only from the membership projection; support is derived from current
extraction, active admission and membership. The canonical summary is
[ARCHITECTURE §6.1](../ARCHITECTURE.md#61-membership-versus-support-canonical-summary).

## Evidence and gaps

- Milestones 10–11-B have no dedicated report or date; their content comes
  from the previous ARCHITECTURE text and AGENTS.md.
- FLH-023's contract and checks are in its plan. FLH-026
  ([report](../validation/FLH-026-workflow-regression.md), 2026-10-08) built a
  repeatable daily-workflow regression harness that exercises this path with a
  fake provider.
- FLH-012 ([report](../validation/FLH-012-workbench-acceptance.md),
  2026-10-07) is the browser acceptance of the release workbench at that time.
- FLH-014, 018, 022, 025 and 027 have no report in the repository; their
  behaviour is documented in [web/README.md](../../web/README.md).
