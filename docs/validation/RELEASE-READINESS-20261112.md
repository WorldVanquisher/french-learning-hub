# Release readiness, 2026-11-12

Evidence for three release-readiness checks on the tree at baseline
`c53b42c526e672e647ae024f058bbf078e498823` plus this change set. Everything ran
on one Linux workstation (Go 1.27.3, Docker 29.9.3 with Compose 5.7.0, Python 3.14.9,
sqlite3 3.54.1) against disposable databases in directories outside the repository.
No real provider, credential, daily database or daily container was used.
What was observed is separated from what still needs the owner.

## 1. Upgrade 020 → 021 and rollback

Command: `python3 -I scripts/release/upgrade_021/rehearse.py WORK_DIR`
(see [RELEASE.md](../RELEASE.md#rehearse-the-020--021-upgrade-before-applying-it)).

Observed (populated mode, final run):

| Stage | Result |
| --- | --- |
| build | PASS: current server (embeds 001–021) |
| populate | PASS: 3 YouTube lessons, 2 completed exercises and 1 failed preparation through a local fake Responses endpoint (3 calls, all to the fake), `no_transcript` 409 with no call, authored reading import, 3 Notebook records (2 `listening_item`, 1 `reading_item`), a retry mark, a writing draft, a submitted mock exam |
| fixture | PASS: converted to the 014 `listening_materials` shape with 021 removed from the ledger; whole schema equal to a pristine 001–020 database; 43 rows in 17 tables; AUTOINCREMENT counter 8 above max id 3 (raised on purpose to prove it is kept) |
| backup | PASS: RELEASE.md Backup block; directory mode 700, `integrity_check` = `ok`, `SHA256SUMS` |
| upgrade | PASS: 021 recorded once; 51 other tables byte-identical; 3 materials kept with the same id/link/title/timestamp as `youtube`; `sqlite_sequence` unchanged; `integrity_check` ok; `foreign_key_check` empty |
| notebook | PASS: `GET /mistake-notebook/items` and the lesson list identical to what the same server showed before the conversion |
| scripts | PASS: import 201 as material 9 (above the kept counter 8, no link or video id); replay 200 with `Idempotency-Replayed: true` and no rows written; learner transcript 409 `authored_script`; Notebook record from the script 201, replay 200, second record for the item 409 `source_already_saved`; retry toggle on an old listening record |
| conflict | PASS: on a copy with the imported script's title altered, import is 409 `script_conflict` and writes nothing |
| rollback | PASS: RELEASE.md Restore block; restored file byte-identical to the backup; logical state equal to the pre-upgrade state (ledger ends at 020); upgraded directory kept |
| old-server | NOT RUN (see below) |
| reupgrade | PASS: the restored database upgrades again and script import works |

Controls:

- `--fixture-db` mode on a read-only copy of the converted fixture: every stage
  passed; the source file gained no `-wal`/`-shm` (it is only copied).
- `--old-server` given the *current* binary: the stage FAILS ("old server changed
  the ledger to end 021"), as it must.
- The state comparator flags a lowered counter, a changed child table, a
  changed link, a missing ledger row, a foreign-key violation and a changed
  source kind (each injected into the recorded post-upgrade state).

Needs the owner:

1. Build the server from the commit before 021 and rerun with
   `--old-server BINARY`, so the rollback start of the older code is observed.
2. Rerun with `--fixture-db` on a copy of a real 020 backup made with the
   Backup block. The synthetic fixture shows the mechanism; it is not the
   daily data.
3. The Docker-level order (tag `before-upgrade`, upgrade, roll back by
   re-tagging) was not exercised; the rehearsal replaces `docker compose
   stop/start` with its own process control.

## 2. Release smoke

Command: `bash scripts/release/smoke.sh WORK_DIR` (see
[RELEASE.md](../RELEASE.md#release-smoke)).

Observed: `config`, `build`, `artifact`, `readiness`, `boundary`,
`persistence`, `demo-start`, `demo-boundary`, `demo-refusal`, `teardown` and
`daily-untouched` all PASS (exit 0). The demo refused
`EXTRACTOR_PROVIDER=openai` with "public demo refuses live providers" and did
not echo the placeholder key. After each run no `flh-smoke` container or
image remained.

Controls: `--inject-failure demo` exited 1 with `teardown` and
`daily-untouched` PASS and nothing left; a relative, in-repository or
non-empty `WORK_DIR` and an unknown injection were refused with exit 2 before
anything was created.

Two earlier runs failed on harness expectations, not on the product, and were
corrected: `/api/...` exists only when `-web-dir` is set, a one-letter library
query is a `400`, and a provider refusal must be the demo's own message (an
incomplete placeholder configuration fails earlier, for another reason).

Not covered: the real demo web bundle (`VITE_FLH_PUBLIC_DEMO`), real-model
demo vectors, the `semantic` profile, and any deployment.

## 3. Daily-use flow in a browser

Headless Debian Chromium (in a throwaway container on the host network)
against a disposable local server: fresh database, loopback only,
`AI_PROVIDER=rule-based`, every other provider `disabled`. The walk ran once in
English and once with the UI set to 简体中文, clicking the catalog labels of
that language. English: 15 steps (the last one switches to 简体中文 and records
the labels each view renders); Chinese: 14 steps. Both: 0 failed, and no request
left the local server.

Observed order and outcomes are recorded in
[LOCAL_LEARNING_WORKFLOW.zh-CN.md §11](../LOCAL_LEARNING_WORKFLOW.zh-CN.md#11-工作台日常流程浏览器实测).
In short:

- Local: saving a question, the rule-based analysis, feedback, workbook
  script import, reading example, writing drafts, Notebook marks and retry,
  the mock exam, and saving missed points as records.
- Refused before any provider call when disabled: extraction (503), AI
  suggestions, listening preparation, writing feedback (notices shown).
- A lost response on **Save question** (request stored, answer dropped) shows
  the unknown-outcome notice; **Check whether it was saved** finds the record
  and the server holds no duplicate.
- The workbench opens on **Concept Review**, not **Home**
  (`web/src/App.tsx` initial view). Reported, not changed.

Not covered: steps that need a provider (real analysis, extraction, unit
review, suggestions, listening/reading/writing/speaking generation), audio
recording, semantic search, and other unknown-outcome paths, which were
checked by their interface text only.
