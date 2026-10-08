import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RecordDetail } from "./RecordDetail";
import { CaptureImport } from "./CaptureImport";
import { RecordsBrowser, RECORDS_PAGE_SIZE } from "../pages/RecordsBrowser";

// Every test renders inside StrictMode, exactly like main.tsx. In development,
// React then mounts each component, runs effect cleanups, and runs effect setups
// again. Mutation lifecycle code must survive that replay.

afterEach(cleanup);

type Reply = { status?: number; body: unknown } | "network-error";
type Handler = Reply | ((body: unknown) => Reply | Promise<Reply>);

function routeFetch(handlers: Record<string, Handler>) {
  const calls: Array<{ method: string; url: string; body: unknown }> = [];
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = String(input);
    let body: unknown;
    try {
      body = init?.body ? JSON.parse(String(init.body)) : undefined;
    } catch {
      body = init?.body;
    }
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

const analysis = (id: number, entryId: number, version: number) => ({
  id,
  entry_id: entryId,
  version,
  category: "grammar",
  explanation: `explanation v${version}`,
  confidence: 0.5,
  uncertainty: "",
  analyzer: "rule-based:v2:fr_l2_taxonomy_v1",
  created_at: "t",
});

const effective = (a: ReturnType<typeof analysis>, extra: Record<string, unknown> = {}) => ({
  analysis_id: a.id,
  entry_id: a.entry_id,
  version: a.version,
  original: { category: a.category, explanation: a.explanation },
  effective: { category: a.category, explanation: a.explanation },
  resolution: "unreviewed",
  feedback_id: null,
  ...extra,
});

function recordHandlers(entryId: number, analyses: Array<ReturnType<typeof analysis>>): Record<string, Handler> {
  const handlers: Record<string, Handler> = {
    [`GET /api/entries/${entryId}`]: { body: { id: entryId, original_input: `Pourquoi ${entryId} ?`, original_context: "c", created_at: "t", updated_at: "t" } },
    [`GET /api/entries/${entryId}/analyses`]: { body: { analyses } },
    [`GET /api/entries/${entryId}/extractions`]: { body: { extractions: [] } },
    [`GET /api/entries/${entryId}/current-extraction`]: { body: { entry_id: entryId, current_extraction_id: null, selection_mode: "automatic" } },
  };
  for (const a of analyses) {
    handlers[`GET /api/analyses/${a.id}/effective`] = { body: effective(a) };
    handlers[`GET /api/analyses/${a.id}/feedback`] = { body: { feedback: [] } };
  }
  return handlers;
}

function renderStrict(ui: React.ReactElement) {
  const result = render(<StrictMode>{ui}</StrictMode>);
  return { ...result, rerenderStrict: (next: React.ReactElement) => result.rerender(<StrictMode>{next}</StrictMode>) };
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

async function confirmAction(label: string, confirmLabel: string) {
  fireEvent.click(await screen.findByRole("button", { name: `${label}…` }));
  fireEvent.click(within(screen.getByRole("group", { name: label })).getByRole("button", { name: confirmLabel }));
}

const feedbackPanel = () => screen.getByRole("region", { name: "Feedback" });
const decide = (label: string) => fireEvent.click(within(feedbackPanel()).getByRole("radio", { name: new RegExp(`^${label}`) }));
const feedbackSubmit = () => within(feedbackPanel()).getByRole("button", { name: /Record "|Recording feedback|Choose a decision/ });

describe("StrictMode: responses settle after effect replay", () => {
  it("analysis: a confirmed response clears pending and shows the outcome", async () => {
    let created = false;
    const handlers = recordHandlers(1, []);
    handlers["GET /api/entries/1/analyses"] = () => ({ body: { analyses: created ? [analysis(11, 1, 1)] : [] } });
    handlers["GET /api/analyses/11/effective"] = { body: effective(analysis(11, 1, 1)) };
    handlers["GET /api/analyses/11/feedback"] = { body: { feedback: [] } };
    handlers["POST /api/entries/1/analysis"] = () => {
      created = true;
      return { status: 201, body: analysis(11, 1, 1) };
    };
    routeFetch(handlers);
    renderStrict(<RecordDetail entryId={1} onBack={() => {}} />);
    await screen.findByText("No analysis.");
    await confirmAction("Request analysis", "Create a new analysis version");

    await banner("status", "Created analysis v1");
    await banner("status", "Analysis versions re-read from the server.");
    expect(screen.getByRole("button", { name: "Request analysis…" })).toBeEnabled();
  });

  it("extraction: a 503 answer clears pending and is followed by a successful re-read", async () => {
    const handlers = recordHandlers(2, [analysis(21, 2, 1)]);
    handlers["POST /api/entries/2/extractions"] = () => ({ status: 503, body: { error: "knowledge extraction is not enabled" } });
    routeFetch(handlers);
    renderStrict(<RecordDetail entryId={2} onBack={() => {}} />);
    await screen.findByText("No extraction stored.");
    await confirmAction("Request extraction", "Send to the extraction provider");

    await banner("alert", "Extraction is not enabled on this server (503)");
    await banner("status", "Stored extractions re-read from the server.");
    expect(screen.getByRole("button", { name: "Request extraction…" })).toBeEnabled();
  });

  it("feedback: a stored decision clears pending, the draft, and shows both re-reads", async () => {
    const a = analysis(31, 3, 1);
    const handlers = recordHandlers(3, [a]);
    handlers["POST /api/analyses/31/feedback"] = () => ({
      status: 201,
      body: { id: 5, analysis_id: 31, status: "accepted", user_note: "", created_at: "t" },
    });
    routeFetch(handlers);
    renderStrict(<RecordDetail entryId={3} onBack={() => {}} />);
    await screen.findByText("No feedback yet.");
    decide("Accept");
    fireEvent.click(feedbackSubmit());

    await banner("status", "Recorded feedback #5 (accepted) for analysis v1.");
    await banner("status", "Feedback history re-read from the server.");
    await banner("status", "Effective interpretation re-read from the server.");
    expect(feedbackSubmit()).toHaveTextContent("Choose a decision to record");
  });

  it("capture: a new import is reported and the button returns", async () => {
    routeFetch({
      "POST /api/captures": { status: 201, body: { capture_id: "strict-1", entry_id: 4, analysis_id: null, created: true } },
    });
    renderStrict(<CaptureImport onImported={() => {}} onOpenRecord={() => {}} />);
    fireEvent.change(screen.getByLabelText("Capture JSON"), { target: { value: '{"capture_id":"strict-1"}' } });
    fireEvent.click(screen.getByRole("button", { name: "Import capture" }));
    await banner("status", "Imported capture strict-1 as new record #4");
    expect(screen.getByRole("button", { name: "Import capture" })).toBeEnabled();
  });
});

describe("StrictMode: uncertain writes and duplicates", () => {
  it("analysis and extraction: unknown outcomes are reported once, never resubmitted", async () => {
    const handlers = recordHandlers(5, [analysis(51, 5, 1)]);
    handlers["POST /api/entries/5/analysis"] = "network-error";
    handlers["POST /api/entries/5/extractions"] = "network-error";
    const calls = routeFetch(handlers);
    renderStrict(<RecordDetail entryId={5} onBack={() => {}} />);
    await screen.findByText("No extraction stored.");

    await confirmAction("Request analysis", "Create a new analysis version");
    await banner("alert", /Outcome unknown\. No response was received, so a new analysis/);
    await banner("status", "Analysis versions re-read from the server.");
    await confirmAction("Request extraction", "Send to the extraction provider");
    await banner("alert", /Outcome unknown\. No response was received, so a new extraction/);
    await banner("status", "Stored extractions re-read from the server.");

    expect(count(calls, "POST", "/api/entries/5/analysis")).toBe(1);
    expect(count(calls, "POST", "/api/entries/5/extractions")).toBe(1);
  });

  it("feedback: an unknown outcome keeps the draft and unblocks only after the history re-read", async () => {
    const handlers = recordHandlers(6, [analysis(61, 6, 1)]);
    handlers["POST /api/analyses/61/feedback"] = "network-error";
    const calls = routeFetch(handlers);
    renderStrict(<RecordDetail entryId={6} onBack={() => {}} />);
    await screen.findByText("No feedback yet.");
    decide("Correct");
    fireEvent.change(screen.getByLabelText("Corrected explanation"), { target: { value: "strict draft" } });
    fireEvent.click(feedbackSubmit());

    await banner("alert", "Outcome unknown.");
    await banner("status", "Feedback history re-read from the server.");
    expect(screen.getByLabelText("Corrected explanation")).toHaveValue("strict draft");
    expect(feedbackSubmit()).toBeEnabled();
    expect(count(calls, "POST", "/api/analyses/61/feedback")).toBe(1);
  });

  it("capture: an unknown import outcome is not resubmitted", async () => {
    const calls = routeFetch({ "POST /api/captures": "network-error" });
    renderStrict(<CaptureImport onImported={() => {}} onOpenRecord={() => {}} />);
    fireEvent.change(screen.getByLabelText("Capture JSON"), { target: { value: '{"capture_id":"strict-2"}' } });
    fireEvent.click(screen.getByRole("button", { name: "Import capture" }));
    await banner("alert", "Outcome unknown.");
    expect(screen.getByRole("button", { name: "Check import status" })).toBeEnabled();
    expect(count(calls, "POST", "/api/captures")).toBe(1);
  });

  it("pending requests cannot be duplicated for analysis, extraction, feedback, or capture", async () => {
    const pAnalysis = deferred();
    const pExtraction = deferred();
    const pFeedback = deferred();
    const pCapture = deferred();
    const handlers = recordHandlers(7, [analysis(71, 7, 1)]);
    handlers["POST /api/entries/7/analysis"] = () => pAnalysis.promise;
    handlers["POST /api/entries/7/extractions"] = () => pExtraction.promise;
    handlers["POST /api/analyses/71/feedback"] = () => pFeedback.promise;
    handlers["POST /api/captures"] = () => pCapture.promise;
    const calls = routeFetch(handlers);
    renderStrict(
      <>
        <RecordDetail entryId={7} onBack={() => {}} />
        <CaptureImport onImported={() => {}} onOpenRecord={() => {}} />
      </>,
    );
    await screen.findByText("No feedback yet.");

    await confirmAction("Request analysis", "Create a new analysis version");
    await confirmAction("Request extraction", "Send to the extraction provider");
    decide("Accept");
    fireEvent.click(feedbackSubmit());
    fireEvent.click(feedbackSubmit());
    fireEvent.change(screen.getByLabelText("Capture JSON"), { target: { value: '{"capture_id":"strict-3"}' } });
    fireEvent.click(screen.getByRole("button", { name: "Import capture" }));
    fireEvent.click(screen.getByRole("button", { name: "Importing…" }));

    expect(screen.getByRole("button", { name: "Request analysis — waiting for the server…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Request extraction — waiting for the server…" })).toBeDisabled();
    expect(within(feedbackPanel()).getByRole("button", { name: "Recording feedback…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Importing…" })).toBeDisabled();

    await act(async () => {
      pAnalysis.resolve({ status: 502, body: { error: "analysis provider unavailable" } });
      pExtraction.resolve({ status: 503, body: { error: "knowledge extraction is not enabled" } });
      pFeedback.resolve({ status: 201, body: { id: 8, analysis_id: 71, status: "accepted", user_note: "", created_at: "t" } });
      pCapture.resolve({ status: 200, body: { capture_id: "strict-3", entry_id: 7, analysis_id: null, created: false } });
    });
    await banner("alert", "No analysis was stored (502)");
    await banner("alert", "Extraction is not enabled on this server (503)");
    await banner("status", "Recorded feedback #8");
    await banner("status", "Already imported");
    for (const url of ["/api/entries/7/analysis", "/api/entries/7/extractions", "/api/analyses/71/feedback", "/api/captures"]) {
      expect(count(calls, "POST", url), url).toBe(1);
    }
  });
});

describe("StrictMode: unmount, record switches, and version switches", () => {
  it("an old analysis callback does not re-read or mark the newly shown record", async () => {
    const slow = deferred();
    const handlers = { ...recordHandlers(8, [analysis(81, 8, 1)]), ...recordHandlers(9, [analysis(91, 9, 1)]) };
    handlers["POST /api/entries/8/analysis"] = () => slow.promise;
    const calls = routeFetch(handlers);
    const onRecordChanged = vi.fn();
    const { rerenderStrict } = renderStrict(<RecordDetail entryId={8} onBack={() => {}} onRecordChanged={onRecordChanged} />);
    await screen.findByRole("button", { name: "v1 (latest)" });
    await confirmAction("Request analysis", "Create a new analysis version");

    rerenderStrict(<RecordDetail entryId={9} onBack={() => {}} onRecordChanged={onRecordChanged} />);
    await screen.findByText("Pourquoi 9 ?");
    await waitFor(() => expect(screen.getByRole("button", { name: "Request analysis…" })).toBeEnabled());
    const readsOf9 = count(calls, "GET", "/api/entries/9/analyses");

    await act(async () => {
      slow.resolve({ status: 201, body: analysis(82, 8, 2) });
    });
    // The list still learns that record 8 changed...
    expect(onRecordChanged).toHaveBeenCalledWith(8);
    expect(onRecordChanged).not.toHaveBeenCalledWith(9);
    // ...but record 9 is not re-read, marked as refreshing, or given 8's outcome.
    expect(count(calls, "GET", "/api/entries/9/analyses")).toBe(readsOf9);
    expect(screen.queryByText(/Re-reading analysis versions|Analysis versions re-read|Created analysis/)).not.toBeInTheDocument();
  });

  it("an old feedback callback does not mark the newly shown record", async () => {
    const slow = deferred();
    const handlers = { ...recordHandlers(10, [analysis(101, 10, 1)]), ...recordHandlers(11, [analysis(111, 11, 1)]) };
    handlers["POST /api/analyses/101/feedback"] = () => slow.promise;
    const calls = routeFetch(handlers);
    const onRecordChanged = vi.fn();
    const { rerenderStrict } = renderStrict(<RecordDetail entryId={10} onBack={() => {}} onRecordChanged={onRecordChanged} />);
    await screen.findByText("No feedback yet.");
    decide("Accept");
    fireEvent.click(feedbackSubmit());

    rerenderStrict(<RecordDetail entryId={11} onBack={() => {}} onRecordChanged={onRecordChanged} />);
    await screen.findByText("Pourquoi 11 ?");
    await screen.findByText("No feedback yet.");
    const effectiveReads = count(calls, "GET", "/api/analyses/111/effective");

    await act(async () => {
      slow.resolve({ status: 201, body: { id: 9, analysis_id: 101, status: "accepted", user_note: "", created_at: "t" } });
    });
    expect(onRecordChanged).toHaveBeenCalledWith(10);
    expect(onRecordChanged).not.toHaveBeenCalledWith(11);
    expect(count(calls, "GET", "/api/analyses/111/effective")).toBe(effectiveReads);
    expect(screen.queryByText(/Recorded feedback|re-read from the server/)).not.toBeInTheDocument();
    expect(feedbackSubmit()).toHaveTextContent("Choose a decision to record");
  });

  it("an extraction result after leaving the record never appears on the next one", async () => {
    const slow = deferred();
    const handlers = { ...recordHandlers(12, [analysis(121, 12, 1)]), ...recordHandlers(13, []) };
    handlers["POST /api/entries/12/extractions"] = () => slow.promise;
    routeFetch(handlers);
    const { rerenderStrict } = renderStrict(<RecordDetail entryId={12} onBack={() => {}} />);
    await screen.findByText("No extraction stored.");
    await confirmAction("Request extraction", "Send to the extraction provider");
    rerenderStrict(<RecordDetail entryId={13} onBack={() => {}} />);
    await screen.findByText("Pourquoi 13 ?");

    await act(async () => {
      slow.resolve({ status: 201, body: { id: 3, entry_id: 12, version: 1, source_analysis_id: 121, source_feedback_id: null, extractor: "x", created_at: "t", units: [] } });
    });
    expect(screen.queryByText(/Stored extraction v1|re-read from the server/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Request extraction…" })).toBeEnabled();
  });

  it("a real unmount during a request discards its UI update but still refreshes the list row", async () => {
    const slow = deferred();
    const handlers = recordHandlers(1, [analysis(11, 1, 1)]);
    handlers["POST /api/entries/1/analysis"] = () => slow.promise;
    handlers[`GET /api/learning-records?limit=${RECORDS_PAGE_SIZE}`] = {
      body: {
        records: [{ entry_id: 1, original_input: "Pourquoi 1 ?", original_context: "", entry_created_at: "t", state: "unreviewed", analysis_id: 11, analysis_version: 1, analyzer: "a", confidence: 0.5, uncertainty: "", analysis_created_at: "t", original: null, effective: { category: "grammar", explanation: "e" }, feedback_id: null }],
        next_before_entry_id: null,
      },
    };
    handlers["GET /api/learning-records?limit=1&before_entry_id=2"] = {
      body: { records: [{ entry_id: 1, original_input: "Pourquoi 1 ?", original_context: "", entry_created_at: "t", state: "unreviewed", analysis_id: 12, analysis_version: 2, analyzer: "a", confidence: 0.5, uncertainty: "", analysis_created_at: "t", original: null, effective: { category: "grammar", explanation: "e" }, feedback_id: null }], next_before_entry_id: 1 },
    };
    const calls = routeFetch(handlers);
    renderStrict(<RecordsBrowser />);
    fireEvent.click(await screen.findByRole("button", { name: /^Open record #1$/ }));
    await confirmAction("Request analysis", "Create a new analysis version");
    fireEvent.click(screen.getByRole("button", { name: "← Back to records" }));

    await act(async () => {
      slow.resolve({ status: 201, body: analysis(12, 1, 2) });
    });
    await waitFor(() => expect(screen.getByRole("list", { name: "Learning records" })).toHaveTextContent("latest analysis v2"));
    expect(count(calls, "GET", "/api/learning-records?limit=1&before_entry_id=2")).toBe(1);

    // Reopening starts from backend state, not the old instance's pending flag.
    fireEvent.click(screen.getByRole("button", { name: /^Open record #1$/ }));
    expect(await screen.findByRole("button", { name: "Request analysis…" })).toBeEnabled();
    expect(screen.queryByText(/Created analysis/)).not.toBeInTheDocument();
  });

  it("feedback drafts stay per version and a late result lands on its own version", async () => {
    const slow = deferred();
    const v1 = analysis(141, 14, 1);
    const v2 = analysis(142, 14, 2);
    const handlers = recordHandlers(14, [v1, v2]);
    handlers["POST /api/analyses/142/feedback"] = () => slow.promise;
    const calls = routeFetch(handlers);
    renderStrict(<RecordDetail entryId={14} onBack={() => {}} />);
    await screen.findByText("No feedback yet.");

    fireEvent.click(screen.getByRole("button", { name: "v1" }));
    await screen.findByRole("heading", { name: /Feedback for analysis v1/ });
    decide("Correct");
    fireEvent.change(screen.getByLabelText("Corrected explanation"), { target: { value: "v1 draft" } });

    fireEvent.click(screen.getByRole("button", { name: "v2 (latest)" }));
    await screen.findByRole("heading", { name: /Feedback for analysis v2/ });
    decide("Accept");
    fireEvent.click(feedbackSubmit());
    fireEvent.click(screen.getByRole("button", { name: "v1" }));
    await screen.findByRole("heading", { name: /Feedback for analysis v1/ });
    expect(screen.getByLabelText("Corrected explanation")).toHaveValue("v1 draft");

    await act(async () => {
      slow.resolve({ status: 201, body: { id: 15, analysis_id: 142, status: "accepted", user_note: "", created_at: "t" } });
    });
    expect(screen.queryByText(/Recorded feedback/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Corrected explanation")).toHaveValue("v1 draft");

    fireEvent.click(screen.getByRole("button", { name: "v2 (latest)" }));
    await banner("status", "Recorded feedback #15 (accepted) for analysis v2.");
    expect(feedbackSubmit()).toHaveTextContent("Choose a decision to record");
    expect(count(calls, "POST", "/api/analyses/142/feedback")).toBe(1);
    expect(count(calls, "POST", "/api/analyses/141/feedback")).toBe(0);
  });
});
