import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RecordDetail } from "./RecordDetail";
import { RecordsBrowser, RECORDS_PAGE_SIZE } from "../pages/RecordsBrowser";

afterEach(cleanup);

type Reply = { status?: number; body: unknown } | "network-error";
type Handler = Reply | (() => Reply | Promise<Reply>);

// routeFetch answers "METHOD /api/path?query" with a reply, a deferred reply, or a
// network error (rejected fetch: no HTTP response). Every call is recorded.
function routeFetch(handlers: Record<string, Handler>) {
  const calls: Array<{ method: string; url: string }> = [];
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = String(input);
    calls.push({ method, url });
    const handler = handlers[`${method} ${url}`];
    const reply = handler === undefined ? { status: 404, body: { error: "not found" } } : typeof handler === "function" ? await handler() : handler;
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

const count = (calls: Array<{ method: string; url: string }>, method: string, url: string) =>
  calls.filter((c) => c.method === method && c.url === url).length;

const entry = (id: number) => ({
  id,
  original_input: `Pourquoi ${id} ?`,
  original_context: `Contexte ${id}`,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
});

const analysis = (id: number, entryId: number, version: number) => ({
  id,
  entry_id: entryId,
  version,
  category: "grammar",
  explanation: `explanation v${version}`,
  confidence: 0.5,
  uncertainty: "",
  analyzer: "rule-based:v2:fr_l2_taxonomy_v1",
  created_at: "2026-10-01T00:00:00Z",
});

const effective = (analysisId: number, entryId: number, version: number, extra: Record<string, unknown> = {}) => ({
  analysis_id: analysisId,
  entry_id: entryId,
  version,
  original: { category: "grammar", explanation: `explanation v${version}` },
  effective: { category: "grammar", explanation: `explanation v${version}` },
  resolution: "unreviewed",
  feedback_id: null,
  ...extra,
});

const unit = (id: number, extra: Record<string, unknown> = {}) => ({
  id,
  ordinal: 1,
  kind: "grammar",
  canonical: "vouloir au présent",
  statement: "Vouloir se conjugue je veux, tu veux, il veut.",
  example: "Je veux partir.",
  confidence: 0.9,
  created_at: "t",
  admission: { ruleset: "knowledge_admission_v1", machine_state: "active", machine_reason: "default_active", effective_state: "active", latest_override: null },
  ...extra,
});

const extraction = (id: number, entryId: number, version: number, units: unknown[]) => ({
  id,
  entry_id: entryId,
  version,
  source_analysis_id: 10,
  source_feedback_id: null,
  extractor: "openai:test-model:knowledge_extraction_v1",
  created_at: "t",
  units,
});

// recordHandlers registers a record with the given analysis versions (all
// unreviewed) and no extraction unless overridden.
function recordHandlers(entryId: number, analyses: Array<ReturnType<typeof analysis>>): Record<string, Handler> {
  const handlers: Record<string, Handler> = {
    [`GET /api/entries/${entryId}`]: { body: entry(entryId) },
    [`GET /api/entries/${entryId}/analyses`]: { body: { analyses } },
    [`GET /api/entries/${entryId}/extractions`]: { body: { extractions: [] } },
    [`GET /api/entries/${entryId}/current-extraction`]: { body: { entry_id: entryId, current_extraction_id: null } },
  };
  for (const a of analyses) {
    handlers[`GET /api/analyses/${a.id}/effective`] = { body: effective(a.id, entryId, a.version) };
  }
  return handlers;
}

async function confirmAction(label: string, confirmLabel: string) {
  fireEvent.click(await screen.findByRole("button", { name: `${label}…` }));
  const group = screen.getByRole("group", { name: label });
  fireEvent.click(within(group).getByRole("button", { name: confirmLabel }));
}

describe("Explicit analysis request", () => {
  it("explains the effect first and sends nothing until confirmed", async () => {
    const calls = routeFetch(recordHandlers(1, []));
    render(<RecordDetail entryId={1} onBack={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Request analysis…" }));
    const group = screen.getByRole("group", { name: "Request analysis" });
    expect(group).toHaveTextContent("stores the result as a new, immutable analysis version");
    expect(group).toHaveTextContent("may be billed");
    expect(group).toHaveTextContent("never retried automatically");
    expect(within(group).getByRole("button", { name: "Create a new analysis version" })).toHaveFocus();

    fireEvent.click(within(group).getByRole("button", { name: "Cancel" }));
    expect(calls.every((c) => c.method === "GET")).toBe(true);
  });

  it("creates one version, re-reads the record, and shows the new latest interpretation", async () => {
    let created = false;
    const handlers = recordHandlers(1, []);
    handlers["GET /api/entries/1/analyses"] = () => ({ body: { analyses: created ? [analysis(11, 1, 1)] : [] } });
    handlers["GET /api/analyses/11/effective"] = { body: effective(11, 1, 1) };
    handlers["POST /api/entries/1/analysis"] = () => {
      created = true;
      return { status: 201, body: analysis(11, 1, 1) };
    };
    const calls = routeFetch(handlers);
    const onRecordChanged = vi.fn();
    render(<RecordDetail entryId={1} onBack={() => {}} onRecordChanged={onRecordChanged} />);
    expect(await screen.findByText("No analysis.")).toBeInTheDocument();

    await confirmAction("Request analysis", "Create a new analysis version");
    expect(await screen.findByRole("status")).toHaveTextContent("Created analysis v1 with rule-based:v2:fr_l2_taxonomy_v1.");
    expect(await screen.findByRole("button", { name: "v1 (latest)" })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByLabelText("Effective interpretation")).toHaveTextContent("explanation v1");
    expect(count(calls, "POST", "/api/entries/1/analysis")).toBe(1);
    expect(onRecordChanged).toHaveBeenCalledWith(1);
  });

  it("reports a provider failure as not stored and keeps the selected historical version", async () => {
    const handlers = recordHandlers(2, [analysis(21, 2, 1), analysis(22, 2, 2)]);
    handlers["POST /api/entries/2/analysis"] = () => ({ status: 502, body: { error: "analysis provider unavailable" } });
    const calls = routeFetch(handlers);
    const onRecordChanged = vi.fn();
    render(<RecordDetail entryId={2} onBack={() => {}} onRecordChanged={onRecordChanged} />);
    fireEvent.click(await screen.findByRole("button", { name: "v1" }));

    await confirmAction("Request analysis", "Create a new analysis version");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("No analysis was stored (502): analysis provider unavailable. The analysis provider may have been contacted.");
    expect(screen.getByRole("button", { name: "v1" })).toHaveAttribute("aria-pressed", "true");
    expect(count(calls, "GET", "/api/entries/2/analyses")).toBe(1);
    expect(onRecordChanged).not.toHaveBeenCalled();
  });

  it("shows an unknown outcome after a network failure, re-reads, and never resubmits", async () => {
    const handlers = recordHandlers(3, [analysis(31, 3, 1)]);
    handlers["POST /api/entries/3/analysis"] = "network-error";
    const calls = routeFetch(handlers);
    const onRecordChanged = vi.fn();
    render(<RecordDetail entryId={3} onBack={() => {}} onRecordChanged={onRecordChanged} />);
    await screen.findByRole("button", { name: "v1 (latest)" });

    await confirmAction("Request analysis", "Create a new analysis version");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Outcome unknown. No response was received, so a new analysis may or may not have been created.");
    expect(alert).not.toHaveTextContent(/failed/i);
    await waitFor(() => expect(count(calls, "GET", "/api/entries/3/analyses")).toBe(2));
    expect(count(calls, "POST", "/api/entries/3/analysis")).toBe(1);
    expect(onRecordChanged).toHaveBeenCalledWith(3);
  });

  it("sends one request when confirm is pressed repeatedly", async () => {
    const pending = deferred();
    const handlers = recordHandlers(4, []);
    handlers["POST /api/entries/4/analysis"] = () => pending.promise;
    const calls = routeFetch(handlers);
    render(<RecordDetail entryId={4} onBack={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Request analysis…" }));
    const confirm = within(screen.getByRole("group", { name: "Request analysis" })).getByRole("button", {
      name: "Create a new analysis version",
    });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(screen.getByRole("button", { name: "Request analysis — waiting for the server…" })).toBeDisabled();
    await act(async () => {
      pending.resolve({ status: 201, body: analysis(41, 4, 1) });
    });
    expect(count(calls, "POST", "/api/entries/4/analysis")).toBe(1);
  });
});

describe("Extraction panel", () => {
  it("shows the current extraction's units with admission, distinct from a zero-unit result", async () => {
    const handlers = recordHandlers(5, [analysis(51, 5, 1)]);
    handlers["GET /api/entries/5/extractions"] = {
      body: { extractions: [extraction(2, 5, 2, [unit(7, { admission: { ruleset: "knowledge_admission_v1", machine_state: "needs_review", machine_reason: "low_confidence", effective_state: "needs_review", latest_override: null } })]), extraction(1, 5, 1, [])] },
    };
    handlers["GET /api/entries/5/current-extraction"] = { body: { entry_id: 5, current_extraction_id: 2 } };
    routeFetch(handlers);
    render(<RecordDetail entryId={5} onBack={() => {}} />);
    const current = await screen.findByLabelText("Current extraction");
    expect(current).toHaveTextContent("Current extraction v2");
    expect(current).toHaveTextContent("from analysis #10");
    const units = within(current).getByRole("list", { name: "Extracted units" });
    expect(units).toHaveTextContent("vouloir au présent");
    expect(units).toHaveTextContent("needs_review (machine: low_confidence)");
    expect(screen.getByText("1 other stored version.")).toBeInTheDocument();
  });

  it("says when the current extraction produced zero units, and when none is stored", async () => {
    const handlers = recordHandlers(6, [analysis(61, 6, 1)]);
    handlers["GET /api/entries/6/extractions"] = { body: { extractions: [extraction(3, 6, 1, [])] } };
    handlers["GET /api/entries/6/current-extraction"] = { body: { entry_id: 6, current_extraction_id: 3 } };
    routeFetch({ ...handlers, ...recordHandlers(8, []) });
    const { rerender } = render(<RecordDetail entryId={6} onBack={() => {}} />);
    expect(await screen.findByText("Zero units.")).toBeInTheDocument();
    rerender(<RecordDetail entryId={8} onBack={() => {}} />);
    expect(await screen.findByText("No extraction stored.")).toBeInTheDocument();
  });

  it.each([
    {
      status: 503,
      error: "knowledge extraction is not enabled",
      expected: "Extraction is not enabled on this server (503) knowledge extraction is not enabled. Nothing was sent to a provider or stored.",
    },
    {
      status: 409,
      error: "entry not eligible for extraction: latest analysis is rejected",
      expected: "The server refused extraction for this record (409) entry not eligible for extraction: latest analysis is rejected. Nothing was sent to a provider or stored.",
    },
    {
      status: 504,
      error: "extraction provider timed out",
      expected: "The extraction provider failed (504) extraction provider timed out. The provider may have been called; nothing was stored.",
    },
  ])("reports a $status answer with the backend message and re-reads stored extractions", async ({ status, error, expected }) => {
    const handlers = recordHandlers(9, [analysis(91, 9, 1)]);
    handlers["POST /api/entries/9/extractions"] = () => ({ status, body: { error } });
    const calls = routeFetch(handlers);
    render(<RecordDetail entryId={9} onBack={() => {}} />);
    await screen.findByText("No extraction stored.");
    await confirmAction("Request extraction", "Send to the extraction provider");
    expect(await screen.findByRole("alert")).toHaveTextContent(expected);
    await waitFor(() => expect(count(calls, "GET", "/api/entries/9/extractions")).toBe(2));
    expect(count(calls, "POST", "/api/entries/9/extractions")).toBe(1);
  });

  it("explains extraction before sending and shows the stored units after success", async () => {
    let stored = false;
    const handlers = recordHandlers(10, [analysis(101, 10, 1)]);
    handlers["GET /api/entries/10/extractions"] = () => ({ body: { extractions: stored ? [extraction(4, 10, 1, [unit(9)])] : [] } });
    handlers["GET /api/entries/10/current-extraction"] = () => ({ body: { entry_id: 10, current_extraction_id: stored ? 4 : null } });
    handlers["POST /api/entries/10/extractions"] = () => {
      stored = true;
      return { status: 201, body: extraction(4, 10, 1, [unit(9)]) };
    };
    routeFetch(handlers);
    render(<RecordDetail entryId={10} onBack={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Request extraction…" }));
    const group = screen.getByRole("group", { name: "Request extraction" });
    expect(group).toHaveTextContent("external service and may be billed");
    expect(group).toHaveTextContent("The server decides eligibility");
    fireEvent.click(within(group).getByRole("button", { name: "Send to the extraction provider" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Stored extraction v1 with 1 unit.");
    expect(await screen.findByLabelText("Current extraction")).toHaveTextContent("Vouloir se conjugue");
  });

  it("shows an unknown extraction outcome after a network failure without resubmitting", async () => {
    const handlers = recordHandlers(11, [analysis(111, 11, 1)]);
    handlers["POST /api/entries/11/extractions"] = "network-error";
    const calls = routeFetch(handlers);
    render(<RecordDetail entryId={11} onBack={() => {}} />);
    await screen.findByText("No extraction stored.");
    await confirmAction("Request extraction", "Send to the extraction provider");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Outcome unknown. No response was received, so a new extraction may or may not have been stored");
    await waitFor(() => expect(count(calls, "GET", "/api/entries/11/extractions")).toBe(2));
    expect(count(calls, "POST", "/api/entries/11/extractions")).toBe(1);
  });

  it("does not show a late extraction result on a different record", async () => {
    const slow = deferred();
    const handlers = { ...recordHandlers(12, [analysis(121, 12, 1)]), ...recordHandlers(13, []) };
    handlers["POST /api/entries/12/extractions"] = () => slow.promise;
    routeFetch(handlers);
    const { rerender } = render(<RecordDetail entryId={12} onBack={() => {}} />);
    await screen.findByText("No extraction stored.");
    await confirmAction("Request extraction", "Send to the extraction provider");
    rerender(<RecordDetail entryId={13} onBack={() => {}} />);
    await screen.findByText("Pourquoi 13 ?");

    await act(async () => {
      slow.resolve({ status: 201, body: extraction(5, 12, 1, [unit(10)]) });
    });
    expect(screen.queryByText(/Stored extraction/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Request extraction…" })).toBeEnabled();
    expect(screen.getByText("No extraction stored.")).toBeInTheDocument();
  });
});

describe("Records list refresh after writes", () => {
  const listRow = (entryId: number, state: string) => ({
    entry_id: entryId,
    original_input: `Pourquoi ${entryId} ?`,
    original_context: "",
    entry_created_at: "t",
    state,
    analysis_id: state === "unanalyzed" ? null : 11,
    analysis_version: state === "unanalyzed" ? null : 1,
    analyzer: null,
    confidence: null,
    uncertainty: null,
    analysis_created_at: null,
    original: null,
    effective: state === "unanalyzed" ? null : { category: "grammar", explanation: "e" },
    feedback_id: null,
  });

  it("re-reads a changed row from the backend and flags a filter it no longer matches", async () => {
    let created = false;
    const handlers = recordHandlers(1, []);
    handlers["GET /api/entries/1/analyses"] = () => ({ body: { analyses: created ? [analysis(11, 1, 1)] : [] } });
    handlers["GET /api/analyses/11/effective"] = { body: effective(11, 1, 1) };
    handlers["POST /api/entries/1/analysis"] = () => {
      created = true;
      return { status: 201, body: analysis(11, 1, 1) };
    };
    handlers[`GET /api/learning-records?state=unanalyzed&limit=${RECORDS_PAGE_SIZE}`] = {
      body: { records: [listRow(1, "unanalyzed")], next_before_entry_id: null },
    };
    handlers[`GET /api/learning-records?limit=${RECORDS_PAGE_SIZE}`] = {
      body: { records: [listRow(1, "unanalyzed")], next_before_entry_id: null },
    };
    handlers["GET /api/learning-records?limit=1&before_entry_id=2"] = () => ({
      body: { records: [listRow(1, created ? "unreviewed" : "unanalyzed")], next_before_entry_id: 1 },
    });
    const calls = routeFetch(handlers);

    render(<RecordsBrowser />);
    await screen.findByText("Showing 1 record.");
    fireEvent.change(screen.getByLabelText("Record state"), { target: { value: "unanalyzed" } });
    fireEvent.click(await screen.findByRole("button", { name: /^Open record #1$/ }));
    await confirmAction("Request analysis", "Create a new analysis version");
    await screen.findByRole("status");
    await waitFor(() => expect(count(calls, "GET", "/api/learning-records?limit=1&before_entry_id=2")).toBe(1));

    fireEvent.click(screen.getByRole("button", { name: "← Back to records" }));
    const row = screen.getByRole("list", { name: "Learning records" });
    expect(within(row).getByText("unreviewed")).toBeInTheDocument();
    expect(row).toHaveTextContent('Changed since this list loaded: now "unreviewed", which no longer matches the "unanalyzed" filter.');
  });

  it("imports through the list, reloads it, and opens the new record", async () => {
    let imported = false;
    const handlers = recordHandlers(2, []);
    handlers[`GET /api/learning-records?limit=${RECORDS_PAGE_SIZE}`] = () => ({
      body: { records: imported ? [listRow(2, "unanalyzed")] : [], next_before_entry_id: null },
    });
    handlers["POST /api/captures"] = () => {
      imported = true;
      return { status: 201, body: { capture_id: "flh-014-list", entry_id: 2, analysis_id: null, created: true } };
    };
    routeFetch(handlers);

    render(<RecordsBrowser />);
    expect(await screen.findByText(/No learning records exist yet/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Import a capture" }));
    fireEvent.change(screen.getByLabelText("Capture JSON"), {
      target: { value: '{"capture_id":"flh-014-list","schema_version":"learning_capture_v1","source":"manual","original_input":"x","original_context":"","discussion_summary":""}' },
    });
    fireEvent.click(screen.getByRole("button", { name: "Import capture" }));
    expect(await screen.findByText("Showing 1 record.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open imported record #2" }));
    expect(await screen.findByText("Pourquoi 2 ?")).toBeInTheDocument();
  });
});
