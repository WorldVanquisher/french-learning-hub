# `flh_extraction_service_v1` payload examples (synthetic, sealed)

Real requests and responses from the private extraction service (`tools/extraction/SERVICE.md`),
recorded on a loopback port by `scripts/service_examples.py`. Every learner text is synthetic,
or a short public-domain excerpt (Jules Verne, recorded in `a_en_lieux.json`).

| Example | For | What it shows |
|---|---|---|
| `01-review-first-revision` | Runtime (FLH) | grounding, cues and the batch plan for one revision |
| `02-review-with-decisions-and-revisions` | Runtime | the learner's decisions carried over or refused across two revisions; quotes that moved |
| `03-feed` | Workbooks | a `flh_practice_review_feed_v1` feed with the 2.2 additions, from the same request shape |
| `04-import-preview` | Runtime | a read-only preview of an agent return (`flh_agent_proposals_v2`) |
| `05-error-contract-mismatch` | Runtime | 409: a client of another contract version |
| `06-error-invalid-source` | Runtime | 422 `invalid_source` |
| `07-manifest` | Runtime, Release | the deployment identity: code hashes, rules, limits, result codes |
| `08-feed-withdrawn-reason-codes` | Workbooks | R4: a revision removes one worked example and the learner rejects another: withdrawn entries with `absent` and `rejected`, one item still offered (source `fixtures/r4_v1/codes/y_en.r2-codes.json`) |
| `09-feed-awaiting-confirmation` | Workbooks | R4: revision 3 before the learner confirms: no item offered, withdrawn with `awaiting_confirmation` and `knowledge_changed`, `since_revision` 2 kept, earlier attempts on withdrawn IDs accepted |

```sh
cd tools/extraction
python3 -I -B scripts/service_examples.py --check     # regenerate and compare (exit 0 = equal)
sha256sum -c fixtures/service_v1/SHA256SUMS
```

Together with `practice_v1/workbooks2/feed-3-r2-withdrawn.json` (`rule_not_approved`, an agent exercise:
the service builds source practice only), real producer output covers all five reason codes.

A response's `deployment_id` names the code that produced it: a change to any packaged file
gives new examples, and `--check` fails until they are regenerated on purpose.
