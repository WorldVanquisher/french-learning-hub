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
    expect(
      screen.getByText(
        "Found in the explanation of a unit filed here, not in the concept's title. Being filed here does not mean the unit supports the concept; open it to see.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("grammar · 2 units filed here, 1 currently supporting · concept #1")).toBeInTheDocument();
    expect(calls.some((c) => c.search === "?q=subj")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "subjonctif après il faut que" }));
    const heading = await screen.findByRole("heading", { name: /subjonctif après il faut que/ });
    await waitFor(() => expect(heading).toHaveFocus());
    const support = screen.getByRole("region", { name: "Currently supporting this concept (1)" });
    expect(within(support).getByText("forme 12")).toBeInTheDocument();
    // A current member from a historical extraction is never shown as support.
    expect(within(support).queryByText("forme 11")).toBeNull();
    const members = screen.getByRole("region", { name: "Filed here but not supporting (1)" });
    expect(within(members).getByText(/extraction v1 of record #110, which is no longer that record's current extraction/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Best explanation (preferred unit)" })).toHaveTextContent("still filed here, but it does not support the concept");
    expect(screen.getByRole("region", { name: "Linked units (1)" })).toHaveTextContent("BROADER link from unit #13 to this concept (link #7, decided by human).");
    const history = screen.getByRole("region", { name: "History: no longer current (1)" });
    expect(history).toHaveTextContent("This unit was later marked INVALID");
    expect(history).toHaveTextContent("6 decisions recorded for this concept");

    fireEvent.click(within(screen.getByRole("region", { name: "Best explanation (preferred unit)" })).getByRole("button", { name: "View source record #110" }));
    expect(await screen.findByRole("heading", { name: "Where unit #11 came from: learning record #110" })).toBeInTheDocument();
    expect(screen.getByText("Pourquoi « il faut que je fasse » ?")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Extraction v1" })).toHaveTextContent("Historical: this is not the record's current extraction (the current one is extraction #1200, selected automatically)");
    const interp = screen.getByRole("region", { name: "Interpretation this extraction used: analysis v1" });
    expect(interp).toHaveTextContent("corrected by a person (feedback #8, corrected)");
    expect(interp).toHaveTextContent("Before correction");
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

  it("keeps every relation one unit holds to a concept, with no duplicate React keys", async () => {
    // Two legitimate, distinct relations recorded from the same unit (#13).
    const detail = {
      schema_version: "knowledge_library_concept_v1", concept: concept(1, "subjonctif après il faut que", "active"),
      preferred_unit: null, supporting_units: [unit(12, true)], non_supporting_members: [],
      current_relations: [
        { relation: "related", link_id: 7, decision_source: "human", decided_at: "t", unit: unit(13, true) },
        { relation: "broader", link_id: 8, decision_source: "human", decided_at: "t", unit: unit(13, true) },
      ],
      historical_units: [], history_event_count: 3,
    };
    library({ "/api/knowledge-library/concepts/1": () => ({ body: detail }) });
    const errors = vi.spyOn(console, "error");
    await openLibrary();
    fireEvent.click(await screen.findByRole("button", { name: "subjonctif après il faut que" }));
    const relations = await screen.findByRole("region", { name: "Linked units (2)" });
    expect(within(relations).getByText("RELATED")).toBeInTheDocument();
    expect(within(relations).getByText("BROADER")).toBeInTheDocument();
    expect(within(relations).getAllByRole("button", { name: /View source record #130/ })).toHaveLength(2);
    expect(relations).toHaveTextContent("RELATED link from unit #13 to this concept (link #7, decided by human).");
    expect(relations).toHaveTextContent("BROADER link from unit #13 to this concept (link #8, decided by human).");
    const keyWarnings = errors.mock.calls.filter((args) => args.some((a) => String(a).includes("same key")));
    expect(keyWarnings).toEqual([]);
  });

  it("explains filing versus support in plain English and keeps French examples marked as French", async () => {
    const detail = {
      schema_version: "knowledge_library_concept_v1", concept: concept(1, "subjonctif après il faut que", "active"),
      preferred_unit: unit(12, true), supporting_units: [unit(12, true, { example: "Il faut que tu viennes demain." })],
      non_supporting_members: [unit(15, true, { admission: "suppressed" })], current_relations: [],
      historical_units: [{ unit: unit(16, true), latest_event: { id: 4, unit_id: 16, concept_id: 1, relation: "same", status: "accepted", decision_source: "human", resolver_version: "", score: null, evidence: "", supersedes_link_id: null, created_at: "t" }, effective_status: "resolved", current_concept_id: 6 }],
      history_event_count: 4,
    };
    library({ "/api/knowledge-library/concepts/1": () => ({ body: detail }) });
    await openLibrary();
    expect(screen.getByText(/is one idea you have learned, such as a grammar rule/)).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "subjonctif après il faut que" }));
    expect(await screen.findByText(/A unit is filed under a concept when it was judged to be the same idea/)).toBeInTheDocument();
    expect(screen.getByText(/^Active: at least one unit currently supports this concept/)).toBeInTheDocument();
    // Technical identifiers stay available, but secondary.
    expect(screen.getByText("Concept #1 · lifecycle normal · support supported")).toBeInTheDocument();
    const support = screen.getByRole("region", { name: "Currently supporting this concept (1)" });
    const example = within(support).getByText("Il faut que tu viennes demain.");
    expect(example).toHaveAttribute("lang", "fr");
    expect(example.parentElement).toHaveTextContent("French example: Il faut que tu viennes demain.");
    expect(screen.getByRole("region", { name: "Filed here but not supporting (1)" })).toHaveTextContent(
      "The learner hid it (admission suppressed).",
    );
    const history = screen.getByRole("region", { name: "History: no longer current (1)" });
    expect(history).toHaveTextContent("This unit was moved: it is now filed under concept #6.");
    expect(within(history).getByRole("button", { name: "concept #6" })).toBeInTheDocument();
  });

  it("runs an explicit semantic search, labels similarity and index state, and opens current concept details", async () => {
    const semantic = {
      schema_version: "knowledge_library_semantic_search_v2", query: "needing to do something", query_representation: "concept_search_query_v1",
      state: "all", limit: 20,
      index: { space: "flh_concepts_x", collection: "flh_concepts_x_rabc", representation: "concept_embedding_text_v1",
        model_id: "fake/bag-of-words@1", dimensions: 64, published_run_id: "abc", published_at: "2026-10-10T12:00:00Z",
        last_run_operation: "sync", last_run_outcome: "failed", last_run_finished_at: "2026-10-10T12:05:00Z",
        last_error: "embedding provider unavailable", health_verified: false, note: "recorded history" },
      considered: 6, skipped: { missing: 1, stale: 1, incompatible: 0, non_positive: 0 }, filtered_by_state: 0,
      score_note: "cosine similarity; not a probability",
      results: [{ concept: concept(1, "subjonctif après il faut que", "active"), similarity: 0.4213, current_member_count: 2, supporting_unit_count: 1 }],
    };
    const calls = library({ "/api/knowledge-library/semantic-search?q=needing+to+do+something": () => ({ body: semantic }) });
    await openLibrary();
    expect(await screen.findByText("2 concepts.")).toBeInTheDocument();
    const before = calls.length;
    fireEvent.click(screen.getByRole("radio", { name: "Semantic" }));
    fireEvent.change(screen.getByLabelText("Search learned material"), { target: { value: "needing to do something" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText(/1 concept by similarity to “needing to do something”/)).toBeInTheDocument();
    expect(screen.getByText(/Similarity 0\.42 \(cosine; not a probability or a SAME judgment\)/)).toBeInTheDocument();
    expect(screen.getByText(/The last index run ended “failed”/)).toHaveTextContent("embedding provider unavailable");
    expect(screen.getByText(/Index published 2026-10-10T12:00:00Z; last run: sync failed/)).toHaveTextContent(
      "not re-verified for this search",
    );
    expect(screen.queryByText(/index complete/)).toBeNull();
    expect(screen.getByText(/2 index entries were dropped as out of date or no longer valid/)).toBeInTheDocument();
    // Only the semantic endpoint was called for this query: no keyword fallback.
    const after = calls.slice(before);
    expect(after.map((c) => c.path)).toEqual(["/api/knowledge-library/semantic-search"]);

    fireEvent.click(screen.getByRole("button", { name: "subjonctif après il faut que" }));
    expect(await screen.findByRole("region", { name: "Currently supporting this concept (1)" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "← Back to semantic results for “needing to do something”" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "subjonctif après il faut que" })).toHaveFocus());
    expect(calls.every((c) => c.method === "GET")).toBe(true);
  });

  it("reports an unconfigured semantic search explicitly and never searches by keyword instead", async () => {
    const calls = library({
      "/api/knowledge-library/semantic-search?q=subjonctif": () => ({ status: 503, body: { error: "semantic search is not configured" } }),
    });
    await openLibrary();
    expect(await screen.findByText("2 concepts.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Semantic" }));
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("Type a query, then Search, to run a semantic search.")).toBeInTheDocument();
    const before = calls.length;
    fireEvent.change(screen.getByLabelText("Search learned material"), { target: { value: "subjonctif" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not run the semantic search: (503) semantic search is not configured");
    expect(calls.slice(before).some((c) => c.path === "/api/knowledge-library/concepts")).toBe(false);
    expect(screen.queryByText(/concepts? matching/)).toBeNull();
  });

  it("runs an explicit hybrid search and shows where each result came from", async () => {
    const index = { space: "flh_concepts_x", collection: "flh_concepts_x_rabc", representation: "concept_embedding_text_v1",
      model_id: "fake/bag-of-words@1", dimensions: 64, published_run_id: "abc", published_at: "2026-10-10T12:00:00Z",
      last_run_operation: "build", last_run_outcome: "published", last_run_finished_at: "2026-10-10T12:05:00Z",
      last_error: "", health_verified: false, note: "recorded history" };
    const hybrid = {
      schema_version: "knowledge_library_hybrid_search_v1", query: "subjonctif", state: "all", limit: 20, depth: 50,
      policy: { version: "concept_hybrid_rrf_v1", rrf_k: 60, weights: { keyword: 1, semantic: 1 }, tie_break: "concept_id_ascending" },
      score_note: "not a probability",
      components: {
        keyword: { returned: 2, total_matches: 2, truncated_at_depth: false, matching: "prefix" },
        semantic: { returned: 2, considered: 8, skipped: { missing: 0, stale: 1, incompatible: 0, non_positive: 0 }, filtered_by_state: 0,
          query_representation: "concept_search_query_v2", index, score_note: "cosine" },
      },
      total_candidates: 3, truncated: false,
      dropped_after_fusion: { missing: 0, filtered_by_state: 0, changed_during_search: 1, duplicate_component_ids: 0 },
      results: [
        { concept: concept(1, "subjonctif après il faut que", "active"), fused_score: 1 / 61 + 1 / 62, sources: ["keyword", "semantic"],
          keyword: { rank: 1, match_tier: "identity", matched_fields: ["target"] }, semantic: { rank: 2, similarity: 0.512 },
          current_member_count: 2, supporting_unit_count: 1 },
        { concept: concept(5, "bien que", "orphaned"), fused_score: 1 / 61, sources: ["semantic"], keyword: null,
          semantic: { rank: 1, similarity: 0.6 }, current_member_count: 0, supporting_unit_count: 0 },
        { concept: concept(3, "faire", "orphaned"), fused_score: 1 / 62, sources: ["keyword"],
          keyword: { rank: 2, match_tier: "unit_evidence", matched_fields: ["unit_statement"] }, semantic: null,
          current_member_count: 1, supporting_unit_count: 0 },
      ],
    };
    const calls = library({ "/api/knowledge-library/hybrid-search?q=subjonctif": () => ({ body: hybrid }) });
    await openLibrary();
    expect(await screen.findByText("2 concepts.")).toBeInTheDocument();
    const before = calls.length;
    fireEvent.click(screen.getByRole("radio", { name: "Hybrid" }));
    fireEvent.change(screen.getByLabelText("Search learned material"), { target: { value: "subjonctif" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    const results = await screen.findByRole("region", { name: "Hybrid results" });
    expect(within(results).getByText("3 merged concepts for “subjonctif”.")).toBeInTheDocument();
    expect(within(results).getByText(/Policy concept_hybrid_rrf_v1: reciprocal rank fusion with k = 60, equal weights/)).toHaveTextContent(
      "not a probability or a relevance estimate",
    );
    expect(within(results).getByText(/index flh_concepts_x_rabc, model fake\/bag-of-words@1/)).toBeInTheDocument();
    const items = within(results).getAllByRole("listitem");
    expect(items.map((li) => within(li).getByRole("button").textContent)).toEqual(["subjonctif après il faut que", "bien que", "faire"]);
    expect(items[0]).toHaveTextContent("Keyword #1 (found in title) · Semantic #2 (similarity 0.51) · Combined score 0.0325");
    expect(items[1]).toHaveTextContent("Not found by keyword · Semantic #1 (similarity 0.60) · Combined score 0.0164");
    expect(items[2]).toHaveTextContent(
      "Keyword #2 (found in the explanation of a unit filed here) · Not among the semantic candidates · Combined score 0.0161",
    );
    expect(within(results).getByText(/semantic search dropped 1 out-of-date or invalid index entry/)).toHaveTextContent(
      "1 concept was removed because it changed or disappeared during the search",
    );
    // Only the hybrid endpoint was called: the browser neither fuses nor falls back.
    expect(calls.slice(before).map((c) => c.path)).toEqual(["/api/knowledge-library/hybrid-search"]);
    fireEvent.click(screen.getByRole("button", { name: "subjonctif après il faut que" }));
    expect(await screen.findByRole("region", { name: "Currently supporting this concept (1)" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "← Back to hybrid results for “subjonctif”" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "subjonctif après il faut que" })).toHaveFocus());
    expect(calls.every((c) => c.method === "GET")).toBe(true);
  });

  it("fails hybrid search explicitly without keyword results and needs a query", async () => {
    const calls = library({
      "/api/knowledge-library/hybrid-search?q=subjonctif&state=active": () => ({
        status: 503, body: { error: "hybrid search needs semantic search, which is not configured" },
      }),
    });
    await openLibrary();
    expect(await screen.findByText("2 concepts.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Hybrid" }));
    let before = calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("Type a query, then Search, to run a hybrid search.")).toBeInTheDocument();
    expect(calls.length).toBe(before);
    before = calls.length;
    fireEvent.change(screen.getByLabelText("Search learned material"), { target: { value: "subjonctif" } });
    fireEvent.change(screen.getByLabelText("Concept status"), { target: { value: "active" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not run the hybrid search: (503) hybrid search needs semantic search, which is not configured",
    );
    expect(calls.slice(before).map((c) => `${c.path}${c.search}`)).toEqual(["/api/knowledge-library/hybrid-search?q=subjonctif&state=active"]);
    expect(screen.queryByRole("region", { name: "Library results" })).toBeNull();
  });

  it("shows an orphaned concept honestly", async () => {
    library();
    await openLibrary();
    fireEvent.click(await screen.findByRole("button", { name: "faire" }));
    expect(await screen.findByText(/Orphaned: no unit currently supports this concept/)).toBeInTheDocument();
    expect(screen.getByText("No unit currently supports this concept.")).toBeInTheDocument();
    expect(screen.getByText("No unit has been chosen as the best explanation.")).toBeInTheDocument();
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
