import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PublicDemoApp from "../PublicDemoApp";
import { hashForScreen, linkFromHash } from "./deepLink";
import { demoServer, IL_FAUT, PRONOUNS } from "./demoTestServer";
import { queryProblem, queryWords } from "./searchLimits";

// Search state and recovery in the public demo (items 051–059): overlapping
// searches, the count tied to the executed query, a failed search keeping the
// last one that worked, explicit retry, blank and encoded link parameters,
// query limits, and restored filters with result focus.

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
});

const renderDemo = (url: string, opts: Parameters<typeof demoServer>[0] = {}) => {
  window.history.pushState(null, "", url);
  const s = demoServer(opts);
  render(<StrictMode><PublicDemoApp /></StrictMode>);
  return s;
};
const search = (q: string) => {
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: q } });
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
};
const resultTitles = () => screen.queryAllByRole("button").filter((b) => b.id.startsWith("library-result-")).map((b) => b.textContent);

describe("overlapping searches (051, 052)", () => {
  it("drops a slow answer that arrives after a newer search's: list, count and address stay the newer one", async () => {
    renderDemo("/#q=pronouns");
    await waitFor(() => expect(resultTitles()).toEqual([PRONOUNS.target]));
    // Hold the next search, then run another; release the held one last.
    let releaseSlow: () => void = () => {};
    const inner = globalThis.fetch;
    globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      if (String(input).includes("q=viennes")) await new Promise<void>((r) => (releaseSlow = r));
      return inner(input, init);
    }) as unknown as typeof fetch;
    search("viennes");
    await waitFor(() => expect(screen.getByText("Searching the knowledge library…")).toBeInTheDocument());
    search("pronouns");
    await waitFor(() => expect(resultTitles()).toEqual([PRONOUNS.target]));
    releaseSlow();
    await new Promise((r) => setTimeout(r, 50));
    // The late "viennes" answer changes nothing: list, count and address stay "pronouns".
    expect(resultTitles()).toEqual([PRONOUNS.target]);
    expect(screen.getByText("1 concept matching “pronouns”.")).toBeInTheDocument();
    expect(window.location.hash).toBe("#q=pronouns");
  });
});

describe("a failed search (053, 054)", () => {
  it("keeps the last search that worked below the error, and names what the retry runs", async () => {
    renderDemo("/#q=pronouns");
    await waitFor(() => expect(resultTitles()).toEqual([PRONOUNS.target]));
    const inner = globalThis.fetch;
    let fail = true;
    globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) =>
      fail && String(input).includes("q=viennes")
        ? new Response(JSON.stringify({ error: "unavailable" }), { status: 503, headers: { "Content-Type": "application/json" } })
        : inner(input, init),
    ) as unknown as typeof fetch;
    search("viennes");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not search the knowledge library:");
    const retry = within(alert).getByRole("button", { name: "Search “viennes” again" });
    // The last usable results stay, labelled, and still work.
    expect(document.getElementById("demo-previous-heading")).toHaveTextContent("Below: the results of “pronouns”, the last search that worked.");
    expect(resultTitles()).toEqual([PRONOUNS.target]);
    expect(screen.getByRole("searchbox")).toHaveValue("viennes");
    fail = false;
    fireEvent.click(retry);
    await waitFor(() => expect(resultTitles()).toEqual([IL_FAUT.target]));
    expect(screen.queryByText(/the last search that worked/)).toBeNull();
  });

  it("while a newer search is pending, shows only that one: no retry for the failed one", async () => {
    renderDemo("/");
    await screen.findByRole("searchbox");
    const inner = globalThis.fetch;
    let release: () => void = () => {};
    globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const u = String(input);
      if (u.includes("q=viennes")) return new Response("{}", { status: 503 });
      if (u.includes("q=pronouns")) await new Promise<void>((r) => (release = r));
      return inner(input, init);
    }) as unknown as typeof fetch;
    search("viennes");
    await screen.findByRole("button", { name: "Search “viennes” again" });
    search("pronouns");
    await waitFor(() => expect(screen.getByText("Searching the knowledge library…")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Search “viennes” again" })).toBeNull();
    release();
    await waitFor(() => expect(resultTitles()).toEqual([PRONOUNS.target]));
  });
});

