# Notebook to practice (2026-11-19)

Synthetic data only. No migration, no provider call, no new route.

## What works

**Mistake Notebook → Make practice** (`web/src/pages/NotebookPractice.tsx`, rule
`practice_draft_v1` in `web/src/pages/practiceDraft.ts`):

1. **Select** saved mistakes. A record whose source no longer resolves (`missing` or
   `unusable`) cannot be selected. It says which stored source failed and offers **Open
   record**. A record saved from an older version is selectable. It names the newer version
   and offers **Open source**.
2. **Preview** one draft per record. The source text, the editable practice question and the
   expected action appear side by side; they stack on a phone.
   - The question starts as stored French text: the item's question (listening or reading), or
     the learner's own words (writing or speaking corrections).
   - The action starts from the skill: answer again, write the corrected sentence, or say it
     aloud.
   - The source line names the exact stored item and the revision the learner saw.
3. **Edit** before approval. Text is kept exactly as typed, including accents, `« »`, `…` and
   line breaks. A blank question blocks approval and announces why.
4. **Make a separate version** adds another draft of the same record (`Version 2`), which can
   be edited independently.
5. **Approve** with the notebook's existing `PUT /mistake-notebook/items/{id}/retry
   {"marked": true}`, once per distinct record:
   - The record appears in Review Today as `retry_marked`.
   - A repeated click is one save: an in-flight guard, and the server's `changed: false`.
   - A record already marked is not resent.
   - Versions of one record are one mark, so Review Today lists the record once.
   - A failed save keeps every draft and edit; **Approve again** resends only what failed.
   - A record deleted in the meantime (404) is named, with **Open record**.
6. **Practise now** goes through the approved drafts with their edited wording:
   1. reveal the stored reference;
   2. self-check (page only).

**Keyboard:**
- Focus moves to the preview heading, then to the result heading.
- **Alt+↓** and **Alt+↑** move between questions.
- **Ctrl+Enter** approves.
- **Escape** returns to the selection; focus goes back to the preview button and the drafts are
  kept.

## Tests

| Command | Cases |
|---|---|
| `cd web && npx vitest run src/pages/practiceDraft.test.ts src/pages/NotebookPractice.test.tsx` | 5 + 6 |

The accent-rich fixture is `web/src/pages/practiceDraft.fixture.ts`. It includes "Hélène",
"Saint-Éloi", "préfère-t-elle", `« Ça dépend… »` and a line break. Edited text is compared byte
for byte and checked to be NFC-stable. The browser run is in the learning-day walkthrough
(`docs/validation/LEARNING-DAY.md`).

## What is not stored, and why

**Kept in the page only:** the edited question, the chosen action, the second versions and the
answers. A reload loses them. Review Today lists the record itself.

No existing table can hold an edited prompt with its provenance:
- `writing_tasks` (learner tasks) has no source columns and no idempotency key.
- Speaking exercises are authored-only.
- Retry marks are a boolean.

Linking a learner task to its note by its prose is forbidden ("never link by parsing").

## Proposal for the owner (needs a migration number)

`practice_prompts`, additive:

```sql
CREATE TABLE practice_prompts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_key    TEXT    NOT NULL UNIQUE,      -- client UUID per approval: a resend replays
    entry_id         INTEGER NOT NULL REFERENCES learning_capture_sources(entry_id),
    copy_number      INTEGER NOT NULL CHECK (copy_number >= 1), -- 2+ = deliberate separate version
    source_type      TEXT    NOT NULL,             -- copied from the record's source at approval
    source_record_id INTEGER NOT NULL,
    source_item      INTEGER NOT NULL,
    source_version   INTEGER NOT NULL,             -- the revision the draft was made from
    question         TEXT    NOT NULL CHECK (length(trim(question)) > 0),
    action           TEXT    NOT NULL CHECK (action IN ('answer_again','write_corrected','say_corrected')),
    rule             TEXT    NOT NULL,             -- practice_draft_v1
    created_at       TEXT    NOT NULL,
    UNIQUE (entry_id, copy_number)
);
```

- **Writes:**
  - A resend under the same `operation_key` replays; a different payload is `409`. This is the
    FLH-029 pattern.
  - A deliberate copy takes the next `copy_number` in the same transaction.
  - Rows are append-only. An edit after approval would be a new copy, or a later
    `practice_prompt_versions` table.
- **Reads:**
  - Review Today lists approved prompts with their source link.
  - A source that no longer resolves degrades the row only (`source_status`).
- **Forward:** a new table only; nothing existing changes or is backfilled.
- **Rollback:** restore the pre-upgrade backup (`docs/RELEASE.md`). An older build ignores the
  table, and its rows are lost on restore.
- **Interaction with 013–014:** a defer (`review_defers`, `docs/validation/REVIEW-TODAY.md`)
  would key on `practice:prompt:<id>` like any other Review Today key.
