import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PublicDemoApp from "../PublicDemoApp";
import { hashForScreen, linkFromHash } from "./deepLink";
import { DEMO_COMPARISONS } from "./comparisons";
import { concept, demoServer, source, unit } from "./demoTestServer";
import { forgetCompareVisits } from "./visit";

// Comparisons (comparisons.ts, CompareScreen.tsx): two public units side by
// side, read through the existing GETs, reached from the start page or a link.

const catalog = JSON.parse(readFileSync(resolve(process.cwd(), "../scripts/demo/flh073/fixtures/catalog.json"), "utf8")) as {
  entries: Array<{ key: string; original_input: string; units: Array<{ key: string; canonical: string; example?: string }> }>;
  concepts: Array<{ key: string; target: string; members: string[] }>;
};

const realMatchMedia = window.matchMedia;
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  // A new page load: the comparison screens' visit memory (visit.ts) starts empty.
  forgetCompareVisits();
  window.matchMedia = realMatchMedia;
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
});

const IMP = concept(5, "imparfait for background and past habits");
const PC = concept(6, "passé composé for a completed event");
const PC_ETRE = concept(7, "passé composé with être");
const impUnit = unit(6, 5, "imparfait pour le contexte", "Quand j'étais petit, je jouais au foot.");
const pcUnit = unit(7, 5, "passé composé pour un événement", "Hier, j'ai joué au foot.");
const etreUnit = unit(8, 6, "passé composé avec être");
const Q = "When do I use the imparfait instead of the passé composé?";

// The demo test server with the tense Concepts; `drop` leaves some out.
function server(drop: { concept6?: boolean; source7?: boolean } = {}) {
  const base = demoServer();
  const inner = globalThis.fetch;
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname.replace(/^\/api/, "");
    const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    const record = () => base.calls.push({ method: (init?.method ?? "GET").toUpperCase(), url: `${url.pathname}${url.search}` });
    const detail = (c: typeof IMP, units: Array<typeof impUnit>) => ({ schema_version: "knowledge_library_concept_v1", concept: c, preferred_unit: null,
      supporting_units: units, non_supporting_members: [], current_relations: [], historical_units: [], history_event_count: 1 });
    const hits = (cs: Array<typeof IMP>) => reply(200, { schema_version: "knowledge_library_search_v1", query: url.searchParams.get("q"), tokens: [], state: "all", limit: 20,
      total_matches: cs.length, truncated: false, results: cs.map((c) => ({ concept: c, match_tier: "identity", matched_fields: ["target"], current_member_count: 1, supporting_unit_count: 1 })) });
    const q = url.searchParams.get("q");
    if (path === "/knowledge-library/concepts" && q === "imparfait") return record(), hits([IMP]);
    // The guided example both units come from (R2: the tour's first step).
    if (path === "/knowledge-library/concepts" && q === "foot") return record(), hits([IMP, PC]);
    if (path === "/knowledge-library/concepts" && q === "passé composé") return record(), hits(drop.concept6 ? [PC_ETRE] : [PC_ETRE, PC]);
    if (path === "/knowledge-library/concepts" && (q === "depuis" || q === "pendant")) return record(), hits([]);
    if (path === "/knowledge-library/concepts/5") return record(), reply(200, detail(IMP, [impUnit]));
    if (path === "/knowledge-library/concepts/6") return record(), reply(200, detail(PC, [pcUnit]));
    if (path === "/knowledge-library/concepts/7") return record(), reply(200, detail(PC_ETRE, [etreUnit]));
    if (path === "/knowledge-library/units/6/source") return record(), reply(200, source(impUnit, 5, Q));
    if (path === "/knowledge-library/units/7/source") return record(), drop.source7 ? reply(404, { error: "not found" }) : reply(200, source(pcUnit, 6, Q));
    return inner(input, init);
  }) as unknown as typeof fetch;
  return base;
}

const renderDemo = (url: string, locale?: string) => {
  if (locale) window.localStorage.setItem("flh.ui-locale.v1", locale);
  window.history.pushState(null, "", url);
  render(<StrictMode><PublicDemoApp /></StrictMode>);
};

