import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PublicDemoApp from "../PublicDemoApp";
import { DEMO_EXAMPLES, resolveExample } from "./examples";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  // Each test starts on the demo's start: the address carries the last screen and search.
  window.history.replaceState(null, "", "/");
});

// The synthetic catalog the public demo artifact is built from (D1); vitest runs in web/.
const catalog = JSON.parse(
  readFileSync(resolve(process.cwd(), "../scripts/demo/flh073/fixtures/catalog.json"), "utf8"),
) as { entries: Array<{ key: string; original_input: string; units: Array<{ key: string; canonical: string }> }>; concepts: Array<{ key: string; target: string; members: string[] }> };

describe("guided examples match the demo catalog", () => {
  it("quotes each example's question on its card exactly as the catalog stores it", () => {
    for (const ex of DEMO_EXAMPLES) {
      const entry = catalog.entries.find((e) => e.units.some((u) => u.canonical.toLocaleLowerCase("fr").includes(ex.seed)))!;
      expect(ex.question, ex.key).toBe(entry.original_input);
    }
  });

  it("each seed names exactly one unit, of a different question, in the language the example says", () => {
    const entries = DEMO_EXAMPLES.map((ex) => {
      const hits = catalog.entries.flatMap((e) => e.units.filter((u) => u.canonical.toLocaleLowerCase("fr").includes(ex.seed)).map(() => e));
      expect(hits, ex.key).toHaveLength(1);
      return hits[0];
    });
    expect(new Set(entries.map((e) => e.key)).size).toBe(DEMO_EXAMPLES.length);
    // Three questions written in French (they quote French in « »), and one
    // written in English (R2: its two units are the imparfait comparison).
    entries.forEach((e, i) => {
      if (DEMO_EXAMPLES[i].lang === "fr") expect(e.original_input, DEMO_EXAMPLES[i].key).toMatch(/« .+ »/);
      else expect(e.original_input, DEMO_EXAMPLES[i].key).toMatch(/^When do I use /);
    });
    expect(DEMO_EXAMPLES.map((e) => e.lang)).toEqual(["fr", "fr", "fr", "en"]);
  });

  it("every unit of an example's question is filed under a Concept", () => {
    for (const ex of DEMO_EXAMPLES) {
      const entry = catalog.entries.find((e) => e.units.some((u) => u.canonical.toLocaleLowerCase("fr").includes(ex.seed)))!;
      for (const u of entry.units) expect(catalog.concepts.some((c) => c.members.includes(u.key)), `${ex.key} ${u.key}`).toBe(true);
    }
  });
});

