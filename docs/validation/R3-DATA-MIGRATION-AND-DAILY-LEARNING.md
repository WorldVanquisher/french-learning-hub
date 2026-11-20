# R3: data migration and verified daily learning (Workbooks, 2026-11-20)

This file is evidence for the Workbooks R3 run (items R3-001 to R3-100). All data is synthetic,
seeded through the API or built by the sealed extraction code. Every check runs on scratch
databases outside the repository.

**What was not run:**
- No AWS resource, paid call or real-agent run was used.
- The new host was a local stand-in: a second server process with its own volume or data directory.

Item statuses, files and exact commands are in the sealed handoffs
(`flh-handoff/overnight-20261120-flh/workbooks-r3/handoff-0NN`).

## 1. Migration toolchain (R3-001 to R3-030)

### `scripts/validation/migration/inventory.py SOURCE --out DIR`

A read-only inventory of a database.

- **How it reads:** it copies the source files byte for byte and records each file's stat and
  SHA-256 before and after. It never prints a row value.
- **What it reports:** counts by role, references (foreign keys and notebook items), encoding,
  identifiers, times, private-text sizes, duplicates, ledger parity and per-table digests.
- **Invariants:**
  - version chains run 1..N without gaps;
  - each listening script revision has exactly one authored exercise;
  - no exam answer was saved after its deadline or its submission.
- **Exit codes:** 0 READY, 1 PROBLEMS, 3 PARTIAL, 4 REFUSE.
- **Tests:** `test_inventory.py`, 9/9.
- **Release lane agreement (R3-041 contract):** the restore runbook runs it on the source and on
  the restored copy. Both must exit 0, with an equal `logical_digest` and equal `rows_by_table`.

### `scripts/validation/migration/rehearse.py WORK`

The two fixtures:
- a 021 learning day;
- an exact 020 database.

For each fixture, the steps are:
1. inventory;
2. `flh-daily.sh backup` in isolated mode;
3. `backup_tool inspect` and `pack`;
4. refuse a half archive, a flipped byte and a truncated archive carrying its own digest;
5. unpack to a fresh volume and copy as RELEASE.md describes;
6. integrity check and `restore_write_check`;
7. serve both copies.

Once both copies are served, it checks:
- stable IDs through the API (notebook, listening, script revisions, Speaking takes and
  transcripts, Review Today keys);
- an equal history export, and `import-preview` reporting complete, 0 new and 0 conflicts;
- inventory parity;
- a receipt;
- a repeated restore leaves the source untouched.

### Daily learning after restore (`daily_after_restore.py`)

- **Learning day:** 89/89 checks on the source and 89/89 on the restored data. The check sets are
  identical (`differing: []`).
- **Practice journey:** 164/164 on the restored data.

## 2. Health and performance (R3-061 to R3-070)

Measured with `scripts/validation/migration/health_perf.py`. The same probe ran against two servers:
- **Start tree:** the server built from this run's start tree.
- **Fixed tree:** the server built from this tree.

The workload: N saved Mistake Notebook records, 30 of them marked for retry, plus 60 Speaking takes.
The Review Today queue was 33 items at every N.

### Review Today, sequential reads (median / p95, ms)

| Saved records | Start tree | Fixed tree |
|---|---|---|
| 40 | 31 / 69 | 26 / 37 |
| 600 | 466 / 595 | 31 / 37 |
| 2,400 | 1,203 / 1,324 | 42 / 54 |

The payload was 34.6 KB for 33 items, about 1.05 KB per item, at every size.

### Concurrency at 2,400 records (median / p95, ms)

The server has one SQLite connection, so requests are served one at a time. Eight clients is the
bound tested, not a promise.

| Clients | Start tree | Fixed tree |
|---|---|---|
| 1 reader | 1,097 / 1,163 | 41 / 44 |
| 8 readers | 8,902 / 9,615; 64 requests dropped | 341 / 390 |
| 4 readers + 1 writer | every request dropped | 245 / 305 |
| 8 readers + 1 writer | every request dropped | 476 / 519 |

"Dropped" means the server closed the connection without an answer.

- **Start tree at 600 records:** with 5 requests per client, every request was answered, but
  8 readers plus a writer took 5.2 s median. An earlier run with 10 requests per client exceeded the
  60 s client timeout.
- **Fixed tree:** every request was answered at every size.

### The slow path fixed (R3-065)

Review Today resolved every notebook record on every read: each record's source and its entry.
`MistakeNotebookService.ReviewItems` now resolves only the marked records and counts the rest for
`history`. The response is unchanged; `review_today_marked_test.go` proves the queue and history are
identical and that only the marked records are resolved.

### Query plans (R3-063)

Each SQL text was checked against the shipped Go source.

| Query | Plan |
|---|---|
| `ListSources` | `SCAN s` with a primary-key search on captures |
| `CurrentMarks` | `SCAN m` with a correlated subquery on the covering index `idx_mistake_retry_marks_entry` |
| `GetSourceByEntry` | the covering autoindex |

Nothing needs an index.

### Still linear

- **The full notebook list:** `GET /mistake-notebook/items` resolves every record: about 1.4 s at
  2,400 records.
- **A large queue:** with the queue itself grown (`review_today/browser_perf.py`), 423 items took
  154 ms median for 467 KB, and the page was ready in 0.21–0.35 s. 1,323 items took 502 ms for
  1.47 MB, ready in about 1 s. There was one request per visit, and window and document listeners
  stayed at 18 over 10 cycles.

