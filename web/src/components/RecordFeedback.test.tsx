import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RecordDetail } from "./RecordDetail";

afterEach(cleanup);

type Reply = { status?: number; body: unknown } | "network-error";
type Handler = Reply | ((body: unknown) => Reply | Promise<Reply>);

// routeFetch answers "METHOD /api/path" with a reply, a function of the parsed
// request body (possibly deferred), or a network error (no HTTP response).
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

const posts = <T extends { method: string; url: string }>(calls: T[], url: string) =>
  calls.filter((c) => c.method === "POST" && c.url === url);

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

type StoredFeedback = {
  id: number;
  analysis_id: number;
  status: string;
  corrected_category?: string;
  corrected_explanation?: string;
  user_note: string;
  created_at: string;
};

const feedback = (id: number, analysisId: number, status: string, extra: Partial<StoredFeedback> = {}): StoredFeedback => ({
  id,
  analysis_id: analysisId,
  status,
  user_note: "",
  created_at: "2026-10-02T00:00:00Z",
  ...extra,
});

// A record whose analyses each start with no feedback, plus one stored extraction.
function recordHandlers(entryId: number, analyses: Array<ReturnType<typeof analysis>>): Record<string, Handler> {
  const handlers: Record<string, Handler> = {
    [`GET /api/entries/${entryId}`]: { body: { id: entryId, original_input: `Pourquoi ${entryId} ?`, original_context: "c", created_at: "t", updated_at: "t" } },
    [`GET /api/entries/${entryId}/analyses`]: { body: { analyses } },
    [`GET /api/entries/${entryId}/extractions`]: {
      body: {
        extractions: [{ id: 70, entry_id: entryId, version: 1, source_analysis_id: analyses[0]?.id ?? 0, source_feedback_id: null, extractor: "openai:test:knowledge_extraction_v1", created_at: "t", units: [] }],
      },
    },
    [`GET /api/entries/${entryId}/current-extraction`]: { body: { entry_id: entryId, current_extraction_id: 70 } },
  };
  for (const a of analyses) {
    handlers[`GET /api/analyses/${a.id}/effective`] = { body: effective(a) };
    handlers[`GET /api/analyses/${a.id}/feedback`] = { body: { feedback: [] } };
  }
  return handlers;
}

