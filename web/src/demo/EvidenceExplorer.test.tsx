import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PublicDemoApp from "../PublicDemoApp";
import { markMatches } from "../pages/libraryHighlight";
import { excerpt, locateTokens } from "./EvidenceCard";
import { concept, demoServer, PRONOUNS, QUESTION, source, unit } from "./demoTestServer";

// "Why it matched" under a public-demo keyword result (EvidenceCard.tsx): the
// result's own match metadata, the matched Concept and unit wording, the
// learner's question each unit came from, and a link to its source record.

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
});

const LONG = `${"Une explication assez longue qui précède le mot cherché, ".repeat(3)}puis le mot remplacement arrive enfin, ${"et la phrase continue encore longtemps après lui. ".repeat(3)}`;
const LONG_UNIT = { ...unit(31, 21, "remplacer un complément", "On remplace « à Paris » par « y »."), statement: LONG };
const MANY = concept(30, "replacing complements");
const MANY_UNITS = [LONG_UNIT, unit(32, 22, "remplacer par en"), unit(33, 23, "remplacer par y"), unit(34, 24, "remplacer par le"), unit(35, 25, "remplacer par lui")];

type Result = { concept: ReturnType<typeof concept>; match_tier: string; matched_fields?: string[] };
// The demo test server, with keyword searches that carry match metadata.
function server(results: Record<string, { tokens?: string[]; results: Result[] }>) {
  const base = demoServer();
  const inner = globalThis.fetch;
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname.replace(/^\/api/, "");
    const q = url.searchParams.get("q") ?? "";
    const reply = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    if (path === "/knowledge-library/concepts" && results[q]) {
      base.calls.push({ method: "GET", url: `${url.pathname}${url.search}` });
      const r = results[q];
      return reply({
        schema_version: "knowledge_library_search_v1", query: q, ...(r.tokens ? { tokens: r.tokens } : {}), state: "all", limit: 20,
        total_matches: r.results.length, truncated: false,
        results: r.results.map((x) => ({ ...x, current_member_count: 2, supporting_unit_count: 2 })),
      });
    }
    if (path === "/knowledge-library/concepts/30") {
      base.calls.push({ method: "GET", url: path });
      return reply({ schema_version: "knowledge_library_concept_v1", concept: MANY, preferred_unit: null, supporting_units: MANY_UNITS.slice(0, 3),
        non_supporting_members: MANY_UNITS.slice(2), current_relations: [], historical_units: [], history_event_count: 5 });
    }
    const m = /^\/knowledge-library\/units\/(3[1-5])\/source$/.exec(path);
    if (m) {
      base.calls.push({ method: "GET", url: path });
      const u = MANY_UNITS.find((x) => x.unit_id === Number(m[1]))!;
      return reply(source(u, 30, `Question ${u.unit_id} : comment remplacer « à Paris » ?`));
    }
    return inner(input, init);
  }) as unknown as typeof fetch;
  return base;
}

const renderDemo = (url: string, locale?: string) => {
  if (locale) window.localStorage.setItem("flh.ui-locale.v1", locale);
  window.history.pushState(null, "", url);
  render(<StrictMode><PublicDemoApp /></StrictMode>);
};
const REMPLACE = { remplace: { tokens: ["remplace"], results: [{ concept: PRONOUNS, match_tier: "unit_evidence", matched_fields: ["unit_canonical"] }] } };
const card = (name: RegExp) => screen.getByRole("region", { name });

