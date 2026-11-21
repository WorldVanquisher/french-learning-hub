import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import PublicDemoApp from "./PublicDemoApp";
import { RecordDetail } from "./components/RecordDetail";
import { unitReviewState } from "./components/ExtractionPanel";
import { ExplicitAction } from "./components/ExplicitAction";
import { RecordsBrowser } from "./pages/RecordsBrowser";
import { LocaleProvider } from "./i18n";
import { act } from "@testing-library/react";
import { VIEW_COPY, VIEW_GROUPS, VIEWS } from "./workbenchViews";
import { en } from "./i18n/en";

// The private workspace shell (workspace.tsx, workspace.css): grouped sections
// in the unchanged tab order, the shell attribute only in the private
// workbench, every rule scoped to it, and a record's source evidence before the
// work on it.

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

type Reply = { status?: number; body: unknown };

function serve(routes: Record<string, unknown>) {
  const calls: Array<{ method: string; url: string }> = [];
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    calls.push({ method: (init?.method ?? "GET").toUpperCase(), url });
    const path = new URL(url, "http://localhost").pathname;
    const fallback: Reply | undefined = /\/current-extraction$/.test(path)
      ? { body: { entry_id: 7, current_extraction_id: null, selection_mode: "automatic" } }
      : /\/extractions$/.test(path)
        ? { body: { extractions: [] } }
        : /\/feedback$/.test(path)
          ? { body: { feedback: [] } }
          : /reviewable-units/.test(path)
            ? { body: { reviewable_units: [] } }
            : path === "/api/concepts"
              ? { body: { concepts: [] } }
              : undefined;
    const reply: Reply = url in routes ? { body: routes[url] } : (fallback ?? { status: 404, body: { error: "not found" } });
    return new Response(JSON.stringify(reply.body), { status: reply.status ?? 200, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
  return calls;
}

describe("the workspace navigation groups", () => {
  it("cover every section exactly once, in the unchanged tab order", () => {
    expect(VIEW_GROUPS.flatMap((g) => g.views)).toEqual([...VIEWS]);
  });

  it("show each group's label and its sections, in tab order, with the current one pressed", () => {
    serve({});
    render(<App />);
    const nav = screen.getByRole("navigation", { name: "Workbench views" });
    const groups = within(nav).getAllByRole("group");
    expect(groups.map((g) => g.getAttribute("aria-labelledby"))).toEqual(VIEW_GROUPS.map((g) => `ws-nav-group-${g.key}`));
    expect(within(nav).getByRole("group", { name: "Records and knowledge" })).toBeInTheDocument();
    const buttons = within(nav).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(VIEWS.map((v) => en[VIEW_COPY[v].tab]));
    // The default section (Concept Review) is the pressed one, and its group is the kicker.
    expect(within(nav).getByRole("button", { name: "Concept Review" })).toHaveAttribute("aria-pressed", "true");
    expect(document.querySelector(".ws-kicker")?.textContent).toBe("Curation and research");
    fireEvent.click(within(nav).getByRole("button", { name: "Knowledge Library" }));
    expect(within(nav).getByRole("button", { name: "Knowledge Library" })).toHaveAttribute("aria-pressed", "true");
    expect(document.querySelector(".ws-kicker")?.textContent).toBe("Records and knowledge");
    expect(window.location.hash).toBe("#/library");
  });

  it("keeps the language selector beside the brand, and the other display settings after the sections", () => {
    serve({});
    render(<App />);
    const language = screen.getByLabelText("Language");
    expect(language.closest(".ws-top")).not.toBeNull();
    const settings = screen.getByRole("group", { name: "Display settings" });
    expect(within(settings).getByLabelText("Explanation language")).toBeInTheDocument();
    expect(within(settings).getByLabelText("Theme")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Workbench views" });
    expect(language.compareDocumentPosition(nav) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe("the shell attribute and the scoped stylesheet", () => {
  it("is set by the private workbench only, and removed when it unmounts", () => {
    serve({});
    const { unmount } = render(<App />);
    expect(document.documentElement.dataset.shell).toBe("workspace");
    unmount();
    expect(document.documentElement.dataset.shell).toBeUndefined();
  });

  it("is never set by the public demo", async () => {
    serve({ "/api/knowledge-library/demo": {} });
    render(<PublicDemoApp />);
    expect(document.documentElement.dataset.shell).toBeUndefined();
  });

  it("scopes every rule in workspace.css to the private shell", () => {
    const css = readFileSync(resolve(process.cwd(), "src/workspace.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    // Every selector list before a "{" (outside @media headers) starts each selector with the shell attribute.
    const selectors = [...css.matchAll(/([^{}]+)\{/g)].map((m) => m[1].trim()).filter((s) => !s.startsWith("@"));
    expect(selectors.length).toBeGreaterThan(40);
    for (const list of selectors)
      for (const sel of list.split(",").map((s) => s.trim())) expect(sel, sel).toMatch(/^:root\[data-shell="workspace"\]/);
  });
});

describe("a record in the workspace", () => {
  it("puts its source evidence (the learner's own words) before the work on it", async () => {
    serve({
      "/api/entries/7": { id: 7, original_input: "Pourquoi « tu me manques » ?", original_context: "Un message.", created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z" },
      "/api/entries/7/analyses": { analyses: [] },
    });
    render(<RecordDetail entryId={7} onBack={() => {}} />);
    const evidence = await screen.findByRole("complementary", { name: "Source evidence" });
    expect(await within(evidence).findByText("Pourquoi « tu me manques » ?")).toBeInTheDocument();
    const work = document.querySelector(".record-work");
    expect(work).not.toBeNull();
    // Reading (and keyboard) order: the evidence first, then the stage, analyses and extraction.
    expect(evidence.compareDocumentPosition(work!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(work as HTMLElement).getByRole("region", { name: "Analysis versions" })).toBeInTheDocument();
  });
});

describe("missing evidence in the workspace (UI-029)", () => {
  it("says so when a question was saved without context", async () => {
    serve({
      "/api/entries/7": { id: 7, original_input: "Pourquoi ?", original_context: "", created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z" },
      "/api/entries/7/analyses": { analyses: [] },
    });
    render(<RecordDetail entryId={7} onBack={() => {}} />);
    const evidence = await screen.findByRole("complementary", { name: "Source evidence" });
    expect(await within(evidence).findByText("(no context recorded)")).toBeInTheDocument();
    expect(within(evidence).getByText("The learner's own words (record #7), stored as written and never rewritten.")).toBeInTheDocument();
  });

  it("shows a record that cannot be read as an error in its evidence column, with a retry", async () => {
    globalThis.fetch = vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      const body = /\/entries\/9$/.test(url) ? { error: "entry not found" } : /analyses$/.test(url) ? { analyses: [] } : /current-extraction$/.test(url) ? { entry_id: 9, current_extraction_id: null, selection_mode: "automatic" } : { extractions: [] };
      return new Response(JSON.stringify(body), { status: /\/entries\/9$/.test(url) ? 404 : 200, headers: { "Content-Type": "application/json" } });
    }) as unknown as typeof fetch;
    render(<RecordDetail entryId={9} onBack={() => {}} />);
    const evidence = await screen.findByRole("complementary", { name: "Source evidence" });
    expect(await within(evidence).findByRole("alert")).toHaveTextContent("Could not load the original record: (404) entry not found");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});

describe("a candidate's state title (UI-021)", () => {
  const ready = (ids: number[]) => ({ status: "ready" as const, data: new Set(ids) });
  const decision = (snapshot: unknown) => ({ status: "ready", data: { snapshot } }) as never;
  it("follows the same reads as the review links, and decides nothing", () => {
    expect(unitReviewState(7, false, ready([7]), null)).toEqual({ kind: "historical" });
    expect(unitReviewState(7, true, null, null)).toEqual({ kind: "checking" });
    expect(unitReviewState(7, true, { status: "error", message: "x" } as never, null)).toEqual({ kind: "unknown" });
    expect(unitReviewState(7, true, ready([7]), null)).toEqual({ kind: "awaiting" });
    expect(unitReviewState(7, true, ready([]), decision({ status: "same", current_same: { membership: { concept_id: 3 }, decision: { id: 1, decision_source: "human" } } }))).toEqual({ kind: "filed", conceptId: 3 });
    expect(unitReviewState(7, true, ready([]), decision({ status: "invalid", current_same: null }))).toEqual({ kind: "invalid" });
    expect(unitReviewState(7, true, ready([]), null)).toEqual({ kind: "decided" });
  });
});

describe("the skip control (UI-097)", () => {
  it("is the first control and moves keyboard focus to the section title", () => {
    serve({});
    render(<App />);
    const skip = screen.getByRole("button", { name: "Skip to the section content" });
    const firstControl = document.querySelector("button, a[href], select, input");
    expect(firstControl).toBe(skip);
    fireEvent.click(skip);
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1, name: "Concept Review" }));
  });
});

describe("keyboard behaviour added in the continuation block", () => {
  it("offers “Show all records” on an empty filtered list; it clears the filters and focuses the first one (UI-128)", async () => {
    const record = { entry_id: 3, original_input: "Pourquoi ?", original_context: "", entry_created_at: "2026-10-01T00:00:00Z", state: "unreviewed", analysis_id: null, analysis_version: null, analyzer: null, confidence: null, uncertainty: "", analysis_created_at: null, original: null, effective: null, feedback_id: null };
    globalThis.fetch = vi.fn(async (input: string | URL | Request) => {
      const url = new URL(String(input), "http://localhost");
      const body = url.searchParams.has("state") ? { records: [], next_before_entry_id: null } : { records: [record], next_before_entry_id: null };
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }) as unknown as typeof fetch;
    render(<RecordsBrowser />);
    await screen.findByText("Pourquoi ?");
    const filters = screen.getByLabelText("Record filters");
    const select = within(filters).getAllByRole("combobox")[0] as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "accepted" } });
    const reset = await screen.findByRole("button", { name: "Show all records (clear the filters)" });
    fireEvent.click(reset);
    expect(await screen.findByText("Pourquoi ?")).toBeInTheDocument();
    expect(select.value).toBe("all");
    expect(document.activeElement).toBe(select);
  });

  it("closes the innermost open disclosure on Escape and keeps focus on its toggle (UI-123)", () => {
    serve({});
    render(<App />);
    const host = document.createElement("div");
    host.innerHTML = '<details open><summary>Technical details</summary><button id="inner">inner</button></details><div class="source-disclosure"><button id="toggle" aria-expanded="true">Hide</button></div>';
    document.body.appendChild(host);
    const toggle = document.getElementById("toggle")!;
    toggle.addEventListener("click", () => toggle.setAttribute("aria-expanded", "false"));
    (document.getElementById("inner") as HTMLButtonElement).focus();
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(host.querySelector("details")!.open).toBe(false);
    expect(document.activeElement).toBe(host.querySelector("summary"));
    toggle.focus();
    fireEvent.keyDown(toggle, { key: "Escape" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(toggle);
    host.remove();
  });

  it("returns focus to the button that opened a confirmation, after Cancel or a settled request (UI-127)", async () => {
    let finish!: () => void;
    const Wrapper = () => {
      const [pending, setPending] = React.useState(false);
      return (
        <ExplicitAction
          label="Request analysis"
          confirmLabel="Create a new analysis version"
          explanation="Sends this record to the analyzer."
          pending={pending}
          onConfirm={() => {
            setPending(true);
            return new Promise<void>((r) => (finish = () => { setPending(false); r(); }));
          }}
        />
      );
    };
    render(<LocaleProvider><Wrapper /></LocaleProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Request analysis…" }));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Create a new analysis version" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Request analysis…" }));
    fireEvent.click(screen.getByRole("button", { name: "Request analysis…" }));
    fireEvent.click(screen.getByRole("button", { name: "Create a new analysis version" }));
    await act(async () => finish());
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Request analysis…" }));
  });
});