describe("query limits (057)", () => {
  it("counts words and bytes the way the server does", () => {
    expect(queryWords("L'élève et l'Élève : à y aller")).toEqual(["eleve", "et", "aller"]);
    expect(queryProblem("un deux trois quatre cinq six sept huit")).toBeNull();
    expect(queryProblem("un deux trois quatre cinq six sept huit neuf")).toEqual({ kind: "words", count: 9 });
    expect(queryProblem("y à ?")).toEqual({ kind: "no-word" });
    expect(queryProblem("é".repeat(101))).toEqual({ kind: "bytes", count: 202 });
    expect(queryProblem("e".repeat(200))).toBeNull();
    expect(queryProblem("   ")).toBeNull();
  });

  it("says which limit a refused search broke and offers to edit it, not to retry", async () => {
    renderDemo("/");
    await screen.findByRole("searchbox");
    const inner = globalThis.fetch;
    globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const u = new URL(String(input), "http://localhost");
      if (u.pathname.endsWith("/knowledge-library/concepts") && queryProblem(u.searchParams.get("q") ?? ""))
        return new Response(JSON.stringify({ error: "invalid knowledge library query: q has more than 8 terms" }), { status: 400, headers: { "Content-Type": "application/json" } });
      return inner(input, init);
    }) as unknown as typeof fetch;
    search("pourquoi dit on que les phrases longues de exercice sont dures");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("“pourquoi dit on que les phrases longues de exercice sont dures” has 11 different words; the search uses at most 8. Remove some words and search again.");
    expect(within(alert).queryByRole("button", { name: /again/ })).toBeNull();
    fireEvent.click(within(alert).getByRole("button", { name: "Edit the search" }));
    expect(screen.getByRole("searchbox")).toHaveFocus();
    search("y");
    expect(await screen.findByText(/has no word of two or more letters or digits/)).toBeInTheDocument();
  });
});

describe("blank, encoded and Unicode link parameters (055, 056)", () => {
  it("treats a blank query as the start's empty search and any other blank value as a link cut short", () => {
    for (const ok of ["#q=", "#q=%20%20", "#q=+"]) {
      const l = linkFromHash(ok);
      expect([l.malformed, l.search.q, l.screen.kind], ok).toEqual([false, "", "results"]);
    }
    for (const bad of ["#example=", "#compare=", "#mode=", "#concept=", "#concept=12&unit="])
      expect(linkFromHash(bad).malformed, bad).toBe(true);
    // R2-085: the optional status filter and step are left out instead.
    for (const ok of ["#state=", "#q=x&state=", "#example=y-en&step="]) expect(linkFromHash(ok).malformed, ok).toBe(false);
  });

  it("reads percent-encoded, raw and decomposed accents, plus signs and encoded separators as the same text", () => {
    expect(linkFromHash("#q=march%C3%A9").search.q).toBe("marché");
    expect(linkFromHash("#q=marché").search.q).toBe("marché");
    expect(linkFromHash("#q=marche%CC%81").search.q).toBe("marché");
    expect(linkFromHash("#q=il+faut").search.q).toBe("il faut");
    expect(linkFromHash("#q=C%2B%2B").search.q).toBe("C++");
    expect(linkFromHash("#q=l%E2%80%99%C3%A9l%C3%A8ve").search.q).toBe("l’élève");
    // An encoded "&concept=1" is part of the query, not a screen.
    const l = linkFromHash("#q=a%26concept%3D1");
    expect([l.search.q, l.screen.kind]).toEqual(["a&concept=1", "results"]);
    // Round trip: the canonical address reads back as the same search.
    for (const q of ["marché", "l’élève", "a&concept=1", "C++", "il faut", "你好"])
      expect(linkFromHash(hashForScreen({ kind: "results" }, { mode: "keyword", q, state: "all" })).search.q, q).toBe(q);
  });

  it("opens a shared link with encoded accents, sends the same text and shows it as written", async () => {
    const s = renderDemo("/#q=pronoun%C3%A9");
    expect(await screen.findByRole("searchbox")).toHaveValue("pronouné");
    await waitFor(() => expect(s.calls.some((c) => c.url === "/api/knowledge-library/concepts?q=pronoun%C3%A9")).toBe(true));
    expect(window.location.hash).toBe("#q=pronoun%C3%A9");
  });
});

describe("restored filters and result focus (059)", () => {
  it("keeps the status filter on reload and Back, and Back focuses the result that was opened", async () => {
    renderDemo("/#q=pronouns&state=active");
    await waitFor(() => expect(resultTitles()).toEqual([PRONOUNS.target]));
    expect(screen.getByRole("combobox", { name: "Concept status" })).toHaveValue("active");
    const result = screen.getByRole("button", { name: PRONOUNS.target });
    result.focus();
    fireEvent.click(result);
    await waitFor(() => expect(window.location.hash).toBe("#q=pronouns&state=active&concept=12"));
    window.history.back();
    await waitFor(() => expect(window.location.hash).toBe("#q=pronouns&state=active"));
    await waitFor(() => expect(screen.getByRole("button", { name: PRONOUNS.target })).toHaveFocus());
    expect(screen.getByRole("combobox", { name: "Concept status" })).toHaveValue("active");
  });
});
