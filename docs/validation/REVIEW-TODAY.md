# Review Today and spaced practice (2026-11-19)

Synthetic data and loopback servers only. No migration, no provider call.

## Review Today (working)

`GET /review-today` and the **Review Today** view are described in `docs/ARCHITECTURE.md`
§4.8.1.

- **Demo:** `scripts/demo/review_today/seed.py` on a fresh scratch database.
- **Browser check:** `scripts/validation/review_today/walkthrough.py WORK_DIR`. It covers desktop
  English and phone 390×844 Chinese: open the queue, complete a workbook item without a reload,
  open the Speaking take, and come back.

Sample queue after the seed (feedback off):

| Source | Reason | Action |
|---|---|---|
| speaking | `review_without_feedback` | Open take 1 |
| notebook | `retry_marked` | Open the lesson · Done for today |

History (not queued): 2 saved mistakes, 1 Speaking take.

## Spaced practice (prototype)

`internal/application/review_schedule.go`: `NextRecommendation(input, now, location)` is a pure
function. The caller supplies the clock and the learner's zone. It is not stored, and it is
**not yet applied** to Review Today.

**Classes, most urgent first:**

| Class | Priority | When | Example |
|---|---|---|---|
| `recovery` | 0 | Something started is stuck; due today | A feedback request that failed or whose outcome is unknown; a machine transcript to check |
| `review` | 1 | Practised before; due on the ladder | A take with completed feedback; a mistake retried once |
| `new` | 2 | Started, never completed; due today, after the others | A prompt started with no take |

**Ladder:** after the n-th completed attempt the item is due +1, +3, +7 or +14 local calendar
days (n = 1, 2, 3, 4+). The interval counts from the latest attempt that has a timestamp. The
rule names that attempt:

```text
ladder n=2 +3d from 2026-11-18 (last attempt)
```

**Fallbacks, all stable and named in the rule:**

| Situation | Base |
|---|---|
| Attempt timestamps missing | the item's creation |
| Creation unknown too | today |
| Older record without scheduling fields | none: a conservative review due today (`legacy`) |
| Due day already past | today (`overdue`) |

Days are the learner's local calendar days: date arithmetic, never 24-hour steps. The tests cover
midnight on both sides, two zones for one instant, and both 2026 New York daylight-saving changes.

**One synthetic week** (`TestSimulateWeek_DailyWorkload`, Europe/Paris, from Monday 2026-11-16).
Each due item is practised once that day:

| Item | Start | Due on days |
|---|---|---|
| A, B | new | 0, 1, 4 |
| C | review, n=1 the day before | 0, 3 |
| D | review, n=2 the day before | 2 |
| E | recovery | 0, 1, 4 |

| Day | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|---|
| Items due | 4 | 3 | 1 | 1 | 3 | 0 | 0 |

**Against stored records (prototype):** `ScheduleInputsFromExport` reads a
`learning_history_export_v1` file into scheduling inputs:
- Speaking exercises are reviews when their latest take has a confirmed transcript, and new
  otherwise.
- Notebook records marked for retry are reviews.

`scripts/validation/compat/older_fixtures.py` runs it on each older fixture's own records, and
every input gets a due day and a rule. It is still not shown in the workbench.

## Blocked: defer and undo (items 013–014)

A manual defer must persist a due date, and no existing table holds one:
- retry marks are a boolean plus a time;
- Speaking has no schedule.

Showing a deferred date that a reload forgets would mislead, so nothing was built. Proposal for
the owner, once a migration number is allocated:

- **Schema:** an append-only `review_defers` table (`item_key`, `defer_until_day`, `zone`,
  `created_at`, `undone_at`), one row per explicit defer.
- **Reads:** Review Today hides an item until its day.
- **Undo:** writes `undone_at` through the same save path. This matches the append-only
  convention of `mistake_retry_marks`.
- **Forward:** a new table only; nothing existing changes.
- **Rollback:** restore the pre-upgrade backup (`docs/RELEASE.md`). An older build ignores the
  table.
