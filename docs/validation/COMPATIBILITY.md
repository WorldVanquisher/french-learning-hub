# Compatibility and upgrade (2026-11-19)

Synthetic data and disposable copies only. The fixtures used here are read and never written;
their SHA-256 is checked unchanged.

| Item | Status | This run |
|---|---|---|
| 081 old-server experiment | **Owner-only.** The pinned pre-021 source (`45be54921925fddf7422f23f83b23f6fa2775e5e`) is not on this machine. No binary with that `vcs.revision` was found (`go version -m` over every `server*` under `~/.cache` and `~/workspace`), so nothing was built | search output in the handoff |
| 082 verify an old binary before use | Verified | `--old-server` with the `c53b42c` build: **FAIL** before use ("applies 021 … not a pre-021 build"). A missing path is refused with exit 2 before anything runs. `test_upgrade_021_options.py`: 6 OK |
| 083 rehearsal with synthetic content | Verified | `rehearse.py`: every stage PASS (build, populate, fixture, backup, upgrade, notebook, scripts, conflict, rollback, reupgrade). old-server NOT RUN: optional. Missing: a server built from `45be549…` |
| 084 independently runnable | Verified | The rehearsal ran alone in 3 s (cached build). The feature suites (`go test`, `vitest`, the learning-day walkthrough) ran without it |
| 085 Review Today on an older fixture | Verified | `older_fixtures.py` on the 2026-11-18 fixture (ledger 021, written by an older build): Review Today 3 items, every route 200, export round trip complete |
| 086 existing storage first | Done | Every working slice here uses existing tables: Review Today, practice drafts, revision studio, Speaking workspace, learning week, export. Storage needs are written as proposals only |
| 087 forward and rollback first | Done | `review_defers` (`REVIEW-TODAY.md`), `practice_prompts` (`NOTEBOOK-PRACTICE.md`), `speaking_transcript_edit` (`SPEAKING-WORKSPACE.md`). Each states its forward and rollback effects. None is applied |
| 088 queue under load | Measured | 120 notebook records marked plus 60 typed takes in 3 exercises: the most the authored packs allow through the API. `GET /review-today`: 123 items, **134,982 bytes**, median 27.5 ms, p95 33.4 ms, max 40.8 ms (30 reads). `/learning-week`: 3.7 ms median. Export preview: 7.6 ms median. Laptop i7-1165G7, loopback |
| 089 export after an interrupted upgrade | Verified (limit below) | A rehearsal 020 copy was started and SIGKILLed after 0, 20, 80 and 300 ms, then restarted. Each time the ledger ended at 021 once, integrity was ok, reads answered and the export round trip was complete. The 2026-11-18 (021) fixture exports the same way |
| 090 owner actions and evidence | See the handoff | |

**Commands:**

```bash
python3 -I scripts/release/upgrade_021/rehearse.py "$(mktemp -d)"
python3 -I scripts/release/upgrade_021/rehearse.py "$(mktemp -d)" --old-server /path/to/server-built-from-45be549
python3 -I -B scripts/release/test_upgrade_021_options.py
python3 -I scripts/validation/compat/older_fixtures.py "$(mktemp -d)" FIXTURE.db [FIXTURE.db ...]
python3 -I scripts/validation/review_today/load.py "$(mktemp -d)" 30
```

**Limits stated plainly:**
- On the small 020 copy the kill landed before migration 021 (0 ms) or after it committed (20 ms
  and later); none landed inside its transaction.
- An interruption inside it would roll back. The rehearsal's rollback and reupgrade stages
  cover the restore path, but a kill inside the migration was not observed here.
- The Review Today response grows about 1.1 KB per item, because each item carries its source
  JSON. It is fine at personal scale; trimming it would be a contract change.
