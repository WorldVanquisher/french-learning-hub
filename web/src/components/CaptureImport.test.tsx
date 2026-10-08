import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CaptureImport } from "./CaptureImport";

afterEach(cleanup);

type Reply = { status?: number; body: unknown } | "network-error";
type Handler = Reply | (() => Reply | Promise<Reply>);

// routeFetch answers "METHOD /api/path" with a reply, a deferred reply, or a
// network error (a rejected fetch, i.e. no HTTP response). Calls are recorded.
function routeFetch(handlers: Record<string, Handler>) {
  const calls: Array<{ method: string; url: string; body?: string }> = [];
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = String(input);
    calls.push({ method, url, body: init?.body as string | undefined });
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

// A synthetic capture with unusual spacing and key order: it must reach the
// server byte-for-byte, exactly like the capture CLI sends a file.
const CAPTURE = `{ "capture_id": "flh-014-test",  "schema_version": "learning_capture_v1",
  "source": "manual", "original_input": "vouloir", "original_context": "test",
  "discussion_summary": "synthetic" }`;

function renderImport() {
  const onImported = vi.fn();
  const onOpenRecord = vi.fn();
  render(<CaptureImport onImported={onImported} onOpenRecord={onOpenRecord} />);
  return { onImported, onOpenRecord };
}

function paste(text: string) {
  fireEvent.change(screen.getByLabelText("Capture JSON"), { target: { value: text } });
}

const importButton = () => screen.getByRole("button", { name: /Import capture|Importing/ });
const posts = <T extends { method: string }>(calls: T[]) => calls.filter((c) => c.method === "POST");

describe("CaptureImport", () => {
  it("rejects invalid JSON locally without sending anything", async () => {
    const calls = routeFetch({});
    renderImport();
    paste('{"capture_id": "x",');
    fireEvent.click(importButton());
    expect(await screen.findByRole("alert")).toHaveTextContent("This is not valid JSON, so nothing was sent");
    expect(calls).toHaveLength(0);
  });

  it("sends the document unchanged and reports a new record with an Open action", async () => {
    const calls = routeFetch({
      "POST /api/captures": { status: 201, body: { capture_id: "flh-014-test", entry_id: 12, analysis_id: null, created: true } },
    });
    const { onImported, onOpenRecord } = renderImport();
    paste(CAPTURE);
    fireEvent.click(importButton());

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("Imported capture flh-014-test as new record #12 without an analysis.");
    expect(posts(calls)).toHaveLength(1);
    expect(posts(calls)[0].body).toBe(CAPTURE);
    expect(onImported).toHaveBeenCalledWith(12);
    fireEvent.click(screen.getByRole("button", { name: "Open imported record #12" }));
    expect(onOpenRecord).toHaveBeenCalledWith(12);
  });

  it("reports an idempotent replay as the existing record without claiming a new import", async () => {
    routeFetch({
      "POST /api/captures": { status: 200, body: { capture_id: "flh-014-test", entry_id: 12, analysis_id: 3, created: false } },
    });
    const { onImported } = renderImport();
    paste(CAPTURE);
    fireEvent.click(importButton());
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Already imported: capture flh-014-test with identical content is record #12. Nothing new was stored.",
    );
    expect(onImported).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Open imported record #12" })).toBeInTheDocument();
  });

  it("explains a conflicting replay and links the existing record from its receipt", async () => {
    const calls = routeFetch({
      "POST /api/captures": () => ({ status: 409, body: { error: "capture_id already exists with different content" } }),
      "GET /api/captures/flh-014-test": {
        body: { capture_id: "flh-014-test", schema_version: "learning_capture_v1", source: "manual", entry_id: 7, analysis_id: null, discussion_summary: "", created_at: "t" },
      },
    });
    const { onImported, onOpenRecord } = renderImport();
    paste(CAPTURE);
    fireEvent.click(importButton());

    const open = await screen.findByRole("button", { name: "Open existing record #7" });
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Conflict (409): capture_id already exists with different content. Nothing was changed.");
    expect(alert).toHaveTextContent("A new learning interaction needs a new capture_id");
    expect(onImported).not.toHaveBeenCalled();
    expect(posts(calls)).toHaveLength(1);
    fireEvent.click(open);
    expect(onOpenRecord).toHaveBeenCalledWith(7);
  });

  it("shows the backend validation message for a rejected capture", async () => {
    routeFetch({
      "POST /api/captures": () => ({ status: 422, body: { error: "validation error\noriginal_input must not be empty" } }),
    });
    renderImport();
    paste(CAPTURE);
    fireEvent.click(importButton());
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The server rejected this capture, so nothing was stored (422)");
    expect(alert).toHaveTextContent("original_input must not be empty");
  });

  it("sends one request for rapid repeated clicks", async () => {
    const pending = deferred();
    const calls = routeFetch({ "POST /api/captures": () => pending.promise });
    renderImport();
    paste(CAPTURE);
    const button = importButton();
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(button);
    expect(screen.getByRole("button", { name: "Importing…" })).toBeDisabled();
    await act(async () => {
      pending.resolve({ status: 201, body: { capture_id: "flh-014-test", entry_id: 12, analysis_id: null, created: true } });
    });
    expect(posts(calls)).toHaveLength(1);
  });

  it("marks a network failure as unknown, never resubmits, and checks the receipt on request", async () => {
    let receiptCalls = 0;
    const calls = routeFetch({
      "POST /api/captures": "network-error",
      "GET /api/captures/flh-014-test": () => {
        receiptCalls += 1;
        return { body: { capture_id: "flh-014-test", schema_version: "learning_capture_v1", source: "manual", entry_id: 12, analysis_id: null, discussion_summary: "", created_at: "t" } };
      },
    });
    const { onImported } = renderImport();
    paste(CAPTURE);
    fireEvent.click(importButton());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Outcome unknown. No response was received, so the capture may or may not have been stored.");
    expect(alert).not.toHaveTextContent(/failed/i);
    expect(posts(calls)).toHaveLength(1);
    expect(receiptCalls).toBe(0);

    fireEvent.click(screen.getByRole("button", { name: "Check import status" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Stored: capture flh-014-test is record #12.");
    expect(posts(calls)).toHaveLength(1);
    expect(onImported).toHaveBeenCalledWith(12);
  });

  it("reports a checked capture that was not stored", async () => {
    routeFetch({
      "POST /api/captures": "network-error",
      "GET /api/captures/flh-014-test": () => ({ status: 404, body: { error: "capture not found" } }),
    });
    renderImport();
    paste(CAPTURE);
    fireEvent.click(importButton());
    fireEvent.click(await screen.findByRole("button", { name: "Check import status" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Not stored: no capture flh-014-test exists on the server. You can import it again.");
    expect(screen.queryByRole("button", { name: "Check import status" })).not.toBeInTheDocument();
  });

  it("ignores a status check that finishes after a newer import started", async () => {
    const slowReceipt = deferred();
    let attempt = 0;
    routeFetch({
      "POST /api/captures": () => {
        attempt += 1;
        return attempt === 1
          ? "network-error"
          : { status: 200, body: { capture_id: "flh-014-test", entry_id: 12, analysis_id: null, created: false } };
      },
      "GET /api/captures/flh-014-test": () => slowReceipt.promise,
    });
    renderImport();
    paste(CAPTURE);
    fireEvent.click(importButton());
    fireEvent.click(await screen.findByRole("button", { name: "Check import status" }));
    // The reader explicitly imports again (safe: identical content) before the check returns.
    fireEvent.click(importButton());
    expect(await screen.findByRole("status")).toHaveTextContent("Already imported");

    await act(async () => {
      slowReceipt.resolve({ status: 404, body: { error: "capture not found" } });
    });
    expect(screen.queryByText(/Not stored/)).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Already imported");
  });

  it("loads a JSON file into the editor without sending it", async () => {
    const calls = routeFetch({});
    renderImport();
    const file = new File([CAPTURE], "capture.json", { type: "application/json" });
    fireEvent.change(screen.getByLabelText("Load from file"), { target: { files: [file] } });
    await waitFor(() => expect(screen.getByLabelText("Capture JSON")).toHaveValue(CAPTURE));
    expect(calls).toHaveLength(0);
  });
});
