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

// banner finds the outcome or refresh banner whose text matches, so a separate
// refresh status next to an outcome never makes a lookup ambiguous.
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
    expect(group).toHaveTextContent("this request calls it and may be billed");
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
    await banner("status", "Created analysis v1 with rule-based:v2:fr_l2_taxonomy_v1.");
    await banner("status", "Analysis versions re-read from the server.");
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
    expect(alert).toHaveTextContent("No analysis was stored (502): analysis provider unavailable. The configured analyzer may have been called.");
    expect(screen.queryByText(/re-read from the server/)).not.toBeInTheDocument();
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
    expect(alert).toHaveTextContent("Outcome unknown. No response was received, so a new analysis may or may not have been created, and the configured analyzer may have been called.");
    expect(alert).not.toHaveTextContent(/failed|re-read/i);
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
      expected: "Extraction is not enabled on this server (503) knowledge extraction is not enabled. The server refuses before calling any extraction provider; nothing was stored.",
    },
    {
      status: 409,
      error: "entry not eligible for extraction: latest analysis is rejected",
      expected: "The server did not store an extraction (409) entry not eligible for extraction: latest analysis is rejected. This conflict can be detected before the provider runs or after it returns, so the extraction provider may have been called.",
    },
    {
      status: 504,
      error: "extraction provider timed out",
      expected: "The extraction provider failed (504) extraction provider timed out. Nothing was stored; the provider may have been called.",
    },
  ])("reports a $status answer with the backend message and re-reads stored extractions", async ({ status, error, expected }) => {
    const handlers = recordHandlers(9, [analysis(91, 9, 1)]);
    handlers["POST /api/entries/9/extractions"] = () => ({ status, body: { error } });
    const calls = routeFetch(handlers);
    render(<RecordDetail entryId={9} onBack={() => {}} />);
    await screen.findByText("No extraction stored.");
    await confirmAction("Request extraction", "Send to the extraction provider");
    await banner("alert", expected);
    await banner("status", "Stored extractions re-read from the server.");
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
    expect(group).toHaveTextContent("may be an external, billed service");
    expect(group).toHaveTextContent("If the interpretation changes while the provider runs, the server refuses to store the result.");
    expect(group).toHaveTextContent("The server decides eligibility");
    fireEvent.click(within(group).getByRole("button", { name: "Send to the extraction provider" }));

    await banner("status", "Stored extraction v1 with 1 unit.");
    await banner("status", "Stored extractions re-read from the server.");
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
    expect(alert).not.toHaveTextContent(/re-read/);
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
    await banner("status", "Created analysis v1");
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

// ---- FLH-015: contract-accurate wording, refresh distinct from mutation outcome ----

describe("FLH-015 extraction outcome wording", () => {
  it("does not claim a post-provider 409 skipped the provider", async () => {
    const handlers = recordHandlers(20, [analysis(201, 20, 1)]);
    handlers["POST /api/entries/20/extractions"] = () => ({
      status: 409,
      body: { error: "extraction source changed: a newer analysis exists for this entry" },
    });
    routeFetch(handlers);
    render(<RecordDetail entryId={20} onBack={() => {}} />);
    await screen.findByText("No extraction stored.");
    await confirmAction("Request extraction", "Send to the extraction provider");

    const alert = await banner("alert", "extraction source changed");
    expect(alert).toHaveTextContent("The server did not store an extraction (409) extraction source changed: a newer analysis exists for this entry.");
    expect(alert).toHaveTextContent("the extraction provider may have been called");
    expect(alert).not.toHaveTextContent(/not (sent|called)|nothing was sent|before calling/i);
  });

  it("only the disabled-extractor 503 says no provider was called", async () => {
    const handlers = recordHandlers(21, [analysis(211, 21, 1)]);
    handlers["POST /api/entries/21/extractions"] = () => ({ status: 503, body: { error: "knowledge extraction is not enabled" } });
    routeFetch(handlers);
    render(<RecordDetail entryId={21} onBack={() => {}} />);
    await screen.findByText("No extraction stored.");
    await confirmAction("Request extraction", "Send to the extraction provider");
    const alert = await banner("alert", "(503)");
    expect(alert).toHaveTextContent("The server refuses before calling any extraction provider; nothing was stored.");
  });
});

describe("FLH-015 refresh after a mutation is reported separately", () => {
  it("keeps a confirmed extraction distinct from a failed re-read, then recovers on reload", async () => {
    let stored = false;
    let listCalls = 0;
    const handlers = recordHandlers(22, [analysis(221, 22, 1)]);
    handlers["GET /api/entries/22/extractions"] = () => {
      listCalls += 1;
      if (listCalls === 2) return { status: 500, body: { error: "could not list extractions" } };
      return { body: { extractions: stored ? [extraction(6, 22, 1, [unit(11)])] : [] } };
    };
    handlers["GET /api/entries/22/current-extraction"] = () => ({ body: { entry_id: 22, current_extraction_id: stored ? 6 : null } });
    handlers["POST /api/entries/22/extractions"] = () => {
      stored = true;
      return { status: 201, body: extraction(6, 22, 1, [unit(11)]) };
    };
    routeFetch(handlers);
    render(<RecordDetail entryId={22} onBack={() => {}} />);
    await screen.findByText("No extraction stored.");
    await confirmAction("Request extraction", "Send to the extraction provider");

    await banner("status", "Stored extraction v1 with 1 unit.");
    const failed = await banner("alert", "Could not re-read stored extractions from the server ((500) could not list extractions)");
    expect(failed).toHaveTextContent("What is shown may be out of date");
    expect(screen.queryByText("Stored extractions re-read from the server.")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Reload extractions" }));
    await banner("status", "Stored extractions re-read from the server.");
    expect(screen.queryByText(/Could not re-read stored extractions/)).not.toBeInTheDocument();
    expect(await screen.findByLabelText("Current extraction")).toHaveTextContent("Vouloir se conjugue");
  });

  it("keeps a confirmed analysis distinct from a failed re-read of its versions", async () => {
    let created = false;
    let listCalls = 0;
    const handlers = recordHandlers(23, []);
    handlers["GET /api/entries/23/analyses"] = () => {
      listCalls += 1;
      if (listCalls === 2) return { status: 500, body: { error: "could not list analyses" } };
      return { body: { analyses: created ? [analysis(231, 23, 1)] : [] } };
    };
    handlers["GET /api/analyses/231/effective"] = { body: effective(231, 23, 1) };
    handlers["POST /api/entries/23/analysis"] = () => {
      created = true;
      return { status: 201, body: analysis(231, 23, 1) };
    };
    routeFetch(handlers);
    render(<RecordDetail entryId={23} onBack={() => {}} />);
    await screen.findByText("No analysis.");
    await confirmAction("Request analysis", "Create a new analysis version");

    await banner("status", "Created analysis v1");
    await banner("alert", "Could not re-read analysis versions from the server ((500) could not list analyses)");
    expect(screen.queryByText("Analysis versions re-read from the server.")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await banner("status", "Analysis versions re-read from the server.");
    expect(await screen.findByRole("button", { name: "v1 (latest)" })).toHaveAttribute("aria-pressed", "true");
  });

  it("blocks another analysis after an unknown outcome until a re-read succeeds, without resubmitting", async () => {
    let listCalls = 0;
    const handlers = recordHandlers(24, [analysis(241, 24, 1)]);
    handlers["GET /api/entries/24/analyses"] = () => {
      listCalls += 1;
      if (listCalls === 2) return { status: 500, body: { error: "could not list analyses" } };
      return { body: { analyses: [analysis(241, 24, 1)] } };
    };
    handlers["POST /api/entries/24/analysis"] = "network-error";
    const calls = routeFetch(handlers);
    render(<RecordDetail entryId={24} onBack={() => {}} />);
    await screen.findByRole("button", { name: "v1 (latest)" });
    await confirmAction("Request analysis", "Create a new analysis version");

    await banner("alert", "Outcome unknown.");
    await banner("alert", "Could not re-read analysis versions");
    expect(screen.getByRole("button", { name: "Request analysis…" })).toBeDisabled();
    expect(screen.getByText(/Unavailable until the analysis versions have been re-read/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await banner("status", "Analysis versions re-read from the server.");
    expect(screen.getByRole("button", { name: "Request analysis…" })).toBeEnabled();
    // The outcome stays unknown (it was never confirmed) and nothing was resent.
    await banner("alert", "Outcome unknown.");
    expect(count(calls, "POST", "/api/entries/24/analysis")).toBe(1);
  });

  it("blocks another extraction after an unknown outcome while the re-read is pending", async () => {
    const slowList = deferred();
    let listCalls = 0;
    const handlers = recordHandlers(25, [analysis(251, 25, 1)]);
    handlers["GET /api/entries/25/extractions"] = () => {
      listCalls += 1;
      return listCalls === 2 ? slowList.promise : { body: { extractions: [] } };
    };
    handlers["POST /api/entries/25/extractions"] = "network-error";
    const calls = routeFetch(handlers);
    render(<RecordDetail entryId={25} onBack={() => {}} />);
    await screen.findByText("No extraction stored.");
    await confirmAction("Request extraction", "Send to the extraction provider");

    await banner("alert", "Outcome unknown.");
    await banner("status", "Re-reading stored extractions from the server…");
    expect(screen.getByRole("button", { name: "Request extraction…" })).toBeDisabled();

    await act(async () => {
      slowList.resolve({ body: { extractions: [] } });
    });
    await banner("status", "Stored extractions re-read from the server.");
    expect(screen.getByRole("button", { name: "Request extraction…" })).toBeEnabled();
    expect(count(calls, "POST", "/api/entries/25/extractions")).toBe(1);
  });
});

describe("FLH-015 stale refresh responses", () => {
  it("does not apply a late extraction re-read to a different record", async () => {
    const slowList = deferred();
    let listCalls = 0;
    const handlers = { ...recordHandlers(26, [analysis(261, 26, 1)]), ...recordHandlers(27, []) };
    handlers["GET /api/entries/26/extractions"] = () => {
      listCalls += 1;
      return listCalls === 2 ? slowList.promise : { body: { extractions: [] } };
    };
    handlers["POST /api/entries/26/extractions"] = () => ({ status: 201, body: extraction(8, 26, 1, [unit(12)]) });
    routeFetch(handlers);
    const { rerender } = render(<RecordDetail entryId={26} onBack={() => {}} />);
    await screen.findByText("No extraction stored.");
    await confirmAction("Request extraction", "Send to the extraction provider");
    await banner("status", "Re-reading stored extractions from the server…");

    rerender(<RecordDetail entryId={27} onBack={() => {}} />);
    await screen.findByText("Pourquoi 27 ?");
    await act(async () => {
      slowList.resolve({ body: { extractions: [extraction(8, 26, 1, [unit(12)])] } });
    });
    expect(screen.queryByText(/re-read from the server|Stored extraction v1/)).not.toBeInTheDocument();
    expect(await screen.findByText("No extraction stored.")).toBeInTheDocument();
  });

  it("marks a list row unconfirmed when its re-read after a write fails", async () => {
    const handlers = recordHandlers(1, []);
    handlers["POST /api/entries/1/analysis"] = () => ({ status: 201, body: analysis(11, 1, 1) });
    handlers["GET /api/analyses/11/effective"] = { body: effective(11, 1, 1) };
    handlers[`GET /api/learning-records?limit=${RECORDS_PAGE_SIZE}`] = {
      body: {
        records: [{
          entry_id: 1, original_input: "Pourquoi 1 ?", original_context: "", entry_created_at: "t", state: "unanalyzed",
          analysis_id: null, analysis_version: null, analyzer: null, confidence: null, uncertainty: null,
          analysis_created_at: null, original: null, effective: null, feedback_id: null,
        }],
        next_before_entry_id: null,
      },
    };
    handlers["GET /api/learning-records?limit=1&before_entry_id=2"] = () => ({ status: 500, body: { error: "could not list learning records" } });
    routeFetch(handlers);
    render(<RecordsBrowser />);
    fireEvent.click(await screen.findByRole("button", { name: /^Open record #1$/ }));
    await confirmAction("Request analysis", "Create a new analysis version");
    await banner("status", "Created analysis v1");
    fireEvent.click(screen.getByRole("button", { name: "← Back to records" }));

    const row = screen.getByRole("list", { name: "Learning records" });
    await waitFor(() =>
      expect(row).toHaveTextContent("This record changed, but its row could not be re-read from the server."),
    );
    expect(within(row).getByText("unanalyzed")).toBeInTheDocument();
  });
});