const concept = (id: number, target: string) => ({
  id, identity_schema_version: "fr_l2_concept_identity_v1", target, pedagogical_intent: "grammar", scope: "",
  identity_features: {}, signature: "{}", preferred_unit_id: null, state: "active", lifecycle_state: "normal",
  support_state: "supported", created_at: "t", updated_at: "t",
});
const unit = (id: number, entry: number, canonical: string, example: string | null = null) => ({
  unit_id: id, kind: "grammar", canonical, statement: `Statement ${id}`, example, entry_id: entry,
  extraction_id: entry, extraction_version: 1, in_current_extraction: true, admission: "active",
});
const detail = (c: ReturnType<typeof concept>, units: ReturnType<typeof unit>[], preferred = true) => ({
  schema_version: "knowledge_library_concept_v1", concept: c, preferred_unit: preferred ? (units[0] ?? null) : null, supporting_units: units,
  non_supporting_members: [], current_relations: [], historical_units: [], history_event_count: units.length,
});
const QUESTION = "Dans « j'y vais » et « j'en veux », qu'est-ce que « y » et « en » remplacent ?";
const source = (u: ReturnType<typeof unit>, conceptId: number, input: string) => ({
  schema_version: "knowledge_library_source_v1", unit: u,
  entry: { id: u.entry_id, original_input: input, original_context: "Synthetic example.", created_at: "2026-11-10", updated_at: "t" },
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

const yLieu = unit(12, 9, "y remplace à + lieu", "Tu vas au marché ? Oui, j'y vais.");
const enNom = unit(13, 9, "en remplace de + nom");
const ilFautOld = unit(1, 1, "subjonctif après il faut que");
const ilFautVenir = unit(14, 10, "il faut que + subjonctif de venir");
const info = {
  schema_version: "knowledge_library_public_demo_v1", read_only: true, data: "synthetic",
  artifact: { version: "v", manifest_sha256: "m", vector_source: "mechanical-test", real_model: false, vector_generator: "flh073_mechanical_hash_v1",
    model_id: "flh073-mechanical-hash@1", dimensions: 64, document_representation: "d", query_representation: "q", release_status: "blocked_mechanical_vectors",
    notice: "n", domain_fingerprint_sha256: "f" },
  query_policy: "p", presets: [{ id: "right-now", label: "Something happening right now", text: "doing something right now" }],
  counters: { preset_vector_lookups: 0, refused_vector_lookups: 0 },
};

function demoServer(fail: Record<string, number> = {}, realModel = false) {
  const calls: Array<{ method: string; url: string }> = [];
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname.replace(/^\/api/, "");
    calls.push({ method: (init?.method ?? "GET").toUpperCase(), url: `${url.pathname}${url.search}` });
    const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    if (fail[path]) return reply(fail[path], { error: "unavailable" });
    const search = (results: Array<{ c: ReturnType<typeof concept>; n: number }>, units = false) =>
      reply(200, { schema_version: "knowledge_library_search_v1", query: url.searchParams.get("q") ?? "",
        tokens: (url.searchParams.get("q") ?? "").split(" ").filter(Boolean), state: "all", limit: 20,
        total_matches: results.length, truncated: false,
        results: results.map(({ c, n }) => ({ concept: c, match_tier: units ? "unit_evidence" : "identity", matched_fields: units ? ["unit_statement", "unit_example"] : ["target"],
          current_member_count: n, supporting_unit_count: n })) });
    if (path === "/knowledge-library/demo") return reply(200, { ...info, artifact: { ...info.artifact, real_model: realModel } });
    if (path === "/knowledge-library/demo/semantic-search")
      return reply(200, { schema_version: "knowledge_library_semantic_search_v2", query: "doing something right now", query_representation: "q", state: "all", limit: 20,
        index: { space: "s", collection: "c", representation: "r", model_id: "flh073-mechanical-hash@1", dimensions: 64, published_run_id: "p", published_at: null,
          last_run_operation: "artifact", last_run_outcome: "published", last_run_finished_at: null, last_error: "", health_verified: false, note: "" },
        considered: 14, skipped: { missing: 0, stale: 0, incompatible: 0, non_positive: 0 }, filtered_by_state: 0, score_note: "",
        results: [{ concept: concept(12, "the pronouns y and en"), similarity: 0.15, current_member_count: 2, supporting_unit_count: 2 }] });
    if (path === "/knowledge-library/concepts") {
      const q = url.searchParams.get("q");
      if (q === "pronouns") return search([{ c: concept(12, "the pronouns y and en"), n: 2 }]);
      if (q === "viennes") return search([{ c: concept(1, "subjunctive after « il faut que »"), n: 2 }], true);
      if (q === "action en cours") return search([]);
      return search([{ c: concept(12, "the pronouns y and en"), n: 2 }, { c: concept(1, "subjunctive after « il faut que »"), n: 2 }]);
    }
    if (path === "/knowledge-library/concepts/12") return reply(200, detail(concept(12, "the pronouns y and en"), [yLieu, enNom]));
    if (path === "/knowledge-library/concepts/1") return reply(200, detail(concept(1, "subjunctive after « il faut que »"), [ilFautOld, ilFautVenir], false));
    if (path === "/knowledge-library/units/12/source") return reply(200, source(yLieu, 12, QUESTION));
    if (path === "/knowledge-library/units/13/source") return reply(200, source(enNom, 12, QUESTION));
    if (path === "/knowledge-library/units/14/source") return reply(200, source(ilFautVenir, 1, "Pourquoi « viennes » et pas « viens » ?"));
    return reply(404, { error: "not available in the public demo" });
  }) as unknown as typeof fetch;
  return calls;
}

