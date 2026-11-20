// Portable learning history panel against a fake of the export preview and
// the import preview: texts off by default, omitted told from absent, audio
// never offered, the two files named with how each opens, and a file check
// that reports integrity and conflicts and writes nothing.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "../i18n";
import type { HistoryExportPreview, HistoryImportPreview } from "../types/history";
import { HistoryExport } from "./HistoryExport";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const preview = (transcripts: boolean, notes: boolean): HistoryExportPreview => ({
  header: {
    format: "learning_history_export_v1", exported_at: "t",
    included: { transcripts, notes, audio: false, credentials: false },
    never_exported: ["audio bytes (never stored)", "credentials and configuration (never read)"],
    parts: { speaking: true, writing: true, notebook: true, listening: true },
    counts: { listening_material: 1, speaking_take: 2, writing_draft: 1, notebook_record: 1 },
    omitted_texts: transcripts ? (notes ? {} : { text: 1, original_input: 1, original_context: 1 }) : notes ? { transcripts: 1 } : { transcripts: 1, text: 1, original_input: 1, original_context: 1 },
  },
  footer: { records: 5, sha256: "a".repeat(64) },
  bytes: 1234,
  files: [
    { format: "ndjson", extension: ".ndjson", opens_as_text: true, app_import: "preview_only", description: "d" },
    { format: "text", extension: ".txt", opens_as_text: true, app_import: "none", description: "d" },
  ],
});
const checked: HistoryImportPreview = {
  format: "learning_history_export_v1", integrity: "complete", problems: [], counts: { speaking_take: 2 }, missing_fields: [], included: { transcripts: true },
  rows: [
    { line: 2, kind: "speaking_take", key: "speaking:prompt:sp-invitation-reponse:take:1", status: "conflict", fields: ["transcripts"], resolution: "server text" },
    { line: 3, kind: "speaking_take", key: "speaking:prompt:sp-invitation-reponse:take:2", status: "same", fields: [], resolution: "server text" },
  ],
  new: 0, same: 1, conflicts: 1, writes: false,
};

function serve() {
  const calls: { method: string; url: string; body: string }[] = [];
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ method, url: url.pathname + url.search, body: String(init?.body ?? "") });
    const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    if (url.pathname === "/api/learning-history/export-preview")
      return json(200, preview(url.searchParams.get("transcripts") === "true", url.searchParams.get("notes") === "true"));
    if (url.pathname === "/api/learning-history/import-preview" && method === "POST") return json(200, checked);
    return json(404, { error: "not found" });
  }) as unknown as typeof fetch;
  return calls;
}

const renderPanel = () =>
  render(
    <LocaleProvider>
      <HistoryExport />
    </LocaleProvider>,
  );

describe("Portable learning history", () => {
  it("previews an export with texts off by default, tells omitted from absent, and names how each file opens", async () => {
    const calls = serve();
    renderPanel();
    expect(calls).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Export or check your learning history…" }));
    expect(screen.getByLabelText("Speaking transcripts")).not.toBeChecked();
    expect(screen.getByLabelText(/Notes and drafts/)).not.toBeChecked();
    expect(screen.queryByLabelText(/audio/i)).toBeNull();
    expect(screen.getByText("Never exported: audio (it is never stored) and credentials or settings (never read).")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Preview the export" }));
    const region = await screen.findByRole("group", { name: "Export preview" });
    expect(within(region).getByRole("status")).toHaveTextContent("5 records in learning_history_export_v1.");
    expect(region.querySelector('[data-kind="speaking_take"]')).toHaveTextContent("Speaking takes: 2");
    expect(region.querySelector('[data-text="transcripts"]')).toHaveTextContent("omitted: 1 record has this text, not selected");
    expect(region.querySelector('[data-text="notes"]')).toHaveTextContent("omitted: 3 records have this text, not selected");
    fireEvent.click(screen.getByLabelText("Speaking transcripts"));
    await waitFor(() => expect(screen.getByRole("group", { name: "Export preview" }).querySelector('[data-text="transcripts"]')).toHaveTextContent("included"));
    expect(calls.map((c) => c.url)).toEqual(["/api/learning-history/export-preview", "/api/learning-history/export-preview?transcripts=true"]);
    const files = within(screen.getByRole("group", { name: "Export preview" })).getByRole("list", { name: "Files" });
    const [nd, txt] = within(files).getAllByRole("listitem");
    expect(within(nd).getByRole("link", { name: "Download .ndjson" })).toHaveAttribute("href", "/api/learning-history/export?transcripts=true");
    expect(nd).toHaveTextContent("opens as text (one JSON record per line); the app's check below reads it. There is no import yet.");
    expect(within(txt).getByRole("link", { name: "Download .txt" })).toHaveAttribute("href", "/api/learning-history/export?transcripts=true&format=text");
    expect(txt).toHaveTextContent("for reading only, not importable");
  });

  it("checks a file without writing: integrity, counts and the resolution of each conflict", async () => {
    const calls = serve();
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Export or check your learning history…" }));
    const text = '{"kind":"header","format":"learning_history_export_v1"}\n';
    const file = new File([text], "day.ndjson", { type: "application/x-ndjson" });
    fireEvent.change(screen.getByLabelText("Export file"), { target: { files: [file] } });
    const result = await screen.findByRole("group", { name: "File check" });
    expect(result).toHaveAttribute("data-integrity", "complete");
    expect(within(result).getByRole("status")).toHaveTextContent("day.ndjson (learning_history_export_v1) is complete: its footer counts and checksum match.");
    expect(result).toHaveTextContent("New: 0 · already stored: 1 · conflicting: 1.");
    const conflict = result.querySelector('[data-status="conflict"]')!;
    expect(conflict).toHaveTextContent("speaking:prompt:sp-invitation-reponse:take:1 (transcripts) — keep the stored record (records are never overwritten); the file's version would be skipped.");
    expect(result).toHaveTextContent("Nothing was written.");
    const posts = calls.filter((c) => c.method === "POST");
    expect(posts).toEqual([{ method: "POST", url: "/api/learning-history/import-preview", body: text }]);
  });
});
