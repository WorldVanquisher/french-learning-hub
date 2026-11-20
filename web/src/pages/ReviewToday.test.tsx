// Review Today against a stateful fake of GET /review-today and the notebook's
// retry save: one item from each source with its reason, the right action for
// each, a completed action leaving the queue without a reload, history kept
// out of the queue but linked, and distinct "nothing yet" / "all done" views.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "../i18n";
import type { NotebookItem } from "../types/notebook";
import type { ReviewToday as ReviewTodayData } from "../types/reviewToday";
import type { SpeakingQueueItem } from "../types/speaking";
import { ReviewToday } from "./ReviewToday";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const notebookItem = (entry: number, marked: boolean): NotebookItem => ({
  entry_id: entry, capture_id: `listening-7-900-${entry}`, saved_at: "2026-11-18T09:00:00Z", skill: "listening",
  source: { type: "listening_item", record_id: 900, item: 2, attempt: "Parce qu'il est moins cher." },
  title: "Inscription au cours de français", prompt: "Pourquoi choisit-elle le cours du soir ?", category: "detail", quote: null,
  reference: "Parce qu'elle travaille la journée.", explanation_en: "e", explanation_zh: "z", hint_en: null, hint_zh: null,
  link: { listening_material_id: 7, listening_exercise_id: 900, listening_transcript_version: 1 },
  record: { original_input: "x", original_context: "y" }, retry: { marked, since: marked ? "2026-11-18T10:00:00Z" : null },
  source_status: "resolved", reference_origin: "authored", generator: "authored:flh_listening_script_pack_v1", latest_version: null,
});
const speakingStep: SpeakingQueueItem = {
  reason: "review_without_feedback", priority: 5, prompt_id: "sp-invitation-reponse", title: "Répondre à une invitation", exercise_id: 3,
  take_id: 31, take_number: 2, state: "awaiting_feedback", improvements: 0, since: "2026-11-18T08:00:00Z", request: "feedback",
  request_enabled: false, pack_status: "current",
};

function serve(state: { items: ReviewTodayData["items"]; history: ReviewTodayData["history"] }) {
  const calls: { method: string; path: string; body: string }[] = [];
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ method, path: url.pathname, body: String(init?.body ?? "") });
    const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    if (method === "GET" && url.pathname === "/api/review-today")
      return json(200, { schema_version: "review_today_v1", generated_at: "t", items: state.items, history: state.history, sources: { speaking: true, notebook: true } });
    const m = /^\/api\/mistake-notebook\/items\/(\d+)\/retry$/.exec(url.pathname);
    if (method === "PUT" && m) {
      state.items = state.items.filter((it) => it.notebook?.entry_id !== Number(m[1]));
      return json(200, { item: notebookItem(Number(m[1]), false), changed: true });
    }
    return json(404, { error: "not found" });
  }) as unknown as typeof fetch;
  return calls;
}

const renderPage = () => {
  const props = { onOpenSpeaking: vi.fn(), onOpenSource: vi.fn(), onShow: vi.fn() };
  render(
    <LocaleProvider>
      <ReviewToday {...props} />
    </LocaleProvider>,
  );
  return props;
};

describe("Review Today", () => {
  it("lists one item from each source with its reason and the action that opens it", async () => {
    serve({
      items: [
        { key: "speaking:exercise:3", source: "speaking", reason: "review_without_feedback", priority: 5, since: "2026-11-18T08:00:00Z", speaking: speakingStep, notebook: null },
        { key: "notebook:entry:41", source: "notebook", reason: "retry_marked", priority: 6, since: "2026-11-18T10:00:00Z", speaking: null, notebook: notebookItem(41, true) },
      ],
      history: { notebook_items: 2, speaking_exercises: 1, speaking_takes: 2 },
    });
    const props = renderPage();
    const queue = await screen.findByRole("list", { name: "Due now" });
    const rows = within(queue).getAllByRole("listitem");
    expect(rows.map((r) => [r.getAttribute("data-source"), r.getAttribute("data-reason")])).toEqual([
      ["speaking", "review_without_feedback"],
      ["notebook", "retry_marked"],
    ]);
    expect(rows[0]).toHaveTextContent("Take 2: your checked transcript has no feedback, and feedback is off.");
    expect(rows[1]).toHaveTextContent(/You marked this for retry on/);
    expect(rows[1]).toHaveTextContent("Pourquoi choisit-elle le cours du soir ?");
    fireEvent.click(within(rows[0]).getByRole("button", { name: "Resume take 2" }));
    expect(props.onOpenSpeaking).toHaveBeenCalledWith(3, 31);
    fireEvent.click(within(rows[1]).getByRole("button", { name: "Open the lesson" }));
    expect(props.onOpenSource).toHaveBeenCalledWith(expect.objectContaining({ skill: "listening", materialId: 7, exerciseId: 900, item: 2 }));
    // History is counted and linked, never queued.
    expect(screen.getByText(/History \(not listed here\): 2 saved mistakes, 2 Speaking takes\./)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Mistake Notebook" }));
    expect(props.onShow).toHaveBeenCalledWith("notebook");
  });

  it("removes a completed workbook item without a reload, keeps the record, and moves focus on", async () => {
    const calls = serve({
      items: [
        { key: "notebook:entry:41", source: "notebook", reason: "retry_marked", priority: 6, since: "2026-11-18T10:00:00Z", speaking: null, notebook: notebookItem(41, true) },
        { key: "notebook:entry:42", source: "notebook", reason: "retry_marked", priority: 6, since: "2026-11-18T11:00:00Z", speaking: null, notebook: notebookItem(42, true) },
      ],
      history: { notebook_items: 2, speaking_exercises: 0, speaking_takes: 0 },
    });
    renderPage();
    const queue = await screen.findByRole("list", { name: "Due now" });
    fireEvent.click(within(within(queue).getAllByRole("listitem")[0]).getByRole("button", { name: "Done for today" }));
    await waitFor(() => expect(within(queue).getAllByRole("listitem")).toHaveLength(1));
    expect(within(queue).getByRole("listitem")).toHaveAttribute("data-key", "notebook:entry:42");
    expect(calls.filter((c) => c.method === "PUT")).toEqual([{ method: "PUT", path: "/api/mistake-notebook/items/41/retry", body: '{"marked":false}' }]);
    await waitFor(() => expect(within(within(queue).getByRole("listitem")).getByRole("button", { name: "Open the lesson" })).toHaveFocus());
    expect(screen.getByText(/Removed from Review Today: Inscription au cours de français\. The record stays in the Mistake Notebook\./)).toBeInTheDocument();
  });

  it("tells 'nothing yet' from 'all done', each with its own next step", async () => {
    serve({ items: [], history: { notebook_items: 0, speaking_exercises: 0, speaking_takes: 0 } });
    let props = renderPage();
    expect(await screen.findByText(/Nothing to review yet/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start a Speaking prompt" }));
    expect(props.onShow).toHaveBeenCalledWith("speaking");
    fireEvent.click(screen.getByRole("button", { name: "Open the workbook lessons" }));
    expect(props.onShow).toHaveBeenCalledWith("listening");
    cleanup();
    serve({ items: [], history: { notebook_items: 3, speaking_exercises: 1, speaking_takes: 4 } });
    props = renderPage();
    expect(await screen.findByText(/All done for now/)).toBeInTheDocument();
    expect(screen.queryByText(/Nothing to review yet/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open the Mistake Notebook" }));
    expect(props.onShow).toHaveBeenCalledWith("notebook");
  });
});
