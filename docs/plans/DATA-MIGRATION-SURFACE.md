# The learner-data migration surface (R3-001–R3-010, 2026-11-20)

This covers the private learner data that daily practice and history depend on, and what moving it
from the NAS to the private staging host involves.

- **The move:** the release lane's documented cutover (`deploy/aws/private-staging/CUTOVER_DRY_RUN.md`,
  `scripts/release/cutover_check.py`).
- **The copy:** a byte copy of the SQLite database, made by `flh-daily.sh backup`. It is moved with
  `backup_tool.py pack/unpack`, put in place with the `docs/RELEASE.md` restore, and upgraded by the
  server's own migrations.
- **Data used here:** synthetic fixtures only. No real learner record was read for this document.

Machine-readable map: `scripts/validation/migration/entities.py`. Tools:
- `inventory.py`: read-only inventory and receipt;
- `rehearse.py`: backup, transfer, restore and parity on fixtures.

## R3-001 Private data stores used by daily practice and history

| Store | What it holds | Moves in a migration? |
|---|---|---|
| `app.db` (+ `-wal`, `-shm`) in `FLH_DATA_DIR` | every learner record: questions and contexts, captures and notebook links, retry marks, Listening, Reading and Writing material, Speaking takes (metadata) and transcripts, exam sessions, analyses, extractions, Concepts, annotation history | **yes**: the only store that must move |
| `FLH_DATA_DIR.backups/flh-*` | verified copies (`app.db`, `SHA256SUMS`) | the chosen backup is the transfer unit; old backups stay on the NAS |
| Qdrant (`FLH_QDRANT_DIR`) and the `semantic_*` tables | the vector index and its bookkeeping | no: rebuildable (`semantic-index rebuild`); the tables are copied as part of `app.db` |
| Browser `localStorage`, per origin | `flh.ui-locale.v1`, `flh.ui-theme.v1`, `flh.explanation-language.v1`, `flh.library.recent.v1`, **`flh.annotation-operations.v1`** (unresolved annotation writes awaiting retry), **`flh.concept-suggestion-requests.v1`** (unresolved suggestion requests) | no: per origin. A new host name starts empty. The two operation stores must be settled (retried or looked up) on the old origin **before** the switch (R3-076) |
| Page memory | the practice prototype's visit, Recall Practice, notebook practice drafts, Review Today's "Hide for this visit" | no: lost on reload by design, and labelled so |
| History exports the learner downloaded (`learning_history_export_v1` NDJSON) | a portable copy | the learner's own files; `import-preview` can check one against any server |
| Extraction lane work directories (JSONL decisions, attempts, packets) | that lane's prototype state | not part of this database; that lane's decision |
| Speaking audio | browser only | **never stored**: there is no audio column, file or log |

## R3-002 Migration ledger and attachment references

- **Ledger:** `schema_migrations` holds 21 rows at this checkout (`001`…`021_listening_authored_scripts.sql`).
  - `inventory.py` compares a source's ledger with the destination checkout's `migrations/`:
    EQUAL, BEHIND (the server upgrades on start), AHEAD or FOREIGN (refuse).
  - The public demo also requires its artifact ledger to equal the embedded migrations.
- **Attachments:** the database stores no file or blob a learner made.

| Reference | Meaning | Checked by |
|---|---|---|
| `speaking_takes.audio_mime/bytes/sha256/duration_ms` | metadata of audio the browser kept; the audio itself was never stored | `inventory.py` counts takes with metadata; nothing to fetch or move |
| `listening_materials.source_url`, `reading_lessons.source_url` | external links, never fetched | counted, never followed |
| `learning_capture_sources (source_type, record_id, item)` | a notebook record names an item inside another record's JSON (`items`, `corrections`, `improvements`) | resolved row by row by `inventory.py` (and by the server's `MistakeSourceResolver`) |
| `semantic_embedding_cache.vector` | the only BLOB column: a cache | listed; rebuildable |

## R3-003 Capture IDs, source revisions and stable practice IDs

| Identifier | Where | Stable across a move? |
|---|---|---|
| `learning_captures.capture_id` → `entry_id` | idempotency key of an import, and its entry | yes: a byte copy keeps both. A re-import of the same `capture_id` on the destination replays (200) instead of duplicating (R3-075) |
| `entry_id`, notebook `(type, record_id, item)` | Mistake Notebook links | yes. Rehearsal: equal through the API on both fixtures |
| `listening_transcripts.version`, `reading_passages.version`, `writing_drafts.version`, `speaking_transcripts.version` | source revisions | yes: rows, counts per version and digests equal after restore |
| Script revision N (transcript N + its authored exercise) | an authored lesson's revisions | yes: compared through `/listening/materials/{id}/revisions` |
| `practice_id`, `knowledge_id`, `evidence_id` (extraction contract) | hashes of content, not database rows | unaffected: no Workbooks table stores them yet (the practice storage proposal would) |
| `operation_id` (requests, sessions) | idempotency of provider and exam requests | copied; never regenerated |

## R3-004 How current exports omit private response text

Measured on the v021 fixture (`evidence/r3-004/export-omission.json`):

| `learning_history_export_v1` option | Learner text it contains |
|---|---|
| default | **none**: no question, context, transcript, draft or notebook answer; structure, IDs, versions and dates only (3,375 bytes) |
| `transcripts=true` | adds Speaking transcript text (3 of 3), nothing else (3,696 bytes) |
| `notes=true` | adds questions (2/2), contexts (2/2), notebook answer attempts (2/2) and Writing drafts (2/2), but not transcripts (3,873 bytes) |
| both | all of the above (4,195 bytes) |
| any | exam choices are never exported (exam sessions are not in the export) |

