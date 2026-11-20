# NAS → AWS cutover and its rollback: dry runs (owner-run on the real hosts)

**One rule:** exactly one writable instance at any time. Two diverged SQLite
databases are never merged.
- **Status:** these are dry runs. The stand-in executed every step locally
  with the real image and the bundle's own `flh-daily.sh`. Results are in
  STANDIN-REHEARSAL.md §17–19.
- **Not run:** nothing here touched the NAS, AWS or DNS.
- **Prerequisite:** the cutover is a separate owner decision after a
  successful staging pass (RUNBOOK.md). This file does not authorize it.

**Definitions:**
- **T0:** the moment `flh-daily.sh stop` returns on the NAS. Before T0 the
  NAS is the only writer; from T0 until T1 nobody writes.
- **T1:** the moment private access (the SSH/SSM alias or tailnet name the
  learner's browser uses) points at AWS.
- **`DUMP(db)`:** `sqlite3 -readonly "$db" .dump | sha256sum`. It is equal for
  byte copies and unaffected by WAL checkpoints. Run it only on a stopped
  service or on a copy.
- **`COUNTS(db)`:** the backup contract agreed with the Workbooks lane (R3-041,
  2026-11-20): row count and `max(rowid)` of **every** table except
  `schema_migrations` (compared as the ledger) and the rebuildable semantic
  caches (`semantic_index_*`, `semantic_embedding_cache`). That is 46 of the 53
  tables at migration 021.
  - `max(rowid)`, not `max(id)`: some tables have no `id` column.
  - `cutover_check.py` measures every table (rows, `max(rowid)` and a digest)
    on a scratch copy, so it is at least this strict.

**Rules from the Workbooks lane's rehearsals:**
- **Never copy `app.db` without its `-wal` file, and never while the service
  writes.** A live copy missed committed rows: 101 rows copied against 127
  committed.
- **Never hold a connection beside a running server.** An outside connection
  holding the write lock stalls every request (the server has one SQLite
  connection): writes fail after the 5 s busy timeout, and `/readyz` goes 503
  after 2 s.

**Additional acceptance, Workbooks-owned and read-only:** run
`python3 -I -B scripts/validation/migration/inventory.py SOURCE --out DIR` on
the NAS backup and on the AWS restored copy.
- Both must exit 0, with an equal `logical_digest` and equal `rows_by_table`.
- The tool checks foreign keys, notebook sources, the version chains
  1..N, one authored exercise per listening script revision, and no exam
  answer after its deadline or submission.
- Take it from the Workbooks lane's final **sealed** `workbooks-r3` handoff-100 (`SHA256SUMS`
  digest `758939cb4055…ca322`; `inventory.py` byte-identical to handoff-075, `90a1ad828d3e…d609a`)
  until it is on `main`. Its `docs/validation/R3-DATA-MIGRATION-AND-DAILY-LEARNING.md` §5 lists
  the related rehearsal commands. The seal carries it in `changes.patch`: apply that
  to a scratch export of the release commit, never to a checkout in use.
- **Rehearsed (release lane, 2026-11-20, stand-in):** after restoring the synthetic fixture and
  stopping the service, it reported READY on the source backup and on the restored data, with an
  equal `logical_digest` and equal `rows_by_table` (53 tables).

## Evidence and verdicts (`scripts/release/cutover_check.py`)

Record each step's measurement instead of copying values by hand, then ask for the verdict.
The tool reads every database from a scratch copy. Values and digests stay in the private
evidence file (0600); the check prints counts and same/different only. On the AWS host it is
`$ROOT/current/repo/scripts/release/cutover_check.py`.

```bash
CC="python3 -I scripts/release/cutover_check.py"; EV=~/flh-cutover-<date>.jsonl    # outside Git
$CC record $EV --step C2-boundary --host nas --db <FLH_DATA_DIR>/app.db           # T0, after stop
$CC record $EV --step C5-restored --host aws --db $ROOT/data/app/app.db --ready-url http://127.0.0.1:$PORT/readyz
$CC check $EV          # HOLD / DO-NOT-SWITCH / SWITCHED / ROLLBACK-A / ROLLBACK-B / ROLLED-BACK / DIVERGED
$CC template --out ~/flh-cutover-owner-checks.md                                  # DNS, identity, routing
```

The steps are C1-aws-empty, C2-boundary, C3-backup, C4-sent, C4-received, C5-restored, C6-smoke,
C7-switch, C8-first-write, then N-check (NAS), A-check (AWS stopped, at a rollback decision) and
R-restored. A failed check before C7 gives DO-NOT-SWITCH. After AWS writes, the check prints how
many rows a NAS restart would discard. The stand-in walkthrough is
`staging/rehearsal/aborted_cutover_rehearsal.py`.