// stateful records POSTed feedback per analysis and answers history and effective
// reads from it, like the backend: the latest feedback decides the effective view.
function withStoredFeedback(handlers: Record<string, Handler>, a: ReturnType<typeof analysis>) {
  const stored: StoredFeedback[] = [];
  handlers[`POST /api/analyses/${a.id}/feedback`] = (body) => {
    const req = body as Record<string, string>;
    const fb = feedback(100 + stored.length, a.id, req.status, {
      ...(req.corrected_category ? { corrected_category: req.corrected_category } : {}),
      ...(req.corrected_explanation ? { corrected_explanation: req.corrected_explanation } : {}),
      user_note: req.user_note ?? "",
    });
    stored.push(fb);
    return { status: 201, body: fb };
  };
  handlers[`GET /api/analyses/${a.id}/feedback`] = () => ({ body: { feedback: stored } });
  handlers[`GET /api/analyses/${a.id}/effective`] = () => {
    const last = stored[stored.length - 1];
    if (!last) return { body: effective(a) };
    const eff =
      last.status === "rejected"
        ? null
        : last.status === "corrected"
          ? { category: last.corrected_category ?? a.category, explanation: last.corrected_explanation ?? a.explanation }
          : { category: a.category, explanation: a.explanation };
    return { body: effective(a, { resolution: last.status, feedback_id: last.id, effective: eff }) };
  };
  return stored;
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

const feedbackPanel = () => screen.getByRole("region", { name: "Feedback" });
const decide = (label: string) => fireEvent.click(within(feedbackPanel()).getByRole("radio", { name: new RegExp(`^${label}`) }));
const submitButton = () => within(feedbackPanel()).getByRole("button", { name: /Record "|Recording feedback|Choose a decision/ });

describe("Record feedback decisions", () => {
  it("accepts the latest analysis, then re-reads history, effective interpretation, and the row", async () => {
    const v1 = analysis(11, 1, 1);
    const handlers = recordHandlers(1, [v1]);
    withStoredFeedback(handlers, v1);
    const calls = routeFetch(handlers);
    const onRecordChanged = vi.fn();
    render(<RecordDetail entryId={1} onBack={() => {}} onRecordChanged={onRecordChanged} />);

    expect(await screen.findByText("No feedback yet.")).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();
    decide("Accept");
    fireEvent.click(submitButton());

    await banner("status", "Recorded feedback #100 (accepted) for analysis v1. This is the latest analysis");
    await banner("status", "Feedback history re-read from the server.");
    await banner("status", "Effective interpretation re-read from the server.");
    expect(posts(calls, "/api/analyses/11/feedback")[0].body).toEqual({ status: "accepted" });
    const history = await screen.findByRole("list", { name: "Feedback history (oldest first)" });
    expect(history).toHaveTextContent("accepted feedback #100 in effect");
    expect(screen.getByLabelText("Effective interpretation")).toHaveTextContent("accepted");
    expect(onRecordChanged).toHaveBeenCalledWith(1);
  });

  it("sends only the corrected fields the reviewer supplied", async () => {
    const v1 = analysis(21, 2, 1);
    const handlers = recordHandlers(2, [v1]);
    withStoredFeedback(handlers, v1);
    const calls = routeFetch(handlers);
    render(<RecordDetail entryId={2} onBack={() => {}} />);
    await screen.findByText("No feedback yet.");

    decide("Correct");
    expect(screen.getByLabelText("Corrected category")).toHaveDisplayValue("Keep the original (grammar)");
    fireEvent.change(screen.getByLabelText("Corrected explanation"), { target: { value: "Une meilleure explication." } });
    fireEvent.change(screen.getByLabelText("Note (optional)"), { target: { value: "checked in a grammar book" } });
    fireEvent.click(submitButton());

    await banner("status", "Recorded feedback #100 (corrected)");
    expect(posts(calls, "/api/analyses/21/feedback")[0].body).toEqual({
      status: "corrected",
      corrected_explanation: "Une meilleure explication.",
      user_note: "checked in a grammar book",
    });
    const eff = await screen.findByLabelText("Effective interpretation");
    await waitFor(() => expect(eff).toHaveTextContent("Une meilleure explication."));
    expect(eff).toHaveTextContent("Original explanation");
    // A stored decision clears its draft.
    expect(within(feedbackPanel()).getByRole("radio", { name: /^Correct/ })).not.toBeChecked();
  });

  it("rejects an analysis and shows the backend's rejected interpretation", async () => {
    const v1 = analysis(31, 3, 1);
    const handlers = recordHandlers(3, [v1]);
    withStoredFeedback(handlers, v1);
    const calls = routeFetch(handlers);
    render(<RecordDetail entryId={3} onBack={() => {}} />);
    await screen.findByText("No feedback yet.");

    decide("Reject");
    fireEvent.click(submitButton());
    await banner("status", "Recorded feedback #100 (rejected)");
    expect(posts(calls, "/api/analyses/31/feedback")[0].body).toEqual({ status: "rejected" });
    expect(await screen.findByText("Rejected interpretation.")).toBeInTheDocument();
    await waitFor(() => expect(within(feedbackPanel()).getByText(/currently rejected/)).toBeInTheDocument());
  });

  it("keeps the draft and shows the backend message when feedback is invalid", async () => {
    const v1 = analysis(41, 4, 1);
    const handlers = recordHandlers(4, [v1]);
    handlers["POST /api/analyses/41/feedback"] = () => ({
      status: 422,
      body: { error: "validation error\ncorrected_category must be one of the fr_l2_taxonomy_v1 taxonomy values" },
    });
    const calls = routeFetch(handlers);
    const onRecordChanged = vi.fn();
    render(<RecordDetail entryId={4} onBack={() => {}} onRecordChanged={onRecordChanged} />);
    await screen.findByText("No feedback yet.");

    decide("Correct");
    fireEvent.change(screen.getByLabelText("Corrected category"), { target: { value: "pragmatics" } });
    fireEvent.click(submitButton());

    const alert = await banner("alert", "No feedback was stored for analysis v1 (422)");
    expect(alert).toHaveTextContent("corrected_category must be one of the fr_l2_taxonomy_v1 taxonomy values. Your draft is kept.");
    expect(screen.getByLabelText("Corrected category")).toHaveValue("pragmatics");
    expect(screen.queryByText(/re-read from the server/)).not.toBeInTheDocument();
    expect(onRecordChanged).not.toHaveBeenCalled();
    expect(posts(calls, "/api/analyses/41/feedback")).toHaveLength(1);
  });

  it("sends one request when submit is pressed repeatedly", async () => {
    const pending = deferred();
    const v1 = analysis(51, 5, 1);
    const handlers = recordHandlers(5, [v1]);
    handlers["POST /api/analyses/51/feedback"] = () => pending.promise;
    const calls = routeFetch(handlers);
    render(<RecordDetail entryId={5} onBack={() => {}} />);
    await screen.findByText("No feedback yet.");
    decide("Accept");
    const button = submitButton();
    fireEvent.click(button);
    fireEvent.click(button);
    expect(within(feedbackPanel()).getByRole("button", { name: "Recording feedback…" })).toBeDisabled();
    await act(async () => {
      pending.resolve({ status: 201, body: feedback(1, 51, "accepted") });
    });
    expect(posts(calls, "/api/analyses/51/feedback")).toHaveLength(1);
  });
});

describe("Historical analysis targets", () => {
  it("records feedback on the selected historical version and says extraction uses the latest", async () => {
    const v1 = analysis(61, 6, 1);
    const v2 = analysis(62, 6, 2);
    const handlers = recordHandlers(6, [v1, v2]);
    withStoredFeedback(handlers, v1);
    const calls = routeFetch(handlers);
    render(<RecordDetail entryId={6} onBack={() => {}} />);

    expect(await screen.findByRole("heading", { name: /Feedback for analysis v2 \(latest version\)/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "v1" }));
    expect(await screen.findByRole("heading", { name: /Feedback for analysis v1 \(historical version; latest is v2\)/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Analysis v1 \(historical version; latest is v2\)/ })).toBeInTheDocument();
    expect(feedbackPanel()).toHaveTextContent("The record's state and any new extraction use the latest analysis, not this historical version.");
    expect(screen.getByLabelText("Knowledge extraction")).toHaveTextContent(
      "A new extraction uses the record's latest analysis (v2) and its latest feedback as the server resolves them when you request it, not the version selected above.",
    );

    await screen.findByText("No feedback yet.");
    decide("Reject");
    fireEvent.click(submitButton());
    await banner("status", "Recorded feedback #100 (rejected) for analysis v1. This is a historical version: the record's state and any new extraction still use the latest analysis v2.");
    expect(posts(calls, "/api/analyses/61/feedback")).toHaveLength(1);
    expect(posts(calls, "/api/analyses/62/feedback")).toHaveLength(0);
    // The selection stays on the historical version that was judged.
    expect(screen.getByRole("button", { name: "v1" })).toHaveAttribute("aria-pressed", "true");
  });

  it("keeps stored extractions visible as evidence and never requests one after feedback", async () => {
    const v1 = analysis(71, 7, 1);
    const handlers = recordHandlers(7, [v1]);
    withStoredFeedback(handlers, v1);
    const calls = routeFetch(handlers);
    render(<RecordDetail entryId={7} onBack={() => {}} />);
    expect(await screen.findByLabelText("Viewed extraction")).toHaveTextContent("Viewing extraction v1 (current, latest stored)");
    await screen.findByText("No feedback yet.");

    decide("Reject");
    fireEvent.click(submitButton());
    await banner("status", "Effective interpretation re-read from the server.");
    expect(screen.getByLabelText("Viewed extraction")).toHaveTextContent("Viewing extraction v1 (current, latest stored)");
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/extractions"))).toBe(false);
    expect(screen.getByLabelText("Knowledge extraction")).toHaveTextContent("feedback never changes or regenerates them");
  });
});

describe("Draft isolation", () => {
  it("keeps each version's draft separate and restores it on return", async () => {
    const v1 = analysis(81, 8, 1);
    const v2 = analysis(82, 8, 2);
    routeFetch(recordHandlers(8, [v1, v2]));
    render(<RecordDetail entryId={8} onBack={() => {}} />);
    await screen.findByText("No feedback yet.");

    decide("Correct");
    fireEvent.change(screen.getByLabelText("Corrected explanation"), { target: { value: "draft for v2" } });
    fireEvent.click(screen.getByRole("button", { name: "v1" }));
    await screen.findByRole("heading", { name: /Feedback for analysis v1/ });
    expect(within(feedbackPanel()).getByRole("radio", { name: /^Correct/ })).not.toBeChecked();
    expect(screen.queryByLabelText("Corrected explanation")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "v2 (latest)" }));
    await screen.findByRole("heading", { name: /Feedback for analysis v2/ });
    expect(screen.getByLabelText("Corrected explanation")).toHaveValue("draft for v2");
  });

  it("keeps a draft through a same-record read refresh", async () => {
    const v1 = analysis(91, 9, 1);
    const handlers = recordHandlers(9, [v1]);
    handlers["POST /api/entries/9/analysis"] = "network-error";
    const calls = routeFetch(handlers);
    render(<RecordDetail entryId={9} onBack={() => {}} />);
    await screen.findByText("No feedback yet.");
    decide("Correct");
    fireEvent.change(screen.getByLabelText("Corrected explanation"), { target: { value: "unsent draft" } });

    // An unknown analysis outcome re-reads the record's analyses.
    fireEvent.click(screen.getByRole("button", { name: "Request analysis…" }));
    fireEvent.click(within(screen.getByRole("group", { name: "Request analysis" })).getByRole("button", { name: "Create a new analysis version" }));
    await banner("status", "Analysis versions re-read from the server.");
    expect(calls.filter((c) => c.url === "/api/entries/9/analyses")).toHaveLength(2);
    expect(screen.getByLabelText("Corrected explanation")).toHaveValue("unsent draft");
  });

  it("starts a different record with no draft", async () => {
    const a = analysis(101, 10, 1);
    const b = analysis(111, 11, 1);
    routeFetch({ ...recordHandlers(10, [a]), ...recordHandlers(11, [b]) });
    const { rerender } = render(<RecordDetail entryId={10} onBack={() => {}} />);
    await screen.findByText("No feedback yet.");
    decide("Correct");
    fireEvent.change(screen.getByLabelText("Corrected explanation"), { target: { value: "draft for record 10" } });

    rerender(<RecordDetail entryId={11} onBack={() => {}} />);
    await screen.findByText("Pourquoi 11 ?");
    await screen.findByRole("heading", { name: /Feedback for analysis v1/ });
    expect(within(feedbackPanel()).getByRole("radio", { name: /^Correct/ })).not.toBeChecked();
    expect(screen.queryByDisplayValue("draft for record 10")).not.toBeInTheDocument();
  });
});

describe("Out-of-order and uncertain feedback", () => {
  it("attaches a late result to the version it was sent for and blocks a duplicate there", async () => {
    const pending = deferred();
    const v1 = analysis(121, 12, 1);
    const v2 = analysis(122, 12, 2);
    const handlers = recordHandlers(12, [v1, v2]);
    handlers["POST /api/analyses/122/feedback"] = () => pending.promise;
    const calls = routeFetch(handlers);
    render(<RecordDetail entryId={12} onBack={() => {}} />);
    await screen.findByText("No feedback yet.");
    decide("Accept");
    fireEvent.click(submitButton());

    fireEvent.click(screen.getByRole("button", { name: "v1" }));
    await screen.findByRole("heading", { name: /Feedback for analysis v1/ });
    await act(async () => {
      pending.resolve({ status: 201, body: feedback(5, 122, "accepted") });
    });
    expect(screen.queryByText(/Recorded feedback/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "v2 (latest)" }));
    await banner("status", "Recorded feedback #5 (accepted) for analysis v2.");
    expect(posts(calls, "/api/analyses/122/feedback")).toHaveLength(1);
    expect(posts(calls, "/api/analyses/121/feedback")).toHaveLength(0);
  });

  it("keeps a version's request pending across a version switch, so it cannot be resent", async () => {
    const pending = deferred();
    const v1 = analysis(131, 13, 1);
    const v2 = analysis(132, 13, 2);
    const handlers = recordHandlers(13, [v1, v2]);
    handlers["POST /api/analyses/132/feedback"] = () => pending.promise;
    const calls = routeFetch(handlers);
    render(<RecordDetail entryId={13} onBack={() => {}} />);
    await screen.findByText("No feedback yet.");
    decide("Accept");
    fireEvent.click(submitButton());
    fireEvent.click(screen.getByRole("button", { name: "v1" }));
    await screen.findByRole("heading", { name: /Feedback for analysis v1/ });
    fireEvent.click(screen.getByRole("button", { name: "v2 (latest)" }));
    await screen.findByRole("heading", { name: /Feedback for analysis v2/ });

    expect(within(feedbackPanel()).getByRole("button", { name: "Recording feedback…" })).toBeDisabled();
    fireEvent.click(within(feedbackPanel()).getByRole("button", { name: "Recording feedback…" }));
    await act(async () => {
      pending.resolve({ status: 201, body: feedback(6, 132, "accepted") });
    });
    expect(posts(calls, "/api/analyses/132/feedback")).toHaveLength(1);
  });

  it("does not show a late history read for a version the reader has left", async () => {
    const slowHistory = deferred();
    const v1 = analysis(141, 14, 1);
    const v2 = analysis(142, 14, 2);
    const handlers = recordHandlers(14, [v1, v2]);
    handlers["GET /api/analyses/141/feedback"] = () => slowHistory.promise;
    routeFetch(handlers);
    render(<RecordDetail entryId={14} onBack={() => {}} />);
    await screen.findByText("No feedback yet.");
    fireEvent.click(screen.getByRole("button", { name: "v1" }));
    await screen.findByText("Loading feedback history…");
    fireEvent.click(screen.getByRole("button", { name: "v2 (latest)" }));
    await screen.findByText("No feedback yet.");

    await act(async () => {
      slowHistory.resolve({ body: { feedback: [feedback(9, 141, "rejected")] } });
    });
    expect(screen.queryByText("feedback #9")).not.toBeInTheDocument();
    expect(screen.getByText("No feedback yet.")).toBeInTheDocument();
  });

  it("reports an unknown outcome, keeps the draft, and blocks resubmission until history is re-read", async () => {
    let historyReads = 0;
    const v1 = analysis(151, 15, 1);
    const handlers = recordHandlers(15, [v1]);
    handlers["POST /api/analyses/151/feedback"] = "network-error";
    handlers["GET /api/analyses/151/feedback"] = () => {
      historyReads += 1;
      return historyReads === 2 ? { status: 500, body: { error: "could not list feedback" } } : { body: { feedback: [] } };
    };
    const calls = routeFetch(handlers);
    const onRecordChanged = vi.fn();
    render(<RecordDetail entryId={15} onBack={() => {}} onRecordChanged={onRecordChanged} />);
    await screen.findByText("No feedback yet.");
    decide("Correct");
    fireEvent.change(screen.getByLabelText("Corrected explanation"), { target: { value: "maybe sent" } });
    fireEvent.click(submitButton());

    const alert = await banner("alert", "Outcome unknown.");
    expect(alert).toHaveTextContent("feedback for analysis v1 may or may not have been recorded");
    expect(alert).not.toHaveTextContent(/failed|re-read/i);
    await banner("alert", "Could not re-read feedback history from the server ((500) could not list feedback)");
    expect(screen.getByLabelText("Corrected explanation")).toHaveValue("maybe sent");
    expect(submitButton()).toBeDisabled();
    expect(within(feedbackPanel()).getByText(/Unavailable until this version's feedback history has been re-read/)).toBeInTheDocument();
    expect(onRecordChanged).toHaveBeenCalledWith(15);

    fireEvent.click(screen.getByRole("button", { name: "Reload feedback history" }));
    await banner("status", "Feedback history re-read from the server.");
    expect(submitButton()).toBeEnabled();
    expect(posts(calls, "/api/analyses/151/feedback")).toHaveLength(1);
  });

  it("separates a stored decision from a failed effective re-read, then recovers on Retry", async () => {
    let effectiveReads = 0;
    const v1 = analysis(161, 16, 1);
    const handlers = recordHandlers(16, [v1]);
    const stored = withStoredFeedback(handlers, v1);
    const answerEffective = handlers["GET /api/analyses/161/effective"] as () => Reply;
    handlers["GET /api/analyses/161/effective"] = () => {
      effectiveReads += 1;
      return effectiveReads === 2 ? { status: 500, body: { error: "could not resolve effective analysis" } } : answerEffective();
    };
    routeFetch(handlers);
    render(<RecordDetail entryId={16} onBack={() => {}} />);
    await screen.findByText("No feedback yet.");
    decide("Accept");
    fireEvent.click(submitButton());

    await banner("status", "Recorded feedback #100 (accepted)");
    await banner("alert", "Could not re-read effective interpretation from the server");
    expect(screen.queryByText("Effective interpretation re-read from the server.")).not.toBeInTheDocument();
    expect(stored).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await banner("status", "Effective interpretation re-read from the server.");
    expect(screen.getByLabelText("Effective interpretation")).toHaveTextContent("accepted");
  });
});

describe("Request shape and same-version ordering", () => {
  it("drops corrected fields left in the draft when the decision changes to Accept", async () => {
    const v1 = analysis(171, 17, 1);
    const handlers = recordHandlers(17, [v1]);
    withStoredFeedback(handlers, v1);
    const calls = routeFetch(handlers);
    render(<RecordDetail entryId={17} onBack={() => {}} />);
    await screen.findByText("No feedback yet.");
    decide("Correct");
    fireEvent.change(screen.getByLabelText("Corrected category"), { target: { value: "vocabulary" } });
    fireEvent.change(screen.getByLabelText("Corrected explanation"), { target: { value: "abandoned correction" } });
    decide("Accept");
    fireEvent.click(submitButton());
    await banner("status", "Recorded feedback #100 (accepted)");
    expect(posts(calls, "/api/analyses/171/feedback")[0].body).toEqual({ status: "accepted" });
  });

  it("does not let a slow earlier history read overwrite the read after feedback", async () => {
    const slowFirst = deferred();
    const v1 = analysis(181, 18, 1);
    const handlers = recordHandlers(18, [v1]);
    const stored = withStoredFeedback(handlers, v1);
    const answerHistory = handlers["GET /api/analyses/181/feedback"] as () => Reply;
    let reads = 0;
    handlers["GET /api/analyses/181/feedback"] = () => {
      reads += 1;
      return reads === 1 ? slowFirst.promise : answerHistory();
    };
    routeFetch(handlers);
    render(<RecordDetail entryId={18} onBack={() => {}} />);
    await screen.findByText("Loading feedback history…");
    decide("Accept");
    fireEvent.click(submitButton());
    await banner("status", "Feedback history re-read from the server.");
    const history = () => screen.getByRole("list", { name: "Feedback history (oldest first)" });
    expect(history()).toHaveTextContent("feedback #100");

    await act(async () => {
      slowFirst.resolve({ body: { feedback: [] } });
    });
    expect(stored).toHaveLength(1);
    expect(history()).toHaveTextContent("feedback #100");
    expect(screen.queryByText("No feedback yet.")).not.toBeInTheDocument();
  });
});
