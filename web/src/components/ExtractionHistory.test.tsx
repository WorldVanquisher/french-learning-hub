import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { ExtractionPanel } from "./ExtractionPanel";
import type { UnitTarget } from "../navigation";

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

type Mode = "automatic" | "pinned";

// A backend fixture for one entry with three stored versions (newest first, as
// the backend lists them): v1 has zero units, v2 and v3 have one unit each. It
// models the FLH-023 contract: GET reports the selection, PUT pins, DELETE
// resumes automatic selection of the latest version.
function history(entryId: number, base: number, start: { current: "v2" | "v3"; mode: Mode } = { current: "v2", mode: "pinned" }) {
  const ids = { v1: base + 1, v2: base + 2, v3: base + 3 };
  const units = { v2: base * 10 + 2, v3: base * 10 + 3 };
  let current: number | null = ids[start.current];
  let mode: Mode = start.mode;
  const list = [
    extraction(ids.v3, entryId, 3, [unit(units.v3, "v3 unit")], 12),
    extraction(ids.v2, entryId, 2, [unit(units.v2, "v2 unit")], 11),
    extraction(ids.v1, entryId, 1, [], 10),
  ];
  const selection = () => ({ body: { entry_id: entryId, current_extraction_id: current, selection_mode: mode } });
  const handlers: Record<string, Handler> = {
    [`GET /api/entries/${entryId}/extractions`]: () => ({ body: { extractions: list } }),
    [`GET /api/entries/${entryId}/current-extraction`]: selection,
    [`PUT /api/entries/${entryId}/current-extraction`]: (body) => {
      current = (body as { extraction_id: number }).extraction_id;
      mode = "pinned";
      return selection();
    },
    [`DELETE /api/entries/${entryId}/current-extraction`]: () => {
      current = ids.v3;
      mode = "automatic";
      return selection();
    },
    // Only the current extraction's units can be reviewable; none are resolved here.
    [`GET /api/reviewable-units?entry_id=${entryId}`]: () => ({
      body: { reviewable_units: current === ids.v2 ? [{ unit_id: units.v2 }] : current === ids.v3 ? [{ unit_id: units.v3 }] : [] },
    }),
  };
  return {
    handlers,
    ids,
    units,
    set: (id: number | null, m: Mode) => {
      current = id;
      mode = m;
    },
  };
}

