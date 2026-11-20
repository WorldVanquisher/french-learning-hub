# Synthetic practice feeds for Workbooks, 2.2 (sealed, read-only)

This bundle is **synthetic**, from the Extraction 2.2 prototype. The extraction lane owns the
practice-content contract; Review Today, scheduling, storage and every Workbooks schema stay
with the Workbooks lane. Nothing here changes the 2.1 bundle (`../workbooks/`), which stays
byte-identical.

```sh
python3 -I -B check_feed_compat.py feed-*.json --replay replay-cases.json   # stdlib only; exit 0 = contract and replay hold
python3 -I -B check_feed_compat.py feed-*.json --json                       # machine-readable, for a verification runner
python3 -I -B check_feed_compat.py feed-*.json --strict-consumer            # also exit 1 when the increment-4 consumer would refuse a feed
sha256sum -c SHA256SUMS                                                     # the seal alone
```

Regenerate from the extraction lane (`tools/extraction`); the output must equal this directory:

```sh
python3 -B -m flh_extraction practice2 demo3 --out "$(mktemp -d)/demo" --check
```

## Files

| File | What it is |
|---|---|
| `feed-1-r1.json` | à/en revision 1 after the learner's batch and individual decisions: 5 exercises |
| `feed-2-r1-newly-approved.json` | the learner accepted an agent's exercise: `added` names it; an attempt and a miss recorded |
| `feed-3-r2-withdrawn.json` | revision 2 removed the excerpt the exercise's rule cites: `withdrawn` with `reason_code: rule_not_approved` |
| `feed-4-r3-awaiting-confirmation.json` | revision 3 put the excerpt back: still withdrawn (`awaiting_confirmation`) until the learner confirms |
| `feed-5-r3-restored.json` | the learner confirmed: `restored` names the same practice ID; its history is unchanged |
| `replay-cases.json` | feed sequences (replays, a repeated restore, a late old feed, a missed feed) with the reference client's expected state |
| `compat-report.json` | each feed (and the 2.1 bundle's feeds) against the contract and the increment-4 consumer rules |
| `check_feed_compat.py` | the checker and reference client (a byte copy of `flh_extraction/feed_compat.py`) |

## Contract additions (`contract_additions: flh_practice_feed_additions_v1`)

All optional; a v1 reader ignores them:

- **per item:**
  - `source_revision` (`revision`, `revision_sha256`), equal to the feed's source;
  - `recall_type`: `unassisted_recall`, `assisted_recall` or `transfer`;
  - `origin`: `source` or `agent_proposal`, with `provenance` (agent, packet, proposal, accepted by the learner) for the latter.
- **per feed:**
  - `feed_seq` and `feed_id` (a hash of the feed; a replay is recognised by it);
  - with a previous feed: `withdrawn` (each with `reason_code`, `reason` and `since_revision`; listed in every later feed until offered again), `restored` and `added`.

Never in a feed: due dates, intervals or schedules, answer keys, attempt texts, skipped items.

## What Workbooks should do (proposal; their decision)

- **Withdrawn:** stop offering the ID and keep its history.
- **Restored:** offer it again with the same history.
- **Replay** (same `feed_id`): change nothing.
- **Older feed** (lower revision or `feed_seq`): ignore it.

**Known gap.** The increment-4 consumer refuses a feed with no items, so the 2.1 bundle's
`feed-y-en-demo-r2.json` (everything withdrawn) is refused there. `compat-report.json`
records this. Either the consumer accepts an empty `items` list when `withdrawn` is
non-empty, or the producer never sends one; that is the owner's call.

All French sentences are synthetic A1/A2 examples and need a native-speaker check. The à/en
fixture quotes six short excerpts of Jules Verne's public-domain text; its source file
records the Wikisource revisions they were checked against.