describe("resolveExample", () => {
  it("collects the units of the seed's question across the matched Concepts and counts other evidence", async () => {
    demoServer();
    const byKey = (key: string) => DEMO_EXAMPLES.find((e) => e.key === key)!;
    const yEn = await resolveExample(byKey("y-en"));
    expect(yEn.kind).toBe("found");
    if (yEn.kind !== "found") return;
    expect(yEn.example.source.entry.original_input).toBe(QUESTION);
    expect(yEn.example.extracted.map((e) => e.unit.unit_id)).toEqual([12, 13]);
    expect(yEn.example.concepts).toEqual([expect.objectContaining({ fromThisQuestion: 2, supporting: 2 })]);

    const ilFaut = await resolveExample(byKey("il-faut-venir"));
    if (ilFaut.kind !== "found") throw new Error("missing");
    expect(ilFaut.example.extracted.map((e) => e.unit.unit_id)).toEqual([14]);
    expect(ilFaut.example.concepts).toEqual([expect.objectContaining({ fromThisQuestion: 1, supporting: 2 })]);
  });

  it("reports an example this build does not contain instead of guessing", async () => {
    demoServer();
    expect(await resolveExample(DEMO_EXAMPLES.find((e) => e.key === "en-train-de")!)).toEqual({ kind: "missing" });
  });
});

