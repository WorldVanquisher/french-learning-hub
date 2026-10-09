import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const concept = (id: number, target: string, state: "active" | "orphaned" | "retired") => ({
  id, identity_schema_version: "fr_l2_concept_identity_v1", target, pedagogical_intent: "grammar", scope: "",
  identity_features: { mode: "subjonctif" }, signature: "{}", preferred_unit_id: id === 1 ? 11 : null, state,
  lifecycle_state: state === "retired" ? "retired" : "normal", support_state: state === "active" ? "supported" : "orphaned",
  created_at: "t", updated_at: "t",
});
const unit = (id: number, current: boolean, extra: Record<string, unknown> = {}) => ({
  unit_id: id, kind: "grammar", canonical: `forme ${id}`, statement: `Énoncé ${id}`, example: null, entry_id: id * 10,
  extraction_id: id * 100, extraction_version: current ? 2 : 1, in_current_extraction: current, admission: "active", ...extra,
});

function library(overrides: Record<string, () => { status?: number; body: unknown }> = {}) {
  const calls: Array<{ method: string; path: string; search: string }> = [];
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ method, path: url.pathname, search: url.search });
    const key = `${url.pathname}${url.search}`;
    let reply: { status?: number; body: unknown };
    if (overrides[key]) reply = overrides[key]();
    else if (url.pathname === "/api/knowledge-library/concepts") {
      const q = url.searchParams.get("q");
      const results = q === "nothing" ? [] : [
        { concept: concept(1, "subjonctif après il faut que", "active"), match_tier: q ? "identity" : "browse", matched_fields: q ? ["target"] : [], current_member_count: 2, supporting_unit_count: 1 },
        { concept: concept(3, "faire", "orphaned"), match_tier: q ? "unit_evidence" : "browse", matched_fields: q ? ["unit_statement"] : [], current_member_count: 1, supporting_unit_count: 0 },
      ];
      reply = { body: { schema_version: "knowledge_library_search_v1", query: q ?? "", tokens: [], state: "all", limit: 20, total_matches: results.length, truncated: false, results } };
    } else if (url.pathname === "/api/knowledge-library/concepts/1") {
      reply = { body: {
        schema_version: "knowledge_library_concept_v1", concept: concept(1, "subjonctif après il faut que", "active"),
        preferred_unit: unit(11, false), supporting_units: [unit(12, true)], non_supporting_members: [unit(11, false)],
        current_relations: [{ relation: "broader", link_id: 7, decision_source: "human", decided_at: "t", unit: unit(13, true) }],
        historical_units: [{ unit: unit(14, true), latest_event: { id: 9, unit_id: 14, concept_id: 1, relation: "same", status: "accepted", decision_source: "human", resolver_version: "", score: null, evidence: "", supersedes_link_id: null, created_at: "t" }, effective_status: "invalid", current_concept_id: null }],
        history_event_count: 6,
      } };
    } else if (url.pathname === "/api/knowledge-library/concepts/3") {
      reply = { body: {
        schema_version: "knowledge_library_concept_v1", concept: concept(3, "faire", "orphaned"), preferred_unit: null,
        supporting_units: [], non_supporting_members: [], current_relations: [], historical_units: [], history_event_count: 1,
      } };
    } else if (url.pathname === "/api/knowledge-library/units/11/source") {
      reply = { body: {
        schema_version: "knowledge_library_source_v1", unit: unit(11, false),
        entry: { id: 110, original_input: "Pourquoi « il faut que je fasse » ?", original_context: "cours", created_at: "2026-01-02", updated_at: "t" },
        extraction: { id: 1100, version: 1, extractor: "stub", source_analysis_id: 5, source_feedback_id: 8, created_at: "t" },
        current_extraction: { extraction_id: 1200, selection_mode: "automatic" },
        source_interpretation: {
          analysis: { id: 5, entry_id: 110, version: 1, category: "grammar", explanation: "original", confidence: 0.8, uncertainty: "", analyzer: "rule-based:v2", created_at: "t" },
          feedback: { id: 8, analysis_id: 5, status: "corrected", corrected_explanation: "corrigée", user_note: "", created_at: "t" },
          effective: { analysis_id: 5, entry_id: 110, version: 1, original: { category: "grammar", explanation: "original" }, effective: { category: "grammar", explanation: "corrigée" }, resolution: "corrected", feedback_id: 8 },
        },
        latest_analysis: { id: 6, version: 2, created_at: "t" },
        annotation: { status: "resolved", current_concept_id: 1 },
      } };
    } else if (url.pathname === "/api/reviewable-units") reply = { body: { reviewable_units: [] } };
    else reply = { body: { concepts: [] } };
    return new Response(JSON.stringify(reply.body), { status: reply.status ?? 200, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
  return calls;
}

async function openLibrary() {
  render(<StrictMode><App /></StrictMode>);
  fireEvent.click(screen.getByRole("button", { name: "Knowledge Library" }));
  expect(await screen.findByRole("heading", { name: "Knowledge Library" })).toBeInTheDocument();
}

describe("Knowledge Library", () => {
  it("searches, opens a concept and its source, and returns to the same query with GETs only", async () => {
    const calls = library();
    await openLibrary();
    expect(await screen.findByText("2 concepts.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search learned material"), { target: { value: "subj" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("2 concepts matching “subj”.")).toBeInTheDocument();
    expect(screen.getByText("Matched in current unit statement (not in the concept identity)")).toBeInTheDocument();
    expect(calls.some((c) => c.search === "?q=subj")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "subjonctif après il faut que" }));
    const heading = await screen.findByRole("heading", { name: /subjonctif après il faut que/ });
    await waitFor(() => expect(heading).toHaveFocus());
    const support = screen.getByRole("region", { name: "Current support (1)" });
    expect(within(support).getByText("forme 12")).toBeInTheDocument();
    // A current member from a historical extraction is never shown as support.
    expect(within(support).queryByText("forme 11")).toBeNull();
    const members = screen.getByRole("region", { name: "Current members that do not provide support (1)" });
    expect(within(members).getByText(/no longer record #110's current extraction/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Preferred representation" })).toHaveTextContent("does not provide support");
    expect(screen.getByRole("region", { name: "Current relations (1)" })).toHaveTextContent("BROADER recorded between unit #13 and this concept");
    const history = screen.getByRole("region", { name: "Historical evidence — not current (1)" });
    expect(history).toHaveTextContent("The unit is now marked INVALID.");
    expect(history).toHaveTextContent("6 append-only events");

    fireEvent.click(within(screen.getByRole("region", { name: "Preferred representation" })).getByRole("button", { name: "View source record #110" }));
    expect(await screen.findByRole("heading", { name: "Source of unit #11: record #110" })).toBeInTheDocument();
    expect(screen.getByText("Pourquoi « il faut que je fasse » ?")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Extraction v1" })).toHaveTextContent("Historical: this is not the record's current extraction (current is extraction #1200, automatic)");
    const interp = screen.getByRole("region", { name: "Interpretation this extraction used: analysis v1" });
    expect(interp).toHaveTextContent("corrected (feedback #8, corrected)");
    expect(interp).toHaveTextContent("corrigée");
    expect(interp).toHaveTextContent("newer analysis (v2)");

    fireEvent.click(screen.getByRole("button", { name: "← Back to results for “subj”" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "subjonctif après il faut que" })).toHaveFocus());
    expect(screen.getByLabelText("Search learned material")).toHaveValue("subj");

    // The query also survives switching views.
    fireEvent.click(screen.getByRole("button", { name: "Annotation Inspector" }));
    fireEvent.click(screen.getByRole("button", { name: "Knowledge Library" }));
    expect(screen.getByText("2 concepts matching “subj”.")).toBeInTheDocument();
    expect(calls.every((c) => c.method === "GET")).toBe(true);
    expect(calls.some((c) => /analysis|extractions|concept-links|invalid|distinctions/.test(c.path))).toBe(false);
  });

  it("shows an orphaned concept honestly", async () => {
    library();
    await openLibrary();
    fireEvent.click(await screen.findByRole("button", { name: "faire" }));
    expect(await screen.findByText(/Orphaned: no unit currently supports this concept/)).toBeInTheDocument();
    expect(screen.getByText("No unit currently supports this concept.")).toBeInTheDocument();
    expect(screen.getByText("No preferred unit is set.")).toBeInTheDocument();
  });

  it("never labels earlier results with a new query while it is searching", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    globalThis.fetch = vi.fn(async (input: string | URL | Request) => {
      const url = new URL(String(input), "http://localhost");
      if (url.searchParams.get("q") === "slow") await gate;
      const body = url.pathname === "/api/knowledge-library/concepts"
        ? { schema_version: "knowledge_library_search_v1", query: url.searchParams.get("q") ?? "", tokens: [], state: "all", limit: 20,
            total_matches: 1, truncated: false,
            results: [{ concept: concept(url.searchParams.get("q") ? 3 : 1, url.searchParams.get("q") ? "faire" : "subjonctif après il faut que", "active"), match_tier: "browse", matched_fields: [], current_member_count: 1, supporting_unit_count: 1 }] }
        : { reviewable_units: [], concepts: [] };
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }) as unknown as typeof fetch;
    await openLibrary();
    expect(await screen.findByText("1 concept.")).toBeInTheDocument();
    // Record every text the DOM shows, including frames replaced within one act().
    const shown: string[] = [];
    const observer = new MutationObserver((records) => {
      for (const r of records) {
        shown.push(r.target.textContent ?? "");
        r.addedNodes.forEach((n) => shown.push(n.textContent ?? ""));
      }
    });
    observer.observe(document.body, { subtree: true, childList: true, characterData: true });
    fireEvent.change(screen.getByLabelText("Search learned material"), { target: { value: "slow" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("Searching the knowledge library…")).toBeInTheDocument();
    await Promise.resolve();
    observer.disconnect();
    expect(shown.filter((t) => t.includes("matching “slow”"))).toEqual([]);
    expect(screen.queryByRole("button", { name: "subjonctif après il faut que" })).toBeNull();
    release();
    expect(await screen.findByText("1 concept matching “slow”.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "faire" })).toBeInTheDocument();
  });

  it("has empty and error states with an explicit retry", async () => {
    let fail = true;
    library({
      "/api/knowledge-library/concepts": () => (fail ? { status: 500, body: { error: "could not search the knowledge library" } } : { body: { schema_version: "knowledge_library_search_v1", query: "", tokens: [], state: "all", limit: 20, total_matches: 0, truncated: false, results: [] } }),
      "/api/knowledge-library/concepts?q=%21": () => ({ status: 400, body: { error: "invalid knowledge library query: q has no searchable term" } }),
    });
    await openLibrary();
    expect(await screen.findByRole("alert")).toHaveTextContent("(500) could not search the knowledge library");
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(/The library is empty/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search learned material"), { target: { value: "nothing" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("No concepts match “nothing”.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search learned material"), { target: { value: "!" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("no searchable term");
  });
});
