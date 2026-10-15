import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PublicDemoApp from "./PublicDemoApp";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const concept = (id: number, target: string) => ({
  id, identity_schema_version: "fr_l2_concept_identity_v1", target, pedagogical_intent: "grammar", scope: "",
  identity_features: {}, signature: "{}", preferred_unit_id: null, state: "active", lifecycle_state: "normal",
  support_state: "supported", created_at: "t", updated_at: "t",
});
const index = { space: "flh073_demo_x", collection: "flh073_demo_x_r54386d802b65", representation: "concept_embedding_text_v1",
  model_id: "flh073-mechanical-hash@1", dimensions: 64, published_run_id: "54386d802b65d2b3", published_at: null,
  last_run_operation: "artifact", last_run_outcome: "published", last_run_finished_at: null, last_error: "", health_verified: false, note: "history" };
const info = {
  schema_version: "knowledge_library_public_demo_v1", read_only: true, data: "synthetic",
  artifact: { version: "54386d802b65d2b3", manifest_sha256: "e44a", vector_source: "mechanical-test", real_model: false,
    vector_generator: "flh073_mechanical_hash_v1", model_id: "flh073-mechanical-hash@1", dimensions: 64,
    document_representation: "concept_embedding_text_v1", query_representation: "concept_search_query_v2",
    release_status: "blocked_mechanical_vectors", notice: "mechanical", domain_fingerprint_sha256: "e0ce" },
  query_policy: "presets only",
  presets: [
    { id: "miss-someone", label: "Telling a friend you miss them", text: "how to tell a friend I miss them" },
    { id: "no-longer", label: "Stopping a habit", text: "no longer doing something" },
  ],
  counters: { preset_vector_lookups: 0, refused_vector_lookups: 0 },
};

function demoServer() {
  const calls: Array<{ method: string; url: string }> = [];
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    calls.push({ method: (init?.method ?? "GET").toUpperCase(), url: `${url.pathname}${url.search}` });
    let body: unknown = { error: "not available in the public demo" };
    let status = 404;
    if (url.pathname === "/api/knowledge-library/demo") [body, status] = [info, 200];
    else if (url.pathname === "/api/knowledge-library/concepts") {
      const q = url.searchParams.get("q") ?? "";
      body = { schema_version: "knowledge_library_search_v1", query: q, tokens: [], state: "all", limit: 20, total_matches: 1, truncated: false,
        results: [{ concept: concept(1, "subjunctive after « il faut que »"), match_tier: q ? "identity" : "browse", matched_fields: q ? ["target"] : [], current_member_count: 1, supporting_unit_count: 1 }] };
      status = 200;
    } else if (url.pathname === "/api/knowledge-library/demo/semantic-search") {
      const p = info.presets.find((x) => x.id === url.searchParams.get("preset"));
      body = { schema_version: "knowledge_library_semantic_search_v2", query: p?.text, query_representation: "concept_search_query_v2",
        state: "all", limit: 20, index, considered: 12, skipped: { missing: 0, stale: 0, incompatible: 0, non_positive: 0 }, filtered_by_state: 0,
        score_note: "cosine", results: [{ concept: concept(4, "tu me manques: saying you miss someone"), similarity: 0.31, current_member_count: 2, supporting_unit_count: 2 }] };
      status = 200;
    } else if (url.pathname === "/api/knowledge-library/demo/hybrid-search") {
      const p = info.presets.find((x) => x.id === url.searchParams.get("preset"));
      body = { schema_version: "knowledge_library_hybrid_search_v1", query: p?.text, state: url.searchParams.get("state") ?? "all", limit: 20, depth: 50,
        policy: { version: "concept_hybrid_rrf_v1", rrf_k: 60, weights: { keyword: 1, semantic: 1 }, tie_break: "concept_id_ascending" }, score_note: "",
        components: { keyword: { returned: 0, total_matches: 0, truncated_at_depth: false, matching: "" },
          semantic: { returned: 1, considered: 12, skipped: { missing: 0, stale: 0, incompatible: 0, non_positive: 0 }, filtered_by_state: 0, query_representation: "concept_search_query_v2", index, score_note: "" } },
        total_candidates: 1, truncated: false, dropped_after_fusion: { missing: 0, filtered_by_state: 0, changed_during_search: 0, duplicate_component_ids: 0 },
        results: [{ concept: concept(10, "ne … plus: no longer"), fused_score: 1 / 61, sources: ["semantic"], keyword: null, semantic: { rank: 1, similarity: 0.4 }, current_member_count: 1, supporting_unit_count: 1 }] };
      status = 200;
    }
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
  return calls;
}

describe("Public demo", () => {
  it("explains the demo, labels mechanical vectors and shows no workbench controls", async () => {
    const calls = demoServer();
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    expect(await screen.findByText(/Development build: the vectors are mechanical test fixtures/)).toHaveTextContent("not how relevant the results are");
    const about = screen.getByRole("region", { name: "About this demo" });
    expect(about).toHaveTextContent("All data here is synthetic");
    expect(about).toHaveTextContent("read-only — nothing you do is saved");
    expect(about).toHaveTextContent("Free-text semantic search is disabled");
    expect(await screen.findByText("1 concept.")).toBeInTheDocument();
    for (const name of ["Learning Records", "Concept Review", "Annotation Inspector", "Experiment Dashboard"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(screen.queryByText(/Import|Request analysis|Extract/i)).toBeNull();
    expect(calls.every((c) => c.method === "GET")).toBe(true);
    expect(document.title).toBe("Knowledge Library — read-only public demo");
    expect(document.documentElement.lang).toBe("en");
  });

  it("keeps keyword free text but runs semantic and hybrid only as presets with the exact text shown", async () => {
    const calls = demoServer();
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    expect(await screen.findByText("1 concept.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search learned material"), { target: { value: "subjonctif" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText(/1 concept matching “subjonctif”/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: "Semantic" }));
    expect(screen.queryByLabelText("Search learned material")).toBeNull();
    const preset = screen.getByLabelText("Example query");
    expect(within(preset).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Telling a friend you miss them: “how to tell a friend I miss them”",
      "Stopping a habit: “no longer doing something”",
    ]);
    expect(screen.getByRole("note")).toHaveTextContent("Semantic and hybrid search are limited to a fixed list of example queries");
    expect(screen.queryByText(/It needs that index and an embedding service/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText(/1 concept by similarity to “how to tell a friend I miss them”/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: "Hybrid" }));
    fireEvent.change(screen.getByLabelText("Example query"), { target: { value: "no-longer" } });
    fireEvent.change(screen.getByLabelText("Concept status"), { target: { value: "active" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    const results = await screen.findByRole("region", { name: "Hybrid results" });
    expect(within(results).getByText(/1 merged concept for “no longer doing something” with status active/)).toBeInTheDocument();
    expect(within(results).getByText(/Not found by keyword · Semantic #1/)).toBeInTheDocument();

    const urls = calls.map((c) => c.url);
    expect(urls).toContain("/api/knowledge-library/demo/semantic-search?preset=miss-someone");
    expect(urls).toContain("/api/knowledge-library/demo/hybrid-search?preset=no-longer&state=active");
    // Never a free-text semantic/hybrid request, and only allowlisted routes.
    expect(urls.some((u) => /\/knowledge-library\/(semantic|hybrid)-search/.test(u))).toBe(false);
    expect(urls.every((u) => /^\/api\/knowledge-library\/(concepts|demo)/.test(u))).toBe(true);
    expect(calls.every((c) => c.method === "GET")).toBe(true);
  });
});
