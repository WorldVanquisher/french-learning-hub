import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RecordsBrowser, RECORDS_PAGE_SIZE } from "./RecordsBrowser";
import { RecordDetail } from "../components/RecordDetail";

afterEach(cleanup);

type Reply = { status?: number; body: unknown };
type Handler = Reply | (() => Reply | Promise<Reply>);

// routeFetch routes "/api/path?query" (exact, including the query string) to a
// static reply or a function that may return a deferred promise, so tests control
// response order. Every request is recorded for assertions.
// Record detail also reads the extraction panel. Unless a test registers those
// reads, they answer "no extraction stored" so they do not add unrelated alerts.
function noExtractionDefault(url: string): Reply | undefined {
  const current = url.match(/^\/api\/entries\/(\d+)\/current-extraction$/);
  if (current) return { body: { entry_id: Number(current[1]), current_extraction_id: null, selection_mode: "automatic" } };
  if (/^\/api\/entries\/\d+\/extractions$/.test(url)) return { body: { extractions: [] } };
  // Record detail also reads the selected version's feedback history.
  if (/^\/api\/analyses\/\d+\/feedback$/.test(url)) return { body: { feedback: [] } };
  return undefined;
}

function routeFetch(handlers: Record<string, Handler>) {
  const calls: Array<{ method: string; url: string }> = [];
  const impl = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    calls.push({ method: (init?.method ?? "GET").toUpperCase(), url });
    const handler = handlers[url] ?? noExtractionDefault(url);
    const reply: Reply =
      handler === undefined
        ? { status: 404, body: { error: "not found" } }
        : typeof handler === "function"
          ? await handler()
          : handler;
    return new Response(JSON.stringify(reply.body), {
      status: reply.status ?? 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as unknown as typeof fetch;
  globalThis.fetch = impl;
  return calls;
}

function deferred() {
  let resolve!: (reply: Reply) => void;
  const promise = new Promise<Reply>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

const firstPage = `/api/learning-records?limit=${RECORDS_PAGE_SIZE}`;
const pageFor = (query: string) => `/api/learning-records?${query}&limit=${RECORDS_PAGE_SIZE}`;

function record(entryId: number, overrides: Record<string, unknown> = {}) {
  return {
    entry_id: entryId,
    original_input: `question ${entryId}`,
    original_context: `context ${entryId}`,
    entry_created_at: "2026-10-01T00:00:00Z",
    state: "unreviewed",
    analysis_id: entryId * 10,
    analysis_version: 1,
    analyzer: "imported:chatgpt-web:learning_capture_v1",
    confidence: 0.9,
    uncertainty: "",
    analysis_created_at: "2026-10-01T00:00:00Z",
    original: { category: "grammar", explanation: "orig" },
    effective: { category: "grammar", explanation: "orig" },
    feedback_id: null,
    ...overrides,
  };
}

function entry(id: number) {
  return {
    id,
    original_input: `Pourquoi ${id} ?`,
    original_context: `Contexte ${id}`,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
  };
}

function analysis(id: number, entryId: number, version: number) {
  return {
    id,
    entry_id: entryId,
    version,
    category: "grammar",
    explanation: `explanation v${version}`,
    confidence: 0.8,
    uncertainty: "",
    analyzer: "rule-based:v2:fr_l2_taxonomy_v1",
    created_at: "2026-10-01T00:00:00Z",
  };
}

function effective(analysisId: number, entryId: number, version: number, overrides: Record<string, unknown> = {}) {
  return {
    analysis_id: analysisId,
    entry_id: entryId,
    version,
    original: { category: "grammar", explanation: `explanation v${version}` },
    effective: { category: "grammar", explanation: `explanation v${version}` },
    resolution: "unreviewed",
    feedback_id: null,
    ...overrides,
  };
}

// detailHandlers registers a fully loaded detail for one entry with one analysis.
function detailHandlers(entryId: number, eff: Record<string, unknown> = {}): Record<string, Handler> {
  const analysisId = entryId * 10;
  return {
    [`/api/entries/${entryId}`]: { body: entry(entryId) },
    [`/api/entries/${entryId}/analyses`]: { body: { analyses: [analysis(analysisId, entryId, 1)] } },
    [`/api/analyses/${analysisId}/effective`]: { body: effective(analysisId, entryId, 1, eff) },
  };
}

describe("RecordsBrowser list, pagination, and filter", () => {
  it("loads older pages with the backend cursor and reports the end of records", async () => {
    const calls = routeFetch({
      [firstPage]: { body: { records: [record(30), record(29)], next_before_entry_id: 29 } },
      [`/api/learning-records?limit=${RECORDS_PAGE_SIZE}&before_entry_id=29`]: {
        body: { records: [record(12)], next_before_entry_id: null },
      },
    });

    render(<RecordsBrowser />);
    expect(screen.getByText("Loading learning records…")).toBeInTheDocument();
    expect(await screen.findByText("question 30")).toBeInTheDocument();
    expect(screen.getByText("Showing 2 records.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Load older records" }));
    expect(await screen.findByText("question 12")).toBeInTheDocument();
    // Older rows are appended after the already loaded page, in backend order.
    const rows = within(screen.getByRole("list", { name: "Learning records" })).getAllByRole("heading");
    expect(rows.map((h) => h.textContent)).toEqual(["Record #30", "Record #29", "Record #12"]);
    expect(screen.getByText("End of records.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load older records" })).not.toBeInTheDocument();
    expect(calls.every((c) => c.method === "GET")).toBe(true);
  });

  it("filters by state through the backend and distinguishes a filtered empty result", async () => {
    const calls = routeFetch({
      [firstPage]: { body: { records: [record(3)], next_before_entry_id: null } },
      [pageFor("state=rejected")]: { body: { records: [], next_before_entry_id: null } },
    });

    render(<RecordsBrowser />);
    await screen.findByText("question 3");

    fireEvent.change(screen.getByLabelText("Record state"), { target: { value: "rejected" } });
    expect(await screen.findByText('No learning records are in the "rejected" state.')).toBeInTheDocument();
    expect(screen.queryByText("question 3")).not.toBeInTheDocument();
    expect(calls.map((c) => c.url)).toContain(pageFor("state=rejected"));
  });

  it("shows a distinct empty inventory message when no records exist", async () => {
    routeFetch({ [firstPage]: { body: { records: [], next_before_entry_id: null } } });
    render(<RecordsBrowser />);
    expect(await screen.findByText(/No learning records exist yet/)).toBeInTheDocument();
  });

  it("discards a list response for a superseded filter", async () => {
    const slowAll = deferred();
    routeFetch({
      [firstPage]: () => slowAll.promise,
      [pageFor("state=accepted")]: { body: { records: [record(7, { state: "accepted" })], next_before_entry_id: null } },
    });

    render(<RecordsBrowser />);
    fireEvent.change(screen.getByLabelText("Record state"), { target: { value: "accepted" } });
    expect(await screen.findByText("question 7")).toBeInTheDocument();

    // The unfiltered request finishes last; its rows must not replace the filtered list.
    await act(async () => {
      slowAll.resolve({ body: { records: [record(99)], next_before_entry_id: null } });
    });
    expect(screen.queryByText("question 99")).not.toBeInTheDocument();
    expect(screen.getByText("question 7")).toBeInTheDocument();
  });

  it("does not append an older page that was requested under a previous filter", async () => {
    const slowOlder = deferred();
    routeFetch({
      [firstPage]: { body: { records: [record(30)], next_before_entry_id: 30 } },
      [`/api/learning-records?limit=${RECORDS_PAGE_SIZE}&before_entry_id=30`]: () => slowOlder.promise,
      [pageFor("state=corrected")]: { body: { records: [record(5, { state: "corrected" })], next_before_entry_id: null } },
    });

    render(<RecordsBrowser />);
    fireEvent.click(await screen.findByRole("button", { name: "Load older records" }));
    fireEvent.change(screen.getByLabelText("Record state"), { target: { value: "corrected" } });
    expect(await screen.findByText("question 5")).toBeInTheDocument();

    await act(async () => {
      slowOlder.resolve({ body: { records: [record(1)], next_before_entry_id: null } });
    });
    expect(screen.queryByText("question 1")).not.toBeInTheDocument();
    expect(screen.getByText("Showing 1 record.")).toBeInTheDocument();
  });

  it("separates a failed first load from a failed older page", async () => {
    let firstAttempt = true;
    routeFetch({
      [firstPage]: () => {
        if (firstAttempt) {
          firstAttempt = false;
          return { status: 500, body: { error: "could not list learning records" } };
        }
        return { body: { records: [record(30)], next_before_entry_id: 30 } };
      },
      [`/api/learning-records?limit=${RECORDS_PAGE_SIZE}&before_entry_id=30`]: {
        status: 500,
        body: { error: "could not list learning records" },
      },
    });

    render(<RecordsBrowser />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load learning records: (500) could not list learning records",
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("question 30")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Load older records" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load older records");
    // Already loaded rows stay visible after an older-page failure.
    expect(screen.getByText("question 30")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry loading older records" })).toBeEnabled();
  });
});

describe("RecordsBrowser detail navigation", () => {
  it("preserves loaded pages, the filter, and focus when returning from a detail", async () => {
    const calls = routeFetch({
      [pageFor("state=unreviewed")]: { body: { records: [record(30), record(29)], next_before_entry_id: 29 } },
      [`/api/learning-records?state=unreviewed&limit=${RECORDS_PAGE_SIZE}&before_entry_id=29`]: {
        body: { records: [record(12)], next_before_entry_id: null },
      },
      [firstPage]: { body: { records: [record(30), record(29)], next_before_entry_id: 29 } },
      ...detailHandlers(12),
    });

    render(<RecordsBrowser />);
    await screen.findByText("question 30");
    fireEvent.change(screen.getByLabelText("Record state"), { target: { value: "unreviewed" } });
    await screen.findByText("question 30");
    fireEvent.click(screen.getByRole("button", { name: "Load older records" }));
    fireEvent.click(await screen.findByRole("button", { name: "Open record #12" }));

    expect(await screen.findByText("Pourquoi 12 ?")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Record #12", level: 2 })).toHaveFocus();
    const listRequests = calls.filter((c) => c.url.startsWith("/api/learning-records")).length;

    fireEvent.click(screen.getByRole("button", { name: "← Back to records" }));
    expect(screen.getByLabelText("Record state")).toHaveValue("unreviewed");
    expect(screen.getByText("Showing 3 records.")).toBeInTheDocument();
    expect(screen.getByText("question 12")).toBeVisible();
    expect(screen.getByRole("button", { name: "Open record #12" })).toHaveFocus();
    // Returning reuses the loaded list rather than refetching it.
    expect(calls.filter((c) => c.url.startsWith("/api/learning-records"))).toHaveLength(listRequests);
  });

  it("ignores a slow detail response for a record the reader has left", async () => {
    const slowEntryA = deferred();
    const slowAnalysesA = deferred();
    routeFetch({
      [firstPage]: { body: { records: [record(2), record(1)], next_before_entry_id: null } },
      "/api/entries/1": () => slowEntryA.promise,
      "/api/entries/1/analyses": () => slowAnalysesA.promise,
      ...detailHandlers(2),
    });

    render(<RecordsBrowser />);
    fireEvent.click(await screen.findByRole("button", { name: "Open record #1" }));
    expect(await screen.findByText("Loading the original record…")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "← Back to records" }));
    fireEvent.click(screen.getByRole("button", { name: "Open record #2" }));
    expect(await screen.findByText("Pourquoi 2 ?")).toBeInTheDocument();

    await act(async () => {
      slowEntryA.resolve({ body: entry(1) });
      slowAnalysesA.resolve({ body: { analyses: [analysis(10, 1, 1)] } });
    });
    expect(screen.queryByText("Pourquoi 1 ?")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Record #2", level: 2 })).toBeInTheDocument();
    expect(screen.getByText("Pourquoi 2 ?")).toBeInTheDocument();
  });

  it("ignores a slow effective interpretation for a version the reader has left", async () => {
    const slowV1 = deferred();
    routeFetch({
      [firstPage]: { body: { records: [record(4)], next_before_entry_id: null } },
      "/api/entries/4": { body: entry(4) },
      "/api/entries/4/analyses": { body: { analyses: [analysis(41, 4, 1), analysis(42, 4, 2)] } },
      "/api/analyses/41/effective": () => slowV1.promise,
      "/api/analyses/42/effective": {
        body: effective(42, 4, 2, { resolution: "accepted", feedback_id: 8 }),
      },
    });

    render(<RecordsBrowser />);
    fireEvent.click(await screen.findByRole("button", { name: "Open record #4" }));
    // The latest version is selected by default.
    expect(await screen.findByRole("button", { name: "v2 (latest)" })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByText("feedback #8")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "v1" }));
    expect(await screen.findByText("Loading the effective interpretation…")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "v2 (latest)" }));
    expect(await screen.findByText("feedback #8")).toBeInTheDocument();

    await act(async () => {
      slowV1.resolve({ body: effective(41, 4, 1, { resolution: "rejected", effective: null, feedback_id: 5 }) });
    });
    expect(screen.queryByText(/Rejected interpretation/)).not.toBeInTheDocument();
    expect(screen.getByText("feedback #8")).toBeInTheDocument();
  });
});

