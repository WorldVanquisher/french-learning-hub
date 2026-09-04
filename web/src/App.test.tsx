import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("App annotation views", () => {
  it("opens the read-only inspector through the local view switch", async () => {
    const calls: Array<{ method: string; path: string }> = [];
    globalThis.fetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      const method = (init?.method ?? "GET").toUpperCase();
      const path = new URL(String(url), "http://localhost").pathname;
      calls.push({ method, path });
      const body = path === "/api/reviewable-units"
        ? { reviewable_units: [] }
        : path === "/api/effective-annotations"
          ? { effective_annotations: [] }
          : { concepts: [] };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as unknown as typeof fetch;

    render(<App />);
    expect(screen.getByRole("heading", { name: "Concept Review" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Annotation Inspector" }));

    expect(
      await screen.findByRole("heading", { name: "Effective Annotation Inspector" }),
    ).toBeInTheDocument();
    expect(await screen.findByText(/No KnowledgeUnits exist in the current extraction/)).toBeInTheDocument();
    expect(calls.some((call) => call.path === "/api/effective-annotations")).toBe(true);
    expect(calls.every((call) => call.method === "GET")).toBe(true);
  });

  it("opens the read-only Experiment Dashboard through the third tab", async () => {
    const calls: Array<{ method: string; path: string }> = [];
    globalThis.fetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      const method = (init?.method ?? "GET").toUpperCase();
      const path = new URL(String(url), "http://localhost").pathname;
      calls.push({ method, path });

      let body: unknown;
      if (path === "/api/reviewable-units") {
        body = { reviewable_units: [] };
      } else if (path === "/api/concepts") {
        body = { concepts: [] };
      } else if (path === "/api/annotation-dataset/v1/quality") {
        body = {
          schema_version: "concept_annotation_quality_report_v1",
          dataset_schema_version: "concept_annotation_dataset_v1",
          valid: true,
          error_count: 0,
          warning_count: 0,
          summary: {
            total_records: 0,
            total_entries: 0,
            total_extractions: 0,
            total_referenced_concepts: 0,
            effective_status: { resolved: 0, unresolved: 0, invalid: 0 },
            admission_effective: { active: 0, suppressed: 0, needs_review: 0 },
            authority: { resolved_human_same: 0, resolved_automatic_same: 0 },
          },
          label_inventory: {
            records_with_any_human_label: 0,
            records_without_human_label: 0,
            human_same_records: 0,
            human_distinct_pairs: 0,
            human_relations: { broader: 0, narrower: 0, related: 0 },
            human_invalid_records: 0,
            unlabeled_unresolved_records: 0,
            automatic_same_only_records: 0,
          },
          provenance: {
            extractors: [],
            concept_identity_schema_versions: [],
            human_label_resolver_versions: [],
          },
          leakage_risk: {
            entries_with_multiple_records: 0,
            max_records_per_entry: 0,
            human_same_concepts: 0,
            human_same_concepts_with_multiple_units: 0,
            human_same_concepts_spanning_multiple_entries: 0,
            max_units_per_human_same_concept: 0,
          },
          issues: [],
        };
      } else {
        body = {
          schema_version: "concept_retrieval_comparison_v1",
          state: "evaluated",
          dataset_valid: true,
          candidate_universe: { concepts: 0 },
          evaluation_samples: { eligible_samples: 0 },
          retrievers: [],
        };
      }
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as unknown as typeof fetch;

    render(<App />);
    expect(screen.getByRole("button", { name: "Concept Review" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Annotation Inspector" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Experiment Dashboard" }));

    expect(
      await screen.findByRole("heading", { name: "Experiment Dashboard" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("No structural dataset errors were reported.")).toBeInTheDocument();
    expect(calls.some((call) => call.path === "/api/annotation-dataset/v1/quality")).toBe(true);
    expect(calls.some((call) => call.path === "/api/retrieval-comparison/v1")).toBe(true);
    expect(calls.every((call) => call.method === "GET")).toBe(true);
  });
});
