import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { markMatches, matchedFeatures, normalizeWord } from "./libraryHighlight";
import { addRecent, clearRecent, readRecent, removeRecent, RECENT_SEARCHES_KEY } from "./recentSearches";
import { addressFor, parseAddress } from "../sectionAddress";

// Workbench Knowledge Library: why a result matched (marked words), a search
// in the address, recent searches kept only in this browser, and "show up to 50"
// when the backend truncated the results.

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  window.localStorage.removeItem(RECENT_SEARCHES_KEY);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const concept = (id: number, target: string, scope = "") => ({
  id, identity_schema_version: "fr_l2_concept_identity_v1", target, pedagogical_intent: "grammaire", scope,
  identity_features: {}, signature: "{}", preferred_unit_id: null, state: "active", lifecycle_state: "normal",
  support_state: "supported", created_at: "t", updated_at: "t",
});

function api(total = 2) {
  const calls: string[] = [];
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    calls.push(`${(init?.method ?? "GET").toUpperCase()} ${url.pathname}${url.search}`);
    if (url.pathname === "/api/knowledge-library/concepts") {
      const q = url.searchParams.get("q") ?? "";
      const tokens = q
        .split(/[^\p{L}\p{N}]+/u)
        .map(normalizeWord)
        .filter((t) => t.length > 1);
      const limit = Number(url.searchParams.get("limit") ?? 20);
      const all = Array.from({ length: total }, (_, i) =>
        i === 0
          ? { concept: concept(1, "subjonctif après il faut que", "après une expression d'obligation"), match_tier: q ? "identity" : "browse", matched_fields: q ? ["target", "scope"] : [], current_member_count: 1, supporting_unit_count: 1 }
          : { concept: concept(i + 1, `Été numéro ${i + 1}`), match_tier: q ? "unit_evidence" : "browse", matched_fields: q ? ["unit_statement"] : [], current_member_count: 1, supporting_unit_count: 1 },
      );
      const results = all.slice(0, limit);
      return new Response(
        JSON.stringify({ schema_version: "knowledge_library_search_v1", query: q, tokens, state: url.searchParams.get("state") ?? "all", limit, total_matches: all.length, truncated: all.length > limit, results }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    const body = url.pathname === "/api/reviewable-units" ? { reviewable_units: [] } : { concepts: [] };
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
  return calls;
}

describe("marked matches", () => {
  it("marks the words the search tokens reach, ignoring case and accents, and nothing else", () => {
    const { container } = render(<p>{markMatches("Il faut qu'il VIENNE en été", ["faut", "vien", "ete", "x"])}</p>);
    expect([...container.querySelectorAll("mark")].map((m) => m.textContent)).toEqual(["faut", "VIENNE", "été"]);
    expect(container.textContent).toBe("Il faut qu'il VIENNE en été");
    expect(markMatches("rien", ["faut"])).toBe("rien");
    expect(markMatches("rien", [])).toBe("rien");
  });
});

describe("matched identity details", () => {
  it("shows only the details the search reaches, in key order, at most three", () => {
    const features = { verb: "faire (to do)", mood: "subjunctive (subjonctif)", "trigger (déclencheur)": "il faut que", z: "subjonctif encore", zz: "subjonctif bis" };
    const { container } = render(<p>{matchedFeatures(features, ["subjonctif"])}</p>);
    expect(container.textContent).toBe("mood: subjunctive (subjonctif)z: subjonctif encorezz: subjonctif bis");
    expect(container.querySelectorAll("mark").length).toBe(3);
    expect(matchedFeatures(features, ["absent"])).toEqual([]);
    expect(matchedFeatures(undefined, ["x"])).toEqual([]);
  });
});

describe("recent searches storage", () => {
  it("keeps at most five, newest first, moves a repeat to the front, removes and clears", () => {
    let list = readRecent()!;
    expect(list).toEqual([]);
    for (const q of ["un", "deux", "trois", "quatre", "cinq", "six"]) list = addRecent(list, { q, state: "all" })!;
    expect(list.map((r) => r.q)).toEqual(["six", "cinq", "quatre", "trois", "deux"]);
    list = addRecent(list, { q: " trois ", state: "all" })!;
    expect(list.map((r) => r.q)).toEqual(["trois", "six", "cinq", "quatre", "deux"]);
    list = addRecent(list, { q: "trois", state: "active" })!;
    expect(list[0]).toEqual({ q: "trois", state: "active" });
    expect(readRecent()).toEqual(list);
    list = removeRecent(list, { q: "six", state: "all" })!;
    expect(list.map((r) => r.q)).not.toContain("six");
    expect(clearRecent()).toEqual([]);
    expect(window.localStorage.getItem(RECENT_SEARCHES_KEY)).toBeNull();
  });

  it("treats invalid stored data as empty and reports refused storage", () => {
    window.localStorage.setItem(RECENT_SEARCHES_KEY, "{not json");
    expect(readRecent()).toEqual([]);
    window.localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify([{ q: "ok", state: "all" }, { q: "", state: "all" }, { q: "x", state: "weird" }, 7]));
    expect(readRecent()).toEqual([{ q: "ok", state: "all" }]);
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(readRecent()).toBeNull();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(addRecent([], { q: "a b", state: "all" })).toBeNull();
  });
});

describe("library address", () => {
  it("parses and writes the library's keyword search strictly", () => {
    expect(parseAddress("#/library?q=il+faut&state=active")).toEqual({ view: "library", library: { q: "il faut", state: "active" } });
    expect(parseAddress("#/library")).toEqual({ view: "library", library: { q: "", state: "all" } });
    expect(addressFor("library", { q: "il faut", state: "all" })).toBe("#/library?q=il+faut");
    expect(addressFor("library", { q: "", state: "retired" })).toBe("#/library?state=retired");
    expect(addressFor("speaking", { q: "x", state: "all" })).toBe("#/speaking");
    for (const bad of ["#/library?q=a&q=b", "#/library?state=gone", "#/library?x=1", "#/speaking?q=a", `#/library?q=${"a".repeat(201)}`]) {
      expect(parseAddress(bad)).toBe("unknown");
    }
  });
});

describe("workbench Knowledge Library search features", () => {
  it("opens the search the address names, marks why results matched, and puts a new search in the address", async () => {
    const calls = api();
    window.history.replaceState(null, "", "/#/library?q=il+faut");
    render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
    const results = await screen.findByRole("region", { name: /Results for/ }).catch(() => screen.findByLabelText(/results/i));
    await waitFor(() => expect(calls.some((c) => c === "GET /api/knowledge-library/concepts?q=il+faut")).toBe(true));
    const first = await screen.findByRole("button", { name: "subjonctif après il faut que" });
    expect([...first.querySelectorAll("mark")].map((m) => m.textContent)).toEqual(["il", "faut"]);
    expect(within(first.closest("li")!).getByText("obligation", { exact: false }).closest("div")!.querySelectorAll("mark").length).toBe(0);
    expect(results).toBeTruthy();
    expect(screen.getByRole("searchbox")).toHaveValue("il faut");
    const before = window.history.length;
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "été" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(window.location.hash).toBe("#/library?q=%C3%A9t%C3%A9"));
    expect(window.history.length).toBe(before);
    expect(calls.every((c) => c.startsWith("GET "))).toBe(true);
  });

  it("follows Back to an earlier section and an edited address to another search", async () => {
    const calls = api();
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Knowledge Library" }));
    fireEvent.change(await screen.findByRole("searchbox"), { target: { value: "il faut" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(window.location.hash).toBe("#/library?q=il+faut"));
    fireEvent.click(screen.getByRole("button", { name: "Home" }));
    expect(window.location.hash).toBe("#/home");
    await act(async () => window.history.back());
    await waitFor(() => expect(screen.getByRole("button", { name: "Knowledge Library" })).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByRole("searchbox")).toHaveValue("il faut");
    await act(async () => {
      window.history.pushState(null, "", "/#/library?q=subjonctif&state=active");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await waitFor(() => expect(screen.getByRole("searchbox")).toHaveValue("subjonctif"));
    await waitFor(() => expect(calls).toContain("GET /api/knowledge-library/concepts?q=subjonctif&state=active"));
  });

  it("keeps recent searches only in this browser, runs, removes and clears them", async () => {
    const calls = api();
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Knowledge Library" }));
    expect(screen.queryByRole("group", { name: "Recent searches:" })).toBeNull();
    for (const q of ["il faut", "été"]) {
      fireEvent.change(await screen.findByRole("searchbox"), { target: { value: q } });
      fireEvent.click(screen.getByRole("button", { name: "Search" }));
    }
    const group = await screen.findByRole("group", { name: "Recent searches:" });
    expect(within(group).getAllByRole("button").map((b) => b.textContent)).toEqual(["été", "×", "il faut", "×", "Clear recent searches"]);
    expect(group).toHaveTextContent("Kept only in this browser (at most 5) and never sent to the server.");
    fireEvent.click(within(group).getByRole("button", { name: "il faut" }));
    expect(screen.getByRole("searchbox")).toHaveValue("il faut");
    fireEvent.click(within(group).getByRole("button", { name: "Remove “été” from recent searches" }));
    expect(within(group).queryByRole("button", { name: "été" })).toBeNull();
    fireEvent.click(within(group).getByRole("button", { name: "Clear recent searches" }));
    expect(screen.queryByRole("group", { name: "Recent searches:" })).toBeNull();
    expect(window.localStorage.getItem(RECENT_SEARCHES_KEY)).toBeNull();
    // Never sent: no request carries the list.
    expect(calls.some((c) => c.includes("recent"))).toBe(false);
  });

  it("says when this browser does not keep recent searches", async () => {
    api();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Knowledge Library" }));
    expect(await screen.findByText("Recent searches are not kept: this browser does not let the page store them.")).toBeInTheDocument();
  });

  it("offers up to 50 results when the backend truncated the search", async () => {
    const calls = api(37);
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Knowledge Library" }));
    fireEvent.change(await screen.findByRole("searchbox"), { target: { value: "été" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText(/Showing the first 20 of 37/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show up to 37" }));
    await waitFor(() => expect(calls).toContain("GET /api/knowledge-library/concepts?q=%C3%A9t%C3%A9&limit=50"));
    expect(await screen.findByText(/37 concepts? match/)).toBeInTheDocument();
  });
});