Paging either the list or the queue is an API change, left for a later task.

### Counters (R3-066)

- Five reads without a write return the same keys and history counts.
- A mark adds exactly that record; the unmark restores the earlier values.

### Errors (R3-067)

Each documented failure answers with a JSON `{"error": …}` that says what is wrong, with no path,
stack, driver text or learner text:

| Failure | Status |
|---|---|
| unknown record | 404 |
| malformed JSON | 400 |
| unknown zone | 400, naming an example zone |
| capture without input | 422 |
| item already saved | 409 `source_already_saved`, naming the record |
| unknown notebook record | 404 |
| extraction disabled | 503 |

The one exception is an unknown route: net/http's plain-text 404.

### SQLite busy (R3-068)

An outside connection held the write lock (`BEGIN IMMEDIATE`) while a write, a read and `/readyz`
arrived.

| Lock held | Write | Read | `/readyz` |
|---|---|---|---|
| 1.5 s | waited, then 200 | 200 after 1.5 s | 200 after 1.4 s |
| 6.5 s | 500 "could not record the retry decision" after the 5 s busy timeout | waited 5 s, then 200 | 503 after 2 s |

With one connection, every request queues behind a write that is waiting for the lock. That is why
the Release runbook only dumps a stopped service or a copy.

## 3. Cutover edges (R3-071 to R3-080)

`scripts/validation/migration/cutover_edges.py WORK` ran 18/18 checks. Every verdict comes from
`scripts/release/cutover_check.py` on real measurements.

| Case | Verdict |
|---|---|
| copy of app.db (without WAL) taken during writes: 101 rows of 127 committed | DO-NOT-SWITCH (C3 fails); a copy after the stop passes |
| capture during the freeze | refused at the connection, nothing written; created once after the switch, then replayed |
| C1–C8 | HOLD before the switch, SWITCHED after; the old host unchanged |
| warm-up fails after the switch, no write on the new host | ROLLBACK-A; the old host's export equals its pre-boundary export |
| both hosts written | DIVERGED; captures re-entered by `capture_id`: 201 once, 200 replay, 409 when changed |
| archive truncated in transit / missing | DO-NOT-SWITCH (C4 fails) / refused at record time |

Two static checks also ran:
- The server sets no cookie and keeps no session. The browser keeps six per-origin `flh.*` keys,
  each with a default.
- The public-demo allowlist names no private learner route, and its tests pass.

## 4. Daily use (R3-081 to R3-090)

### Interactions to the first graded answer

Measured with `practice_feed/measure.mjs` at desktop and 320 px.

| Path | Baseline | This run |
|---|---|---|
| via today's set | 28 | 28 |
| via "Open the concept" | 38 | 34 |

The "Open the concept" path dropped because the page's section menu is now collapsed: one Tab stop
until opened. The scripted wall-clock time was 1.2–1.9 s.

### UI changes

All covered by tests:
- **Extraction 2.2 reason codes:** explained in both catalogs; an unknown code is shown verbatim.
- **Not offered:** the claims the feed does not offer, with each quote's grounding.
- **Feed timeout:** the revision and draft are kept, and the retry is explicit.
- **A finished concept:** the page offers the next concept, or the study packet.
- **Failed "Done for today" save:** focus returns to that item's button.
- **Timeout notice:** it holds its own id, so ids stay unique.

### Browser runs

- The practice journey passes 164/164 with these changes in five combinations: desktop English,
  320 px English and Chinese, 200 % zoom and large text.
- The French and Chinese text of the new list fits at 320 px.

## 5. Commands for Release (R3-097)

```
python3 -I -B scripts/validation/migration/inventory.py SOURCE --out DIR           # before and after restore
python3 -I scripts/validation/migration/rehearse.py WORK                            # backup/restore rehearsal (Docker)
python3 -I scripts/validation/migration/cutover_edges.py WORK [--binary SERVER]     # cutover edges, local stand-in
python3 -I scripts/validation/migration/health_perf.py WORK [--binary SERVER]       # read path at 40/600/2400 records
python3 -I scripts/validation/migration/daily_after_restore.py WORK --rehearsal R --handoff H21
python3 -I scripts/validation/extraction_practice/storage_r3.py WORK --rows H22/sample/workbooks2/storage-rows.json
```

## 6. Pinned versions (R3-096)

**Schema and seals:**
- Schema ledger: `001`–`021`.
- Extraction 2.1 handoff: SHA256SUMS `bad6f86e…`.
- Extraction 2.2 handoff: SHA256SUMS `e529568b…`.

**Contracts:** `learning_capture_v1`, `review_today_v1`, `learning_history_export_v1`,
`flh_practice_review_feed_v1` with `flh_practice_feed_additions_v1`, `flh_practice_packet_v2`,
`flh_migration_inventory_v1`, `flh-cutover-evidence/v1`.

**Browser checks:** Playwright 1.49.1 in `node:22-bookworm-slim`.

## 7. Open owner decisions (R3-098)

**Practice storage:**
- Which parts to ship: minimum, optional A (retention) or optional B (decisions).
- The migration number (022 proposed).
- Whether answer text is ever kept.
- The extraction lane's agreement, needed for part B.

See `docs/plans/PRACTICE-STORAGE-RELEASE-RECORD.md`.

**Real learner data:** migrating it, the staging target, AWS and DNS remain separate owner
decisions.

**Paging:** the full notebook list and a very large queue (section 2).