describe("Public demo guided path", () => {
  it("opens an example, follows it to the Concept and the evidence, and returns to the example and the start", async () => {
    const calls = demoServer();
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    expect(await screen.findByText(/Follow a French learner's question to the rules taken from it/)).toBeInTheDocument();
    expect(screen.getByText("Read-only")).toBeInTheDocument();
    expect(screen.getByText("Synthetic data")).toBeInTheDocument();
    expect(screen.getByText("Development build")).toBeInTheDocument();
    expect(screen.getByLabelText("Search learned material")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /One question, two pronouns$/ }));
    const heading = await screen.findByRole("heading", { name: "One question, two pronouns" });
    await waitFor(() => expect(heading).toHaveFocus());
    const question = await screen.findByText(QUESTION, { selector: "blockquote" });
    expect(question).toHaveAttribute("lang", "fr");
    expect(screen.getByRole("heading", { name: /What was extracted: 2 units/ })).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: /What was extracted/ })).getByText("y remplace à + lieu")).toBeInTheDocument();
    expect(screen.getByText("2 supporting units, all from this question.")).toBeInTheDocument();
    // Step 4 names the record and the extraction and interpretation its units came from.
    expect(screen.getByRole("heading", { name: /The source evidence/ })).toBeInTheDocument();
    expect(screen.getByText(/This question is learning record #9\. Its units come from extraction v1, which used interpretation v1/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "See the evidence for “y remplace à + lieu”" })).toBeInTheDocument();
    // The labels stay visible away from the starting screen.
    expect(screen.getByText("Read-only")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: /^Open the Concept “.+” and its evidence$/ }));
    const back = await screen.findByRole("button", { name: "← Back to the example “One question, two pronouns”" });
    fireEvent.click(screen.getAllByRole("button", { name: "View source record #9 for unit #12" })[0]);
    expect(await screen.findByRole("heading", { name: "Original learning record #9" })).toBeInTheDocument();
    // The way back names the Concept, not only its number.
    expect(await screen.findByRole("button", { name: "← Back to concept #12: the pronouns y and en" })).toBeInTheDocument();
    // The reason the record is shown, and the unit's current filing, name it too.
    expect(screen.getAllByRole("button", { name: "concept #12, “the pronouns y and en”" })).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "← Back to the example “One question, two pronouns”" }));
    expect(await screen.findByRole("heading", { name: "One question, two pronouns" })).toBeInTheDocument();
    expect(back).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "← Back to examples and search" }));
    await waitFor(() => expect(screen.getByRole("button", { name: /One question, two pronouns$/ })).toHaveFocus());
    expect(calls.every((c) => c.method === "GET")).toBe(true);
    expect(calls.every((c) => /^\/api\/knowledge-library\/(concepts|units|demo)/.test(c.url))).toBe(true);
  });

  it("leads each example card with the learner's question, the most beginner-friendly French one first", async () => {
    demoServer();
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    const cards = await screen.findAllByRole("button", { name: /(One question, two pronouns|New evidence for a known rule|One question, two Concepts|One question, two tenses)$/ });
    expect(cards).toHaveLength(4);
    DEMO_EXAMPLES.forEach((ex, i) => {
      const question = within(cards[i]).getByText(ex.question);
      // In the language it is written in: French for three, English for one.
      expect(question).toHaveAttribute("lang", ex.lang);
      expect(question).toHaveAttribute("dir", "auto");
    });
    // The question comes first, so the card is chosen by the question itself:
    // R2-032, a beginner's question (is « je suis cuisinant » French?) first.
    expect(cards[0].textContent).toMatch(/^Pour dire « I'm cooking right now »/);
    expect(cards[3].textContent).toMatch(/^When do I use the imparfait/);
  });

  it("shows on the example that its Concept can now be found by keyword search", async () => {
    demoServer();
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    fireEvent.click(await screen.findByRole("button", { name: /One question, two pronouns$/ }));
    await screen.findByText(QUESTION, { selector: "blockquote" });
    expect(screen.getByText(/The Concept can now be found by keyword search:/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Search “pronouns”" }));
    const result = await screen.findByRole("button", { name: "the pronouns y and en" });
    expect(window.location.hash).toBe("#q=pronouns");
    expect(screen.getByLabelText("Search learned material")).toHaveValue("pronouns");
    expect(result.closest("li")).toHaveTextContent("Found in title: pronouns.");
    expect(result.closest("li")?.querySelector(".demo-match mark")).toHaveTextContent("pronouns");
  });

  it("names the matched words of a unit-wording match, from the search's own fields", async () => {
    demoServer();
    window.history.replaceState(null, "", "/#q=viennes");
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    const result = await screen.findByRole("button", { name: "subjunctive after « il faut que »" });
    const line = result.closest("li")!.querySelector(".demo-match")!;
    expect(line).toHaveTextContent(
      "Found in the explanation of a unit filed here, the example of a unit filed here, not in the Concept's title: viennes. “Show why it matched” shows that wording and whether the unit currently supports the Concept.",
    );
    expect(line.querySelector("mark")).toHaveTextContent("viennes");
  });

  it("names the evidence's Concept by its number only when its title cannot be read", async () => {
    demoServer({ "/knowledge-library/concepts/12": 503 });
    window.history.replaceState(null, "", "/#concept=12&unit=12");
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    expect(await screen.findByRole("heading", { name: "Original learning record #9" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "← Back to concept #12" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "concept #12" })).toHaveLength(2);
  });

  it("leaves out the Best explanation section when no unit was chosen", async () => {
    demoServer();
    window.history.replaceState(null, "", "/#concept=1");
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    expect(await screen.findByRole("heading", { name: /Currently supporting this concept/ })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Best explanation (preferred unit)" })).toBeNull();
    cleanup();
    window.history.replaceState(null, "", "/#concept=12");
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    expect(await screen.findByRole("heading", { name: "Best explanation (preferred unit)" })).toBeInTheDocument();
  });

  it("opens a unit's source straight from the example and returns to that example", async () => {
    demoServer();
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    fireEvent.click(await screen.findByRole("button", { name: /New evidence for a known rule/ }));
    expect(await screen.findByText("2 supporting units: 1 from this question and 1 from other questions.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "See where unit #14 came from" }));
    expect(await screen.findByText("Pourquoi « viennes » et pas « viens » ?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "← Back to the example “New evidence for a known rule”" }));
    expect(await screen.findByRole("heading", { name: "New evidence for a known rule" })).toBeInTheDocument();
  });

  it("names each unit's source link by its unit, so a screen reader's link list tells them apart (R4-DEM-027)", async () => {
    demoServer();
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    fireEvent.click(await screen.findByRole("button", { name: /One question, two pronouns$/ }));
    expect(await screen.findByRole("button", { name: "See where unit #12 came from" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "See where unit #13 came from" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "See where this unit came from" })).toBeNull();
  });

  it("states a failed example read with a retry, and an example this build lacks with the search instead", async () => {
    demoServer({ "/knowledge-library/concepts/12": 503 });
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    fireEvent.click(await screen.findByRole("button", { name: /One question, two pronouns/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not load this example: (503)");
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "One question, two Concepts" }));
    fireEvent.click(await screen.findByRole("button", { name: "Search for “action en cours” instead" }));
    expect(await screen.findByLabelText("Search learned material")).toHaveValue("action en cours");
  });
});

describe("Public demo interactions", () => {
  it("lets the browser's Back retrace example → Concept → example → start without leaving the demo", async () => {
    demoServer();
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    fireEvent.click(await screen.findByRole("button", { name: /One question, two pronouns/ }));
    await screen.findByText(QUESTION, { selector: "blockquote" });
    fireEvent.click(screen.getByRole("button", { name: /^Open the Concept “.+” and its evidence$/ }));
    await screen.findByRole("heading", { level: 2, name: /the pronouns y and en/ });

    window.history.back();
    expect(await screen.findByText(QUESTION, { selector: "blockquote" })).toBeInTheDocument();
    window.history.back();
    await waitFor(() => expect(screen.getByRole("button", { name: /One question, two pronouns$/ })).toHaveFocus());
  });

  it("puts a mechanical-vector notice beside semantic scores, and none for a real-model build", async () => {
    demoServer();
    const { unmount } = render(<StrictMode><PublicDemoApp /></StrictMode>);
    await screen.findByRole("button", { name: /One question, two pronouns/ });
    fireEvent.click(screen.getByRole("radio", { name: "Semantic" }));
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    const results = await screen.findByRole("region", { name: "Semantic results" });
    expect(within(results).getByRole("note")).toHaveTextContent("It is not evidence that these Concepts are related to the query.");
    unmount();

    demoServer({}, true);
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    await screen.findByRole("button", { name: /One question, two pronouns/ });
    expect(screen.queryByText("Development build")).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "Semantic" }));
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    const real = await screen.findByRole("region", { name: "Semantic results" });
    expect(within(real).queryByRole("note")).toBeNull();
  });

  it("separates the Concept, its evidence and the learner's question, and keeps one set of back actions in view", async () => {
    demoServer();
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    fireEvent.change(await screen.findByLabelText("Search learned material"), { target: { value: "pronouns" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    fireEvent.click(await screen.findByRole("button", { name: "the pronouns y and en" }));
    await screen.findByRole("heading", { level: 2, name: /the pronouns y and en/ });
    const nav = screen.getByRole("navigation", { name: "Return" });
    expect(within(nav).getByRole("button", { name: "← Back to results for “pronouns”" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "← Back to results for “pronouns”" })).toHaveLength(1);
    expect(screen.getByText("Concept details: status, type and identity")).toBeInTheDocument();
    expect(screen.getAllByText("Evidence: taken from learning record #9 and filed under this Concept.")).toHaveLength(2);
    expect(screen.queryByRole("heading", { name: /Linked units/ })).toBeNull();
    expect(screen.queryByRole("heading", { name: /History: no longer current/ })).toBeNull();

    fireEvent.click(screen.getAllByRole("button", { name: "View source record #9 for unit #12" })[0]);
    const entry = await screen.findByRole("heading", { level: 3, name: "Original learning record #9" });
    const question = screen.getByText(QUESTION, { selector: "blockquote" });
    // The learner's question comes before the unit taken from it.
    expect(question.compareDocumentPosition(screen.getByRole("heading", { level: 3, name: "The unit (#12)" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(entry).toBeInTheDocument();
    expect(screen.getByText(/Why this record is shown: unit #12 was taken from it and is filed under/)).toBeInTheDocument();
    // The provenance trail stays visible after the unit.
    expect(screen.getByRole("heading", { level: 3, name: "Interpretation this extraction used: analysis v1" })).toBeVisible();
    const sourceNav = screen.getByRole("navigation", { name: "Return" });
    expect(within(sourceNav).getAllByRole("button")).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: /^← Back to concept #12/ })).toHaveLength(1);
  });
});
