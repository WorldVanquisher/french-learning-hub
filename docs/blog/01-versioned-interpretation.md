# Keeping the learner's words: versioned interpretation and human correction

> Retrospective draft, prepared 2026-10-10. Not yet published. The milestones
> described here have no recorded dates; their order is known from the project
> documentation.

French Learning Hub started from a narrow goal: questions asked while learning
French should not disappear inside individual chat conversations. That sounds
like a note-taking problem. It turned into a data-modelling problem as soon as
machine interpretation entered the picture.

## The trap: one row that means three things

The first version stored a learning entry with the learner's input, its
context, and three nullable columns: `category`, `explanation` and
`confidence`. That is the obvious schema, and it quietly mixes three different
kinds of truth:

- what the learner actually wrote, which should never change;
- what a machine thinks it means, which changes whenever the analyzer changes;
- what a person decides after reading the machine's answer.

If all three live in one row, every re-analysis overwrites an earlier
interpretation, and a human correction erases the evidence of what the machine
said. You can no longer ask "what did the rule engine say last month, and did
anyone disagree?"

## Separating source, interpretation and judgment

The design that replaced it is simple to state:

- **Entry** holds only the learner-authored source: input, context and
  timestamps. It is never rewritten.
- **Analysis** is a separate, immutable record with a per-entry version.
  Analysing again appends version 2, 3 and so on, and each version records its
  provenance, for example `rule-based:v2:fr_l2_taxonomy_v1` or
  `openai:<model>:fr_l2_taxonomy_v1`.
- **Feedback** is an append-only human judgment on one analysis: accepted,
  corrected or rejected. It never modifies the analysis it refers to.
- **Effective analysis** is not stored at all. It is computed on each read from
  an analysis and its latest feedback. A rejection means there is no effective
  interpretation, and an older acceptance never resurfaces after a later
  rejection.

The old entry columns could not simply be dropped: databases created by the
first migration still have them. They remain in the physical table, but the
active model and API ignore them. No values were migrated or synthesized, and
the migration history was not rewritten. That is a small, deliberate piece of
technical debt traded for never having to rebuild an existing user's table.

## A local analyzer that explains itself

The default analyzer runs locally and needs no API key. It began as a
four-branch `switch` that looked at question marks and word counts. It was
replaced by named, weighted rules over both the input and the context. Explicit
cues such as "how do I say" win; weak token-count fallbacks apply only when
nothing explicit matches.

Two choices matter more than the rules themselves:

- The confidence value is documented as a **heuristic decision score, not a
  calibrated probability**. It is useful for ordering and for advising review,
  not for claiming accuracy.
- The engine can set an advisory `NeedsAI` flag, but it **never calls a
  provider**. An OpenAI analyzer exists behind the same interface, chosen at
  startup by `AI_PROVIDER`. Provider failures store nothing and return `502` or
  `504`; there is no automatic retry and no fallback in either direction.

Categories live in one shared taxonomy, `fr_l2_taxonomy_v1`, so the database
never stores a provider-specific category system. Model output outside it is
rejected before storage.

## Getting real conversations in without building a chatbot

Many learning questions happen in an AI chat assistant. The tempting
integration is to connect to it. The project chose the opposite: a versioned
`learning_capture_v1` document that the learner prepares (a copyable prompt in
Chinese helps produce it), and a `POST /captures` endpoint that stores it as an
ordinary entry plus an optional version-1 analysis, in one transaction.

The endpoint makes no model call and never sees a transcript. Imports are
idempotent by a client-chosen `capture_id`, decided by a fingerprint of the
normalized content. A replay of the same content returns the existing record
with `200`; different content under the same id is a `409` and never
overwrites. A thin command-line client posts the document unchanged, so the
server remains the only owner of the rules.

## A wrong "latest"

Several features ask for the *latest* feedback, override or judgment.
RFC3339 strings with different fraction widths or time-zone offsets do not sort
chronologically when compared as plain text, so a text ordering can pick the
wrong "latest". The correction (FLH-004, which has no separate report in the
repository) registered a custom SQLite collation that parses
each value and compares instants, with the row id breaking ties. Existing rows
did not need migrating. The cost is documented too: external SQLite tools must
register the collation to run these queries, and binary timestamp indexes
cannot serve the custom ordering.

## What it does not do

There is no staleness flag when a newer analysis appears, no automatic
re-analysis, and no scheduling. The design keeps enough provenance to add those
later without rewriting history.

## Verification

The numbered milestones have no separate validation reports. The earliest dated
check, FLH-001 on 2026-10-07, exercised the real capture workflow with and
without an imported analysis, identical and conflicting replays, and a restart,
and observed no data-integrity failure. Later release acceptance (FLH-011)
confirmed that capture idempotency survives replacing the container.

## Sources in the repository

- `docs/ARCHITECTURE.md` §3–4 (current behaviour)
- `docs/history/01-learning-records.md`
- `docs/plans/FLH-001-sanity-check.md`
- `docs/validation/FLH-011-release-acceptance.md`
- `docs/CAPTURE_PROMPT.zh-CN.md`, `docs/LOCAL_LEARNING_WORKFLOW.zh-CN.md`