function renderPanel(entryId: number, extra: { onNavigateToUnit?: (t: UnitTarget) => void; returnEpoch?: number } = {}) {
  const panel = (id: number, props = extra) => (
    <StrictMode>
      <ExtractionPanel key={id} entryId={id} latestVersion={4} {...props} />
    </StrictMode>
  );
  const result = render(panel(entryId));
  return {
    ...result,
    switchTo: (next: number) => result.rerender(panel(next)),
    rerenderWith: (props: typeof extra) => result.rerender(panel(entryId, props)),
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
const summary = () => screen.getByLabelText("Extraction summary");
const modeHint = () => screen.getByLabelText("Selection mode");
const view = (label: string) => fireEvent.click(versions().getByRole("button", { name: label }));

async function confirm(label: string, confirmLabel: string) {
  fireEvent.click(await screen.findByRole("button", { name: `${label}…` }));
  fireEvent.click(within(screen.getByRole("group", { name: label })).getByRole("button", { name: confirmLabel }));
}
const pinViewed = (version: number) => confirm(`Pin v${version} as the current extraction`, `Pin v${version}`);
const resume = () => confirm("Resume automatic latest selection", "Remove the pin");

describe("Browsing history and selection mode", () => {
  it("separates viewed, current, latest, and the pinned mode; browsing is read-only", async () => {
    const { handlers } = history(1, 100);
    const calls = routeFetch(handlers);
    renderPanel(1);

    await screen.findByLabelText("Viewed extraction");
    const initialReads = count(calls, "GET", "/api/entries/1/extractions");
    expect(summary()).toHaveTextContent("Current: v2 · Selection: pinned · Latest stored: v3 · 3 versions stored");
    expect(modeHint()).toHaveTextContent("Pinned: the server keeps v2 as current although v3 is the latest stored version.");
    expect(versions().getAllByRole("button").map((b) => b.textContent)).toEqual(["v1", "v2 (current, pinned)", "v3 (latest)"]);
    expect(versions().getByRole("button", { name: "v2 (current, pinned)" })).toHaveAttribute("aria-pressed", "true");
    expect(viewed()).toHaveTextContent("Viewing extraction v2 (current)");

    view("v3 (latest)");
    expect(viewed()).toHaveTextContent("Viewing extraction v3 (not current, latest stored)");
    expect(viewed()).toHaveTextContent("give no concept support while v2 is current");
    expect(viewed()).toHaveTextContent("from analysis #12");
    view("v1");
    expect(within(viewed()).getByText("Zero units.")).toBeInTheDocument();

    expect(calls.every((c) => c.method === "GET")).toBe(true);
    expect(count(calls, "GET", "/api/entries/1/extractions")).toBe(initialReads);
  });

  it("shows automatic selection, and a pin to the latest version as pinned-and-latest", async () => {
    const { handlers, ids } = history(2, 200, { current: "v3", mode: "automatic" });
    const calls = routeFetch(handlers);
    renderPanel(2);
    await screen.findByLabelText("Viewed extraction");
    expect(summary()).toHaveTextContent("Current: v3 · Selection: automatic · Latest stored: v3");
    expect(modeHint()).toHaveTextContent("Automatic: the server treats the latest stored extraction as current");
    expect(screen.queryByRole("button", { name: "Resume automatic latest selection…" })).not.toBeInTheDocument();
    expect(versions().getByRole("button", { name: "v3 (current, latest)" })).toBeInTheDocument();

    // The current latest version can still be pinned explicitly.
    await pinViewed(3);
    await banner("status", "Confirmed by re-read: the server reports v3 (pinned) as the current extraction.");
    expect(calls.filter((c) => c.method === "PUT").map((c) => c.body)).toEqual([{ extraction_id: ids.v3 }]);
    expect(modeHint()).toHaveTextContent("Pinned: v3 is pinned and is also the latest stored version. It stays current even if a newer extraction is stored later.");
    expect(versions().getByRole("button", { name: "v3 (current, pinned, latest)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resume automatic latest selection…" })).toBeEnabled();
  });

  it("shows no stored extraction under automatic selection with a null current id", async () => {
    routeFetch({
      "GET /api/entries/3/extractions": { body: { extractions: [] } },
      "GET /api/entries/3/current-extraction": { body: { entry_id: 3, current_extraction_id: null, selection_mode: "automatic" } },
    });
    renderPanel(3);
    expect(await screen.findByText("No extraction stored.")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Stored extraction versions" })).not.toBeInTheDocument();
  });
});

describe("Pinning a version", () => {
  it("explains the effect, PUTs only the version id, and confirms it by re-reading", async () => {
    const { handlers, ids } = history(4, 400);
    const calls = routeFetch(handlers);
    renderPanel(4);
    await screen.findByLabelText("Viewed extraction");
    view("v1");

    fireEvent.click(screen.getByRole("button", { name: "Pin v1 as the current extraction…" }));
    const group = screen.getByRole("group", { name: "Pin v1 as the current extraction" });
    for (const text of [
      "Its units become the ones offered in Concept Review and counted as concept support",
      "Nothing is deleted or rewritten",
      "SAME memberships, DISTINCT and relation labels, and INVALID judgments stay stored",
      "No extraction is run.",
      "A pinned version stays current even when the record is extracted again, including when it is the latest now.",
      "Resume automatic latest selection",
    ]) {
      expect(group).toHaveTextContent(text);
    }
    fireEvent.click(within(group).getByRole("button", { name: "Pin v1" }));

    await banner("status", "The server accepted v1 as the pinned current extraction.");
    await banner("status", "Confirmed by re-read: the server reports v1 (pinned) as the current extraction.");
    expect(calls.filter((c) => c.method === "PUT").map((c) => c.body)).toEqual([{ extraction_id: ids.v1 }]);
    expect(versions().getByRole("button", { name: "v1 (current, pinned)" })).toHaveAttribute("aria-pressed", "true");
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("does not trust the PUT echo: a re-read showing another version is reported", async () => {
    const { handlers, ids } = history(5, 500);
    handlers["PUT /api/entries/5/current-extraction"] = () => ({ body: { entry_id: 5, current_extraction_id: ids.v1, selection_mode: "pinned" } });
    routeFetch(handlers);
    renderPanel(5);
    await screen.findByLabelText("Viewed extraction");
    view("v1");
    await pinViewed(1);

    await banner("status", "The server accepted v1 as the pinned current extraction.");
    const alert = await banner("alert", "The re-read shows v2 (pinned) as current, not v1 (pinned).");
    expect(alert).toHaveTextContent("It may have been changed again elsewhere");
    expect(screen.queryByText(/Confirmed by re-read/)).not.toBeInTheDocument();
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
    await pinViewed(3);

    await banner("alert", "The server did not change the current extraction selection (422): validation error\nextraction does not belong to this entry.");
    await banner("status", "Stored extractions re-read from the server.");
    expect(viewed()).toHaveTextContent("Viewing extraction v3 (not current, latest stored)");
    expect(count(calls, "GET", "/api/entries/6/extractions")).toBe(initialReads + 1);
  });

  it("keeps an accepted pin distinct from a failed re-read, then confirms on reload", async () => {
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
    await pinViewed(1);

    await banner("status", "The server accepted v1 as the pinned current extraction.");
    await banner("alert", "Could not re-read stored extractions from the server ((500) could not list extractions)");
    expect(screen.queryByText(/Confirmed by re-read/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reload extractions" }));
    await banner("status", "Confirmed by re-read: the server reports v1 (pinned) as the current extraction.");
    expect(viewed()).toHaveTextContent("Viewing extraction v1 (current)");
  });

  it("reports an unknown pin outcome, hides versions until the re-read, never resubmits", async () => {
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
    await pinViewed(1);

    const alert = await banner("alert", "Outcome unknown.");
    expect(alert).toHaveTextContent("v1 may or may not have been pinned as current");
    await screen.findByText("Loading extractions…");
    expect(screen.queryByRole("button", { name: /Pin v\d as the current extraction/ })).not.toBeInTheDocument();

    await act(async () => {
      slowList.resolve(answerList());
    });
    await banner("alert", "The re-read shows v2 (pinned) as current, not v1 (pinned).");
    expect(screen.getByRole("button", { name: "Pin v1 as the current extraction…" })).toBeEnabled();
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
    fireEvent.click(screen.getByRole("button", { name: "Pin v1 as the current extraction…" }));
    const button = within(screen.getByRole("group", { name: "Pin v1 as the current extraction" })).getByRole("button", { name: "Pin v1" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(screen.getByRole("button", { name: "Pin v1 as the current extraction — waiting for the server…" })).toBeDisabled();
    // Resuming automatic selection shares the pending selection write.
    expect(screen.getByRole("button", { name: "Resume automatic latest selection — waiting for the server…" })).toBeDisabled();
    await act(async () => {
      pending.resolve({ body: { entry_id: 9, current_extraction_id: ids.v1, selection_mode: "pinned" } });
    });
    expect(count(calls, "PUT", "/api/entries/9/current-extraction")).toBe(1);
  });
});

describe("Resuming automatic latest selection", () => {
  it("explains the effect, DELETEs once, and confirms automatic selection by re-reading", async () => {
    const { handlers } = history(10, 1000);
    const calls = routeFetch(handlers);
    renderPanel(10);
    await screen.findByLabelText("Viewed extraction");

    fireEvent.click(screen.getByRole("button", { name: "Resume automatic latest selection…" }));
    const group = screen.getByRole("group", { name: "Resume automatic latest selection" });
    for (const text of [
      "treats the latest stored extraction (now v3) as current, following later extractions automatically",
      "units of the previously pinned version stay stored",
      "Nothing is deleted or rewritten",
      "No extraction is run and no provider is called.",
      "never retried automatically",
    ]) {
      expect(group).toHaveTextContent(text);
    }
    fireEvent.click(within(group).getByRole("button", { name: "Remove the pin" }));

    await banner("status", "The server removed the pin and reported automatic selection.");
    await banner("status", "Confirmed by re-read: the server reports v3 (automatic) as the current extraction.");
    expect(summary()).toHaveTextContent("Current: v3 · Selection: automatic · Latest stored: v3");
    expect(screen.queryByRole("button", { name: "Resume automatic latest selection…" })).not.toBeInTheDocument();
    expect(calls.filter((c) => c.method !== "GET").map((c) => `${c.method} ${c.url}`)).toEqual([
      "DELETE /api/entries/10/current-extraction",
    ]);
  });

  it("reports a re-pin by someone else as a conflict instead of claiming automatic", async () => {
    const { handlers, ids, set } = history(11, 1100);
    handlers["DELETE /api/entries/11/current-extraction"] = () => {
      // The pin is removed, then re-applied elsewhere before the re-read.
      set(ids.v2, "pinned");
      return { body: { entry_id: 11, current_extraction_id: ids.v3, selection_mode: "automatic" } };
    };
    routeFetch(handlers);
    renderPanel(11);
    await screen.findByLabelText("Viewed extraction");
    await resume();

    await banner("status", "The server removed the pin and reported automatic selection.");
    await banner("alert", "The re-read shows v2 (pinned) as current, not automatic selection.");
    expect(screen.getByRole("button", { name: "Resume automatic latest selection…" })).toBeEnabled();
  });

  it("reports a failed clear as unchanged and an unknown one without resubmitting", async () => {
    const { handlers } = history(12, 1200);
    let attempt = 0;
    handlers["DELETE /api/entries/12/current-extraction"] = () => {
      attempt += 1;
      return attempt === 1 ? { status: 500, body: { error: "could not clear current extraction selection" } } : "network-error";
    };
    const calls = routeFetch(handlers);
    renderPanel(12);
    await screen.findByLabelText("Viewed extraction");

    await resume();
    await banner("alert", "The server did not change the current extraction selection (500): could not clear current extraction selection.");
    await banner("status", "Stored extractions re-read from the server.");

    await resume();
    await banner("alert", "Outcome unknown. No response was received, so the pin may or may not have been removed.");
    await banner("alert", "The re-read shows v2 (pinned) as current, not automatic selection.");
    expect(count(calls, "DELETE", "/api/entries/12/current-extraction")).toBe(2);
  });
});

describe("Unit links follow backend review eligibility", () => {
  it("offers review only for units the backend lists; historical units can only be inspected", async () => {
    const { handlers, ids, units } = history(13, 1300);
    const calls = routeFetch(handlers);
    const onNavigateToUnit = vi.fn();
    renderPanel(13, { onNavigateToUnit });
    await screen.findByText("Awaiting concept review.");

    fireEvent.click(screen.getByRole("button", { name: `Review unit #${units.v2} in Concept Review` }));
    expect(onNavigateToUnit).toHaveBeenLastCalledWith({ kind: "review", entryId: 13, unitId: units.v2, extractionId: ids.v2, extractionVersion: 2 });

    view("v3 (latest)");
    expect(within(viewed()).getByText("Historical unit: not reviewable while another version is current.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Review unit #/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: `Inspect stored labels of unit #${units.v3}` }));
    expect(onNavigateToUnit).toHaveBeenLastCalledWith({ kind: "inspect", entryId: 13, unitId: units.v3, extractionId: ids.v3, extractionVersion: 3 });
    expect(count(calls, "GET", "/api/reviewable-units?entry_id=13")).toBeGreaterThan(0);
  });

  it("does not offer review for a current unit the backend no longer lists", async () => {
    const { handlers, units } = history(14, 1400);
    handlers["GET /api/reviewable-units?entry_id=14"] = { body: { reviewable_units: [] } };
    routeFetch(handlers);
    renderPanel(14, { onNavigateToUnit: vi.fn() });
    await screen.findByText("Not awaiting review (already resolved or marked INVALID).");
    expect(screen.queryByRole("button", { name: /Review unit #/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: `Inspect unit #${units.v2}` })).toBeInTheDocument();
  });

  it("offers a recheck when review status cannot be read, and re-reads on return", async () => {
    const { handlers, units } = history(15, 1500);
    const answer = handlers["GET /api/reviewable-units?entry_id=15"] as () => Reply;
    let fail = true;
    handlers["GET /api/reviewable-units?entry_id=15"] = () => (fail ? { status: 500, body: { error: "could not list reviewable units" } } : answer());
    const calls = routeFetch(handlers);
    const { rerenderWith } = renderPanel(15, { onNavigateToUnit: vi.fn(), returnEpoch: 0 });
    await banner("alert", "Could not check which units await review: (500) could not list reviewable units");
    expect(screen.queryByRole("button", { name: /Review unit #/ })).not.toBeInTheDocument();

    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Recheck review status" }));
    await screen.findByRole("button", { name: `Review unit #${units.v2} in Concept Review` });

    const before = count(calls, "GET", "/api/reviewable-units?entry_id=15");
    rerenderWith({ onNavigateToUnit: vi.fn(), returnEpoch: 1 });
    await waitFor(() => expect(count(calls, "GET", "/api/reviewable-units?entry_id=15")).toBe(before + 1));
  });
});

describe("Refreshes, stale responses, and record switches", () => {
  it("keeps the viewed version through a same-record refresh after another write", async () => {
    const { handlers } = history(16, 1600);
    handlers["POST /api/entries/16/extractions"] = () => ({ status: 503, body: { error: "knowledge extraction is not enabled" } });
    const calls = routeFetch(handlers);
    renderPanel(16);
    await screen.findByLabelText("Viewed extraction");
    const initialReads = count(calls, "GET", "/api/entries/16/extractions");
    view("v1");
    await confirm("Request extraction", "Send to the extraction provider");

    await banner("status", "Stored extractions re-read from the server.");
    expect(count(calls, "GET", "/api/entries/16/extractions")).toBe(initialReads + 1);
    expect(versions().getByRole("button", { name: "v1" })).toHaveAttribute("aria-pressed", "true");
  });

  it("discards an older re-read that finishes after a newer one", async () => {
    const slowAfterPin = deferred();
    const { handlers, ids, set } = history(17, 1700);
    const answerCurrent = handlers["GET /api/entries/17/current-extraction"] as () => Reply;
    let slowNext = false;
    handlers["GET /api/entries/17/current-extraction"] = () => {
      if (!slowNext) return answerCurrent();
      slowNext = false;
      return slowAfterPin.promise;
    };
    handlers["POST /api/entries/17/extractions"] = () => ({ status: 503, body: { error: "knowledge extraction is not enabled" } });
    routeFetch(handlers);
    renderPanel(17);
    await screen.findByLabelText("Viewed extraction");
    view("v1");
    slowNext = true;
    await pinViewed(1);
    await banner("status", "The server accepted v1 as the pinned current extraction.");

    await confirm("Request extraction", "Send to the extraction provider");
    await banner("status", "Stored extractions re-read from the server.");
    expect(versions().getByRole("button", { name: "v1 (current, pinned)" })).toBeInTheDocument();

    set(ids.v2, "pinned");
    await act(async () => {
      slowAfterPin.resolve({ body: { entry_id: 17, current_extraction_id: ids.v2, selection_mode: "pinned" } });
    });
    expect(versions().getByRole("button", { name: "v1 (current, pinned)" })).toBeInTheDocument();
  });

  it("isolates record switches: no viewed version or late selection result carries over", async () => {
    const pending = deferred();
    const a = history(18, 1800);
    const b = history(19, 1900);
    a.handlers["DELETE /api/entries/18/current-extraction"] = () => pending.promise;
    const calls = routeFetch({ ...a.handlers, ...b.handlers });
    const { switchTo } = renderPanel(18);
    await screen.findByLabelText("Viewed extraction");
    view("v1");
    await resume();

    switchTo(19);
    await waitFor(() => expect(viewed()).toHaveTextContent("Viewing extraction v2 (current)"));
    const readsOf19 = count(calls, "GET", "/api/entries/19/extractions");
    await act(async () => {
      pending.resolve({ body: { entry_id: 18, current_extraction_id: a.ids.v3, selection_mode: "automatic" } });
    });
    expect(screen.queryByText(/removed the pin|Confirmed by re-read|Outcome unknown/)).not.toBeInTheDocument();
    expect(count(calls, "GET", "/api/entries/19/extractions")).toBe(readsOf19);
    expect(screen.getByRole("button", { name: "Resume automatic latest selection…" })).toBeEnabled();
    expect(count(calls, "DELETE", "/api/entries/19/current-extraction")).toBe(0);
  });
});
