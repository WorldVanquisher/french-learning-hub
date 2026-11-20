# R4 lifecycle fixture (synthetic, offline)

The y/en source through revisions 1-3 as four `flh_practice_review_feed_v1` feeds with the
2.2 additions, produced by the extraction service (`flh_extraction_service_v1`):

1. `feed-1-r1.json`: five items, three outcomes (two attempts, one reveal).
2. `feed-2-r2-withdrawn.json`: no item offered; all five withdrawn (`knowledge_changed`).
3. `feed-3-r3-awaiting.json`: still none offered; three withdrawn as `awaiting_confirmation`,
   two as `knowledge_changed`, `since_revision` 2 kept.
4. `feed-4-r3-restored.json`: all five restored with their three outcomes.

`replay-cases.json` uses the format of the sealed replay cases (`deliver` = feed files in
order; `expect.actions` and `expect.items` with `offered`, `history` count and `reason`). Run it
with the reference consumer:

    python3 -I -B check_feed_compat.py --replay replay-cases.json   # from this directory, with a copy of feed_compat.py

or with Workbooks' `feedClient.applyFeed` the way `feedClient.test.ts` runs the earlier cases.
Attempt texts are never in a feed. Regenerate with `scripts/r4_lifecycle.py --write`.
