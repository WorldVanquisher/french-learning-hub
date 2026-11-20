# Practice storage decision: approvals, attempts, deferred items, personal corrections

**Status: PROPOSED (revision 2).** Nothing here is implemented. Applying it needs the owner's
approval and a migration number (`0NN` below). Until then every slice keeps this state in the page
and says so. Date: 2026-11-19. Workbooks lane.

**Revision 2 (increment 5).** Three changes, each tested on scratch databases, end of this file:
- answer text is kept only on an explicit opt-in (`answer_kept`);
- one undo per defer, of the same item;
- one retire per correction.

The one-page sheet for the owner is `PRACTICE-STORAGE-DECISION-SHEET.md`.

The four kinds of learner state that are page-only today:

| Kind | Where it comes from | Today |
|---|---|---|
| **Approvals** | The learner approves, rejects or edits proposed practice content: extraction draft items (`flh_practice_decision_v1`, Extraction 2.0), and notebook practice drafts (021/024/026) | Extraction: the prototype's local JSONL. Notebook drafts: approval is the retry mark, and the edited wording is page-only |
| **Practice attempts** | Attempts and reveals with an outcome (`flh_practice_attempt_v1`); recall self-checks | Page-only (`ConceptPractice`, Recall Practice, Retry session) |
| **Deferred items** | "Not today, show it on day D", and undoing that (013–014) | Not built. "Hide for this visit" is page-only |
| **Personal corrections** | The learner's own corrected wording to practise later: a Speaking transcript edit (047), an edited notebook draft (024), an edited extraction item | Notebook drafts and Speaking: page-only. Extraction: local JSONL |

## Option A: reuse existing tables (no migration)

| Need | The closest existing table | Why it does not hold the need |
|---|---|---|
| Approvals | admission overrides on `knowledge_units` (005); `mistake_retry_marks` (019) | An admission override is Concept authority: `active` changes derived Concept support. A practice approval must not move Concept support. A retry mark is a boolean per notebook entry, with no item hash, no reject or edit, and no extraction item |
| Attempts | `exam_answers` (020); `speaking_takes` and `writing_drafts` | Exam answers belong to a timed session with a deadline. Takes and drafts are production in their own skill, with their own state machines. No table records attempt, reveal and outcome for a practice item |
| Defers | `mistake_retry_marks` | It has no date. "Done for today" is unmarking, which removes the item rather than postponing it. Speaking steps have nothing similar |
| Corrections | `learning_captures` and `learning_capture_sources` (019) | The notebook is the right home in principle, but `source_type` is a SQLite CHECK list (`listening_item`, `reading_item`, `writing_correction`, `speaking_improvement`). A new type needs a **table rebuild** (the 021 pattern), with `mistake_retry_marks` referencing it. A capture without a `source_ref` loses the link, and linking by prose is forbidden |

**Verdict:** reuse cannot hold any of the four faithfully. The tables that come closest either
change another authority (admission → Concept support) or need a rebuild of a referenced table.
Option A stays what ships today: page-only state, labelled.

## Option B: a minimal new schema (recommended)

**Shape:**
- One additive migration with **four new append-only tables**. No existing table, row, constraint
  or index changes; no rebuild; no backfill.
- Each write has a client `operation_key` (UUID). A resend replays and a different payload is
  `409`, as in FLH-029.
- Each table is append-only like `mistake_retry_marks`: repositories expose no update or delete,
  and the current state is derived on read.

