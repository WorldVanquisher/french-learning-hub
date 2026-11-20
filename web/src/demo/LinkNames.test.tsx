import { StrictMode } from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PublicDemoApp from "../PublicDemoApp";
import { concept, demoServer, PRONOUNS, source, unit } from "./demoTestServer";
import { forgetCompareVisits } from "./visit";

// Item 050: two links with the same accessible name must lead to the same
// place. "Why it matched" and the comparison each list two units taken from
// one record; their source links once both read "Open source record #9" while
// opening different units' sources. Each link now names its unit.

afterEach(() => {
  cleanup();
  forgetCompareVisits();
  vi.restoreAllMocks();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
});

// Every link on the page, grouped by accessible name: a name must not name two addresses.
function clashes() {
  const byName = new Map<string, Set<string>>();
  for (const a of screen.queryAllByRole("link")) {
    const name = a.textContent?.trim() ?? "";
    byName.set(name, new Set([...(byName.get(name) ?? []), a.getAttribute("href") ?? ""]));
  }
  return [...byName].filter(([, hrefs]) => hrefs.size > 1).map(([name, hrefs]) => `${name} → ${[...hrefs].join(" | ")}`);
}

function server() {
  demoServer();
  const inner = globalThis.fetch;
  const reply = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  const IMP = concept(5, "imparfait for background and past habits");
  const PC = concept(6, "passé composé for a completed event");
  const u6 = unit(6, 5, "imparfait pour le contexte", "Quand j'étais petit, je jouais au foot.");
  const u7 = unit(7, 5, "passé composé pour un événement", "Hier, j'ai joué au foot.");
  const detail = (c: typeof IMP, us: Array<typeof u6>) => ({ schema_version: "knowledge_library_concept_v1", concept: c, preferred_unit: null,
    supporting_units: us, non_supporting_members: [], current_relations: [], historical_units: [], history_event_count: 1 });
  const hits = (q: string, cs: Array<{ c: typeof IMP; tier: string; fields: string[] }>, tokens: string[]) => reply({ schema_version: "knowledge_library_search_v1", query: q, tokens,
    state: "all", limit: 20, total_matches: cs.length, truncated: false,
    results: cs.map((x) => ({ concept: x.c, match_tier: x.tier, matched_fields: x.fields, current_member_count: 2, supporting_unit_count: 2 })) });
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname.replace(/^\/api/, "");
    const q = url.searchParams.get("q");
    if (path === "/knowledge-library/concepts" && q === "remplace") return hits(q, [{ c: PRONOUNS, tier: "unit_evidence", fields: ["unit_canonical"] }], ["remplace"]);
    if (path === "/knowledge-library/concepts" && q === "imparfait") return hits(q, [{ c: IMP, tier: "identity", fields: ["target"] }], ["imparfait"]);
    if (path === "/knowledge-library/concepts" && q === "passé composé") return hits(q, [{ c: PC, tier: "identity", fields: ["target"] }], ["passe", "compose"]);
    if (path === "/knowledge-library/concepts/5") return reply(detail(IMP, [u6]));
    if (path === "/knowledge-library/concepts/6") return reply(detail(PC, [u7]));
    if (path === "/knowledge-library/units/6/source") return reply(source(u6, 5, "When do I use the imparfait instead of the passé composé?"));
    if (path === "/knowledge-library/units/7/source") return reply(source(u7, 6, "When do I use the imparfait instead of the passé composé?"));
    return inner(input, init);
  }) as unknown as typeof fetch;
}

const renderDemo = (url: string) => {
  window.history.pushState(null, "", url);
  server();
  render(<StrictMode><PublicDemoApp /></StrictMode>);
};

describe("links that share a name lead to the same place", () => {
  it("in “Why it matched”, two units of record #9", async () => {
    renderDemo("/#q=remplace");
    (await screen.findByRole("button", { name: "Show why it matched" })).click();
    await waitFor(() => expect(screen.getAllByRole("link", { name: /Open the source of unit/ })).toHaveLength(2));
    expect(clashes()).toEqual([]);
  });

  it("in the comparison, two units of record #5", async () => {
    renderDemo("/#compare=imparfait-passe-compose");
    // The evidence is behind one disclosure on a narrow screen (R2).
    (await screen.findByRole("button", { name: "Show the evidence: question, interpretation, rule and Concept" })).click();
    await waitFor(() => expect(screen.getAllByRole("link", { name: /Open the source of unit/ })).toHaveLength(2));
    expect(clashes()).toEqual([]);
  });
});
