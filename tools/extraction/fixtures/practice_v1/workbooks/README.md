# Synthetic practice feed for Workbooks (sealed, read-only)

This bundle is **synthetic**, from the Extraction 2.1 prototype. The extraction
lane owns the practice-content contract. Review Today, scheduling and every
Workbooks schema stay with the Workbooks lane. Nothing here asks Workbooks to change.

```sh
python3 verify.py            # standard library only: the seal, every feed, the three cases (exit 0 = OK)
sha256sum -c SHA256SUMS      # the seal alone
```

To regenerate it from the extraction lane, run this in `tools/extraction`. The output must equal this directory byte for byte:

```sh
python3 -B -m flh_extraction practice workbooks-bundle --out NEW_DIR --check
```

## Files

| File | What it is |
|---|---|
| `feed-y-en-demo-r1.json` | y vs en, revision 1: 5 practice items (explain, choose, produce) with attempt outcomes |
| `feed-y-en-demo-r2.json` | the same source after a revision changed one quote: 0 items, 5 `withdrawn` |
| `feed-y-en-demo-r2-reapproved.json` | after the learner re-approved the changed items: the same 5 practice IDs again |
| `feed-savoir-connaitre-demo-r1.json` | savoir vs connaître, revision 1: 5 items; attempt examples include `invalid` and `self_check` |
| `cases.json` | three cases with expectations: `changed-source`, `duplicate-correction`, `study-packet-without-answers` |
| `duplicate-correction-*.json` | the study packet an agent saw, its return (one correction twice) and the read-only preview |
| `study-packet.json`, `study-packet.md` | a study packet (v2) and the answer keys that must not appear in it (in `cases.json`) |
| `MANIFEST.json` | every feed's source, revision, revision hash and practice IDs by kind; the ID rules |
| `verify.py`, `SHA256SUMS` | the checker and the seal |

## What a feed promises (`flh_practice_review_feed_v1`)

- **Stable IDs.**
  - `practice_id` hashes the knowledge ID and the exercise kind. It survives a source revision and a learner correction.
  - `knowledge_id` never hashes the revision.
- **Source revision.** `source.revision` and `source.revision_sha256` say which revision the items come from.
  - When a revision changes evidence, the items built on it are listed under `withdrawn`, with the reason, until the learner decides again.
  - The withdrawn list appears only when the feed was made with `--previous`.
- **Exercise types.** Each item has a `kind`:
  - `explain`: unaided recall, always a self-check;
  - `choose`: recognition, exact;
  - `produce`: production; accepted variants are correct, anything else is a self-check.
- **Attempt outcomes.** Each `outcomes[]` entry has `seq`, `action` (`attempt` | `reveal`) and an `outcome`:
  - `correct`, `incorrect`, `self_check`, `revealed` or `invalid`;
  - `revealed` and `self_check` are not `correct`.
- **Never included:** due dates, intervals or schedules, answer keys, or attempt texts.

## The three cases

1. **Changed source.** Revision 2 withdraws every revision 1 item, because the contrast they rest on cites a quote that changed. After re-approval the same practice IDs return. Workbooks should:
   - stop offering a withdrawn ID and keep its history;
   - offer it again when it reappears.
2. **Duplicate correction.** An agent proposed the same correction twice. The preview classes the second as `duplicate`, and accepting it is refused. Accepting the first changes no practice ID and leaves the feed byte-identical.
3. **Study packet without answers.** No produce answer, accepted variant or worked-example explanation appears in the study packet's JSON or Markdown.

All French sentences are synthetic A1/A2 examples and need a native-speaker check before learner use.
