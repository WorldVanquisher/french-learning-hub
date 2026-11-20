import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PublicDemoApp from "../PublicDemoApp";
import { en } from "../i18n/en";
import { zhCN } from "../i18n/zh-CN";
import { concept, demoServer, source, unit } from "./demoTestServer";

// R2-021…029: evidence discovery in "Why it matched". Matched and supported
// are told apart for every unit, from the unit's own fields; an excerpt that
// is not there, or does not hold the search words, says so; the question's
// context is shown in place; a unit's evidence has a short public link; and no
// wording claims more support than the Concept read gives.

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
  Reflect.deleteProperty(navigator, "clipboard");
});

const MARKET = concept(40, "going to the market");
const u41 = unit(41, 31, "aller au marché", "Je vais au marché le samedi.");
const u42 = { ...unit(42, 32, "au marché", "Elle est au marché."), in_current_extraction: false };
const u43 = { ...unit(43, 33, "marché couvert", "Le marché couvert ouvre à huit heures."), admission: "suppressed" };
const u44 = unit(44, 34, "faire le marché");
const QUESTIONS: Record<number, string> = {
  41: "Pourquoi « au marché » et pas « à le marché » ?",
  42: "How do I say “at the market”?",
  43: "Un « marché couvert », c'est quoi ?",
};

