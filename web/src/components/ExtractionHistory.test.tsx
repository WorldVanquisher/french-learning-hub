import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { ExtractionPanel } from "./ExtractionPanel";

// Rendered inside StrictMode, as main.tsx does, so every test also covers the
// development effect replay. That replay reads the panel twice on mount, so tests
// arm a failure or delay just before the write and compare call counts with a
// baseline taken after the initial load, never with absolute numbers.
afterEach(cleanup);

type Reply = { status?: number; body: unknown } | "network-error";
type Handler = Reply | ((body: unknown) => Reply | Promise<Reply>);

function routeFetch(handlers: Record<string, Handler>) {
  const calls: Array<{ method: string; url: string; body: unknown }> = [];
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = String(input);
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, url, body });
    const handler = handlers[`${method} ${url}`];
    const reply = handler === undefined ? { status: 404, body: { error: "not found" } } : typeof handler === "function" ? await handler(body) : handler;
    if (reply === "network-error") throw new TypeError("Failed to fetch");
    return new Response(JSON.stringify(reply.body), { status: reply.status ?? 200, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
  return calls;
}

function deferred() {
  let resolve!: (reply: Reply) => void;
  const promise = new Promise<Reply>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

const count = <T extends { method: string; url: string }>(calls: T[], method: string, url: string) =>
  calls.filter((c) => c.method === method && c.url === url).length;

const unit = (id: number, canonical: string) => ({
  id,
  ordinal: 1,
  kind: "grammar",
  canonical,
  statement: `statement ${canonical}`,
  example: null,
  confidence: 0.9,
  created_at: "t",
  admission: { ruleset: "knowledge_admission_v1", machine_state: "active", machine_reason: "default_active", effective_state: "active", latest_override: null },
});

const extraction = (id: number, entryId: number, version: number, units: unknown[], sourceAnalysis = 10) => ({
  id,
  entry_id: entryId,
  version,
  source_analysis_id: sourceAnalysis,
  source_feedback_id: null,
  extractor: "openai:test-model:knowledge_extraction_v1",
  created_at: `2026-10-0${version}T00:00:00Z`,
  units,
});

// Entry `entryId` with three stored versions (newest first, as the backend lists
// them): v1 has zero units, v2 is current (explicitly selected), v3 is latest.
// The current pointer is mutable so a PUT changes what later GETs return.
function history(entryId: number, base: number) {
  let current: number | null = base + 2;
  const list = [
    extraction(base + 3, entryId, 3, [unit(base * 10 + 3, "v3 unit")], 12),
    extraction(base + 2, entryId, 2, [unit(base * 10 + 2, "v2 unit")], 11),
    extraction(base + 1, entryId, 1, [], 10),
  ];
  const handlers: Record<string, Handler> = {
    [`GET /api/entries/${entryId}/extractions`]: () => ({ body: { extractions: list } }),
    [`GET /api/entries/${entryId}/current-extraction`]: () => ({ body: { entry_id: entryId, current_extraction_id: current } }),
    [`PUT /api/entries/${entryId}/current-extraction`]: (body) => {
      current = (body as { extraction_id: number }).extraction_id;
      return { body: { entry_id: entryId, current_extraction_id: current } };
    },
  };
  return { handlers, ids: { v1: base + 1, v2: base + 2, v3: base + 3 }, setCurrent: (id: number | null) => (current = id) };
}

function renderPanel(entryId: number) {
  const result = render(
    <StrictMode>
      <ExtractionPanel entryId={entryId} latestVersion={4} />
    </StrictMode>,
  );
  return {
    ...result,
    switchTo: (next: number) =>
      result.rerender(
        <StrictMode>
          <ExtractionPanel key={next} entryId={next} latestVersion={4} />
        </StrictMode>,
      ),
  };
}

async function banner(role: "status" | "alert", text: string | RegExp): Promise<HTMLElement> {
  const matches = (el: HTMLElement) =>
    typeof text === "string" ? (el.textContent ?? "").includes(text) : text.test(el.textContent ?? "");
  let found: HTMLElement | undefined;
  await waitFor(() => {
    found = screen.queryAllByRole(role).find(matches);
    expect(found, `no ${role} containing ${String(text)}`).toBeDefined();
  });
  return found as HTMLElement;
}

const versions = () => within(screen.getByRole("group", { name: "Stored extraction versions" }));
const viewed = () => screen.getByLabelText("Viewed extraction");
const view = (label: string) => fireEvent.click(versions().getByRole("button", { name: label }));

async function selectViewedAsCurrent(version: number) {
  fireEvent.click(await screen.findByRole("button", { name: `Make v${version} the current extraction…` }));
  fireEvent.click(
    within(screen.getByRole("group", { name: `Make v${version} the current extraction` })).getByRole("button", {
      name: `Set v${version} as current`,
    }),
  );
}

describe("Browsing extraction history is read-only", () => {
  it("separates the viewed, current, and latest versions and shows each version's units", async () => {
    const { handlers } = history(1, 100);
    const calls = routeFetch(handlers);
    renderPanel(1);

    await screen.findByLabelText("Viewed extraction");
    const initialReads = count(calls, "GET", "/api/entries/1/extractions");
    expect(screen.getByLabelText("Extraction summary")).toHaveTextContent("Current: v2 · Latest stored: v3 · 3 versions stored");
    expect(screen.getByText(/A newer version \(v3\) is stored, but the server keeps v2 as current/)).toBeInTheDocument();
    expect(versions().getAllByRole("button").map((b) => b.textContent)).toEqual(["v1", "v2 (current)", "v3 (latest)"]);
    // The current version is viewed by default.
    expect(versions().getByRole("button", { name: "v2 (current)" })).toHaveAttribute("aria-pressed", "true");
    expect(viewed()).toHaveTextContent("Viewing extraction v2 (current)");
    expect(viewed()).toHaveTextContent("v2 unit");

    view("v3 (latest)");
    expect(viewed()).toHaveTextContent("Viewing extraction v3 (not current, latest stored)");
    expect(viewed()).toHaveTextContent("Not current: its units stay stored as history but are not offered for review and give no concept support while v2 is current.");
    expect(viewed()).toHaveTextContent("from analysis #12");
    view("v1");
    expect(viewed()).toHaveTextContent("Viewing extraction v1 (not current)");
    expect(within(viewed()).getByText("Zero units.")).toBeInTheDocument();

    // Viewing sends nothing and re-reads nothing.
    expect(calls.every((c) => c.method === "GET")).toBe(true);
    expect(count(calls, "GET", "/api/entries/1/extractions")).toBe(initialReads);
    expect(screen.queryByRole("button", { name: "Make v2 the current extraction…" })).not.toBeInTheDocument();
  });

  it("distinguishes no stored extraction from stored versions with none current", async () => {
    const { handlers, setCurrent } = history(2, 200);
    setCurrent(null);
    routeFetch({
      ...handlers,
      "GET /api/entries/3/extractions": { body: { extractions: [] } },
      "GET /api/entries/3/current-extraction": { body: { entry_id: 3, current_extraction_id: null } },
    });
    const { switchTo } = renderPanel(2);
    expect(await screen.findByText("No current extraction.")).toBeInTheDocument();
    expect(screen.getByLabelText("Extraction summary")).toHaveTextContent("Current: none · Latest stored: v3");
    expect(viewed()).toHaveTextContent("Viewing extraction v3 (not current, latest stored)");
    expect(screen.getByRole("button", { name: "Make v3 the current extraction…" })).toBeEnabled();

    switchTo(3);
    expect(await screen.findByText("No extraction stored.")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Stored extraction versions" })).not.toBeInTheDocument();
  });
});

describe("Explicit current-version selection", () => {
  it("explains the effect, PUTs only the version id, and confirms it by re-reading", async () => {
    const { handlers, ids } = history(4, 400);
    const calls = routeFetch(handlers);
    renderPanel(4);
    await screen.findByLabelText("Viewed extraction");
    view("v1");

    fireEvent.click(screen.getByRole("button", { name: "Make v1 the current extraction…" }));
    const group = screen.getByRole("group", { name: "Make v1 the current extraction" });
    for (const text of [
      "Its units become the ones offered in Concept Review and counted as concept support",
      "Nothing is deleted or rewritten",
      "SAME memberships, DISTINCT and relation labels, and INVALID judgments stay stored",
      "No extraction is run.",
      "later versions will not replace it automatically",
      "never retried automatically",
    ]) {
      expect(group).toHaveTextContent(text);
    }
    fireEvent.click(within(group).getByRole("button", { name: "Set v1 as current" }));

    await banner("status", "The server accepted v1 as the current extraction.");
    await banner("status", "Confirmed by re-read: the server reports v1 as the current extraction.");
    expect(calls.filter((c) => c.method === "PUT").map((c) => c.body)).toEqual([{ extraction_id: ids.v1 }]);
    expect(versions().getByRole("button", { name: "v1 (current)" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Extraction summary")).toHaveTextContent("Current: v1 · Latest stored: v3");
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("does not trust the PUT echo: a re-read showing another version is reported", async () => {
    const { handlers, ids } = history(5, 500);
    handlers["PUT /api/entries/5/current-extraction"] = () => ({ body: { entry_id: 5, current_extraction_id: ids.v1 } });
    routeFetch(handlers);
    renderPanel(5);
    await screen.findByLabelText("Viewed extraction");
    view("v1");
    await selectViewedAsCurrent(1);

    await banner("status", "The server accepted v1 as the current extraction.");
    const alert = await banner("alert", "The re-read shows v2 as current, not v1.");
    expect(alert).toHaveTextContent("It may have been changed again elsewhere");
    expect(screen.queryByText(/Confirmed by re-read/)).not.toBeInTheDocument();
    expect(versions().getByRole("button", { name: "v2 (current)" })).toBeInTheDocument();
  });

  it("reports a 422 as unchanged, keeps the viewed version, and still re-reads", async () => {
    const { handlers } = history(6, 600);
    handlers["PUT /api/entries/6/current-extraction"] = () => ({
      status: 422,
      body: { error: "validation error\nextraction does not belong to this entry" },
    });
    const calls = routeFetch(handlers);
    renderPanel(6);
    await screen.findByLabelText("Viewed extraction");
    const initialReads = count(calls, "GET", "/api/entries/6/extractions");
    view("v3 (latest)");
    await selectViewedAsCurrent(3);

    await banner("alert", "The server did not change the current extraction (422): validation error\nextraction does not belong to this entry.");
    await banner("status", "Stored extractions re-read from the server.");
    expect(viewed()).toHaveTextContent("Viewing extraction v3 (not current, latest stored)");
    expect(screen.queryByText(/Confirmed by re-read/)).not.toBeInTheDocument();
    expect(count(calls, "GET", "/api/entries/6/extractions")).toBe(initialReads + 1);
  });

  it("keeps an accepted selection distinct from a failed re-read, then confirms on reload", async () => {
    const { handlers } = history(7, 700);
    const answerList = handlers["GET /api/entries/7/extractions"] as () => Reply;
    let failNext = false;
    handlers["GET /api/entries/7/extractions"] = () => {
      if (!failNext) return answerList();
      failNext = false;
      return { status: 500, body: { error: "could not list extractions" } };
    };
    routeFetch(handlers);
    renderPanel(7);
    await screen.findByLabelText("Viewed extraction");
    view("v1");
    failNext = true;
    await selectViewedAsCurrent(1);

    await banner("status", "The server accepted v1 as the current extraction.");
    await banner("alert", "Could not re-read stored extractions from the server ((500) could not list extractions)");
    expect(screen.queryByText(/Confirmed by re-read/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Reload extractions" }));
    await banner("status", "Confirmed by re-read: the server reports v1 as the current extraction.");
    // The reader's viewed version survived the failed and the successful re-read.
    expect(viewed()).toHaveTextContent("Viewing extraction v1 (current)");
  });

  it("reports an unknown outcome, blocks another selection until a re-read, never resubmits", async () => {
    const slowList = deferred();
    const { handlers } = history(8, 800);
    const answerList = handlers["GET /api/entries/8/extractions"] as () => Reply;
    let slowNext = false;
    handlers["GET /api/entries/8/extractions"] = () => {
      if (!slowNext) return answerList();
      slowNext = false;
      return slowList.promise;
    };
    handlers["PUT /api/entries/8/current-extraction"] = "network-error";
    const calls = routeFetch(handlers);
    renderPanel(8);
    await screen.findByLabelText("Viewed extraction");
    view("v1");
    slowNext = true;
    await selectViewedAsCurrent(1);

    const alert = await banner("alert", "Outcome unknown.");
    expect(alert).toHaveTextContent("v1 may or may not have become the current extraction");
    // While the re-read runs no version state, and so no selection control, is shown.
    await screen.findByText("Loading extractions…");
    expect(screen.queryByRole("button", { name: /Make v\d the current extraction/ })).not.toBeInTheDocument();

    await act(async () => {
      slowList.resolve(answerList());
    });
    await banner("status", "Stored extractions re-read from the server.");
    // The re-read shows the request did not take effect; the reader may retry explicitly.
    await banner("alert", "The re-read shows v2 as current, not v1.");
    expect(screen.getByRole("button", { name: "Make v1 the current extraction…" })).toBeEnabled();
    expect(count(calls, "PUT", "/api/entries/8/current-extraction")).toBe(1);
  });

  it("sends one PUT for a repeated confirm while pending", async () => {
    const pending = deferred();
    const { handlers, ids } = history(9, 900);
    handlers["PUT /api/entries/9/current-extraction"] = () => pending.promise;
    const calls = routeFetch(handlers);
    renderPanel(9);
    await screen.findByLabelText("Viewed extraction");
    view("v1");
    fireEvent.click(screen.getByRole("button", { name: "Make v1 the current extraction…" }));
    const confirm = within(screen.getByRole("group", { name: "Make v1 the current extraction" })).getByRole("button", {
      name: "Set v1 as current",
    });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(screen.getByRole("button", { name: "Make v1 the current extraction — waiting for the server…" })).toBeDisabled();
    await act(async () => {
      pending.resolve({ body: { entry_id: 9, current_extraction_id: ids.v1 } });
    });
    expect(count(calls, "PUT", "/api/entries/9/current-extraction")).toBe(1);
  });
});

describe("Refreshes, stale responses, and record switches", () => {
  it("keeps the viewed version through a same-record refresh after another write", async () => {
    const { handlers } = history(10, 1000);
    handlers["POST /api/entries/10/extractions"] = () => ({ status: 503, body: { error: "knowledge extraction is not enabled" } });
    const calls = routeFetch(handlers);
    renderPanel(10);
    await screen.findByLabelText("Viewed extraction");
    const initialReads = count(calls, "GET", "/api/entries/10/extractions");
    view("v1");
    fireEvent.click(screen.getByRole("button", { name: "Request extraction…" }));
    fireEvent.click(within(screen.getByRole("group", { name: "Request extraction" })).getByRole("button", { name: "Send to the extraction provider" }));

    await banner("status", "Stored extractions re-read from the server.");
    expect(count(calls, "GET", "/api/entries/10/extractions")).toBe(initialReads + 1);
    expect(versions().getByRole("button", { name: "v1" })).toHaveAttribute("aria-pressed", "true");
    expect(viewed()).toHaveTextContent("Viewing extraction v1 (not current)");
  });

  it("discards an older re-read that finishes after a newer one", async () => {
    const slowAfterSelect = deferred();
    const { handlers, ids, setCurrent } = history(11, 1100);
    const answerCurrent = handlers["GET /api/entries/11/current-extraction"] as () => Reply;
    let slowNext = false;
    handlers["GET /api/entries/11/current-extraction"] = () => {
      if (!slowNext) return answerCurrent();
      slowNext = false;
      return slowAfterSelect.promise;
    };
    handlers["POST /api/entries/11/extractions"] = () => ({ status: 503, body: { error: "knowledge extraction is not enabled" } });
    routeFetch(handlers);
    renderPanel(11);
    await screen.findByLabelText("Viewed extraction");
    view("v1");
    slowNext = true;
    await selectViewedAsCurrent(1);
    await banner("status", "The server accepted v1 as the current extraction.");

    // A second write starts a newer re-read before the first one answers.
    fireEvent.click(screen.getByRole("button", { name: "Request extraction…" }));
    fireEvent.click(within(screen.getByRole("group", { name: "Request extraction" })).getByRole("button", { name: "Send to the extraction provider" }));
    await banner("status", "Stored extractions re-read from the server.");
    expect(versions().getByRole("button", { name: "v1 (current)" })).toBeInTheDocument();

    // The stale answer (still v2) arrives last and must be ignored.
    setCurrent(ids.v2);
    await act(async () => {
      slowAfterSelect.resolve({ body: { entry_id: 11, current_extraction_id: ids.v2 } });
    });
    expect(versions().getByRole("button", { name: "v1 (current)" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "v2 (current)" })).not.toBeInTheDocument();
  });

  it("isolates record switches: no viewed version or late selection result carries over", async () => {
    const pending = deferred();
    const a = history(12, 1200);
    const b = history(13, 1300);
    a.handlers["PUT /api/entries/12/current-extraction"] = () => pending.promise;
    const calls = routeFetch({ ...a.handlers, ...b.handlers });
    const { switchTo } = renderPanel(12);
    await screen.findByLabelText("Viewed extraction");
    view("v1");
    await selectViewedAsCurrent(1);

    switchTo(13);
    await waitFor(() => expect(viewed()).toHaveTextContent("Viewing extraction v2 (current)"));
    expect(versions().getByRole("button", { name: "v2 (current)" })).toHaveAttribute("aria-pressed", "true");
    const readsOf13 = count(calls, "GET", "/api/entries/13/extractions");

    await act(async () => {
      pending.resolve({ body: { entry_id: 12, current_extraction_id: a.ids.v1 } });
    });
    expect(screen.queryByText(/accepted v1|Confirmed by re-read|Outcome unknown/)).not.toBeInTheDocument();
    expect(count(calls, "GET", "/api/entries/13/extractions")).toBe(readsOf13);
    // Record 13 has no pending selection of its own.
    view("v1");
    expect(screen.getByRole("button", { name: "Make v1 the current extraction…" })).toBeEnabled();
    expect(count(calls, "PUT", "/api/entries/13/current-extraction")).toBe(0);
  });
});
