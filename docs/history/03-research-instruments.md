# 3. Annotation dataset and retrieval experiments

Covers milestones 11-C to 13-A1. Dates are **unknown**; the order is the
milestone order. Current behaviour:
[ARCHITECTURE §8](../ARCHITECTURE.md#8-annotation-dataset-and-retrieval-research).

## Why this work exists

The Concept Review workbench was built to collect human resolution decisions
that a later resolver could learn from. Before any model work, the project
needed three things: a stable dataset of those decisions, a way to tell whether
the dataset is internally consistent, and a fair way to measure simple
retrieval baselines against human ground truth. Model training itself was
deliberately left out.

## Initial implementation, in order

1. **Dataset v1 (11-C).** A read-only, versioned JSON/NDJSON snapshot of every
   unit in each entry's current extraction, with evidence, provenance, effective
   annotation and a deliberately narrow `human_labels` section: an automatic
   SAME can be effective but is never emitted as human gold.
2. **Quality report (11-D).** Structural validation and descriptive statistics
   over Dataset v1 only. Warnings never invalidate the report; an invalid
   dataset still returns HTTP `200` with `valid: false`.
3. **Evaluation foundation (12-A).** One evaluation policy: human CURRENT SAME
   is the only positive truth; seed SAME created by NEW CONCEPT is excluded as
   temporal leakage; the candidate universe is the current non-retired catalog;
   metrics are Recall@1/3/5 and MRR, with `null` (not zero) when there are no
   samples. The first retriever is exact signature match.
4. **Weighted lexical cosine (12-B)**, **corpus-aware BM25 (12-C)** and an
   **optional embedding baseline (12-D)** were added behind the same retriever
   interface and registry, each required to share the same population, truth
   and metrics so that only rankings can differ.
5. **Comparison (13-A0).** One compact report with the four baselines in a fixed
   order. It fails with `500` rather than mix different populations, and shows
   a disabled embedding provider as an explicit `unavailable` row.
6. **Experiment Dashboard (13-A1).** A read-only workbench view of the quality
   summary and the comparison; the browser computes no metrics.

## Later corrections and caveats

No later task changed these reports. Two limitations were documented as part
of the work rather than fixed:

- The candidate catalog is the current one, not a reconstruction of what
  existed when a label was made, so later Concepts compete too.
- The embedding representation includes the query example and candidate
  target, while the lexical and BM25 query does not, so the comparison is not a
  scorer-only ablation ([ARCHITECTURE §8.8](../ARCHITECTURE.md#88-interpreting-comparisons)).

Frozen-vector tests establish ranking behaviour; they say nothing about the
quality of any real embedding model.

## Evidence and gaps

- No dedicated report or date exists for milestones 11-C to 13-A1. Their
  contracts are recorded in AGENTS.md and ARCHITECTURE.
- No retrieval metric from real data is recorded in the repository, and none is
  claimed here. A fresh database produces `null` metrics by design.