function server() {
  const base = demoServer();
  const inner = globalThis.fetch;
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname.replace(/^\/api/, "");
    const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    const log = () => base.calls.push({ method: (init?.method ?? "GET").toUpperCase(), url: `${url.pathname}${url.search}` });
    if (path === "/knowledge-library/concepts" && url.searchParams.get("q") === "marché") {
      log();
      return reply(200, {
        schema_version: "knowledge_library_search_v1", query: "marché", tokens: ["marche"], state: "all", limit: 20, total_matches: 1, truncated: false,
        results: [{ concept: MARKET, match_tier: "unit_evidence", matched_fields: ["unit_canonical", "unit_example"], current_member_count: 4, supporting_unit_count: 1 }],
      });
    }
    if (path === "/knowledge-library/concepts/40") {
      log();
      return reply(200, { schema_version: "knowledge_library_concept_v1", concept: MARKET, preferred_unit: null, supporting_units: [u41],
        non_supporting_members: [u42, u43, u44], current_relations: [], historical_units: [], history_event_count: 4 });
    }
    const m = /^\/knowledge-library\/units\/(4[1-4])\/source$/.exec(path);
    if (m) {
      log();
      const id = Number(m[1]);
      if (id === 44) return reply(404, { error: "not found" });
      const u = [u41, u42, u43].find((x) => x.unit_id === id)!;
      return reply(200, source(u, 40, QUESTIONS[id]));
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
const unitRow = (id: number) => document.getElementById(`demo-ev-src-40-${id}`)!.closest("li")!;

async function openEvidence(show = "Show why it matched", link = /Open the source of unit #43/) {
  fireEvent.click(await screen.findByRole("button", { name: show }));
  await screen.findByRole("link", { name: link });
}

describe("matched and supported, told apart (R2-021/022/025)", () => {
  it("labels each unit and says why a filed unit does not support, from its own fields", async () => {
    server();
    renderDemo("/#q=marché");
    await openEvidence();
    const support = (id: number) => unitRow(id).querySelector("[data-support]")!;
    expect(support(41)).toHaveAttribute("data-support", "supports");
    expect(support(41).querySelector(".tag")).toHaveTextContent("Supports");
    expect(support(41)).toHaveTextContent("Concept #40, “going to the market”: this unit currently supports it.");
    expect(support(42)).toHaveAttribute("data-reason", "superseded");
    expect(support(42).querySelector(".tag")).toHaveTextContent("Filed, not supporting");
    expect(support(42)).toHaveTextContent("it comes from an earlier extraction of its question that a newer one replaced, so it does not currently support it.");
    expect(support(43)).toHaveAttribute("data-reason", "admission");
    expect(support(43)).toHaveTextContent("its admission is “suppressed”, so it does not currently support it.");
    // The matched words are marked in each unit's wording either way.
    expect(within(unitRow(42)).getAllByText("marché", { selector: "mark" }).length).toBeGreaterThan(0);
  });

  it("gives no excerpt and a question without the words their own copy", async () => {
    server();
    renderDemo("/#q=marché");
    await openEvidence();
    expect(unitRow(41).querySelector("[data-excerpt]")).toHaveAttribute("data-excerpt", "match");
    expect(within(unitRow(41)).getAllByText("marché", { selector: "blockquote mark" })).toHaveLength(2);
    expect(unitRow(42).querySelector("[data-excerpt]")).toHaveAttribute("data-excerpt", "no-match");
    expect(within(unitRow(42)).getByText("The search words are not in the question itself; they matched the unit's wording above.")).toBeInTheDocument();
    expect(within(unitRow(42)).getByText(/This wording comes from an earlier extraction of the question/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show 1 more unit" }));
    await waitFor(() => expect(document.querySelector("#demo-ev-src-40-44")?.closest("li")?.querySelector("[data-excerpt]")).toHaveAttribute("data-excerpt", "none"));
    expect(within(unitRow(44)).getByText("No excerpt: the source record of unit #44 is not in this demo build.")).toBeInTheDocument();
    expect(within(unitRow(44)).queryByText(/could not be read/)).toBeNull();
  });

  it("shows the question's recorded context and interpretation in place, with no further request (R2-023/026)", async () => {
    const s = server();
    renderDemo("/#q=marché");
    await openEvidence();
    const calls = s.calls.length;
    const toggle = within(unitRow(41)).getByRole("button", { name: "Show the question's context" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const ctx = document.getElementById(toggle.getAttribute("aria-controls")!)!;
    expect(ctx).toHaveTextContent("Context recorded with the question");
    expect(ctx).toHaveTextContent("Synthetic example.");
    expect(ctx).toHaveTextContent("Stored interpretation");
    expect(s.calls.length).toBe(calls);
    expect(window.location.hash).toBe("#q=march%C3%A9");
  });

  it("copies a short public link to a unit's evidence, which opens that evidence (R2-027)", async () => {
    server();
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderDemo("/#q=marché");
    await openEvidence();
    fireEvent.click(within(unitRow(41)).getByRole("button", { name: "Copy a link to the source of unit #41" }));
    expect(await within(unitRow(41)).findByText("Link copied: #concept=40&unit=41")).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/#concept=40&unit=41`);
    cleanup();
    renderDemo("/#concept=40&unit=41");
    expect(await screen.findByText(QUESTIONS[41], { selector: "blockquote" })).toBeInTheDocument();
  });
});

describe("accented words and the Chinese interface (R2-028)", () => {
  it("marks the accented word, labels support and links each unit, in 简体中文", async () => {
    server();
    renderDemo("/#q=marché", "zh-CN");
    await openEvidence("查看匹配原因", /打开单元 #43 的来源/);
    expect(within(unitRow(41)).getAllByText("marché", { selector: "mark" }).length).toBeGreaterThan(0);
    expect(unitRow(41).querySelector("[data-support] .tag")).toHaveTextContent("支持");
    expect(unitRow(42).querySelector("[data-support] .tag")).toHaveTextContent("已归入，未支持");
    expect(unitRow(42).querySelector("[data-support]")).toHaveTextContent("已被更新的提取取代，所以当前不支持它");
    expect(within(unitRow(41)).getByRole("link", { name: "打开单元 #41 的来源（记录 #31）" })).toHaveAttribute("href", "#q=march%C3%A9&concept=40&unit=41");
    expect(within(unitRow(41)).getByRole("button", { name: "复制单元 #41 来源的链接" })).toBeInTheDocument();
  });
});

describe("support wording never overstates the artifact (R2-029, R2-083)", () => {
  it("says “supports” only for units the Concept read lists as supporting", async () => {
    server();
    renderDemo("/#q=marché");
    await openEvidence();
    fireEvent.click(screen.getByRole("button", { name: "Show 1 more unit" }));
    await screen.findByRole("link", { name: /Open the source of unit #44/ });
    const supporting = new Set([u41.unit_id]);
    const rows = [...document.querySelectorAll(".demo-evidence-unit")];
    expect(rows).toHaveLength(4);
    for (const row of rows) {
      const id = Number(row.querySelector("a")!.id.split("-").pop());
      const says = row.querySelector("[data-support]")!;
      expect(says.getAttribute("data-support"), `unit ${id}`).toBe(supporting.has(id) ? "supports" : "member");
      expect(/currently supports it\./.test(says.textContent ?? ""), `unit ${id}`).toBe(supporting.has(id));
    }
  });

  it("keeps every public-demo message free of proof, proficiency, pronunciation and score claims, and support claims current", () => {
    const pick = (cat: Record<string, string>) => Object.entries(cat).filter(([k]) => k.startsWith("demo."));
    const enOver = /\b(prove[sn]?|proof|guarantee[sd]?|confirm(s|ed)?|mastered|master(s|ing)?|fluent|fluency|proficien\w*|pronunciation|pronounce|score[sd]?|grade[sd]?|correct answer|always supports?|definitely)\b/i;
    // A negated claim (“不能证明”: cannot prove) is the opposite of an overstatement.
    const zhOver = /((?<!不能|无法)证明|(?<!不能|无法)保证|确认|掌握|精通|流利|熟练|发音|分数|评分|得分|正确答案|一定支持)/;
    expect(pick(en).filter(([, v]) => enOver.test(v)).map(([k]) => k)).toEqual([]);
    expect(pick(zhCN).filter(([, v]) => zhOver.test(v)).map(([k]) => k)).toEqual([]);
    // A sentence that says a unit supports a Concept says it is current.
    for (const [k, v] of pick(en)) if (/\bsupports it\b/.test(v)) expect(v, k).toMatch(/currently supports it/);
    for (const [k, v] of pick(zhCN)) if (/支持它/.test(v) && !/不支持它/.test(v)) expect(v, k).toMatch(/当前支持它/);
  });
});

describe("search status is announced by a region present before the search (R2-045)", () => {
  it("says the search is running and then what it found, in its own words", async () => {
    demoServer();
    renderDemo("/");
    const region = document.getElementById("demo-search-status");
    await screen.findByRole("navigation", { name: "Where to start" });
    expect(document.getElementById("demo-search-status")).toHaveAttribute("role", "status");
    expect(document.getElementById("demo-search-status")).toHaveTextContent("");
    expect(region === null || region === document.getElementById("demo-search-status")).toBe(true);
    fireEvent.change(screen.getByLabelText("Search learned material"), { target: { value: "pronouns" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(document.getElementById("demo-search-status")).toHaveTextContent("Searching for “pronouns”…");
    await waitFor(() => expect(document.getElementById("demo-search-status")).toHaveTextContent("Search for “pronouns” done: 1 concept."));
  });
});