describe("why a keyword result matched", () => {
  it("opens on request, says how each word matched and shows the Concept and unit wording with the learner's question", async () => {
    const s = server(REMPLACE);
    renderDemo("/#q=remplace");
    const toggle = await screen.findByRole("button", { name: "Show why it matched" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(s.calls.some((c) => c.url.includes("/concepts/12"))).toBe(false);
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveAccessibleName("Hide why it matched");
    const region = card(/Why “the pronouns y and en” matched/);
    expect(toggle.getAttribute("aria-controls")).toBe(region.id);
    // 017: the tier from the result's match_tier; exact vs beginning from the tokens.
    expect(await within(region).findByText("Some of the words you searched for, or all of them, are only in the wording of units filed under this Concept.")).toBeInTheDocument();
    expect(within(region).getByText((_, el) => el?.tagName === "LI" && el.textContent === "“remplace” is the whole word remplace.")).toHaveAttribute("data-match", "exact");
    // 012: the matched unit wording beside the learner's question it was taken from, both marked.
    expect(within(region).getByText("None of these words is in the Concept's own wording.")).toBeInTheDocument();
    const units = within(region).getAllByRole("listitem").filter((li) => li.classList.contains("demo-evidence-unit"));
    expect(units).toHaveLength(2);
    expect(units[0]).toHaveTextContent("Unity remplace à + lieu");
    expect([...units[0].querySelectorAll("dd mark")].map((m) => m.textContent)).toContain("remplace");
    await waitFor(() => expect(units[0].querySelector("blockquote")?.textContent).toBe(QUESTION));
    expect([...units[0].querySelectorAll("blockquote mark")].map((m) => m.textContent)).toEqual(["remplacent"]);
    expect(within(units[0]).getByText("The learner's question (record #9)")).toBeInTheDocument();
    // Only GETs, only the Concept and the shown units' sources.
    expect(s.calls.every((c) => c.method === "GET")).toBe(true);
    expect(s.calls.filter((c) => /\/units\/\d+\/source/.test(c.url)).map((c) => c.url)).toEqual(
      expect.arrayContaining(["/api/knowledge-library/units/12/source", "/api/knowledge-library/units/13/source"]),
    );
  });

  it("says when a word is the beginning of a longer word", async () => {
    server({ rempl: { tokens: ["rempl"], results: [{ concept: PRONOUNS, match_tier: "unit_evidence", matched_fields: ["unit_canonical"] }] } });
    renderDemo("/#q=rempl");
    fireEvent.click(await screen.findByRole("button", { name: "Show why it matched" }));
    const li = await screen.findByText((_, el) => el?.tagName === "LI" && el.textContent === "“rempl” is the beginning of remplace.");
    expect(li).toHaveAttribute("data-match", "prefix");
  });

  it("works from the keyboard: a native toggle, Escape closes the card and returns focus, links are links", async () => {
    server(REMPLACE);
    renderDemo("/#q=remplace");
    const toggle = await screen.findByRole("button", { name: "Show why it matched" });
    expect(toggle.tagName).toBe("BUTTON");
    fireEvent.click(toggle);
    const [link] = await screen.findAllByRole("link", { name: /Open the source of unit #\d+ \(record #9\)/ });
    link.focus();
    fireEvent.keyDown(link, { key: "Escape" });
    expect(screen.queryByRole("region", { name: /Why “the pronouns y and en” matched/ })).toBeNull();
    expect(toggle).toHaveFocus();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("links each unit to its source record, and Back returns to the open card with focus on that link", async () => {
    server(REMPLACE);
    renderDemo("/#q=remplace");
    fireEvent.click(await screen.findByRole("button", { name: "Show why it matched" }));
    const links = await screen.findAllByRole("link", { name: /^Open the source of unit #1[23] \(record #9\)$/ });
    // 014 / 019: a real link, the same for this search however history moves.
    expect(links[0]).toHaveAttribute("href", "#q=remplace&concept=12&unit=12");
    expect(links[1]).toHaveAttribute("href", "#q=remplace&concept=12&unit=13");
    // 050: links to different sources have different names.
    expect(links.map((l) => l.textContent)).toEqual(["Open the source of unit #12 (record #9)", "Open the source of unit #13 (record #9)"]);
    links[0].focus();
    fireEvent.click(links[0]);
    expect(window.location.hash).toBe("#q=remplace&concept=12&unit=12");
    await screen.findByText(QUESTION, { selector: "blockquote" });
    // Back: the results again, the card still open, focus on the link that left.
    window.history.back();
    await waitFor(() => expect(window.location.hash).toBe("#q=remplace"));
    await waitFor(() => expect(screen.getByRole("link", { name: "Open the source of unit #12 (record #9)" })).toHaveFocus());
    expect(screen.getByRole("link", { name: "Open the source of unit #12 (record #9)" })).toHaveAttribute("href", "#q=remplace&concept=12&unit=12");
    // Forward: the same source again.
    window.history.forward();
    await waitFor(() => expect(window.location.hash).toBe("#q=remplace&concept=12&unit=12"));
    expect(await screen.findByText(QUESTION, { selector: "blockquote" })).toBeInTheDocument();
  });

  it("groups each unit's matched fields, shortens long wording with a way to read it whole, and shows more units on request", async () => {
    server({ remplacement: { tokens: ["remplac"], results: [{ concept: MANY, match_tier: "unit_evidence", matched_fields: ["unit_canonical", "unit_example", "unit_statement"] }] } });
    renderDemo("/#q=remplacement");
    fireEvent.click(await screen.findByRole("button", { name: "Show why it matched" }));
    const region = card(/Why “replacing complements” matched/);
    await within(region).findAllByRole("link", { name: /Open the source of unit/ });
    const units = [...region.querySelectorAll(".demo-evidence-unit")] as HTMLElement[];
    expect(units).toHaveLength(3);
    // The first unit matched in three fields: one group, three labelled rows.
    expect([...units[0].querySelectorAll("dt")].map((d) => d.textContent)).toEqual(["Unit", "Example", "Explanation", "The learner's question (record #21)", "What it supports"]);
    const explanation = units[0].querySelectorAll("dd")[2];
    expect(explanation.textContent!.startsWith("…")).toBe(true);
    expect(explanation.textContent!.length).toBeLessThan(LONG.length);
    expect(explanation.querySelector("mark")?.textContent).toBe("remplacement");
    const whole = within(units[0]).getByRole("button", { name: "Show the whole wording" });
    fireEvent.click(whole);
    expect(units[0].querySelectorAll("dd")[2].textContent).toBe(LONG);
    expect(within(units[0]).getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
    // Two more units on request, focus on the first one shown.
    fireEvent.click(within(region).getByRole("button", { name: "Show 2 more units" }));
    await waitFor(() => expect(region.querySelectorAll(".demo-evidence-unit")).toHaveLength(5));
    await waitFor(() => expect(document.activeElement?.id).toBe("demo-ev-src-30-34"));
    // What each unit supports, from the Concept read: units 31–33 support it,
    // 34 and 35 are filed there without supporting it.
    const support = [...region.querySelectorAll(".demo-evidence-unit [data-support]")].map((d) => d.getAttribute("data-support"));
    expect(support).toEqual(["supports", "supports", "supports", "member", "member"]);
    expect(region.querySelectorAll(".demo-evidence-unit [data-support] dd")[3]).toHaveTextContent(
      "Concept #30, “replacing complements”: this unit is filed there but does not currently support it.",
    );
  });

  it("says, for each matched unit, the Concept it currently supports, so no other screen is needed", async () => {
    server(REMPLACE);
    renderDemo("/#q=remplace");
    fireEvent.click(await screen.findByRole("button", { name: "Show why it matched" }));
    const region = card(/Why “the pronouns y and en” matched/);
    await within(region).findAllByRole("link", { name: /Open the source of unit/ });
    const first = region.querySelector(".demo-evidence-unit [data-support]")!;
    expect(first).toHaveAttribute("data-support", "supports");
    expect(first).toHaveTextContent("What it supportsSupports Concept #12, “the pronouns y and en”: this unit currently supports it.");
    expect(first.querySelector(".tag")).toHaveTextContent("Supports");
    expect(window.location.hash).toBe("#q=remplace");
  });

  it("says so when a result carries no match details, and fetches nothing for it", async () => {
    const s = server({ pronoms: { results: [{ concept: PRONOUNS, match_tier: "identity" }] } });
    renderDemo("/#q=pronoms");
    fireEvent.click(await screen.findByRole("button", { name: "Show why it matched" }));
    expect(screen.getByText(/This result came without match details/)).toBeInTheDocument();
    expect(screen.queryByText(/^Found in/)).toBeNull();
    expect(s.calls.some((c) => c.url.includes("/concepts/12"))).toBe(false);
  });

  it("reports a Concept that cannot be read, with a retry", async () => {
    const s = server(REMPLACE);
    renderDemo("/#q=remplace");
    const toggle = await screen.findByRole("button", { name: "Show why it matched" });
    s.hold("/knowledge-library/concepts/12");
    fireEvent.click(toggle);
    expect(screen.getByText("Loading why it matched…")).toHaveAttribute("role", "status");
    s.release("/knowledge-library/concepts/12");
    expect(await screen.findAllByRole("link", { name: /Open the source of unit #\d+ \(record #9\)/ })).toHaveLength(2);
  });

  it("reads the same in 简体中文", async () => {
    server(REMPLACE);
    renderDemo("/#q=remplace", "zh-CN");
    fireEvent.click(await screen.findByRole("button", { name: "查看匹配原因" }));
    expect(await screen.findByText((_, el) => el?.tagName === "LI" && el.textContent === "“remplace”是完整的词 remplace。")).toBeInTheDocument();
    expect(await screen.findAllByRole("link", { name: /打开单元 #\d+ 的来源（记录 #9）/ })).toHaveLength(2);
  });
});

describe("matching French wording safely", () => {
  const marks = (text: string, tokens: string[]) => {
    const { container } = render(<p>{markMatches(text, tokens)}</p>);
    const out = [...container.querySelectorAll("mark")].map((m) => m.textContent);
    const shown = container.textContent;
    cleanup();
    return { out, text: shown };
  };
  it("marks accented, elided and hyphenated words by their accent-free beginning, leaving the text intact", () => {
    const text = "L'élève qu’il préfère : « Élèves, aujourd'hui ! » — peut-être.";
    const r = marks(text, ["eleve", "aujourd", "etre", "qu"]);
    expect(r.out).toEqual(["élève", "qu", "Élèves", "aujourd", "être"]);
    expect(r.text).toBe(text);
  });
  it("matches decomposed accents and keeps them inside the marked word", () => {
    const nfd = "Il préfère le café.";
    const r = marks(nfd, ["prefere", "cafe"]);
    expect(r.out).toEqual(["préfère", "café"]);
    expect(r.text).toBe(nfd);
  });
  it("never renders stored text as markup", () => {
    const { container } = render(<p>{markMatches("<img src=x onerror=alert(1)> remplace", ["remplace", "img"])}</p>);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toBe("<img src=x onerror=alert(1)> remplace");
  });
  it("names whole words before beginnings, and the words as written", () => {
    expect(locateTokens(["Les élèves remplacent", "un élève"], ["eleve", "rempl"])).toEqual([
      { token: "eleve", word: "élève", exact: true },
      { token: "rempl", word: "remplacent", exact: false },
    ]);
    expect(locateTokens(["rien"], ["absent"])).toEqual([{ token: "absent", word: null, exact: false }]);
  });
  it("cuts long wording at spaces around the first match", () => {
    const r = excerpt(LONG, ["remplac"]);
    expect(r.cut).toBe(true);
    expect(r.text).toMatch(/^…\S/);
    expect(r.text).toMatch(/\S…$/);
    expect(r.text).toContain("remplacement");
    expect(excerpt("court", ["court"])).toEqual({ text: "court", cut: false });
  });
});
