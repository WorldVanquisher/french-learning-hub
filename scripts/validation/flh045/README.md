# FLH-045 offline evaluation preparation

These are author-proposed synthetic records awaiting human review, not collected
human ground truth or production annotations. There is no application loader,
retriever implementation, model client or experiment runner here.

From the repository root, using Python's standard library only:

```sh
python3 -B scripts/validation/flh045/validate.py
python3 -B -m unittest discover -s scripts/validation/flh045 -p 'test_*.py' -v
```

The validator prints counts and SHA-256 hashes to stdout and exits nonzero on
invalid input. An optional positional path validates a candidate fixture copy.
`-B` prevents bytecode files. Tests use automatically removed temporary files;
there are no database, network, container or dependency-install operations.

Files:

- `fixture.json`: 24 identity proposals, 56 authored queries, 56 proposed
  judgments and 14 indivisible paraphrase/contrast groups. IDs C001–C024,
  Q001–Q056 and J001–J056 are fixture IDs, not application IDs.
- `validate.py`: strict schema, references, duplicates, bilingual coverage,
  judgment consistency, group/split boundaries and visible leakage checks.
- `test_validate.py`: shipped-inventory and adversarial mutation/CLI checks.
- `experiment-record.template.json`: unexecuted recording template. Null means
  unmeasured; fill a copy in task-owned temporary output after approval.

`unit_evidence` provides only the existing Unit query's kind, canonical,
statement and example inputs. Production derives candidate identity from the
Unit; the fixture intentionally supplies no expected candidate identity.
`free_text` is a separately addressed search input, even when its sentence
matches the Unit statement. Metadata and judgments must never reach a provider.

Development contains 32 single-target and two ambiguous queries. Held-out
contains 16 single-target, two ambiguous and four no-match queries. F09–F14 are
reserved before any tuning. All 24 Concepts stay in the fixed candidate catalog;
query splits do not filter the catalog. Ambiguous/no-match records cannot be
scored by the current positive-only evaluation policy.

The validator does not adjudicate French correctness, semantic relevance,
paraphrase originality or hidden semantic leakage. Whole visible identity-copy
and metadata checks are conservative guards, not proof of independence. Changes
need review, new hashes and explicit versioning; do not silently turn proposed
labels into approved ones or move held-out families to development.

See [the preparation plan](../../../docs/plans/FLH-045-retrieval-evaluation.md)
for the contract map, separate protocols, approval gate and executed evidence.
Fake vectors and passing self-tests cannot establish retrieval quality.