## Preconditions

| # | Check | Command | Dry run |
| --- | --- | --- | --- |
| P1 | The AWS staging pass passed (RUNBOOK §5–7, every E row) | RUNBOOK §7 | E2–E6 PASS |
| P2 | The same release on both hosts, and the AWS bundle knows every migration in the NAS database | AWS: `flh-staging-bundle status` (commit, tree, image); NAS: `docker image inspect -f '{{.Id}}' french-learning-hub:local` and `sqlite3 -readonly <FLH_DATA_DIR>/app.db 'select count(*) from schema_migrations'` ≤ the bundle's `MANIFEST.json` `migrations.count` | P2 PASS |
| P3 | The NAS's latest backup verifies | `cd <backup> && sha256sum -c SHA256SUMS` | (13b) |
| P4 | Rollback window (e.g. 14 days) and who decides | written down | — |
| P5 | Public DNS answers recorded: `dig +short A/AAAA/CAA <public demo name>`, `dig +short NS <apex>` | read-only | — |

## Abort criteria (decided before T0; any one of them stops the cutover)

Write the time limit and the decider down at P4. "Abort" means: no switch, the NAS stays the only
writer. Before T1 nothing on the NAS changed, so the NAS restarts as it was (put the settings file
back first, step 2b in reverse).

| When | Abort if | `cutover_check.py` verdict | Then |
| --- | --- | --- | --- |
| before step 2 | any of P1–P5 is not met, or the AWS bundle knows fewer migrations than the NAS database | (not started) | do not start |
| step 3 | the backup's `sha256sum -c` fails, or `DUMP(backup)` ≠ T0 | DO-NOT-SWITCH | restart the NAS; take a new backup later |
| step 4 | the received file's `sha256sum -c` fails twice | DO-NOT-SWITCH | restart the NAS |
| step 5 | the restore is refused or not ready, `DUMP`/`COUNTS` ≠ T0, or `integrity_check` ≠ ok | DO-NOT-SWITCH | restart the NAS; AWS keeps its staging data aside |
| step 6 | search or replay ≠ 200, or `DUMP` changed | DO-NOT-SWITCH | restart the NAS |
| any step before 7 | the freeze window (now − T0) passes the limit written at P4 | HOLD → abort | restart the NAS; record why |
| after 7, before 8 | `flh-staging-bundle status` is not `IDENTITY OK`, or the access path fails | ROLLBACK-A (AWS took no write) | NAS settings back, start the NAS |
| after 8 | anything wrong with the data on AWS | ROLLBACK-B | procedure B only: never restart the NAS directly (the check prints how many rows that would discard) |
| any time | both sides were written after T0 | DIVERGED | stop both; never merge; the owner decides from the two backups |

## Cutover (18)

