# R4 baseline report (frozen before any R4 change)

Service `flh-extraction-rules@e978b6c2bdb6/flh_extraction_service_v1/flh_practice_drafter_v1`. Synthetic corpus `flh_extraction_r4_corpus_v1`; requests in `corpus/`, full responses in `baseline/`.

| # | Scenario | Route | Status | What the learner sees |
|---|---|---|---|---|
| 01 | evidence-r1 | `/v1/review` | 200 | r1: pending 7; support supported 4, unsupported 1, generated 2; batch 5, left for review 2 |
| 02 | quality-negation | `/v1/review` | 200 | r1: pending 6; support supported 6; batch 6, left for review 0 |
| 03 | quality-accents | `/v1/review` | 200 | r1: pending 4; support supported 1, unsupported 3; batch 1, left for review 3 |
| 04 | quality-paraphrase | `/v1/review` | 200 | r1: pending 8; support supported 5, unsupported 3; batch 5, left for review 3 |
| 05 | approved-r1 | `/v1/review` | 200 | r1: approved 6, rejected 1; support supported 4, unsupported 1, generated 2; batch 0, left for review 0 |
| 06 | feed-r1 | `/v1/feed` | 200 | r1 seq 1: 5 offered, 3 outcomes; withdrawn none; restored 0; added 0 |
| 07 | revision-r2 | `/v1/review` | 200 | r2: approved 4, rejected 1, needs_review 2; support supported 2, unsupported 3, generated 2; batch 0, left for review 2 |
| 08 | feed-r2-withdrawn | `/v1/feed` | 200 | r2 seq 2: 0 offered, 0 outcomes; withdrawn knowledge_changed 5; restored 0; added 0 |
| 09 | revision-r3 | `/v1/review` | 200 | r3: approved 2, rejected 1, needs_review 4; support supported 4, unsupported 1, generated 2; batch 0, left for review 4 |
| 10 | feed-r3-awaiting | `/v1/feed` | 200 | r3 seq 3: 0 offered, 0 outcomes; withdrawn awaiting_confirmation 3, knowledge_changed 2; restored 0; added 0 |
| 11 | confirmed-r3 | `/v1/review` | 200 | r3: approved 6, rejected 1; support supported 4, unsupported 1, generated 2; batch 0, left for review 0 |
| 12 | feed-r3-restored | `/v1/feed` | 200 | r3 seq 4: 5 offered, 3 outcomes; withdrawn none; restored 5; added 0 |
