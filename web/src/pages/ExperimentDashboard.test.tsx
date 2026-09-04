import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ExperimentDashboard } from "./ExperimentDashboard";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const qualityReport = {
  schema_version: "concept_annotation_quality_report_v1",
  dataset_schema_version: "concept_annotation_dataset_v1",
  valid: true,
  error_count: 0,
  warning_count: 2,
  summary: {
    total_records: 12,
    total_entries: 7,
    total_extractions: 7,
    total_referenced_concepts: 5,
    effective_status: { resolved: 7, unresolved: 4, invalid: 1 },
    admission_effective: { active: 10, suppressed: 1, needs_review: 1 },
    authority: { resolved_human_same: 5, resolved_automatic_same: 2 },
  },
  label_inventory: {
    records_with_any_human_label: 9,
    records_without_human_label: 3,
    human_same_records: 5,
    human_distinct_pairs: 4,
    human_relations: { broader: 1, narrower: 1, related: 2 },
    human_invalid_records: 1,
    unlabeled_unresolved_records: 3,
    automatic_same_only_records: 2,
  },
  provenance: {
    extractors: [],
    concept_identity_schema_versions: [],
    human_label_resolver_versions: [],
  },
  leakage_risk: {
    entries_with_multiple_records: 2,
    max_records_per_entry: 3,
    human_same_concepts: 4,
    human_same_concepts_with_multiple_units: 1,
    human_same_concepts_spanning_multiple_entries: 1,
    max_units_per_human_same_concept: 2,
  },
  issues: [],
};

const retrievalReport = {
  schema_version: "concept_retrieval_comparison_v1",
  state: "evaluated",
  dataset_valid: true,
  candidate_universe: { concepts: 9 },
  evaluation_samples: { eligible_samples: 4 },
  retrievers: [
    {
      retriever: "exact_signature_retriever_v1",
      state: "evaluated",
      metrics: { recall_at_1: 0.25, recall_at_3: 0.5, recall_at_5: 0.75, mrr: 0.3125 },
    },
    {
      retriever: "weighted_lexical_retriever_v1",
      state: "evaluated",
      metrics: { recall_at_1: 0.5, recall_at_3: 0.75, recall_at_5: 1, mrr: 0.625 },
    },
    {
      retriever: "bm25_retriever_v1",
      state: "evaluated",
      metrics: { recall_at_1: 0.75, recall_at_3: 1, recall_at_5: 1, mrr: 0.8125 },
    },
    {
      retriever: "embedding_retriever_v1",
      state: "unavailable",
      metrics: { recall_at_1: null, recall_at_3: null, recall_at_5: null, mrr: null },
    },
  ],
};

function dashboardFetch(
  quality: unknown = qualityReport,
  comparison: unknown = retrievalReport,
) {
  const calls: Array<{ method: string; path: string }> = [];
  const impl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const path = new URL(String(url), "http://localhost").pathname;
    calls.push({ method, path });
    const body = path === "/api/annotation-dataset/v1/quality" ? quality : comparison;
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as unknown as typeof fetch;
  return { impl, calls };
}

describe("ExperimentDashboard", () => {
  it("shows useful loading states while both reports are pending", () => {
    globalThis.fetch = vi.fn(() => new Promise<Response>(() => undefined)) as unknown as typeof fetch;

    render(<ExperimentDashboard />);

    expect(screen.getByText("Loading dataset quality…")).toBeInTheDocument();
    expect(screen.getByText("Loading retrieval comparison…")).toBeInTheDocument();
  });

  it("renders quality supervision and fixed retrieval rows in backend order", async () => {
    const { impl, calls } = dashboardFetch();
    globalThis.fetch = impl;

    render(<ExperimentDashboard />);

    const qualitySection = (await screen.findByRole("heading", { name: "Dataset Quality" })).closest("section");
    expect(qualitySection).not.toBeNull();
    expect(await within(qualitySection as HTMLElement).findByText("Valid")).toBeInTheDocument();
    for (const [label, value] of [
      ["Errors", "0"],
      ["Warnings", "2"],
      ["Total Records", "12"],
      ["Total Entries", "7"],
      ["Human SAME", "5"],
      ["Human DISTINCT", "4"],
      ["Human INVALID", "1"],
      ["Unlabeled Unresolved", "3"],
      ["Resolved by human SAME", "5"],
      ["Resolved by automatic SAME", "2"],
    ]) {
      const term = within(qualitySection as HTMLElement).getByText(label);
      expect(term.parentElement).toHaveTextContent(`${label}${value}`);
    }

    const table = await screen.findByRole("table", { name: /backend-provided experiment order/ });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => within(row).getByRole("rowheader").textContent)).toEqual([
      "Exact Signatureexact_signature_retriever_v1",
      "Weighted Lexicalweighted_lexical_retriever_v1",
      "BM25bm25_retriever_v1",
      "Embeddingembedding_retriever_v1",
    ]);
    expect(within(rows[2]).getByText("81.3%")).toBeInTheDocument();
    expect(within(rows[3]).getByText("unavailable")).toBeInTheDocument();
    expect(within(rows[3]).getAllByText("—")).toHaveLength(4);
    expect(calls.map((call) => call.path).sort()).toEqual([
      "/api/annotation-dataset/v1/quality",
      "/api/retrieval-comparison/v1",
    ]);
    expect(calls.every((call) => call.method === "GET")).toBe(true);
  });

  it("makes invalid quality and blocked experiment states explicit", async () => {
    const invalidQuality = {
      ...qualityReport,
      valid: false,
      error_count: 3,
      warning_count: 1,
    };
    const blockedComparison = {
      ...retrievalReport,
      state: "blocked_invalid_dataset",
      dataset_valid: false,
      evaluation_samples: { eligible_samples: 0 },
      retrievers: retrievalReport.retrievers.map((row) => ({
        ...row,
        state: row.state === "unavailable" ? "unavailable" : "blocked_invalid_dataset",
        metrics: { recall_at_1: null, recall_at_3: null, recall_at_5: null, mrr: null },
      })),
    };
    globalThis.fetch = dashboardFetch(invalidQuality, blockedComparison).impl;

    render(<ExperimentDashboard />);

    expect(await screen.findByText("Invalid")).toBeInTheDocument();
    expect(screen.getByText("Structural dataset errors block retrieval evaluation.")).toBeInTheDocument();
    expect(screen.getAllByText("blocked_invalid_dataset").length).toBeGreaterThan(1);
    expect(screen.getByText("No")).toBeInTheDocument();
  });

  it("keeps quality visible when retrieval comparison fails", async () => {
    globalThis.fetch = vi.fn(async (url: string | URL | Request) => {
      const path = new URL(String(url), "http://localhost").pathname;
      if (path === "/api/annotation-dataset/v1/quality") {
        return new Response(JSON.stringify(qualityReport), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ error: "comparison temporarily unavailable" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }) as unknown as typeof fetch;

    render(<ExperimentDashboard />);

    expect(await screen.findByText("Valid")).toBeInTheDocument();
    expect(screen.getByText("Total Records").parentElement).toHaveTextContent("Total Records12");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load retrieval comparison: (500) comparison temporarily unavailable",
    );
  });
});