| Step | Where | Command | Expected | Dry run |
| --- | --- | --- | --- | --- |
| 1 | AWS (`ec2-user`) | `stg stop`; `mv "$ROOT/data/app" "$ROOT/data/app.staging-pass-$(date -u +%Y%m%dT%H%M%SZ)"`; `mkdir -m 700 "$ROOT/data/app"` | staging data kept aside, never deleted; service stopped | C1 PASS |
| 2a | NAS (learner has stopped writing, service still running) | `GET /learning-history/export?transcripts=true&notes=true` saved **beside the final backup** (learner data: the backup's encryption and retention, never in evidence or reports) | export file written | (R3, Workbooks contract) |
| 2 | NAS | stop using the workbench and any listening-pull timer; `bash scripts/daily/flh-daily.sh stop` | **T0**. Record the time | C2 PASS |
| 2b | NAS | **guard:** `mv ~/.config/flh/daily.env ~/.config/flh/daily.env.moved-to-aws-<date>`; then `bash scripts/daily/flh-daily.sh status` | `settings file not found`, exit 2. No NAS write can start, not even by habit or by a timer | C2 PASS (status and start both refused) |
| 2c | NAS | record `DUMP` and `COUNTS` of `<FLH_DATA_DIR>/app.db` | written down | C2 |
| 3 | NAS | `FLH_DAILY_ENV=~/.config/flh/daily.env.moved-to-aws-<date> bash scripts/daily/flh-daily.sh backup`; `sha256sum -c SHA256SUMS` in it | the service stays stopped; `DUMP(backup/app.db)` == T0 | C3 PASS (0.6 s) |
| 3b | NAS | Workbooks `inventory.py` on the backup directory (from its sealed handoff-075) | exit 0 (READY); `logical_digest` recorded | (R3; rehearsed with the sealed tool) |
| 4 | NAS → S3 → AWS | as RUNBOOK §6 (tar + `.sha256`, `aws s3 cp` to `backups/`, verify on the host before untarring) | `sha256sum -c` OK | C4 PASS |
| 5 | AWS | `stg restore "$ROOT/transfer/<backup>"` | ready; `DUMP` and `COUNTS` == T0; `PRAGMA integrity_check` = ok | C5 PASS (2.3 s) |
| 5b | AWS | `inventory.py` on a copy of the restored data; the export through the port forward, compared with 2a without `exported_at`/`generated_at`; then `POST /learning-history/import-preview` with the NAS export | exit 0 and the same `logical_digest` and `rows_by_table` as 3b; exports equal; preview complete, 0 new, 0 conflicts; `DUMP` unchanged | (R3; the preview never writes) |
| 6 | AWS (port forward) | one keyword search; open one source; **replay one stored capture** (`POST /captures` with its existing `capture_id` and identical content) | search 200, replay 200, `DUMP` unchanged | C6 PASS |
| 7 | client | point private access at AWS (the SSM port forward, RUNBOOK E10). **Public DNS is not involved** | **T1**. The freeze window (T1 − T0) is the time nobody can write | C7 PASS (3.3 s on the stand-in) |
| 8 | AWS | the owner's first real write | 201. From now on AWS holds the newest state | C8 PASS |
| 9 | NAS | keep it stopped and intact for the window: the data directory, the final backup, the image tagged `:before-cutover`, the moved settings file | `DUMP` of the NAS still equals T0 | C8 PASS |

## Rollback (19): first measure whether AWS accepted writes

Stop AWS (`stg stop`), then compute `DUMP` of `$ROOT/data/app/app.db`.

| Measurement | Case | Procedure |
| --- | --- | --- |
| `DUMP` == T0 | **A.** no AWS write | Move the NAS settings file back, `flh-daily.sh start` on the NAS, and point private access back. Nothing is lost |
| `DUMP` ≠ T0 and `integrity_check` ok | **B.** AWS accepted writes (the usual case) | Procedure B below. **Never** just restart the NAS: it lacks every write after T1. The dry run listed them: `R0-naive-rollback-would-lose.json` |
| AWS database damaged | **C.** | Restore the newest good AWS backup with procedure B. If none is good, restore the NAS final backup, then re-enter the AWS-only captures (below) |

**Procedure B** keeps the writes accepted on AWS. Dry run: R1a–R2 PASS,
3.0 s on the stand-in.

1. **AWS:** `stg backup` with the service stopped. Record `DUMP` of the
   backup, which must equal the `DUMP` of AWS.
2. **Guard AWS against a second writer:**
   `mv "$ROOT/staging.env" "$ROOT/staging.env.rolled-back-to-nas-<date>"`.
   Every `stg` command is then refused.
3. **Transfer to the NAS:** tar + SHA-256, verified on arrival.
4. **Check compatibility before restoring.** The NAS release must know every
   migration in the AWS database: the AWS backup's
   `select count(*) from schema_migrations` must be ≤ the NAS release's
   migration count. If it is not, upgrade the NAS to the AWS release first.
   Never start an older image on a newer database.
5. **NAS:**
   `mv ~/.config/flh/daily.env.moved-to-aws-<date> ~/.config/flh/daily.env`,
   then `bash scripts/daily/flh-daily.sh restore <AWS backup>`. The NAS's T0
   data is kept as `<FLH_DATA_DIR>.before-restore-<stamp>`.
6. **Verify on the NAS:**
   - `DUMP` == the AWS backup's;
   - the first AWS-only record reads back;
   - `/readyz` is 200;
   - `integrity_check` is ok.
7. **Point private access back** to the NAS. Keep AWS stopped with its
   volume and backup until the post-rollback check, then tear down
   (RUNBOOK §9).

**Re-entering AWS-only captures (case C only):**
- **Export:** export the captures created after T1 from the last readable
  AWS database.
- **Re-import:** re-import them as `learning_capture_v1` documents with their
  original `capture_id`.
  - A replay adds nothing.
  - A differing one conflicts instead of overwriting.
- **No import path:** analyses, extractions, annotations, workbook revisions
  and Speaking takes made after T1 cannot be re-imported; list them for the
  owner.

## What the dry runs do not show

- **Real times:** real network transfer and EBS times. The stand-in's
  freeze window (3.3 s) is a lower bound; plan for the transfer of the real
  database size.
- **The real hosts:**
  - the NAS's own wrapper in normal (non-isolated) mode;
  - SSM port forwarding as the learner's access path;
  - the AWS host's power-off deadline.

**Bounded runtime and production use:** this staging root is bounded by
design. The host powers off after at most 12 h, and shutdown terminates the
instance. Moving daily use to AWS therefore needs a separate production
decision and configuration:
- continuous runtime, with shutdown not set to terminate;
- scheduled off-host backups;
- the budget.

Make that decision before T0, never after it.