describe("RecordDetail states", () => {
  async function openRecord(entryId: number, handlers: Record<string, Handler>) {
    routeFetch({
      [firstPage]: { body: { records: [record(entryId)], next_before_entry_id: null } },
      ...handlers,
    });
    render(<RecordsBrowser />);
    fireEvent.click(await screen.findByRole("button", { name: `Open record #${entryId}` }));
  }

  it("shows the original input and context and an explicit no-analysis state", async () => {
    await openRecord(6, {
      "/api/entries/6": { body: entry(6) },
      "/api/entries/6/analyses": { body: { analyses: [] } },
    });
    expect(await screen.findByText("Pourquoi 6 ?")).toBeInTheDocument();
    expect(screen.getByText("Contexte 6")).toBeInTheDocument();
    expect(await screen.findByText("No analysis.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Effective interpretation")).not.toBeInTheDocument();
  });

  it("shows a rejected interpretation as having no effective values", async () => {
    await openRecord(7, detailHandlers(7, { resolution: "rejected", effective: null, feedback_id: 3 }));
    expect(await screen.findByText("Rejected interpretation.")).toBeInTheDocument();
    const section = screen.getByLabelText("Effective interpretation");
    expect(within(section).getByText("Rejected explanation")).toBeInTheDocument();
    expect(within(section).queryByText("Explanation")).not.toBeInTheDocument();
    expect(within(section).getByText("feedback #3")).toBeInTheDocument();
  });

  it("labels an unreviewed interpretation as not human-confirmed", async () => {
    await openRecord(8, detailHandlers(8));
    const section = await screen.findByLabelText("Effective interpretation");
    expect(within(section).getByText("unreviewed")).toBeInTheDocument();
    expect(within(section).getByText(/no human has accepted or corrected it/)).toBeInTheDocument();
    expect(within(section).getByText("no feedback")).toBeInTheDocument();
  });

  it("shows a corrected interpretation beside the original values", async () => {
    await openRecord(9, detailHandlers(9, {
      resolution: "corrected",
      effective: { category: "usage", explanation: "corrected text" },
      feedback_id: 4,
    }));
    const section = await screen.findByLabelText("Effective interpretation");
    expect(within(section).getByText("corrected text")).toBeInTheDocument();
    expect(within(section).getByText("Original explanation")).toBeInTheDocument();
  });

  it("keeps loaded sections visible when another detail read fails, and retries", async () => {
    let analysesAttempts = 0;
    await openRecord(5, {
      "/api/entries/5": { body: entry(5) },
      "/api/entries/5/analyses": () => {
        analysesAttempts += 1;
        return analysesAttempts === 1
          ? { status: 500, body: { error: "could not list analyses" } }
          : { body: { analyses: [analysis(50, 5, 1)] } };
      },
      "/api/analyses/50/effective": { body: effective(50, 5, 1) },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load analysis versions: (500) could not list analyses",
    );
    expect(screen.getByText("Pourquoi 5 ?")).toBeInTheDocument();
    expect(screen.queryByText("No analysis.")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByLabelText("Effective interpretation")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("reports a failed effective interpretation without hiding the analysis", async () => {
    await openRecord(11, {
      "/api/entries/11": { body: entry(11) },
      "/api/entries/11/analyses": { body: { analyses: [analysis(110, 11, 1)] } },
      "/api/analyses/110/effective": { status: 500, body: { error: "could not resolve effective analysis" } },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load the effective interpretation: (500) could not resolve effective analysis",
    );
    expect(screen.getByRole("heading", { name: /^Analysis v1\b/ })).toBeInTheDocument();
  });
});

describe("RecordDetail historical interpretation retry", () => {
  it("retries the failed historical version without selecting or requesting the latest", async () => {
    let historicalAttempts = 0;
    const calls = routeFetch({
      "/api/entries/4": { body: entry(4) },
      "/api/entries/4/analyses": { body: { analyses: [analysis(41, 4, 1), analysis(42, 4, 2)] } },
      "/api/analyses/42/effective": { body: effective(42, 4, 2) },
      "/api/analyses/41/effective": () => {
        historicalAttempts += 1;
        return historicalAttempts === 1
          ? { status: 500, body: { error: "historical interpretation failed" } }
          : { body: effective(41, 4, 1, { resolution: "accepted", feedback_id: 5 }) };
      },
    });

    render(<RecordDetail entryId={4} onBack={() => {}} />);
    await screen.findByText("analysis #42");
    fireEvent.click(screen.getByRole("button", { name: "v1" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("historical interpretation failed");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("feedback #5")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "v1" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "v2 (latest)" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("heading", { name: /^Analysis v1\b/ })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(calls.filter((c) => c.url === "/api/analyses/41/effective")).toHaveLength(2);
    expect(calls.filter((c) => c.url === "/api/analyses/42/effective")).toHaveLength(1);
  });

  it("discards a pending historical retry when switching entries and selects the new latest version", async () => {
    const slowRetry = deferred();
    let historicalAttempts = 0;
    const calls = routeFetch({
      "/api/entries/4": { body: entry(4) },
      "/api/entries/4/analyses": { body: { analyses: [analysis(41, 4, 1), analysis(42, 4, 2)] } },
      "/api/analyses/42/effective": { body: effective(42, 4, 2) },
      "/api/analyses/41/effective": () => {
        historicalAttempts += 1;
        return historicalAttempts === 1
          ? { status: 500, body: { error: "historical interpretation failed" } }
          : slowRetry.promise;
      },
      "/api/entries/6": { body: entry(6) },
      "/api/entries/6/analyses": { body: { analyses: [analysis(61, 6, 1), analysis(62, 6, 2)] } },
      "/api/analyses/62/effective": { body: effective(62, 6, 2, { feedback_id: 9 }) },
    });

    const { rerender } = render(<RecordDetail entryId={4} onBack={() => {}} />);
    await screen.findByText("analysis #42");
    fireEvent.click(screen.getByRole("button", { name: "v1" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/analyses/41/effective")).toHaveLength(2));

    rerender(<RecordDetail entryId={6} onBack={() => {}} />);
    await screen.findByText("feedback #9");
    await act(async () => {
      slowRetry.resolve({ body: effective(41, 4, 1, { feedback_id: 5 }) });
    });
    expect(screen.getByText("analysis #62")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "v2 (latest)" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("feedback #5")).not.toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/analyses/61/effective")).toBe(false);
  });
});

describe("RecordDetail stale responses without remounting", () => {
  it("discards an earlier entry's responses when the same detail switches entries", async () => {
    const slowEntry1 = deferred();
    const slowAnalyses1 = deferred();
    routeFetch({
      "/api/entries/1": () => slowEntry1.promise,
      "/api/entries/1/analyses": () => slowAnalyses1.promise,
      ...detailHandlers(2),
    });

    const { rerender } = render(<RecordDetail entryId={1} onBack={() => {}} />);
    rerender(<RecordDetail entryId={2} onBack={() => {}} />);
    expect(await screen.findByText("Pourquoi 2 ?")).toBeInTheDocument();
    expect(await screen.findByLabelText("Effective interpretation")).toBeInTheDocument();

    await act(async () => {
      slowEntry1.resolve({ body: entry(1) });
      slowAnalyses1.resolve({ body: { analyses: [analysis(10, 1, 1), analysis(11, 1, 2)] } });
    });
    expect(screen.queryByText("Pourquoi 1 ?")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "v2 (latest)" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "v1 (latest)" })).toHaveAttribute("aria-pressed", "true");
  });
});