## R3-005 Schema and feature versions of the fixtures

| Fixture | Ledger | Built by | Features present |
|---|---|---|---|
| `v021-daily` | 21 (`021_listening_authored_scripts.sql`) | this tree's server and `scripts/demo/learning_day/seed.py`, plus a Mock Exam session | authored script with a pack update offered, 2 notebook records (1 marked), Speaking 1 exercise / 2 takes / 3 transcript versions (an own correction), Writing 1 task / 2 drafts, exam 1 submitted session |
| `v020-legacy` | 20 (`020_mock_exams.sql`) | `scripts/release/upgrade_021/rehearse.py` populate (a local fake provider, no paid call) and its exact 020 conversion | 3 YouTube lessons (transcript v1 and v2), a failed preparation, 3 notebook records (listening, reading; 1 marked), a reading lesson, a Writing draft, a submitted exam |
| `walkthrough-20261118-ledger021.db` (older build) and `rehearsal-020.db` (earlier increment's fixtures) | 21 and 20 | earlier increments | used by `older_fixtures.py` |

Content digests, which identify the content independently of timestamps:
`v021-daily` `2ad2ff3f7cc8…` and `v020-legacy` `3e95bd6da7d6…`. Each was identical across two
independent builds.

## R3-006 Write points that must pause before a snapshot

- **48 HTTP write routes** (`POST`/`PUT`/`DELETE`; one of them, `POST /learning-history/import-preview`, writes
  nothing).
  - By area: Listening 8, knowledge units 8, Speaking 6, Writing 4, Reading 4, Exam 4, entries 5,
    captures 2, concepts 2, suggestions 2, notebook 1, analyses 1.
  - **`flh-daily.sh backup` stops the service first**, so all of them pause together, and the backup is
    taken only from a stopped database.
- **Command-line writers**, which must not run during a snapshot:
  - `/app/listening-pull`, and its optional systemd timer `flh-listening-pull` (it fails while the
    service is stopped, which is safe);
  - `semantic-index` (`build`/`sync`/`rebuild`: semantic tables and Qdrant);
  - `capture` (posts through HTTP, so it is paused with the service).
- **Readers that may keep running against a backup:** `history-export`, `inventory.py`, `backup_tool.py`.
- **Browser-side pending writes:** `flh.annotation-operations.v1` and
  `flh.concept-suggestion-requests.v1` hold unresolved requests. Settle them on the old origin before
  the cutover: retry with the same key, or look them up.

## R3-007 Each persisted entity and its destination field

The destination is the same schema, so every table maps to itself, column for column
(`entities.destination`). The move is a byte copy, then the server's own migrations.

| Source state | What happens to it |
|---|---|
| a 020 database | the server applies 021 on start (rebuilds `listening_materials` with `source_kind`, keeping IDs and the counter) |
| a 021 database | unchanged |

The history export is the only alternative format. Its kinds and the tables they come from:

| Export kind | Tables |
|---|---|
| `notebook_record` | `learning_entries`, `learning_captures`, `learning_capture_sources`, `mistake_retry_marks` |
| `listening_material` | `listening_materials`, `listening_transcripts`, `listening_exercises` |
| `speaking_take` | `speaking_takes`, `speaking_transcripts` |
| `writing_draft` | `writing_tasks`, `writing_drafts` |

Analyses, extractions, Concepts and exams are not exported.

## R3-008 When the previous schema must remain bootable

The previous server (020) must remain bootable, from its unchanged NAS data, until three things
hold:
1. the destination passed C5 (restored), C6 (smoke) and C8 (first write), per `cutover_check.py`;
2. the owner confirms `SWITCHED`;
3. a backup of the destination exists.

Until `C8`, rollback A only restarts the NAS with its data unchanged. After a write on the
destination, rollback is procedure B (restore the destination's backup onto the NAS), and that needs
the destination's schema.

Per `RELEASE.md`, a newer database never runs under an older image: restore instead. The pinned
pre-021 build itself is the owner's item (`45be549…`, not on this machine).

## R3-009 Data excluded from a rehearsal

- **Real learner data:** never read, copied or inventoried here. Moving it is a separate owner
  decision (R3-098).
- **Cache tables** (`semantic_*`): copied with the file, but not compared row by row. They are
  rebuildable, and empty in the fixtures.
- **Operational bookkeeping** (requests, leases, pull runs): copied and digested, but not
  interpreted.
- **Outside the database:** browser `localStorage`, page memory, Qdrant, the extraction lane's
  JSONL, and Speaking audio (never stored).

## R3-010 Fixture scope and acceptance cases

**Scope:** the two synthetic fixtures above (the current and the previous supported schema), built
twice each. The two older fixtures are used for compatibility.

**Acceptance**, each scripted in `rehearse.py` (40 checks on both fixtures):

| Area | Checks |
|---|---|
| Inventory | READY, and the source unchanged by it |
| Backup | made by the wrapper, `COMPLETE` |
| Pack | size and digest recorded |
| Transfer | interrupted, damaged and truncated archives refused, with nothing left behind |
| Restore | to a fresh private volume; integrity ok |
| Write readiness | passes; a read-only file or directory fails with its reason |
| Serving | the server starts on the restored data, and the ledger EQUALs the checkout |
| Stable IDs | notebook, listening and revisions, Review Today keys, Speaking takes and transcripts equal through the API |
| Counts and digests | every learner table equal (021's rebuild aside) |
| History export | equal, and `import-preview` complete with 0 new and 0 conflicts |
| Receipt | written |
| Repeat | a second restore equals; the source is untouched |
