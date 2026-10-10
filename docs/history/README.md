# Development history

This directory tells how French Learning Hub reached its current design: what
was built first, what was later found to be wrong or incomplete, and how it was
corrected. It is organized by theme, not as one long log. The authoritative
description of **current** behaviour is [ARCHITECTURE.md](../ARCHITECTURE.md);
the original task contracts and evidence stay unchanged in
[docs/plans/](../plans/) and [docs/validation/](../validation/), and this
history links to them instead of copying them.

## How to read the evidence

The reports were written by different coding agents (Claude Code and Codex) and
reviewed by the human owner, who alone performed Git operations. The words
below are used deliberately and are not interchangeable:

| Term | Meaning here |
| --- | --- |
| **Implemented** | The behaviour exists in the current working tree (code, tests or configuration can be inspected). |
| **Author-verified** | The implementing agent ran checks and reported them. |
| **Independently verified** | A different task or agent ran its own checks against the integrated code and reported them. |
| **Merged** | Recorded only where a report states the human said so. Coding agents never inspected Git, so most reports cannot establish merge state or commit identity. |
| **NOT RUN** | A report explicitly says a check (often a real browser or a human presentation) was not performed. |

**Dates.** A date appears only when a plan or validation report states it.
Where a report names a time zone, it is America/Toronto or Canada/Eastern. The numbered milestones
(1 to 13-A1) and the v1.0 cleanup have no dated evidence in the repository, so
their dates are **unknown**; their order is known from the documents that
describe them. Example timestamps in API samples are illustrative, not
evidence.

## Themes

| # | Narrative | Covers |
| --- | --- | --- |
| 1 | [Learning records and versioned interpretation](01-learning-records.md) | Milestones 1–9, v1.0 Entry cleanup, FLH-004, FLH-009 |
| 2 | [Knowledge units, concepts and human annotation](02-knowledge-and-concepts.md) | Milestones 10–11-B, the annotation-semantics patch, FLH-014/018/022/023/025 |
| 3 | [Annotation dataset and retrieval experiments](03-research-instruments.md) | Milestones 11-C to 13-A1 |
| 4 | [Release packaging and hardening](04-release-and-hardening.md) | v1.0 release work, FLH-001, 008–013, 016, 017, 019, 021, 026 |
| 5 | [Lost responses and annotation idempotency](05-annotation-idempotency.md) | FLH-027 to FLH-033 |
| 6 | [Knowledge Library and its demo](06-knowledge-library-and-demo.md) | FLH-034 to FLH-039 |

## Dated task reports

Every dated report in the repository, in date order. "Owner" is as recorded.

