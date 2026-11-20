# Notes for the extraction lane: what Workbooks found consuming Extraction 2.2 (R3-060, 2026-11-20)

**How it was found.** Workbooks read the sealed `extraction2-20261119/handoff-2.2` (SHA256SUMS
`e529568b…`), and its `sample/workbooks2` bundle seal verifies. The bundle's feeds were consumed
byte for byte (`build_fixture22.py`). That lane's sealed `check_feed_compat.py` was run read-only.

**This note changes no file of that lane.**

## What holds (no mismatch)

- **Contract and replay:** all five 2.2 feeds meet the contract, and every replay case passes
  (their checker, exit 0; `evidence/r3-060/`).
- **Workbooks' parser:** `practiceFeed.ts` accepts all five, including withdrawn entries with
  `knowledge_ids`, `reason_code` and `since_revision`, the feed-level `feed_id`, `feed_seq`,
  `restored` and `added`, and the item-level `source_revision`, `recall_type`, `origin` and
  `provenance`.
- **Workbooks' feed client** (`feedClient.ts`):
  - It reproduces their reference client: the same actions (applied, replay, stale) and the same
    final state, in every sealed replay case.
  - It computes every `feed_id` exactly as `feed_id()` does.

## Actual mismatches to resolve on their side

| # | Where | Mismatch | Evidence | Suggested resolution |
|---|---|---|---|---|
| 1 | `check_feed_compat.py` `--strict-consumer`, `compat-report.json` | It models the **increment-4** Workbooks consumer. That consumer refused an all-withdrawn feed, and their report still lists that gap for `feed-y-en-demo-r2.json`. The increment-5 consumer (now in main) accepts an empty `items` list | `practiceFeed.test.ts` "reads `withdrawn` and `previous`, and an empty item list…"; their `compat-report.json` `bundle_2_1_unchanged` | Model the current consumer, or drop the rule. The gap is closed |
| 2 | `STORAGE-DECISION-RECORD.md` §5 and `storage-proposed-0NN.sql` | It pins Workbooks' **revision 1** SQL and states "the Workbooks proposal's default: yes [answer text is stored], locally". Revisions 2 and 3 store no answer text by default. Revision 3 has no text column in its minimum, and keeps text only under the learner's separate retention decision | `PRACTICE-STORAGE-DECISION.md` "Revision 3"; `storage_r3.py` R3-043/R3-044 | Re-pin revision 3. Their two attempt rows with text then load only after an explicit retention row |
| 3 | `reason_code` values | The bundle uses `rule_not_approved` and `awaiting_confirmation`, and the reference client falls back to `unspecified`. The set is not stated as closed, so Workbooks cannot tell a new code from a typo | `feed-3-r2-withdrawn.json`, `feed-4-r3-awaiting-confirmation.json` | List the codes in PRACTICE.md and call the list closed. Workbooks shows an unknown code verbatim, with a general sentence |

## Adopted from their record (no action needed)

- `agent_exercise` and `provenance_json`: adopted in revision 3 (optional B). Their 12 sealed
  decisions load (`storage_r3.py` R3-041).
- Deterministic operation keys (a hash of the source, record kind and sequence): compatible with
  `operation_key UNIQUE`, so a re-import is a replay.