describe("comparisons match the demo catalog", () => {
  it("names, for each side, wording found in exactly one catalog unit, and both units have an example", () => {
    for (const c of DEMO_COMPARISONS)
      for (const side of c.sides) {
        const units = catalog.entries.flatMap((e) => e.units.filter((u) => u.canonical.toLocaleLowerCase("fr").includes(side.seed)));
        expect(units, `${c.key}: ${side.seed}`).toHaveLength(1);
        expect(units[0].example, side.seed).toBeTruthy();
        // …and a Concept the side's query names holds it.
        const holder = catalog.concepts.find((k) => k.members.includes(units[0].key));
        expect(holder, side.seed).toBeDefined();
      }
  });
  it("links a comparison, and a Concept or source opened from it, and refuses anything else", () => {
    expect(linkFromHash("#compare=depuis-pendant").screen).toEqual({ kind: "compare", compare: "depuis-pendant" });
    expect(linkFromHash("#compare=depuis-pendant&concept=8&unit=9").screen).toEqual({ kind: "source", conceptId: 8, unitId: 9, compare: "depuis-pendant" });
    expect(hashForScreen({ kind: "compare", compare: "imparfait-passe-compose" })).toBe("#compare=imparfait-passe-compose");
    expect(hashForScreen({ kind: "concept", conceptId: 5, compare: "imparfait-passe-compose" })).toBe("#compare=imparfait-passe-compose&concept=5");
    for (const bad of ["#compare=unknown", "#compare=depuis-pendant&example=y-en", "#compare=depuis-pendant&unit=9"])
      expect(linkFromHash(bad).malformed, bad).toBe(true);
    // R2-085: a step (an example's) on a comparison link is left out.
    expect(linkFromHash("#compare=depuis-pendant&step=2")).toMatchObject({ screen: { kind: "compare", compare: "depuis-pendant" }, malformed: false });
  });
});