| Date | Task | Kind | Owner | Recorded outcome |
| --- | --- | --- | --- | --- |
| 2026-10-07 | [FLH-001](../plans/FLH-001-sanity-check.md) | Sanity check | Codex | Release verification passed; two P1 and one P2 finding, four follow-ups proposed |
| 2026-10-07 | [FLH-011](../validation/FLH-011-release-acceptance.md) | Release acceptance | Codex | Exercised Docker release workflow passes, including backup/restore |
| 2026-10-07 | [FLH-012](../validation/FLH-012-workbench-acceptance.md) | Browser acceptance | Claude Code | 27/27 browser checks; one pre-existing CSS defect |
| 2026-10-07 | [FLH-013](../validation/FLH-013-release-edge-cases.md) | Release edge-case audit | Claude Code (self-audit) | Eight findings, including restore persistence and cross-site writes |
| 2026-10-08 | [FLH-016](../validation/FLH-016-release-recovery.md) | Recovery fixes | Codex | Durable restore, file-only daily migration, fail-fast `make verify` |
| 2026-10-08 | [FLH-019](../plans/FLH-019-browser-boundary.md) | Browser boundary | Codex | Host allowlist and origin checks implemented |
| 2026-10-08 | [FLH-023](../plans/FLH-023-extraction-selection-mode.md) | Extraction selection | Codex | `selection_mode` and return-to-automatic |
| 2026-10-08 | [FLH-026](../validation/FLH-026-workflow-regression.md) | Workflow regression harness | Codex | Native and container runs pass |
| 2026-10-08 | [FLH-028](../validation/FLH-028-review-response-loss.md) | Response-loss investigation | Codex | 104 cases; documents what reads can and cannot prove |
| 2026-10-08 | [FLH-029](../validation/FLH-029-annotation-idempotency.md) | Idempotency implementation | Codex | Keyed DISTINCT/relation writes; real browser NOT RUN |
| 2026-10-09 | [FLH-030](../validation/FLH-030-idempotency-browser-acceptance.md) | Browser acceptance | Claude Code | 24/24 checks in DEV and PROD; three defects |
| 2026-10-09 | [FLH-031](../validation/FLH-031-idempotency-contract-verification.md) | Author verification | Codex (FLH-029 author) | Contract holds; three evidence/harness defects |
| 2026-10-09 | [FLH-033](../validation/FLH-033-validation-harness.md) | Harness fixes | Codex | FLH-031 findings corrected |
| 2026-10-09 | [FLH-035](../validation/FLH-035-knowledge-library-acceptance.md) | Library acceptance | Codex | Contract checks pass; five findings (B1–B5) |
| 2026-10-09 | [FLH-036](../validation/FLH-036-knowledge-demo.md) | Library fixes | Claude Code | B1–B5 fixed; browser walkthrough on macOS |
| 2026-10-10 | [FLH-037](../validation/FLH-037-knowledge-demo-final.md) | Final Library acceptance | Codex | 84 probe groups pass on Linux; browser and human presentation NOT RUN |
| 2026-10-10 | [FLH-038](../validation/FLH-038-english-demo-experience.md) | English demo | Claude Code | English fixture and copy; browser walkthrough on macOS |

Reports without a stated date: [FLH-008](../plans/FLH-008-release.md),
[FLH-009](../plans/FLH-009-env.md), [FLH-017](../validation/FLH-017-browser-request-boundary.md),
[FLH-021](../plans/FLH-021-mutation-lifecycle.md),
[FLH-029 plan](../plans/FLH-029-annotation-idempotency.md),
[FLH-032](../validation/FLH-032-annotation-recovery.md),
[FLH-034](../plans/FLH-034-knowledge-library.md). Their order relative to the
dated reports is inferred from cross-references and is stated in each
narrative. FLH-002, 005–007, 015, 020, 024 and 027 have no report in the
repository; FLH-003, 004, 010, 014, 018, 022 and 025 are known only from
references in other documents.

## Undated milestones

The numbered milestones predate the FLH task series. Their order, and what each
introduced, comes from the previous README and ARCHITECTURE text; no date is
recorded.

| Milestone | Introduced | Narrative |
| --- | --- | --- |
| 1 | Entry persistence | [1](01-learning-records.md) |
| 2–3 | Versioned analyses; immutable feedback | [1](01-learning-records.md) |
| 4–6 | Pluggable OpenAI analyzer; effective analysis; explainable rule engine | [1](01-learning-records.md) |
| 7–9 | Learning inventory; capture import; capture CLI | [1](01-learning-records.md) |
| 10 | Knowledge extraction and admission | [2](02-knowledge-and-concepts.md) |
| 10.5, 10.5.1 | KnowledgeConcept identity; correctness patch (migration 007) | [2](02-knowledge-and-concepts.md) |
| 10.6 + patch | Concept Review UI; INVALID and DISTINCT labels (migration 008) | [2](02-knowledge-and-concepts.md) |
| 10.7 | Client-side catalog discovery in the review UI | [2](02-knowledge-and-concepts.md) |
| 11-A, 11-B | Effective annotation; Inspector | [2](02-knowledge-and-concepts.md) |
| 11-C, 11-D | Dataset v1; quality report | [3](03-research-instruments.md) |
| 12-A to 12-D | Exact, weighted lexical, BM25 and embedding retrieval baselines | [3](03-research-instruments.md) |
| 13-A0, 13-A1 | Baseline comparison; Experiment Dashboard | [3](03-research-instruments.md) |
| v1.0 | Entry ownership cleanup, release verification, release packaging | [1](01-learning-records.md), [4](04-release-and-hardening.md) |

Retrospective article drafts based on this history are in
[docs/blog/](../blog/README.md).
