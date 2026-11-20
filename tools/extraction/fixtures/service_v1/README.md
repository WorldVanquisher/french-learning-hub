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

```sh
cd tools/extraction
python3 -I -B scripts/service_examples.py --check     # regenerate and compare (exit 0 = equal)
sha256sum -c fixtures/service_v1/SHA256SUMS
```

A response's `deployment_id` names the code that produced it: a change to any packaged file
gives new examples, and `--check` fails until they are regenerated on purpose.
