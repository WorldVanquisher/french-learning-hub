import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { ConceptContent, MembershipComparison, UnitSourceDisclosure } from "./components/ConceptContent";
import { ReviewQueue } from "./pages/ReviewQueue";

afterEach(cleanup);

// FLH-093: reading a Concept's current content and a unit's original question
// before an explicit membership decision. All learning content below is
// synthetic, authored for these tests (French "ne … plus" / "ne … jamais").

type Reply = { status?: number; body: unknown };
type Handler = unknown | (() => Reply | Promise<Reply>);

// router answers "METHOD /api/path" keys and records every call.
function router(handlers: Record<string, Handler>) {
  const calls: Array<{ method: string; path: string; body: unknown }> = [];
  const impl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const path = new URL(String(url), "http://localhost").pathname;
    calls.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const h = handlers[`${method} ${path}`];
    const reply: Reply = h === undefined ? { status: 404, body: { error: "not found" } } : typeof h === "function" ? await (h as () => Reply | Promise<Reply>)() : { body: h };
    return new Response(JSON.stringify(reply.body), { status: reply.status ?? 200, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
  globalThis.fetch = impl;
  return calls;
}

function deferred() {
  let resolve!: (r: Reply) => void;
  const promise = new Promise<Reply>((r) => (resolve = r));
  return { promise, resolve };
}

function concept(id: number, target: string, state: "active" | "orphaned" = "active", preferred: number | null = null) {
  return {
    id, identity_schema_version: "fr_l2_concept_identity_v1", target, pedagogical_intent: "grammar", scope: "négation",
    identity_features: {}, signature: `{"target":"${target}"}`, preferred_unit_id: preferred, state,
    lifecycle_state: "normal", support_state: state === "active" ? "supported" : "orphaned",
    created_at: "2026-10-21T10:00:00Z", updated_at: "2026-10-21T10:00:00Z",
  };
}

function libUnit(id: number, entry: number, statement: string, example: string | null, current = true) {
  return {
    unit_id: id, kind: "grammar", canonical: `unit ${id}`, statement, example, entry_id: entry,
    extraction_id: entry, extraction_version: current ? 1 : 1, in_current_extraction: current, admission: "active",
  };
}

const NE_PLUS = [
  libUnit(401, 11, "« Ne … plus » indique qu'une action ou un état a cessé.", "Je ne fume plus depuis l'an dernier."),
  libUnit(402, 12, "Avec « ne … plus », « plus » se place après le verbe conjugué.", "Il ne travaille plus ici."),
  libUnit(403, 13, "Aux temps composés, « plus » se place avant le participe passé.", "Je n'ai plus vu Paul."),
  libUnit(404, 14, "À l'oral, le « ne » de « ne … plus » est souvent omis.", "J'en veux plus."),
  libUnit(405, 15, "« Ne … plus » se combine avec « jamais » : « ne … plus jamais ».", "Je ne le ferai plus jamais."),
];

// Concept 40 has five supporting units (401 preferred), one filed-but-not-
// supporting member from an older extraction and one historical INVALID unit.
const neplus = {
  schema_version: "knowledge_library_concept_v1",
  concept: concept(40, "ne … plus", "active", 401),
  preferred_unit: NE_PLUS[0],
  supporting_units: NE_PLUS,
  non_supporting_members: [libUnit(406, 16, "ÉNONCÉ D'UNE ANCIENNE EXTRACTION", null, false)],
  current_relations: [],
  historical_units: [{ unit: libUnit(407, 17, "ÉNONCÉ INVALIDE", null), latest_event: {}, effective_status: "invalid", current_concept_id: null }],
  history_event_count: 9,
};

// Concept 41 keeps its identity but has no current support.
const nejamais = {
  schema_version: "knowledge_library_concept_v1",
  concept: concept(41, "ne … jamais", "orphaned"),
  preferred_unit: null, supporting_units: [], non_supporting_members: [], current_relations: [], historical_units: [], history_event_count: 2,
};

function source(unitId: number, entryId: number, input: string, context: string, current = true) {
  return {
    schema_version: "knowledge_library_source_v1",
    unit: { ...libUnit(unitId, entryId, "s", null, current) },
    entry: { id: entryId, original_input: input, original_context: context, created_at: "2026-10-21T09:00:00Z" },
    extraction: { id: entryId, version: current ? 2 : 1, extractor: "openai:stub-model:knowledge_extraction_v1", source_analysis_id: 1, source_feedback_id: null, created_at: "2026-10-21T09:01:00Z" },
    current_extraction: { extraction_id: entryId, selection_mode: "automatic" },
    source_interpretation: {},
  };
}

const QUESTION = "Pourquoi dit-on « je ne mange plus de viande » ?\nJe confonds avec « pas plus ».";

describe("ConceptContent", () => {
  it("shows the preferred unit and current support only, counting non-supporting and historical units", async () => {
    const calls = router({ "GET /api/knowledge-library/concepts/40": neplus });
    render(<ConceptContent conceptId={40} />);
    const region = await screen.findByRole("region", { name: "Contents of concept #40" });
    expect(region).toHaveTextContent("ne … plus");
    expect(region).toHaveTextContent("Type: grammar · Scope: négation");
    expect(region).toHaveTextContent("Units currently supporting it: 5.");
    expect(within(region).getByRole("heading", { name: "Preferred explanation" })).toBeInTheDocument();
    expect(region).toHaveTextContent("Chosen by a person as the best explanation; it also currently supports this concept.");
    // The preferred unit is shown once; three of the other four supporting units.
    expect(within(region).getAllByText(NE_PLUS[0].statement)).toHaveLength(1);
    expect(region).toHaveTextContent("Showing 3 of 4.");
    expect(within(region).queryByText(NE_PLUS[4].statement)).toBeNull();
    fireEvent.click(within(region).getByRole("button", { name: "Show all 4" }));
    expect(within(region).getByText(NE_PLUS[4].statement)).toBeInTheDocument();
    // Never shown as evidence: only counted, with the reason elsewhere.
    expect(region).not.toHaveTextContent("ÉNONCÉ D'UNE ANCIENNE EXTRACTION");
    expect(region).not.toHaveTextContent("ÉNONCÉ INVALIDE");
    expect(region).toHaveTextContent("Units filed here but not counted as current support: 1.");
    expect(region).toHaveTextContent("Earlier units that are history only: 1.");
    // Technical identity is present but collapsed.
    expect(region.querySelector("details.raw")).not.toHaveAttribute("open");
    expect(calls.every((c) => c.method === "GET")).toBe(true);
  });

  it("states that an orphaned Concept has no current support", async () => {
    router({ "GET /api/knowledge-library/concepts/41": nejamais });
    render(<ConceptContent conceptId={41} />);
    const region = await screen.findByRole("region", { name: "Contents of concept #41" });
    expect(region).toHaveTextContent("No unit currently supports this concept, so there is no current evidence to compare with.");
    expect(within(region).queryByRole("heading", { name: "Current supporting evidence" })).toBeNull();
  });

  it("distinguishes loading, a missing Concept, and a failed read with an explicit retry", async () => {
    let fail = true;
    const gate = deferred();
    router({
      "GET /api/knowledge-library/concepts/43": () => gate.promise,
      "GET /api/knowledge-library/concepts/44": () => ({ status: 404, body: { error: "concept not found" } }),
      "GET /api/knowledge-library/concepts/42": () => (fail ? { status: 500, body: { error: "database is locked" } } : { body: nejamais }),
    });
    const { rerender } = render(<ConceptContent conceptId={43} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading what concept #43 contains…");
    rerender(<ConceptContent conceptId={44} />);
    expect(await screen.findByText("Concept #44 was not found on the server, so its contents cannot be shown.")).toBeInTheDocument();
    rerender(<ConceptContent conceptId={42} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load what concept #42 contains: (500) database is locked");
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("region", { name: "Contents of concept #41" })).toBeInTheDocument();
    await act(async () => gate.resolve({ body: neplus }));
  });

  it("reports an unexpected response shape as a failed read instead of breaking the page", async () => {
    router({ "GET /api/knowledge-library/concepts/45": { concept: concept(45, "malformed") } });
    render(<ConceptContent conceptId={45} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load what concept #45 contains: unexpected response from the server");
  });

  it("never shows a late answer for an earlier selection", async () => {
    const slow = deferred();
    router({
      "GET /api/knowledge-library/concepts/40": () => slow.promise,
      "GET /api/knowledge-library/concepts/41": nejamais,
    });
    const { rerender } = render(<MembershipComparison conceptId={40} membership={null} />);
    expect(screen.getByText("Loading what concept #40 contains…")).toBeInTheDocument();
    rerender(<MembershipComparison conceptId={41} membership={null} />);
    expect(await screen.findByRole("region", { name: "Contents of concept #41" })).toBeInTheDocument();
    await act(async () => slow.resolve({ body: neplus }));
    expect(screen.queryByText(NE_PLUS[0].statement)).toBeNull();
    expect(screen.queryByRole("region", { name: "Contents of concept #40" })).toBeNull();
    expect(screen.getByText(/SAME files this unit under concept #41 as one more piece of evidence/)).toBeInTheDocument();
  });

  it("explains a reassignment when the unit already belongs to another Concept", async () => {
    router({ "GET /api/knowledge-library/concepts/41": nejamais });
    render(<MembershipComparison conceptId={41} membership={{ concept_id: 40, link_id: 3, updated_at: "2026-10-21T10:00:00Z" }} />);
    expect(await screen.findByText(/This unit is currently filed under concept #40\. SAME would move its membership to concept #41/)).toBeInTheDocument();
  });
});

describe("UnitSourceDisclosure", () => {
  it("opens the original question inline with GET only, keeping line breaks and labelling a historical extraction", async () => {
    const calls = router({ "GET /api/knowledge-library/units/406/source": source(406, 16, QUESTION, "", false) });
    render(<UnitSourceDisclosure unitId={406} />);
    expect(calls).toHaveLength(0); // nothing is read until the reviewer asks
    fireEvent.click(screen.getByRole("button", { name: "Show the original question for unit #406" }));
    const region = await screen.findByRole("region", { name: "Original question for unit #406" });
    expect(region).toHaveTextContent("Learning record #16: what the learner wrote");
    expect(region.querySelector(".pre-wrap")?.textContent).toBe(QUESTION);
    expect(region).toHaveTextContent("(no context recorded)");
    expect(region).toHaveTextContent("which is not the record's current extraction.");
    fireEvent.click(screen.getByRole("button", { name: "Hide the original question for unit #406" }));
    expect(screen.queryByRole("region", { name: "Original question for unit #406" })).toBeNull();
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual(["GET /api/knowledge-library/units/406/source"]);
  });

  it("reports a failed source read and retries only when asked", async () => {
    let fail = true;
    router({
      "GET /api/knowledge-library/units/9/source": () => (fail ? { status: 503, body: { error: "unavailable" } } : { body: source(9, 30, QUESTION, "Avec ma tutrice.") }),
    });
    render(<UnitSourceDisclosure unitId={9} />);
    fireEvent.click(screen.getByRole("button", { name: "Show the original question for unit #9" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the original question for unit #9: (503) unavailable");
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Avec ma tutrice.")).toBeInTheDocument();
  });
});

describe("Concept Review with readable Concept content", () => {
  const unitFixture = (id: number, entry: number) => ({
    unit_id: id, kind: "grammar", canonical: "ne … plus (cessation)",
    statement: id === 9 ? "« Ne … plus » marque qu'une habitude s'est arrêtée." : "« Ne … jamais » exprime l'absence totale.",
    example: id === 9 ? "Elle ne boit plus de café." : "Il ne ment jamais.",
    confidence: 0.9,
    candidate_identity: { target: "ne … plus", pedagogical_intent: "grammar", scope: "négation", identity_features: {} },
    signature: "{sig}", entry_id: entry,
  });

  function queueHandlers(extra: Record<string, Handler> = {}) {
    const unit = unitFixture(9, 30);
    return {
      "GET /api/reviewable-units": { reviewable_units: [unit, unitFixture(10, 31)], next_cursor: null, limit: 50 },
      "GET /api/concepts": { concepts: [concept(40, "ne … plus", "active", 401), concept(41, "ne … jamais", "orphaned")] },
      "GET /api/knowledge-units/9/concept-membership": { unit_id: 9, current_membership: null },
      "GET /api/knowledge-units/9/concept-resolution": { unit_id: 9, candidate_identity: unit.candidate_identity, signature: unit.signature, decision: "no_match", matches: [] },
      "GET /api/knowledge-units/9/source": {},
      "GET /api/knowledge-library/units/9/source": source(9, 30, QUESTION, "Discussion avec ma tutrice (synthétique, FLH-093)."),
      "GET /api/knowledge-library/units/402/source": source(402, 12, "Où se place « plus » ?", ""),
      ...extra,
    };
  }

  async function onUnit9() {
    render(<ReviewQueue />);
    await screen.findByText("« Ne … plus » marque qu'une habitude s'est arrêtée.");
    await waitFor(() => expect(screen.getAllByRole("button", { name: "select this concept" }).length).toBeGreaterThan(0));
  }

  it("inspects the unit's source and a candidate's support with reads only, keeping position, search and drafts", async () => {
    const calls = router(queueHandlers({
      "GET /api/knowledge-library/concepts/40": neplus,
      "POST /api/knowledge-units/9/concept-links/same": { id: 70, unit_id: 9, concept_id: 40, relation: "same", status: "accepted" },
      "GET /api/reviewable-units?": {},
    }));
    await onUnit9();
    const search = screen.getByRole("searchbox", { name: "Search existing concepts" });
    fireEvent.change(search, { target: { value: "ne" } });
    const target = screen.getByLabelText("target");
    fireEvent.change(target, { target: { value: "ne … plus (habitude)" } });
    expect(screen.getByText("unit 1 of 2")).toBeInTheDocument();

    // The unit's own original question, inline.
    fireEvent.click(screen.getByRole("button", { name: "Show the original question for unit #9" }));
    const src = await screen.findByRole("region", { name: "Original question for unit #9" });
    expect(src.querySelector(".pre-wrap")?.textContent).toBe(QUESTION);
    fireEvent.click(screen.getByRole("button", { name: "Hide the original question for unit #9" }));

    // A candidate's contents, expanded without selecting it.
    const card = screen.getByText("ne … plus", { selector: "strong" }).closest(".candidate") as HTMLElement;
    fireEvent.click(within(card).getByRole("button", { name: "Show what concept #40 contains" }));
    const contents = await within(card).findByRole("region", { name: "Contents of concept #40" });
    fireEvent.click(within(contents).getByRole("button", { name: "Show the original question for unit #402" }));
    expect(await within(contents).findByText("Où se place « plus » ?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "SAME → selected" })).toBeDisabled();

    // Selecting shows the comparison beside the unit; still nothing is written.
    fireEvent.click(within(card).getByRole("button", { name: "select this concept" }));
    const comparison = screen.getByRole("region", { name: "Compare before deciding" });
    expect(await within(comparison).findByRole("region", { name: "Contents of concept #40" })).toHaveTextContent(NE_PLUS[0].statement);
    expect(comparison).toHaveTextContent("SAME files this unit under concept #40 as one more piece of evidence.");

    // Position, search text and the identity draft survived every inspection.
    expect(screen.getByText("unit 1 of 2")).toBeInTheDocument();
    expect(search).toHaveValue("ne");
    expect(screen.getByLabelText("target")).toHaveValue("ne … plus (habitude)");
    expect(calls.every((c) => c.method === "GET")).toBe(true);
    expect(calls.some((c) => c.path.startsWith("/api/knowledge-library/") && c.method !== "GET")).toBe(false);

    // The explicit SAME still uses the existing endpoint and body.
    fireEvent.click(screen.getByRole("button", { name: "SAME → selected" }));
    await waitFor(() => {
      const write = calls.find((c) => c.method === "POST");
      expect(write).toEqual({ method: "POST", path: "/api/knowledge-units/9/concept-links/same", body: { concept_id: 40 } });
    });
    expect(calls.filter((c) => c.method !== "GET")).toHaveLength(1);
  });

  it("follows the latest selection when an earlier candidate's detail answers late", async () => {
    const slow = deferred();
    router(queueHandlers({
      "GET /api/knowledge-library/concepts/40": () => slow.promise,
      "GET /api/knowledge-library/concepts/41": nejamais,
    }));
    await onUnit9();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search existing concepts" }), { target: { value: "ne" } });
    const cardFor = (target: string) => screen.getByText(target, { selector: "strong" }).closest(".candidate") as HTMLElement;
    fireEvent.click(within(cardFor("ne … plus")).getByRole("button", { name: "select this concept" }));
    const comparison = screen.getByRole("region", { name: "Compare before deciding" });
    expect(within(comparison).getByText("Loading what concept #40 contains…")).toBeInTheDocument();
    fireEvent.click(within(cardFor("ne … jamais")).getByRole("button", { name: "select this concept" }));
    expect(await within(comparison).findByText(/No unit currently supports this concept/)).toBeInTheDocument();
    await act(async () => slow.resolve({ body: neplus }));
    expect(within(comparison).queryByText(NE_PLUS[0].statement)).toBeNull();
    expect(within(comparison).getByRole("heading", { name: "Selected concept #41" })).toBeInTheDocument();
  });

  it("keeps the review usable when a candidate's detail read fails", async () => {
    router(queueHandlers({ "GET /api/knowledge-library/concepts/40": () => ({ status: 500, body: { error: "boom" } }) }));
    await onUnit9();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search existing concepts" }), { target: { value: "ne … plus" } });
    fireEvent.click(screen.getAllByRole("button", { name: "select this concept" })[0]);
    const comparison = screen.getByRole("region", { name: "Compare before deciding" });
    expect(await within(comparison).findByRole("alert")).toHaveTextContent("Could not load what concept #40 contains: (500) boom");
    // The failure blocks nothing: the explicit decision remains the reviewer's.
    expect(screen.getByRole("button", { name: "SAME → selected" })).toBeEnabled();
  });
});