<!-- proposed-sql:start -->
```sql
-- 0NN_practice_state.sql (PROPOSED; number allocated by the owner). Additive only.

-- Approvals, and edits of proposed content: one row per learner decision.
-- subject_kind/subject_id name what was decided: an extraction item (k-…) on
-- its source revision, or a notebook practice draft (notebook:entry:N#copy).
-- A decision counts only while item_hash equals the item's current hash (the
-- extraction contract's carry-forward rule); otherwise the item needs review.
CREATE TABLE practice_decisions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_key           TEXT    NOT NULL UNIQUE,
    subject_kind            TEXT    NOT NULL CHECK (subject_kind IN ('extraction_item', 'notebook_draft')),
    subject_id              TEXT    NOT NULL,
    source_id               TEXT    NOT NULL,
    source_revision_sha256  TEXT    NOT NULL CHECK (length(source_revision_sha256) = 64),
    item_hash               TEXT    NOT NULL,
    action                  TEXT    NOT NULL CHECK (action IN ('approve', 'reject', 'edit')),
    edited_text             TEXT,
    reason                  TEXT,
    created_at              TEXT    NOT NULL,
    CHECK ((action = 'edit') = (edited_text IS NOT NULL AND length(trim(edited_text)) > 0))
);
CREATE INDEX idx_practice_decisions_subject ON practice_decisions(subject_kind, subject_id, id);

-- Attempts and reveals. A reveal is never an attempt and carries no answer.
-- By default only the outcome is stored (answer_kept = 0, answer_text NULL).
-- answer_text is kept only on the learner's explicit opt-in (answer_kept = 1);
-- it stays local and never goes into a feed or a packet (the extraction
-- contract excludes attempt texts). Revised in increment 5 (R2-044/045).
CREATE TABLE practice_attempts (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_key           TEXT    NOT NULL UNIQUE,
    practice_id             TEXT    NOT NULL,
    source_id               TEXT    NOT NULL,
    source_revision_sha256  TEXT    NOT NULL CHECK (length(source_revision_sha256) = 64),
    action                  TEXT    NOT NULL CHECK (action IN ('attempt', 'reveal')),
    outcome                 TEXT    NOT NULL CHECK (outcome IN ('correct', 'incorrect', 'self_check', 'revealed', 'invalid')),
    self_check              TEXT    CHECK (self_check IS NULL OR self_check IN ('got', 'notyet')),
    answer_text             TEXT,
    answer_kept             INTEGER NOT NULL DEFAULT 0 CHECK (answer_kept IN (0, 1)),
    local_day               TEXT    NOT NULL,
    zone                    TEXT    NOT NULL,
    created_at              TEXT    NOT NULL,
    CHECK ((action = 'reveal') = (outcome = 'revealed')),
    CHECK (action = 'attempt' OR answer_text IS NULL),
    CHECK (self_check IS NULL OR outcome IN ('self_check', 'revealed')),
    CHECK (answer_text IS NULL OR answer_kept = 1)
);
CREATE INDEX idx_practice_attempts_item ON practice_attempts(practice_id, id);

-- Deferred items (013–014), append-only: a defer hides item_key from Review
-- Today until defer_until_day in zone; an undo row cancels one defer row.
CREATE TABLE review_defers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_key    TEXT    NOT NULL UNIQUE,
    item_key         TEXT    NOT NULL,
    action           TEXT    NOT NULL CHECK (action IN ('defer', 'undo')),
    defer_until_day  TEXT,
    zone             TEXT    NOT NULL,
    refers_to        INTEGER REFERENCES review_defers(id),
    created_at       TEXT    NOT NULL,
    CHECK ((action = 'defer') = (defer_until_day IS NOT NULL AND refers_to IS NULL)),
    CHECK ((action = 'undo') = (refers_to IS NOT NULL AND defer_until_day IS NULL))
);
CREATE INDEX idx_review_defers_item ON review_defers(item_key, id);
-- Independent events (increment 5, R2-047): an undo cancels exactly one defer
-- of the same item, and a defer is undone at most once.
CREATE UNIQUE INDEX idx_review_defers_one_undo ON review_defers(refers_to) WHERE action = 'undo';
CREATE TRIGGER review_defers_undo_targets_defer BEFORE INSERT ON review_defers
WHEN NEW.action = 'undo' AND NOT EXISTS (
    SELECT 1 FROM review_defers d WHERE d.id = NEW.refers_to AND d.action = 'defer' AND d.item_key = NEW.item_key)
BEGIN
    SELECT RAISE(ABORT, 'an undo refers to a defer of the same item');
END;

-- Personal corrections to practise later, append-only: 'add' keeps the
-- learner's corrected wording beside the original and the exact version it
-- corrects; 'retire' (done) refers to one add. Review Today lists open adds.
CREATE TABLE personal_corrections (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_key    TEXT    NOT NULL UNIQUE,
    action           TEXT    NOT NULL CHECK (action IN ('add', 'retire')),
    subject_kind     TEXT    CHECK (subject_kind IS NULL OR subject_kind IN ('speaking_transcript', 'writing_draft', 'notebook_entry', 'extraction_item')),
    subject_ref      TEXT,
    subject_version  INTEGER,
    original_text    TEXT,
    corrected_text   TEXT,
    refers_to        INTEGER REFERENCES personal_corrections(id),
    created_at       TEXT    NOT NULL,
    CHECK ((action = 'add') = (subject_kind IS NOT NULL AND subject_ref IS NOT NULL AND corrected_text IS NOT NULL
                               AND length(trim(corrected_text)) > 0 AND refers_to IS NULL)),
    CHECK ((action = 'retire') = (refers_to IS NOT NULL AND corrected_text IS NULL))
);
CREATE INDEX idx_personal_corrections_subject ON personal_corrections(subject_kind, subject_ref, id);
-- A retire closes exactly one add, at most once (increment 5).
CREATE UNIQUE INDEX idx_personal_corrections_one_retire ON personal_corrections(refers_to) WHERE action = 'retire';
CREATE TRIGGER personal_corrections_retire_targets_add BEFORE INSERT ON personal_corrections
WHEN NEW.action = 'retire' AND NOT EXISTS (SELECT 1 FROM personal_corrections a WHERE a.id = NEW.refers_to AND a.action = 'add')
BEGIN
    SELECT RAISE(ABORT, 'a retire refers to an add');
END;
```
<!-- proposed-sql:end -->

