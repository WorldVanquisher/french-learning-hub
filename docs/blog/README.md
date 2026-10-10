# Retrospective article drafts

These are **retrospective drafts** for the owner's personal website. They were
prepared on 2026-10-10 from the repository's documentation and validation
reports, after the work they describe. They have not been published, and they
are not contemporaneous posts. The work dates they mention come from
[docs/history/](../history/README.md); where the evidence has no date, the
articles say so.

Ground rules used for every draft:

- Claims are limited to what the repository's code, plans and validation
  reports support. Each draft ends with the repository paths of its sources.
- No quotation, motivation, personal anecdote or result is invented. Where the
  evidence records the owner's feedback (for example the FLH-038 demo feedback),
  it is reported as recorded.
- Implementation was carried out with AI coding agents (Claude Code and Codex)
  working under the owner's direction, task contracts and review, as described
  in `AGENTS.md`. The drafts do not claim that the owner hand-wrote every line.
- Links point to repository paths only, so the text stays portable; add website
  links when publishing.

| # | Draft | Theme |
| --- | --- | --- |
| 1 | [Keeping the learner's words: versioned interpretation and human correction](01-versioned-interpretation.md) | Learning-record pipeline |
| 2 | [Evidence is not identity: from extracted units to durable concepts](02-evidence-and-identity.md) | Knowledge units, concepts, current authority |
| 3 | [Shipping a small Go, React and SQLite service, then testing that it recovers](03-packaging-and-recovery.md) | Release packaging and hardening |
| 4 | [When the response never arrives: idempotent annotation writes](04-lost-responses.md) | Request idempotency |
| 5 | [A knowledge library that shows its sources, and a demo that tells the truth](05-knowledge-library-demo.md) | Search, traceability and demo |

The retrieval-evaluation work (dataset, quality report, four baselines) is
covered briefly in draft 2 rather than in a separate article: the repository
records its design but no measured results on real data, which would make a
standalone article thin.
