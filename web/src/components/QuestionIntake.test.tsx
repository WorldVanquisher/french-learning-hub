import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QuestionIntake, newCaptureId, questionCapture } from "./QuestionIntake";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

type Reply = { status?: number; body: unknown } | "network-error";
type Handler = Reply | (() => Reply | Promise<Reply>);

// The backend for one test: POST /api/captures answers from a queue (one reply per
// request, in order); GET receipts answer from handlers. Every request is recorded.
function backend(posts: Handler[], gets: Record<string, Handler> = {}) {
  const calls: Array<{ method: string; url: string; body?: string }> = [];
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = String(input);
    calls.push({ method, url, body: init?.body as string | undefined });
    const handler =
      method === "POST" && url === "/api/captures" ? posts.shift() : method === "GET" ? gets[url] : undefined;
    const reply: Reply =
      handler === undefined ? { status: 404, body: { error: "not found" } } : typeof handler === "function" ? await handler() : handler;
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

const created = (entry: number, captureId = "x") => ({ status: 201, body: { capture_id: captureId, entry_id: entry, analysis_id: null, created: true } });
const replayed = (entry: number) => ({ status: 200, body: { capture_id: "x", entry_id: entry, analysis_id: null, created: false } });

function renderIntake() {
  const onSaved = vi.fn();
  const onOpenRecord = vi.fn();
  render(<QuestionIntake onSaved={onSaved} onOpenRecord={onOpenRecord} />);
  return { onSaved, onOpenRecord };
}
const question = () => screen.getByLabelText("Your question");
const context = () => screen.getByLabelText("Where it came from (optional)");
const type = (el: HTMLElement, value: string) => fireEvent.change(el, { target: { value } });
const posts = (calls: Array<{ method: string; url: string; body?: string }>) => calls.filter((c) => c.method === "POST");
const sent = (call: { body?: string }) => JSON.parse(call.body ?? "{}");

describe("QuestionIntake payload", () => {
  it("builds a manual learning_capture_v1 with the text exactly as typed and no analysis", () => {
    const id = newCaptureId();
    expect(id).toMatch(/^question-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(newCaptureId()).not.toBe(id);
    const body = JSON.parse(questionCapture(id, { question: "  Pourquoi\n\t« il faut que » ?  ", context: "" }));
    expect(body).toEqual({
      schema_version: "learning_capture_v1",
      capture_id: id,
      source: "manual",
      original_input: "  Pourquoi\n\t« il faut que » ?  ",
      original_context: "",
    });
  });
});

describe("QuestionIntake question mode", () => {
  it("is the default mode and saves question and context as written, as an unanalyzed record", async () => {
    const calls = backend([created(7)]);
    const { onSaved, onOpenRecord } = renderIntake();
    expect(screen.getByRole("button", { name: "Question" })).toHaveAttribute("aria-pressed", "true");
    type(question(), "Pourquoi « il faut que je fasse »\net pas « fais » ?");
    type(context(), "Cours du mardi,  exercice 3");
    fireEvent.click(screen.getByRole("button", { name: "Save question" }));

    expect(await screen.findByText(/Saved as new record #7, not yet analyzed\./)).toBeInTheDocument();
    expect(onSaved).toHaveBeenCalledWith(7);
    const body = sent(posts(calls)[0]);
    expect(body.original_input).toBe("Pourquoi « il faut que je fasse »\net pas « fais » ?");
    expect(body.original_context).toBe("Cours du mardi,  exercice 3");
    expect(body.source).toBe("manual");
    expect("analysis" in body || "discussion_summary" in body).toBe(false);
    // Only the capture request: no analysis, extraction or provider endpoint.
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual(["POST /api/captures"]);

    fireEvent.click(screen.getByRole("button", { name: "Open saved record #7" }));
    expect(onOpenRecord).toHaveBeenCalledWith(7);
    // A confirmed save starts a fresh, empty question.
    expect(question()).toHaveValue("");
    expect(context()).toHaveValue("");
  });

  it("requires a non-blank question and sends nothing otherwise", () => {
    const calls = backend([]);
    renderIntake();
    const save = screen.getByRole("button", { name: "Save question" });
    expect(save).toBeDisabled();
    type(question(), "   \n\t ");
    expect(save).toBeDisabled();
    type(context(), "only context");
    expect(save).toBeDisabled();
    fireEvent.click(save);
    expect(calls).toHaveLength(0);
  });

  it("sends one request for repeated clicks while a save is pending", async () => {
    const slow = deferred();
    const calls = backend([() => slow.promise]);
    renderIntake();
    type(question(), "Une question");
    const save = screen.getByRole("button", { name: "Save question" });
    fireEvent.click(save);
    fireEvent.click(save);
    fireEvent.click(screen.getByRole("button", { name: "Saving…" }));
    expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();
    await act(async () => slow.resolve(created(3)));
    expect(await screen.findByText(/Saved as new record #3/)).toBeInTheDocument();
    expect(posts(calls)).toHaveLength(1);
  });

  it("keeps the text after a validation rejection, and a corrected save uses a new identity", async () => {
    const calls = backend([{ status: 400, body: { error: "original_input exceeds maximum length" } }, created(5)]);
    renderIntake();
    type(question(), "trop long");
    fireEvent.click(screen.getByRole("button", { name: "Save question" }));
    expect(await screen.findByText(/rejected this question, so nothing was stored/)).toHaveTextContent("original_input exceeds maximum length");
    expect(question()).toHaveValue("trop long");

    type(question(), "plus court");
    fireEvent.click(screen.getByRole("button", { name: "Save question" }));
    await screen.findByText(/Saved as new record #5/);
    const [first, second] = posts(calls).map(sent);
    expect(second.capture_id).not.toBe(first.capture_id);
    expect(second.original_input).toBe("plus court");
  });

  it("treats a lost response as unknown, keeps the text, and resends the identical attempt only on request", async () => {
    const calls = backend(["network-error", replayed(7)]);
    const { onSaved } = renderIntake();
    type(question(), "Question perdue ?");
    fireEvent.click(screen.getByRole("button", { name: "Save question" }));

    expect(await screen.findByText(/may or may not have been saved/)).toBeInTheDocument();
    expect(screen.queryByText(/nothing was stored/)).not.toBeInTheDocument();
    expect(question()).toHaveValue("Question perdue ?");
    expect(posts(calls)).toHaveLength(1); // no automatic retry
    expect(onSaved).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Send the same question again" }));
    expect(await screen.findByText(/already saved as record #7; nothing new was stored/)).toBeInTheDocument();
    const [first, second] = posts(calls);
    expect(second.body).toBe(first.body); // same capture_id, byte-identical content
    expect(onSaved).toHaveBeenCalledWith(7);
  });

  it("reports a 5xx as unknown and resolves it with a read-only receipt check", async () => {
    let captureId = "";
    const calls = backend([{ status: 503, body: { error: "database is locked" } }], {});
    renderIntake();
    type(question(), "Vérifier ?");
    fireEvent.click(screen.getByRole("button", { name: "Save question" }));
    expect(await screen.findByText(/may or may not have been saved/)).toHaveTextContent("(503) database is locked");
    captureId = sent(posts(calls)[0]).capture_id;

    // First check fails: still unknown. Second check finds the stored receipt.
    let checks = 0;
    globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      calls.push({ method: (init?.method ?? "GET").toUpperCase(), url: String(input) });
      checks += 1;
      if (checks === 1) throw new TypeError("Failed to fetch");
      return new Response(JSON.stringify({ capture_id: captureId, entry_id: 12, schema_version: "learning_capture_v1", source: "manual" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as unknown as typeof fetch;
    fireEvent.click(screen.getByRole("button", { name: "Check whether it was saved" }));
    expect(await screen.findByText(/still unknown/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check whether it was saved" }));
    expect(await screen.findByText(/It was saved: record #12\./)).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "GET").map((c) => c.url)).toEqual([
      `/api/captures/${captureId}`,
      `/api/captures/${captureId}`,
    ]);
    expect(posts(calls)).toHaveLength(1);
  });

  it("confirms 'not saved' through the receipt check and keeps the text for a normal save", async () => {
    const calls = backend(["network-error"]);
    renderIntake();
    type(question(), "Pas enregistrée");
    fireEvent.click(screen.getByRole("button", { name: "Save question" }));
    await screen.findByText(/may or may not have been saved/);
    fireEvent.click(screen.getByRole("button", { name: "Check whether it was saved" }));
    expect(await screen.findByText("It was not saved. Your text is kept and can be saved now.")).toBeInTheDocument();
    expect(question()).toHaveValue("Pas enregistrée");
    expect(screen.getByRole("button", { name: "Save question" })).toBeEnabled();
    expect(posts(calls)).toHaveLength(1);
  });

  it("never reuses an unconfirmed identity for edited text, and sends nothing until the reader decides", async () => {
    const calls = backend(["network-error", created(8)]);
    renderIntake();
    type(question(), "Version 1");
    fireEvent.click(screen.getByRole("button", { name: "Save question" }));
    await screen.findByText(/may or may not have been saved/);

    type(question(), "Version 2");
    expect(screen.getByRole("status")).toHaveTextContent("You changed the text while the earlier save is unconfirmed.");
    expect(screen.getByRole("button", { name: "Send the same question again" })).toBeDisabled();
    expect(posts(calls)).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Stop tracking the earlier attempt" }));
    expect(screen.getByText(/It may still have been saved/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save question" }));
    await screen.findByText(/Saved as new record #8/);
    const [first, second] = posts(calls).map(sent);
    expect(first.original_input).toBe("Version 1");
    expect(second.original_input).toBe("Version 2");
    expect(second.capture_id).not.toBe(first.capture_id);
  });

  it("reports a conflict without overwriting anything and keeps the text", async () => {
    backend([{ status: 409, body: { error: "capture_id already used with different content" } }]);
    renderIntake();
    type(question(), "Conflit");
    fireEvent.click(screen.getByRole("button", { name: "Save question" }));
    expect(await screen.findByText(/refused this save as a conflict, so nothing was stored or overwritten/)).toBeInTheDocument();
    expect(question()).toHaveValue("Conflit");
  });

  it("keeps both drafts when switching modes and sends nothing", () => {
    const calls = backend([]);
    renderIntake();
    type(question(), "Ma question");
    type(context(), "Mon contexte");
    fireEvent.click(screen.getByRole("button", { name: "Capture JSON" }));
    expect(screen.getByRole("button", { name: "Capture JSON" })).toHaveAttribute("aria-pressed", "true");
    type(screen.getByLabelText("Capture JSON"), '{"capture_id":"draft"}');
    fireEvent.click(screen.getByRole("button", { name: "Question" }));
    expect(question()).toHaveValue("Ma question");
    expect(context()).toHaveValue("Mon contexte");
    fireEvent.click(screen.getByRole("button", { name: "Capture JSON" }));
    expect(screen.getByLabelText("Capture JSON")).toHaveValue('{"capture_id":"draft"}');
    expect(calls).toHaveLength(0);
  });

  it("does not write the learner's text to browser storage", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    backend([created(4)]);
    renderIntake();
    type(question(), "Texte privé");
    type(context(), "Contexte privé");
    fireEvent.click(screen.getByRole("button", { name: "Save question" }));
    await screen.findByText(/Saved as new record #4/);
    expect(setItem).not.toHaveBeenCalled();
  });
});

describe("QuestionIntake capture mode", () => {
  it("keeps the existing JSON import, with its candidate analysis reported as imported", async () => {
    const calls = backend([{ status: 201, body: { capture_id: "c-1", entry_id: 9, analysis_id: 90, created: true } }]);
    const { onSaved } = renderIntake();
    fireEvent.click(screen.getByRole("button", { name: "Capture JSON" }));
    const raw = '{"schema_version":"learning_capture_v1","capture_id":"c-1","source":"chatgpt-web","original_input":"q","analysis":{"category":"grammar","explanation":"e","confidence":0.5}}';
    type(screen.getByLabelText("Capture JSON"), raw);
    fireEvent.click(screen.getByRole("button", { name: "Import capture" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(9));
    // The document is sent unchanged; the browser adds or changes nothing.
    expect(posts(calls)[0].body).toBe(raw);
  });
});