**Current state is read, never stored:**
- **Approval of a subject:** the latest decision row, if its `item_hash` equals the item's current
  hash. Otherwise the item is `needs_review`.
- **Deferred:** a `defer` row with no `undo` referring to it, and `defer_until_day` after today in
  the learner's zone.
- **Open correction:** an `add` row with no `retire` referring to it.
- **Outcomes per practice item:** read from `practice_attempts`, which is what
  `flh_practice_review_feed_v1` would report.

These queries run in the prototype check below.

**What each table replaces:**
- `practice_decisions` replaces the separate `practice_prompts` proposal (021/023/026) for
  notebook drafts. An edited draft is a `notebook_draft` decision with `edited_text`; a
  deliberate second version is subject `notebook:entry:N#2`.
- `review_defers` is the 013–014 proposal, made fully append-only: an undo row instead of
  updating `undone_at`.
- `personal_corrections` replaces 047's table rebuild. If the owner later wants corrections as
  notebook records, that rebuild can still happen; this table loses nothing.

## Comparison

| | A: reuse | B: four new tables |
|---|---|---|
| Faithful storage of all four | No | Yes |
| Touches existing tables or authority | Yes (admission → Concept support), or a rebuild of `learning_capture_sources` | No |
| Migration risk | Rebuild: needs a rehearsal like 021 | Additive `CREATE TABLE` / `CREATE INDEX` only |
| Idempotent writes | Not available on those tables | `operation_key UNIQUE`, the FLH-029 pattern |
| Append-only history | Partly | Yes, including undo and retire |
| Public demo | Unaffected | **Affected:** the demo checks that the artifact's ledger equals the embedded migrations, so artifacts are rebuilt and the four tables must be empty and unlisted (release lane) |
| Work after approval | Small but wrong | Repositories, services, routes and UI wiring for each kind: one slice at a time |

## Migration effects

**Forward:**
- Four `CREATE TABLE` and four `CREATE INDEX` statements, in one migration transaction, with the
  ledger row in the same transaction (`internal/storage/sqlite/db.go`).
- Existing rows, tables and constraints are byte-identical afterwards (checked below).
- No backfill: page-only state was never stored, so there is nothing to migrate. A learner's open
  pages lose their page state on reload, as they already say.

**Rollback (`docs/RELEASE.md`):**
- Migrations are forward-only. To roll back, restore the backup taken before the upgrade and start
  the older image.
- Everything written to the four tables after that backup is lost, along with all other writes.
- An older image would not refuse the newer database and would ignore the four tables, since none
  of its code reads them. The documented rule stays: never run an older image on a newer
  database; restore instead.

