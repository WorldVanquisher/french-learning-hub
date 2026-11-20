# Learning week and a traceable Review Today (2026-11-19)

`GET /learning-week?zone=` (`learning_week_v1`) is derived from stored rows on every read. It has
no table and no provider call, and it never scores anything. The workbench shows it as
**This week** on the Review Today page. Both reads send the browser's IANA zone; empty means
UTC, and an unknown zone is `400`.

## Counted kinds (one stored row each)

| Kind | Rows | Column |
|---|---|---|
| `production` | Speaking take with a confirmed transcript (at its first confirmation); Writing draft v1 | Production practice |
| `reviewed` | Mistake Notebook record saved; a record whose current retry state is "done" | Reviewed |
| `own_correction` | Speaking transcript version with origin `corrected`; Writing draft v2+ | Your corrections |
| `provider_feedback` | Completed Speaking or Writing feedback | Feedback received |

**Counting rules:**
- Each event counts once per **(kind, item, local day)**, so a repeated save never inflates a
  total. `duplicates_ignored` says how many were folded.
- Shares appear only from **20** counted actions (production + reviewed). Below that, counts
  only.
- Only a record's current retry state is visible (`CurrentMarks`), so earlier mark and unmark
  decisions on the same record are not counted.

## Handwritten sequence (`TestBuildLearningWeek_HandwrittenSequence`)

The zone is Europe/Paris and now is Thursday 2026-11-19 10:00, so the week is 11-13 … 11-19.

| # | Event | Local time | Counted? |
|---|---|---|---|
| e1 | production, take 1 (exercise 1) | 11-13 09:00 | yes |
| e2 | the same take again | 11-13 09:05 | duplicate |
| e3 | own correction, transcript 5 | 11-13 09:10 | yes |
| e4 | provider feedback 7 | 11-14 20:00 | yes |
| e5 | production, draft 3 (task 2), at 2026-11-16 23:30 **UTC** | 11-17 00:30 | yes, on 11-17 |
| e6 | own correction, draft 4 | 11-17 08:00 | yes |
| e7 | reviewed, record 41 saved | 11-19 08:00 | yes |
| e8 | reviewed, record 41 done | 11-19 09:00 | yes |
| e9 | record 41 done again | 11-19 09:30 | duplicate |
| e10 | production, take 2 | 11-12 23:00 | before the week |
| e11 | production, take 3 (exercise 4) | 11-19 09:45 | yes |
| e12 | record 41 done | 11-18 10:00 | yes (another day) |

| Day | 13 | 14 | 15 | 16 | 17 | 18 | 19 | Total |
|---|---|---|---|---|---|---|---|---|
| Production | 1 | 0 | 0 | 0 | 1 | 0 | 1 | 3 |
| Reviewed | 0 | 0 | 0 | 0 | 0 | 1 | 2 | 3 |
| Your corrections | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 2 |
| Feedback received | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 |

- Distinct exercises: 3 (speaking 1, writing 2, speaking 4).
- Active days: 5. Duplicates: 2.
- Sparse (6 < 20), so no share is shown.

**In UTC** (`TestBuildLearningWeek_ZoneDecidesTheDay`), e5 falls on 11-16, not 11-17, and there
are 6 active days. The learner's zone decides the day, and Review Today uses the same zone for
`since_day` and `today` (`TestLearningWeek_CountsStoredWorkOnceInTheLearnersZone`).

## Items 051–060

| Item | Status |
|---|---|
| 051 weekly summary | Implemented: table, totals, distinct exercises, active days |
| 052 own correction vs provider feedback | Implemented: separate kinds and columns; corrections listed by their author |
| 053 reviewed vs production | Implemented: definitions on the page; separate kinds |
| 054 dismiss without deleting | Workbook items: "Done for today" (existing, persisted, keeps the record). Speaking steps: **prototype** "Hide for this visit" (page-only). A persisted defer is blocked on `review_defers` (013–014) |
| 055 sparse activity | Implemented: no percentage below 20 counted actions |
| 056 revisit a correction | Implemented: "Your corrections this week" reopens the take at its version or the draft |
| 057 duplicate completions | Implemented: (kind, item, day) once; tested with duplicates and a doubled list |
| 058 one timezone | Implemented: one browser zone for both reads; the server computes the days |
| 059 traceable suggestions | Implemented: each Review Today row says "Based on: …", naming the stored record, reason and local day |
| 060 handwritten sequence | Verified: the tables above equal the test |
