# Evidence is not identity: from extracted units to durable concepts

> Retrospective draft, prepared 2026-10-10. Not yet published. The milestones
> described here (10 to 13-A1) have no recorded dates in the repository.

Once learning records were safely versioned, the next step was to turn them into
something reviewable: the individual ideas a learner actually met. This is where
the project's most important distinction appeared. A piece of evidence that an
idea came up is not the same thing as the idea itself.

## Extraction produces evidence

Knowledge extraction reads one record together with its current effective
interpretation and returns zero or more **knowledge units**. A unit is meant to
be the smallest *reviewable* learning objective that arose in that interaction,
not every linguistic fact in the text. Zero units is a valid answer.

Several constraints keep this honest:

- Extraction runs only on an explicit request, never as a side effect, and is
  refused when the record is unanalysed or its interpretation was rejected.
- Each extraction is an immutable, versioned record of exactly which analysis
  and feedback it used. If a newer analysis or feedback arrives while the
  provider is working, the write is discarded with `409` instead of attaching
  old units to a new interpretation.
- The only extractor is an opt-in OpenAI adapter. When it is disabled, the
  endpoint answers `503`. There is no rule-based extractor pretending to
  understand semantics.
- A fixed admission ruleset recommends `active`, `suppressed` (exact duplicates)
  or `needs_review` (low confidence). A human can append an override, and the
  latest override wins. Nothing is deleted.

## Why a unit cannot be the identity

Re-extracting the same record, or meeting the same idea in a different record,
produces *new* units. If review history were attached to units, it would
fragment every time. So the project introduced a separate **KnowledgeConcept**:
a durable identity with an explicit schema (target, pedagogical intent, scope
and extensible identity features) and a deterministic signature.

Automatic resolution is deliberately timid. A unit is linked to a Concept
automatically only when exactly one Concept has the same signature. When none
or several match, a human decides. No embeddings, fuzzy matching or learned
similarity are used for resolution, because there were no human labels yet to
justify or evaluate them.

## The correction: history is not current authority

The first concept model stored resolution decisions in one table and updated
old rows to mark them superseded. It also stored a support flag that had to be
kept in sync. A correctness patch (milestone 10.5.1) replaced that with a
sharper model:

- **History is append-only.** A new decision is a new row that points back to
  the one it replaces. No row is ever updated.
- **Current membership is a projection.** Each unit has at most one *current*
  SAME membership, held in a small mutable table. Reading current membership
  from history is explicitly wrong, because a superseded decision may still
  read "accepted".
- **Support is derived, never stored.** A unit supports a Concept only when it
  is a current member, belongs to its record's *current* extraction, and has
  active admission. A newer extraction, an override or a correction changes
  support on the next read, with no recompute step.
- **Identity outlives support.** A Concept with no support is *orphaned*, not
  deleted, and still owns its signature.
- **Humans can correct anything** — automatic or human — by moving the
  membership. The old decision stays in history.

This separation is what later made the Knowledge Library possible: a page can
show "filed here but not supporting" with an exact reason, because those are
different facts in the data.

## Labels that mean what a dataset needs

A human review workbench recorded SAME, NEW CONCEPT, BROADER, NARROWER, RELATED
and INVALID decisions. Its first release exposed two gaps. INVALID only worked
on units that already had a membership, so an obviously bad unit could not be
labelled. And when a reviewer looked at candidate A and decided "not A", nothing
recorded that judgment. A follow-up migration added a reversible unit-level
INVALID judgment and explicit DISTINCT pairs, each in its own append-only
table. A read-only resolver then composes all of these into one *effective*
annotation per unit, without guessing when the data is inconsistent.

## Measuring before modelling

The labels were collected so that a resolver could be evaluated later. The
project built the measurement instruments first:

- a versioned dataset export in which automatic SAME is never treated as human
  gold;
- a quality report that flags structural problems without discarding labels;
- an evaluation policy shared by four retrieval baselines (exact signature,
  weighted lexical cosine, BM25 and an optional embedding provider), so only
  rankings can differ, plus a comparison that refuses to mix populations.

Two limitations were written down rather than hidden: the candidate catalog is
the current one, not a historical reconstruction, and the embedding input
includes fields the lexical baselines do not use. No retrieval results on real
data are recorded in the repository, and this article claims none. On a fresh
database the metrics are `null` by design.

## What was intentionally left out

No training, no learned or automatically applied resolver, no review scheduling
and no mastery estimation. Those were set aside until there is enough human
data to judge them.

## Sources in the repository

- `docs/ARCHITECTURE.md` §5–8, especially §6.1 (membership versus support)
- `docs/history/02-knowledge-and-concepts.md`, `docs/history/03-research-instruments.md`
- `docs/plans/FLH-023-extraction-selection-mode.md`
- `web/README.md` (Concept Review behaviour)