**Release and demo:**
- A rehearsal like 021's for `021 → 0NN`. It is additive, so no rebuild checks are needed: schema
  diff, ledger, integrity and foreign keys only.
- The public demo artifacts need a rebuild (ledger equality), with the new tables empty.

## Checked as a prototype (no migration file was added)

```bash
python3 -I -B scripts/validation/extraction_practice/storage_prototype.py "$(mktemp -d)" [--compare-with SERVER_DB]
```

`--compare-with` takes a database the current server created on its first start. It proves the
scratch 021 schema is the server's own; it was identical (91 objects) in this run.

**What the check does:**
1. Builds a scratch database with migrations 001–021 in the server's order.
2. Adds synthetic rows to existing tables.
3. Applies the SQL above.
4. Checks that every existing object and row is unchanged.
5. Checks every constraint with valid and invalid rows.
6. Runs the four current-state queries.
7. Rehearses the rollback by restoring the pre-migration copy.

## Owner decisions

1. Option B, or stay page-only.
2. A migration number.
3. Whether `answer_text` is stored (default: yes, local only) or never stored.
4. Whether the extraction lane's own decision and attempt JSONL moves to these tables. That is
   their contract, so it needs their agreement.

## Increment 5: inventory, ownership and evidence (revision 2)

### Where this state lives today, and who would read the tables (R2-041)

**Where the state lives today:**

| State | Today, where | Stored? |
|---|---|---|
| Practice approvals | the extraction tool's `flh_practice_decision_v1` JSONL (that lane); notebook practice drafts: approval is the retry mark (`mistake_retry_marks`), edited wording page-only (`NotebookPractice.tsx`); agent corrections accepted "for this visit" in the prototype (`practiceSession.ts` `accepted`) | JSONL in that lane's work directory; retry mark stored; the rest page-only |
| Practice attempts | the extraction tool's `flh_practice_attempt_v1` JSONL; the prototype visit (`practiceSession.ts` `attempts`, `checks`); Recall Practice and notebook retry sessions (component state); Mock Exam answers (`exam_answers`, stored, its own session) | page-only except the extraction JSONL and exam answers |
| Deferred items | "Hide for this visit" in Review Today (`ReviewToday.tsx` `hidden`) | page-only |
| Personal corrections | Speaking's own corrections (`speaking_transcripts`, origin `corrected`, stored); edited notebook draft wording (page); the prototype's saved mistakes (`practiceSession.ts` `personal`) | partly stored (Speaking), the rest page-only |

**Readers of each proposed table** (none exists yet):

