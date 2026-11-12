import { vi } from "vitest";

// A small synthetic public demo for component tests: the demo description, a
// two-Concept catalog in the shape of the D1 fixtures, and the sources of three
// units. Everything is invented test data. Requests are recorded; any path or
// query can be failed (status) or held until the test releases it.

export const QUESTION = "Dans « j'y vais » et « j'en veux », qu'est-ce que « y » et « en » remplacent ?";
export const OTHER_QUESTION = "Pourquoi « viennes » et pas « viens » ?";

export const concept = (id: number, target: string) => ({
  id, identity_schema_version: "fr_l2_concept_identity_v1", target, pedagogical_intent: "grammar", scope: "",
  identity_features: {}, signature: "{}", preferred_unit_id: null, state: "active", lifecycle_state: "normal",
  support_state: "supported", created_at: "t", updated_at: "t",
});
export const unit = (id: number, entry: number, canonical: string, example: string | null = null) => ({
  unit_id: id, kind: "grammar", canonical, statement: `Statement ${id}`, example, entry_id: entry,
  extraction_id: entry, extraction_version: 1, in_current_extraction: true, admission: "active",
});
const detail = (c: ReturnType<typeof concept>, units: ReturnType<typeof unit>[]) => ({
  schema_version: "knowledge_library_concept_v1", concept: c, preferred_unit: null, supporting_units: units,
  non_supporting_members: [], current_relations: [], historical_units: [], history_event_count: units.length,
});
export const source = (u: ReturnType<typeof unit>, conceptId: number, input: string, createdAt = "2026-11-10T08:30:00Z") => ({
  schema_version: "knowledge_library_source_v1", unit: u,
  entry: { id: u.entry_id, original_input: input, original_context: "Synthetic example.", created_at: createdAt, updated_at: "t" },
  extraction: { id: u.entry_id, version: 1, extractor: "fixture:flh073:knowledge_extraction_v1", source_analysis_id: 1, source_feedback_id: null, created_at: "t" },
  current_extraction: { extraction_id: u.entry_id, selection_mode: "automatic" },
  source_interpretation: {
    analysis: { id: 1, entry_id: u.entry_id, version: 1, category: "grammar", explanation: "e", confidence: 1, uncertainty: "", analyzer: "fixture:flh073:fr_l2_taxonomy_v1", created_at: "t" },
    feedback: null,
    effective: { analysis_id: 1, entry_id: u.entry_id, version: 1, original: { category: "grammar", explanation: "e" }, effective: { category: "grammar", explanation: "e" }, resolution: "unreviewed", feedback_id: null },
  },
  latest_analysis: { id: 1, version: 1, created_at: "t" },
  annotation: { status: "resolved", current_concept_id: conceptId },
});

export const yLieu = unit(12, 9, "y remplace à + lieu", "Tu vas au marché ? Oui, j'y vais.");
export const enNom = unit(13, 9, "en remplace de + nom");
export const ilFautOld = unit(1, 1, "subjonctif après il faut que");
export const ilFautVenir = unit(14, 10, "il faut que + subjonctif de venir");
export const PRONOUNS = concept(12, "the pronouns y and en");
export const IL_FAUT = concept(1, "subjunctive after « il faut que »");

export const info = (realModel = false) => ({
  schema_version: "knowledge_library_public_demo_v1", read_only: true, data: "synthetic",
  artifact: { version: "v", manifest_sha256: "m", vector_source: "mechanical-test", real_model: realModel, vector_generator: "flh073_mechanical_hash_v1",
    model_id: "flh073-mechanical-hash@1", dimensions: 64, document_representation: "d", query_representation: "q",
    release_status: "blocked_mechanical_vectors", notice: "n", domain_fingerprint_sha256: "f" },
  query_policy: "p", presets: [{ id: "right-now", label: "Something happening right now", text: "doing something right now" }],
  counters: { preset_vector_lookups: 0, refused_vector_lookups: 0 },
});

export interface DemoServerOptions {
  // Path (without /api) → HTTP status to answer with instead.
  fail?: Record<string, number>;
  // An empty catalog (no Concept matches anything, browsing included).
  empty?: boolean;
}

export function demoServer(opts: DemoServerOptions = {}) {
  const calls: Array<{ method: string; url: string }> = [];
  const held = new Map<string, Array<() => void>>();
  const hold = new Set<string>();
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname.replace(/^\/api/, "");
    calls.push({ method: (init?.method ?? "GET").toUpperCase(), url: `${url.pathname}${url.search}${url.hash}` });
    if (hold.has(path)) await new Promise<void>((resolve) => held.set(path, [...(held.get(path) ?? []), resolve]));
    const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    if (opts.fail?.[path]) return reply(opts.fail[path], { error: "unavailable" });
    const search = (hits: Array<ReturnType<typeof concept>>) =>
      reply(200, { schema_version: "knowledge_library_search_v1", query: url.searchParams.get("q") ?? "", tokens: [], state: url.searchParams.get("state") ?? "all", limit: 20,
        total_matches: hits.length, truncated: false,
        results: hits.map((c) => ({ concept: c, match_tier: "identity", matched_fields: ["target"], current_member_count: 2, supporting_unit_count: 2 })) });
    if (path === "/knowledge-library/demo") return reply(200, info());
    if (path === "/knowledge-library/demo/semantic-search")
      return reply(200, { schema_version: "knowledge_library_semantic_search_v2", query: "doing something right now", query_representation: "q", state: "all", limit: 20,
        index: { space: "s", collection: "c", representation: "r", model_id: "flh073-mechanical-hash@1", dimensions: 64, published_run_id: "p", published_at: null,
          last_run_operation: "artifact", last_run_outcome: "published", last_run_finished_at: null, last_error: "", health_verified: false, note: "" },
        considered: 2, skipped: { missing: 0, stale: 0, incompatible: 0, non_positive: 0 }, filtered_by_state: 0, score_note: "",
        results: [{ concept: PRONOUNS, similarity: 0.15, current_member_count: 2, supporting_unit_count: 2 }] });
    if (path === "/knowledge-library/concepts") {
      if (opts.empty) return search([]);
      const q = url.searchParams.get("q") ?? "";
      if (q === "") return search([PRONOUNS, IL_FAUT]);
      if (q === "pronouns") return search([PRONOUNS]);
      if (q === "viennes" || q === "il faut") return search([IL_FAUT]);
      return search([]);
    }
    if (path === "/knowledge-library/concepts/12") return reply(200, detail(PRONOUNS, [yLieu, enNom]));
    if (path === "/knowledge-library/concepts/1") return reply(200, detail(IL_FAUT, [ilFautOld, ilFautVenir]));
    if (path === "/knowledge-library/units/12/source") return reply(200, source(yLieu, 12, QUESTION));
    if (path === "/knowledge-library/units/13/source") return reply(200, source(enNom, 12, QUESTION));
    if (path === "/knowledge-library/units/14/source") return reply(200, source(ilFautVenir, 1, OTHER_QUESTION));
    if (path === "/knowledge-library/units/1/source") return reply(200, source(ilFautOld, 1, "When do I use the subjunctive after il faut que?"));
    return reply(404, { error: "not available in the public demo" });
  }) as unknown as typeof fetch;
  return {
    calls,
    hold: (path: string) => hold.add(path),
    release: (path: string) => {
      hold.delete(path);
      for (const resolve of held.get(path) ?? []) resolve();
      held.delete(path);
    },
  };
}