describe("comparing two examples", () => {
  const SHOW = "Show the evidence: question, interpretation, rule and Concept";
  const pair = () => screen.getByRole("region", { name: "The two examples" });

  it("opens from the start page with both examples together, the evidence behind one control, and needs only GETs", async () => {
    const s = server();
    renderDemo("/");
    const card = await screen.findByRole("button", { name: /^Imparfait or passé composé\?/ });
    // Let the start screen's first effects run (its history entry), as a visitor's first click would.
    await act(async () => {});
    fireEvent.click(card);
    expect(window.location.hash).toBe("#compare=imparfait-passe-compose");
    await waitFor(() => expect(screen.getByRole("heading", { level: 2, name: "Imparfait or passé composé?" })).toHaveFocus());
    // R2-003/004: the pair, each example under its unit wording, in French.
    await screen.findByRole("region", { name: "The two examples" });
    const sides = within(pair()).getAllByRole("listitem");
    expect(sides).toHaveLength(2);
    expect(within(sides[0]).getByText("imparfait pour le contexte")).toHaveAttribute("lang", "fr");
    expect(within(sides[0]).getByText("Quand j'étais petit, je jouais au foot.")).toHaveAttribute("lang", "fr");
    expect(within(sides[1]).getByText("passé composé pour un événement")).toBeInTheDocument();
    expect(within(sides[1]).getByText("Hier, j'ai joué au foot.")).toHaveAttribute("data-compare-example");
    // R2-005: the rest behind one disclosure, closed on a narrow screen (jsdom has no media queries).
    const toggle = within(pair()).getByRole("button", { name: SHOW });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute("aria-controls", "demo-compare-evidence");
    expect(screen.queryAllByRole("article")).toHaveLength(0);
    const length = window.history.length;
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveTextContent("Hide the evidence");
    const cards = screen.getAllByRole("article");
    expect(cards).toHaveLength(2);
    expect(within(cards[0]).getByRole("heading", { level: 3 })).toHaveTextContent("imparfait for background and past habits");
    expect(within(cards[1]).getByRole("heading", { level: 3 })).toHaveTextContent("passé composé for a completed event");
    const rows = (c: HTMLElement) => within(c).getAllByRole("heading", { level: 4 }).map((h) => h.textContent);
    expect(rows(cards[0])).toEqual(["The learner's question (record #5)", "The stored interpretation of that question", "The rule taken from it", "Filed under"]);
    expect(rows(cards[1])).toEqual(rows(cards[0]));
    expect(screen.getByText("Both units were taken from the same learner question, record #5.")).toBeInTheDocument();
    // R2-006: opening the evidence keeps the comparison's link and adds no history entry.
    expect(window.location.hash).toBe("#compare=imparfait-passe-compose");
    expect(window.history.length).toBe(length);
    // A link to each source record and Concept, as real links that keep the comparison.
    expect(within(cards[0]).getByRole("link", { name: "Open the source of unit #6 (record #5)" })).toHaveAttribute("href", "#compare=imparfait-passe-compose&concept=5&unit=6");
    expect(within(cards[1]).getByRole("link", { name: "Open Concept #6" })).toHaveAttribute("href", "#compare=imparfait-passe-compose&concept=6");
    // R2-007: Escape inside the evidence closes it and returns focus to its control.
    const link = within(cards[0]).getByRole("link", { name: "Open the source of unit #6 (record #5)" });
    link.focus();
    fireEvent.keyDown(link, { key: "Escape" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await waitFor(() => expect(toggle).toHaveFocus());
    // No account, no write: every request is a GET to the read API.
    expect(s.calls.every((c) => c.method === "GET")).toBe(true);
    expect(s.calls.every((c) => c.url.startsWith("/api/knowledge-library/"))).toBe(true);
  });

  it("starts with the evidence open on a wide screen", async () => {
    server();
    window.matchMedia = ((q: string) => ({ matches: q === "(min-width: 721px)", media: q, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia;
    renderDemo("/#compare=imparfait-passe-compose");
    expect(await screen.findByRole("button", { name: "Hide the evidence" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByRole("article")).toHaveLength(2);
  });

  it("returns from a source to the comparison as it was left, with focus on the link used, and a reload starts fresh", async () => {
    server();
    renderDemo("/#compare=imparfait-passe-compose");
    fireEvent.click(await screen.findByRole("button", { name: SHOW }));
    const link = screen.getByRole("link", { name: "Open the source of unit #6 (record #5)" });
    link.focus();
    fireEvent.click(link);
    expect(window.location.hash).toBe("#compare=imparfait-passe-compose&concept=5&unit=6");
    await screen.findByText(Q, { selector: "blockquote" });
    fireEvent.click(screen.getByRole("button", { name: "← Back to the comparison “Imparfait or passé composé?”" }));
    await waitFor(() => expect(window.location.hash).toBe("#compare=imparfait-passe-compose"));
    // The evidence is open again and the link has focus.
    await waitFor(() => expect(screen.getByRole("link", { name: "Open the source of unit #6 (record #5)" })).toHaveFocus());
    expect(screen.getByRole("button", { name: "Hide the evidence" })).toHaveAttribute("aria-expanded", "true");
    // Reload on the source: the same screen and the same way back; the comparison then opens as new.
    fireEvent.click(screen.getByRole("link", { name: "Open the source of unit #6 (record #5)" }));
    await screen.findByText(Q, { selector: "blockquote" });
    cleanup();
    forgetCompareVisits();
    renderDemo(window.location.pathname + window.location.hash);
    await screen.findByText(Q, { selector: "blockquote" });
    fireEvent.click(screen.getByRole("button", { name: "← Back to the comparison “Imparfait or passé composé?”" }));
    await waitFor(() => expect(window.location.hash).toBe("#compare=imparfait-passe-compose"));
    expect(await screen.findByRole("button", { name: SHOW })).toHaveAttribute("aria-expanded", "false");
  });

  it("Back from the comparison returns to the start with focus on its card", async () => {
    server();
    renderDemo("/");
    const card = await screen.findByRole("button", { name: /^Imparfait or passé composé\?/ });
    card.focus();
    fireEvent.click(card);
    await screen.findByRole("region", { name: "The two examples" });
    fireEvent.click(screen.getByRole("button", { name: "← Back to the start" }));
    await waitFor(() => expect(window.location.hash).toBe(""));
    await waitFor(() => expect(screen.getByRole("button", { name: /^Imparfait or passé composé\?/ })).toHaveFocus());
  });

  it("shows what it can when a side or a source is missing, with a useful way on", async () => {
    server({ concept6: true, source7: true });
    renderDemo("/#compare=imparfait-passe-compose");
    await screen.findByRole("region", { name: "The two examples" });
    expect(within(pair()).getByText("Not in this demo build: “passé composé”")).toBeInTheDocument();
    fireEvent.click(within(pair()).getByRole("button", { name: SHOW }));
    const cards = screen.getAllByRole("article");
    expect(within(cards[0]).getByRole("heading", { level: 3 })).toHaveTextContent("imparfait for background and past habits");
    expect(within(cards[1]).getByRole("heading", { level: 3 })).toHaveTextContent("Not in this demo build: “passé composé”");
    // No practice without both sides.
    expect(screen.queryByRole("button", { name: "Try a question" })).toBeNull();
    fireEvent.click(within(pair()).getByRole("button", { name: "Search for “passé composé”" }));
    await waitFor(() => expect(window.location.hash).toBe("#q=pass%C3%A9+compos%C3%A9"));
    cleanup();
    forgetCompareVisits();
    server({ source7: true });
    renderDemo("/#compare=imparfait-passe-compose");
    fireEvent.click(await screen.findByRole("button", { name: SHOW }));
    const again = screen.getAllByRole("article");
    expect(within(again[1]).getByText("The source record of unit #7 is not in this demo build.")).toBeInTheDocument();
    expect(within(again[1]).queryByRole("link", { name: /Open the source of unit/ })).toBeNull();
    expect(within(again[1]).getByRole("link", { name: "Open Concept #6" })).toBeInTheDocument();
  });

  it("an unknown comparison link opens the start with the notice", async () => {
    server();
    renderDemo("/#compare=nope");
    expect(await screen.findByText(/link/i, { selector: ".demo-bad-link" })).toBeInTheDocument();
    expect(window.location.hash).toBe("");
  });

  it("reads the same in 简体中文", async () => {
    server();
    renderDemo("/#compare=imparfait-passe-compose", "zh-CN");
    expect(await screen.findByRole("heading", { level: 2, name: "imparfait 还是 passé composé？" })).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "两个例句" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "显示依据：提问、解读、规则和概念" }));
    const cards = screen.getAllByRole("article");
    expect(within(cards[0]).getAllByRole("heading", { level: 4 })[0]).toHaveTextContent("学习者的提问（记录 #5）");
    expect(within(cards[0]).getByRole("link", { name: "打开单元 #6 的来源（记录 #5）" })).toBeInTheDocument();
  });

  it("links to the guided example its units come from, and a clean link to the comparison can be copied", async () => {
    server();
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderDemo("/#compare=imparfait-passe-compose");
    await screen.findByRole("region", { name: "The two examples" });
    fireEvent.click(screen.getByRole("button", { name: "Copy a link to this comparison" }));
    await screen.findByText("Link copied: #compare=imparfait-passe-compose");
    expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/#compare=imparfait-passe-compose`);
    fireEvent.click(screen.getByRole("button", { name: "The question both come from: One question, two tenses" }));
    expect(window.location.hash).toBe("#example=imparfait");
    expect(await screen.findByRole("heading", { level: 2, name: "One question, two tenses" })).toBeInTheDocument();
    expect(await screen.findByText(Q, { selector: "blockquote" })).toHaveAttribute("lang", "en");
    // …and back again, from the example's “Keep exploring”.
    fireEvent.click(screen.getByRole("button", { name: "Compare its two rules side by side: Imparfait or passé composé?" }));
    expect(window.location.hash).toBe("#compare=imparfait-passe-compose");
    Reflect.deleteProperty(navigator, "clipboard");
  });

  it("falls back to a selected field when the browser refuses to copy", async () => {
    server();
    Object.defineProperty(navigator, "clipboard", { value: { writeText: vi.fn(async () => Promise.reject(new Error("denied"))) }, configurable: true });
    renderDemo("/#compare=imparfait-passe-compose");
    await screen.findByRole("region", { name: "The two examples" });
    fireEvent.click(screen.getByRole("button", { name: "Copy a link to this comparison" }));
    expect(await screen.findByRole("textbox", { name: "Link" })).toHaveValue(`${window.location.origin}/#compare=imparfait-passe-compose`);
    expect(screen.getByText(/Your browser did not allow copying/)).toBeInTheDocument();
    Reflect.deleteProperty(navigator, "clipboard");
  });
});

describe("choose-first practice (R2)", () => {
  const QUESTION = "Which form completes the example?";
  const sentence = () => document.querySelector("[data-practice-sentence]")!;
  // The outcome mixes interface text with French forms (spans of their own).
  const outcomeText = async (text: string | RegExp) => {
    await waitFor(() => expect(document.getElementById("demo-practice-outcome")).toHaveTextContent(text));
    return document.getElementById("demo-practice-outcome")!;
  };

  it("asks with the context first, reveals only after a choice, links both forms to their evidence and names the valid alternative", async () => {
    const s = server();
    renderDemo("/");
    window.localStorage.clear();
    window.sessionStorage.clear();
    fireEvent.click(await screen.findByRole("button", { name: "Try “Imparfait or passé composé?” as a question first" }));
    expect(window.location.hash).toBe("#compare=imparfait-passe-compose");
    await waitFor(() => expect(screen.getByRole("heading", { level: 3, name: QUESTION })).toBeInTheDocument());
    // R2-012: the learner's question and its recorded context before any choice.
    expect(screen.getByText("Example 1 of 2. Nothing is saved or sent.")).toBeInTheDocument();
    expect(screen.getByText(Q, { selector: "blockquote" })).toBeInTheDocument();
    expect(screen.getByText("Synthetic example.")).toBeInTheDocument();
    expect(sentence().textContent).toBe("Quand j'étais petit, _____blank au foot.");
    // The pair (which would give the answer away) and every explanation stay hidden.
    expect(screen.queryByRole("region", { name: "The two examples" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Why each form" })).toBeNull();
    expect(screen.queryByRole("link", { name: /See the evidence/ })).toBeNull();
    expect(document.querySelector("[data-practice-alternate]")).toBeNull();
    const group = screen.getByRole("group", { name: "Complete the example" });
    const choices = within(group).getAllByRole("button");
    expect(choices.map((b) => b.textContent)).toEqual(["je jouais (imparfait)", "j'ai joué (passé composé)", "Skip and show the answer"]);
    // R2-013: a choice reveals; the outcome is announced and focused.
    fireEvent.click(choices[1]);
    const outcome = await outcomeText(/^You chose “j'ai joué”\. This example uses “je jouais”, but “j'ai joué” is also possible here, with another meaning \(see below\)\.$/);
    expect(outcome.closest("[role=status]")).not.toBeNull();
    await waitFor(() => expect(document.getElementById("demo-practice-outcome")).toHaveFocus());
    expect(sentence().textContent).toBe("Quand j'étais petit, je jouais au foot.");
    expect(choices[1]).toHaveAttribute("aria-pressed", "true");
    expect(choices[1]).toHaveAttribute("aria-disabled", "true");
    // A second click changes nothing.
    fireEvent.click(choices[0]);
    expect(choices[0]).toHaveAttribute("aria-pressed", "false");
    // R2-014: both forms with their unit's rule and a link to its evidence.
    expect(screen.getByRole("heading", { name: "Why each form" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See the evidence: unit #6, record #5" })).toHaveAttribute("href", "#compare=imparfait-passe-compose&concept=5&unit=6");
    expect(screen.getByRole("link", { name: "See the evidence: unit #7, record #5" })).toHaveAttribute("href", "#compare=imparfait-passe-compose&concept=6&unit=7");
    expect(document.querySelector("[data-practice-form=used] .demo-practice-form")).toHaveTextContent("“je jouais” (imparfait): the form this example uses.");
    // R2-015: the valid alternative, with its other meaning.
    expect(screen.getByRole("heading", { name: "Also possible" })).toBeInTheDocument();
    expect(document.querySelector("[data-practice-alternate] p")).toHaveTextContent(/^“j'ai joué” also makes a correct sentence here, with another meaning/);
    // R2-016: nothing written, stored or sent, and the address never named progress.
    expect(window.location.hash).toBe("#compare=imparfait-passe-compose");
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(document.cookie).toBe("");
    expect(s.calls.every((c) => c.method === "GET" && c.url.startsWith("/api/knowledge-library/"))).toBe(true);
  });

  it("offers the other example, an explicit skip, and keeps both answers when Back returns from the evidence", async () => {
    server();
    renderDemo("/#compare=imparfait-passe-compose");
    fireEvent.click(await screen.findByRole("button", { name: "Try a question" }));
    await waitFor(() => expect(screen.getByRole("heading", { level: 3, name: QUESTION })).toHaveFocus());
    fireEvent.click(screen.getByRole("button", { name: "je jouais (imparfait)" }));
    await outcomeText("You chose “je jouais”. That is the form this example uses.");
    // R2-017: one visible way to the second example.
    fireEvent.click(screen.getByRole("button", { name: "Try the other example" }));
    await waitFor(() => expect(screen.getByRole("heading", { level: 3, name: QUESTION })).toHaveFocus());
    expect(screen.getByText("Example 2 of 2. Nothing is saved or sent.")).toBeInTheDocument();
    expect(sentence().textContent).toBe("Hier, _____blank au foot.");
    fireEvent.click(screen.getByRole("button", { name: "Skip and show the answer" }));
    await outcomeText("Skipped. This example uses “j'ai joué”.");
    expect(document.querySelector("[data-practice-alternate] p")).toHaveTextContent(/^“je jouais” is also possible here, with another meaning/);
    // R2-018: open the evidence, come back: the same example, revealed, focus on the link used.
    const link = screen.getByRole("link", { name: "See the evidence: unit #7, record #5" });
    link.focus();
    fireEvent.click(link);
    expect(window.location.hash).toBe("#compare=imparfait-passe-compose&concept=6&unit=7");
    await screen.findByRole("button", { name: "← Back to the comparison “Imparfait or passé composé?”" });
    act(() => window.history.back());
    await waitFor(() => expect(window.location.hash).toBe("#compare=imparfait-passe-compose"));
    await waitFor(() => expect(screen.getByRole("link", { name: "See the evidence: unit #7, record #5" })).toHaveFocus());
    expect(screen.getByText("Example 2 of 2. Nothing is saved or sent.")).toBeInTheDocument();
    await outcomeText("Skipped. This example uses “j'ai joué”.");
    // The first example kept its answer too.
    fireEvent.click(screen.getByRole("button", { name: "Try the other example" }));
    await outcomeText("You chose “je jouais”. That is the form this example uses.");
    // Try again clears that example only; leaving shows the pair.
    fireEvent.click(screen.getByRole("button", { name: "Try this example again" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "je jouais (imparfait)" })).toHaveFocus());
    fireEvent.click(screen.getByRole("button", { name: "Leave the question and show both examples" }));
    await waitFor(() => expect(screen.getByRole("heading", { level: 3, name: "The two examples" })).toHaveFocus());
  });

  it("is not part of the link: a reload of the comparison opens the pair, and answers are gone", async () => {
    server();
    renderDemo("/#compare=imparfait-passe-compose");
    fireEvent.click(await screen.findByRole("button", { name: "Try a question" }));
    fireEvent.click(await screen.findByRole("button", { name: "je jouais (imparfait)" }));
    await outcomeText(/That is the form this example uses/);
    cleanup();
    forgetCompareVisits();
    renderDemo(window.location.pathname + window.location.hash);
    expect(await screen.findByRole("region", { name: "The two examples" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try a question" }));
    expect(await screen.findByRole("button", { name: "Skip and show the answer" })).toBeInTheDocument();
  });

  it("reads in 简体中文, French forms untranslated", async () => {
    server();
    renderDemo("/#compare=imparfait-passe-compose", "zh-CN");
    fireEvent.click(await screen.findByRole("button", { name: "试一道题" }));
    expect(await screen.findByRole("heading", { level: 3, name: "哪个形式能补全例句？" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "j'ai joué（passé composé）" }));
    await outcomeText("你选择了“j'ai joué”。这个例句用的是“je jouais”，不过这里也可以用“j'ai joué”，但意思不同（见下文）。");
    expect(screen.getByRole("link", { name: "查看依据：单元 #6，记录 #5" })).toBeInTheDocument();
  });
});

describe("the first screen's ways in and the 60-second tour (R2)", () => {
  it("names browsing and searching apart, and its entries move focus within the page", async () => {
    server();
    renderDemo("/");
    const start = await screen.findByRole("navigation", { name: "Where to start" });
    expect(within(start).getAllByRole("button").map((b) => b.textContent)).toEqual(["60-second tour", "Examples", "Comparisons", "Search the library"]);
    // The search section says how searching differs from the prepared paths.
    expect(screen.getByText(/^Search looks through the whole synthetic library for the words you type; the examples and comparisons above are prepared paths/)).toBeInTheDocument();
    const length = window.history.length;
    fireEvent.click(within(start).getByRole("button", { name: "Examples" }));
    expect(screen.getByRole("heading", { name: "Start with an example" })).toHaveFocus();
    fireEvent.click(within(start).getByRole("button", { name: "Comparisons" }));
    expect(screen.getByRole("heading", { name: "Compare two examples", level: 2 })).toHaveFocus();
    fireEvent.click(within(start).getByRole("button", { name: "Search the library" }));
    expect(screen.getByLabelText("Search learned material")).toHaveFocus();
    expect(window.history.length).toBe(length);
    expect(window.location.hash).toBe("");
  });

  it("goes question → comparison → source, follows Back, and can be left without moving", async () => {
    server();
    renderDemo("/");
    fireEvent.click(await screen.findByRole("button", { name: "60-second tour" }));
    expect(window.location.hash).toBe("#example=imparfait");
    const bar = () => screen.getByRole("navigation", { name: "60-second tour" });
    await waitFor(() => expect(bar()).toHaveTextContent("60-second tour, step 1 of 3: A learner's question"));
    expect(await screen.findByText(Q, { selector: "blockquote" })).toBeInTheDocument();
    fireEvent.click(within(bar()).getByRole("button", { name: "Next: Two examples side by side" }));
    expect(window.location.hash).toBe("#compare=imparfait-passe-compose");
    await screen.findByRole("region", { name: "The two examples" });
    expect(bar()).toHaveTextContent("step 2 of 3");
    await waitFor(() => expect(within(bar()).getByRole("button", { name: "Next: The source evidence" })).toBeEnabled());
    fireEvent.click(within(bar()).getByRole("button", { name: "Next: The source evidence" }));
    expect(window.location.hash).toBe("#compare=imparfait-passe-compose&concept=5&unit=6");
    expect(bar()).toHaveTextContent("step 3 of 3: The source evidence");
    act(() => window.history.back());
    await waitFor(() => expect(bar()).toHaveTextContent("step 2 of 3"));
    // R2-035: leaving keeps the position.
    fireEvent.click(within(bar()).getByRole("button", { name: "Leave the tour and stay here" }));
    expect(screen.queryByRole("navigation", { name: "60-second tour" })).toBeNull();
    expect(window.location.hash).toBe("#compare=imparfait-passe-compose");
    expect(screen.getByRole("region", { name: "The two examples" })).toBeInTheDocument();
  });

  it("says when the visitor has left the path, and returns to it", async () => {
    server();
    renderDemo("/");
    fireEvent.click(await screen.findByRole("button", { name: "60-second tour" }));
    await screen.findByText(Q, { selector: "blockquote" });
    fireEvent.click(screen.getByRole("button", { name: "← Back to examples and search" }));
    await waitFor(() => expect(screen.getByRole("navigation", { name: "60-second tour" })).toHaveTextContent("You have left the tour's path."));
    fireEvent.click(screen.getByRole("button", { name: "Return to the tour" }));
    expect(window.location.hash).toBe("#example=imparfait");
  });
});

describe("canonical links (R2-084/085)", () => {
  it.each([["en"], ["zh-CN"]])("opens what a link with a bad optional or unknown parameter names, at its canonical address (%s)", async (locale) => {
    server();
    renderDemo("/#compare=imparfait-passe-compose&step=7&utm_source=chat", locale === "en" ? undefined : locale);
    await screen.findByRole("region", { name: locale === "en" ? "The two examples" : "两个例句" });
    expect(window.location.hash).toBe("#compare=imparfait-passe-compose");
    expect(document.querySelector(".demo-bad-link")).toBeNull();
    cleanup();
    forgetCompareVisits();
    server();
    renderDemo("/#q=imparfait&state=bogus", locale === "en" ? undefined : locale);
    await screen.findByRole("button", { name: "imparfait for background and past habits" });
    expect(window.location.hash).toBe("#q=imparfait");
  });
});