| Table | Would be read by |
|---|---|
| `practice_decisions` | the extraction feed and packet export (which knowledge is approved; `needs_review` after a revision); notebook practice (the edited draft); the history export |
| `practice_attempts` | Review Today (reason `practice_outcome`, today's set); the learning week (counts by local day and skill); the history export (answer text only when kept); the feed's `outcomes`; the packet's `last_confusion` and `next_exercise` |
| `review_defers` | Review Today (hide until the day; undo); the learning week ("deferred"); the history export |
| `personal_corrections` | Review Today (an open correction is due practice); Speaking and notebook views (the learner's wording beside the original); the history export |

### Field ownership (R2-043)

| Field (all four tables) | Written by | Authority |
|---|---|---|
| `operation_key` | the client, once per learner action (UUID) | idempotency only: a replay returns the stored row, a changed payload is `409` |
| `subject_kind`, `subject_id`, `item_key`, `subject_ref`, `practice_id` | the server, from the item the learner acted on (never typed by the learner) | identity of the thing acted on; `practice_id` and knowledge IDs are the extraction lane's stable IDs |
| `source_id`, `source_revision_sha256`, `item_hash`, `subject_version` | the server, copied from the feed or record version shown | the version the action was made on; a decision counts only while `item_hash` is current |
| `action` | the learner's explicit choice (approve, reject, edit; attempt, reveal; defer, undo; add, retire) | the learner |
| `outcome` | the grader (exact match) or `self_check` / `revealed` by rule | the grading rule (`grade()` parity); never the learner |
| `self_check` | the learner (I had it / Not yet) | the learner's judgment, kept apart from `outcome` |
| `answer_text`, `answer_kept` | the learner, only with an explicit opt-in per attempt | the learner; never in a feed, packet or default export |
| `edited_text`, `corrected_text`, `original_text` | the learner (or an accepted agent proposal, with its provenance in `reason`) | the learner |
| `defer_until_day`, `zone`, `local_day` | the server from the learner's zone | Workbooks' scheduling (no interval, no algorithm stored) |
| `refers_to` | the server (the row undone or retired) | the triggers below |
| `created_at` | the server clock | ordering only |

**Derived on read, never stored:**
- the current approval state, deferred items, open corrections and due practice;
- weekly counts;
- today's set.

### Revision 2 and its evidence (scratch databases only)

`storage_prototype.py WORK --compare-with SERVER_DB --visit-export EXPORT.json`. The scratch 021
schema must equal a server-built one. Results are in `evidence/` at the 050 checkpoint.

| Item | What was shown |
|---|---|
| R2-044 outcome only | Rows without answer text still give the same feed outcomes and week counts; no text column is needed for any reader |
| R2-045 opt-in | An answer text is refused unless that attempt has `answer_kept = 1` (CHECK); with the opt-in it is kept |
| R2-046 duplicate submits | Three resends of one `operation_key` replay. The same key with a changed payload is a conflict. The week's counts do not move |
| R2-047 defer and undo | Defer A, defer B, undo A, defer A again: four rows, each its own event. The second undo of a defer, an undo of an undo, and an undo naming another item's defer are refused (unique index, trigger) |
| R2-048 correction → due | An open correction is due at once. Deferred, it is hidden until its day. It is due again after, and gone once retired |
| R2-053 interrupted write | The approval is its own write: a crash before the attempt's COMMIT keeps the approval and no attempt. With both in one transaction, neither is kept |
| R2-054 weekly counts | Counts read committed attempts only: an approval, an interrupted write or a resend adds nothing |
| R2-055 backup and restore | The browser walkthrough's exported visit loads as attempts. A backup per `docs/RELEASE.md` (copy, `integrity_check`, SHA-256) restores it row for row |

`upgrade_rehearsal.py WORK` runs the real server on a throwaway database:
- **R2-052:** the server revises an authored script to revision 2, then the proposed SQL is
  applied. Lesson, revisions, Review Today, the week and the notebook read identically. The
  revised exercise stays revision 2.
- **R2-057:** an export made before the upgrade is inspected after it: complete, 0 new, 0
  conflicts. A new export equals it.
- **R2-056:** the rollback loses exactly what was written after the backup.

### What disappears on reload in the prototype today (R2-049)

| Action in the prototype | Kept while the page lives | After a reload |
|---|---|---|
| Panel open, today's set progress, opened concept | yes (also across workbench views) | gone: panel closed |
| Drafts, checks in flight, answers, reveals, self-checks | yes | gone |
| Revisions applied ("Simulate the next feed") and kept drafts | yes | gone: back to revision 1 |
| Saved mistakes (personal items), corrections accepted for the visit | yes | gone |
| Simulated slow check, the visit log, the week view | yes | gone |
| The exported visit JSON | only what the learner copied to the clipboard | the copy stays where the learner pasted it |

Every row above is labelled in the page ("Disappears on reload…"). The walkthrough checks that a
reload leaves the panel closed and no state behind (no web storage written).

## Revision 3 (R3, 2026-11-20): minimum persistence, optional parts, and the 2.2 contract

**Status: PROPOSED; still no migration file.** Revision 2 above stays as the record of increment 5.
This revision splits the proposal into a **minimum** and two **optional** parts.

**Changes from revision 2:**
- It applies the extraction lane's amendment
  (`extraction2-20261119/handoff-2.2/sample/workbooks2/STORAGE-DECISION-RECORD.md`).
- The learner's free-text retention is its own decision (R3-041–R3-045).
- Every table enforces append-only in SQL.

**Checked on scratch databases only:**
```bash
python3 -I -B scripts/validation/extraction_practice/storage_r3.py "$(mktemp -d)" --rows HANDOFF_2_2/sample/workbooks2/storage-rows.json
```

### Review against the live contract (R3-041)

| Contract element (Extraction 2.2) | Revision 2 | Revision 3 |
|---|---|---|
| practice ID stable across revisions, `withdrawn`/`restored`/`added`, `reason_code`, `since_revision`, `feed_id`/`feed_seq` | not stored, and need not be: feeds are rebuildable and replay-safe by `feed_id` | unchanged: attempts keep `practice_id` and the revision they were made on, so a withdrawn item's history survives and a restored one continues it |
| learner decision with `draft_id`, `material_hash`, batch, `via`, attestation | no column for the 2.2 context | `provenance_json` (JSON-checked), from the amendment |
| agent exercise decision | refused (`subject_kind`) | `agent_exercise`, from the amendment |
| attempt and reveal, never correct when revealed | yes | yes |
| `text_omitted: true` in exports; no attempt text in feeds or packets | `answer_kept` per attempt | text only while the learner's **retention decision** is on (below); exports keep their own `text_omitted` rule |
| deterministic `operation_key` (a hash of source, record kind and sequence) | UUID from the client | either; both are UNIQUE, so an import of the extraction JSONL is idempotent |

### Minimum versus optional (R3-042)

| Part | Tables | Needed for | Without it |
|---|---|---|---|
| **minimum** | `practice_attempts` (outcome only: no text column), `review_defers` | practice history and "Not today" surviving a reload; the weekly counts | page-only, as today |
| **optional A: answer text** | `practice_text_retention` (the learner's decision), plus `practice_attempts.answer_text` (added by `ALTER TABLE … ADD COLUMN`, enforced by a trigger) | recomputing a matched variant or a known confusion later | outcomes stay; the "known confusion" link of an old miss cannot be rebuilt (Extraction 2.2 §7) |
| **optional B: decisions** | `practice_decisions` (amended), `personal_corrections` | approvals and corrections kept in Workbooks instead of the extraction JSONL | the extraction lane's JSONL stays authoritative |

### Raw response fields that must not persist by default (R3-043)

| Field | Default |
|---|---|
| the typed answer of an attempt | **not stored**: there is no column in the minimum |
| a reveal's text | never: a reveal has no answer |
| a self-check note | never (the self-check is `got` or `notyet`) |
| a matched variant or known error | not stored; recomputed when the text is kept |
| an agent's raw return or a packet body | not stored; only its provenance IDs, in `provenance_json` |
| Speaking audio | never stored anywhere (unchanged) |

### A separate learner decision for free-text retention (R3-044)

- `practice_text_retention` holds append-only rows (`keep_answer_text` 1 or 0).
- The **latest** row decides. A trigger refuses an attempt with text unless that row says keep.
  With no row at all, nothing is kept.
- This decision is separate from every practice action, so changing it changes no outcome.
- Turning it off can be followed by an erase. The one mutation the triggers allow is
  `UPDATE practice_attempts SET answer_text = NULL`. Any other update or delete of an attempt is
  refused.

### Idempotent writes and conflicts (R3-045)

- Every row has a UNIQUE `operation_key`.
- The application writes once, using `insert_once` in the prototype:

| The same `operation_key` arrives with | Result |
|---|---|
| the same payload | the stored row (a replay) |
| any other payload | a conflict (`409`), never an overwrite |

- A deterministic key derived by the extraction lane makes a re-import of its JSONL a replay.
- Attempts and reveals are intentionally new events, each with its own key.

<!-- proposed-sql-r3-minimum:start -->
```sql
-- 0NN_practice_state.sql, revision 3, MINIMUM (number allocated by the owner). Additive only.
CREATE TABLE practice_attempts (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_key           TEXT    NOT NULL UNIQUE,
    practice_id             TEXT    NOT NULL CHECK (practice_id GLOB 'p-[0-9a-f]*' AND length(practice_id) = 14),
    source_id               TEXT    NOT NULL,
    source_revision         INTEGER CHECK (source_revision IS NULL OR source_revision >= 1), -- the number when known (2.2 feeds carry it; imported JSONL may not)
    source_revision_sha256  TEXT    NOT NULL CHECK (length(source_revision_sha256) = 64),
    action                  TEXT    NOT NULL CHECK (action IN ('attempt', 'reveal')),
    outcome                 TEXT    NOT NULL CHECK (outcome IN ('correct', 'incorrect', 'self_check', 'revealed', 'invalid')),
    self_check              TEXT    CHECK (self_check IS NULL OR self_check IN ('got', 'notyet')),
    local_day               TEXT    NOT NULL,
    zone                    TEXT    NOT NULL,
    created_at              TEXT    NOT NULL,
    CHECK ((action = 'reveal') = (outcome = 'revealed')),
    CHECK (self_check IS NULL OR outcome IN ('self_check', 'revealed'))
);
CREATE INDEX idx_practice_attempts_item ON practice_attempts(practice_id, id);
CREATE INDEX idx_practice_attempts_day ON practice_attempts(local_day);
CREATE TRIGGER practice_attempts_no_delete BEFORE DELETE ON practice_attempts
BEGIN SELECT RAISE(ABORT, 'practice attempts are append-only'); END;
CREATE TRIGGER practice_attempts_no_update BEFORE UPDATE ON practice_attempts
BEGIN SELECT RAISE(ABORT, 'practice attempts are append-only'); END;

CREATE TABLE review_defers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_key    TEXT    NOT NULL UNIQUE,
    item_key         TEXT    NOT NULL,
    action           TEXT    NOT NULL CHECK (action IN ('defer', 'undo')),
    defer_until_day  TEXT,
    zone             TEXT    NOT NULL,
    refers_to        INTEGER REFERENCES review_defers(id),
    created_at       TEXT    NOT NULL,
    CHECK ((action = 'defer') = (defer_until_day IS NOT NULL AND refers_to IS NULL)),
    CHECK ((action = 'undo') = (refers_to IS NOT NULL AND defer_until_day IS NULL))
);
CREATE INDEX idx_review_defers_item ON review_defers(item_key, id);
CREATE UNIQUE INDEX idx_review_defers_one_undo ON review_defers(refers_to) WHERE action = 'undo';
CREATE TRIGGER review_defers_undo_targets_defer BEFORE INSERT ON review_defers
WHEN NEW.action = 'undo' AND NOT EXISTS (
    SELECT 1 FROM review_defers d WHERE d.id = NEW.refers_to AND d.action = 'defer' AND d.item_key = NEW.item_key)
BEGIN SELECT RAISE(ABORT, 'an undo refers to a defer of the same item'); END;
CREATE TRIGGER review_defers_no_change BEFORE UPDATE ON review_defers
BEGIN SELECT RAISE(ABORT, 'review defers are append-only'); END;
CREATE TRIGGER review_defers_no_delete BEFORE DELETE ON review_defers
BEGIN SELECT RAISE(ABORT, 'review defers are append-only'); END;
```
<!-- proposed-sql-r3-minimum:end -->

<!-- proposed-sql-r3-retention:start -->
```sql
-- revision 3, OPTIONAL A: the learner's decision to keep answer text (after the minimum).
CREATE TABLE practice_text_retention (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_key     TEXT    NOT NULL UNIQUE,
    keep_answer_text  INTEGER NOT NULL CHECK (keep_answer_text IN (0, 1)),
    created_at        TEXT    NOT NULL
);
CREATE TRIGGER practice_text_retention_append_only BEFORE UPDATE ON practice_text_retention
BEGIN SELECT RAISE(ABORT, 'the retention decision is append-only: add a new row'); END;
ALTER TABLE practice_attempts ADD COLUMN answer_text TEXT CHECK (answer_text IS NULL OR length(answer_text) <= 2000);
CREATE TRIGGER practice_attempts_text_needs_retention BEFORE INSERT ON practice_attempts
WHEN NEW.answer_text IS NOT NULL AND (NEW.action = 'reveal' OR coalesce(
    (SELECT keep_answer_text FROM practice_text_retention ORDER BY id DESC LIMIT 1), 0) != 1)
BEGIN SELECT RAISE(ABORT, 'answer text is kept only while the learner chose to keep it, and never on a reveal'); END;
DROP TRIGGER practice_attempts_no_update;
CREATE TRIGGER practice_attempts_only_erase_text BEFORE UPDATE ON practice_attempts
WHEN NOT (NEW.answer_text IS NULL AND NEW.id = OLD.id AND NEW.operation_key = OLD.operation_key AND NEW.practice_id = OLD.practice_id
          AND NEW.source_id = OLD.source_id AND NEW.source_revision = OLD.source_revision AND NEW.source_revision_sha256 = OLD.source_revision_sha256
          AND NEW.action = OLD.action AND NEW.outcome = OLD.outcome AND NEW.self_check IS OLD.self_check AND NEW.local_day = OLD.local_day
          AND NEW.zone = OLD.zone AND NEW.created_at = OLD.created_at)
BEGIN SELECT RAISE(ABORT, 'only erasing the answer text is allowed'); END;
```
<!-- proposed-sql-r3-retention:end -->

<!-- proposed-sql-r3-decisions:start -->
```sql
-- revision 3, OPTIONAL B: decisions (with the Extraction 2.2 amendment) and personal corrections.
CREATE TABLE practice_decisions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_key           TEXT    NOT NULL UNIQUE,
    subject_kind            TEXT    NOT NULL CHECK (subject_kind IN ('extraction_item', 'notebook_draft', 'agent_exercise')),
    subject_id              TEXT    NOT NULL,
    source_id               TEXT    NOT NULL,
    source_revision_sha256  TEXT    NOT NULL CHECK (length(source_revision_sha256) = 64),
    item_hash               TEXT    NOT NULL,
    action                  TEXT    NOT NULL CHECK (action IN ('approve', 'reject', 'edit')),
    edited_text             TEXT,
    reason                  TEXT,
    provenance_json         TEXT    CHECK (provenance_json IS NULL OR json_valid(provenance_json)),
    created_at              TEXT    NOT NULL,
    CHECK ((action = 'edit') = (edited_text IS NOT NULL AND length(trim(edited_text)) > 0))
);
CREATE INDEX idx_practice_decisions_subject ON practice_decisions(subject_kind, subject_id, id);
CREATE TRIGGER practice_decisions_append_only BEFORE UPDATE ON practice_decisions
BEGIN SELECT RAISE(ABORT, 'practice decisions are append-only'); END;
CREATE TRIGGER practice_decisions_no_delete BEFORE DELETE ON practice_decisions
BEGIN SELECT RAISE(ABORT, 'practice decisions are append-only'); END;

CREATE TABLE personal_corrections (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_key    TEXT    NOT NULL UNIQUE,
    action           TEXT    NOT NULL CHECK (action IN ('add', 'retire')),
    subject_kind     TEXT    CHECK (subject_kind IS NULL OR subject_kind IN ('speaking_transcript', 'writing_draft', 'notebook_entry', 'extraction_item')),
    subject_ref      TEXT,
    subject_version  INTEGER,
    original_text    TEXT,
    corrected_text   TEXT,
    refers_to        INTEGER REFERENCES personal_corrections(id),
    created_at       TEXT    NOT NULL,
    CHECK ((action = 'add') = (subject_kind IS NOT NULL AND subject_ref IS NOT NULL AND corrected_text IS NOT NULL
                               AND length(trim(corrected_text)) > 0 AND refers_to IS NULL)),
    CHECK ((action = 'retire') = (refers_to IS NOT NULL AND corrected_text IS NULL))
);
CREATE INDEX idx_personal_corrections_subject ON personal_corrections(subject_kind, subject_ref, id);
CREATE UNIQUE INDEX idx_personal_corrections_one_retire ON personal_corrections(refers_to) WHERE action = 'retire';
CREATE TRIGGER personal_corrections_retire_targets_add BEFORE INSERT ON personal_corrections
WHEN NEW.action = 'retire' AND NOT EXISTS (SELECT 1 FROM personal_corrections a WHERE a.id = NEW.refers_to AND a.action = 'add')
BEGIN SELECT RAISE(ABORT, 'a retire refers to an add'); END;
CREATE TRIGGER personal_corrections_append_only BEFORE UPDATE ON personal_corrections
BEGIN SELECT RAISE(ABORT, 'personal corrections are append-only'); END;
```
<!-- proposed-sql-r3-decisions:end -->
