// Review Today, R4 (Workbooks): a clear reason and action per supported item,
// stable order across reloads, one row per workbook question, coming back from
// a lesson to the same item, recoverable failed saves (also for a group), the
// next-review recommendation, and the same paths in Chinese. A stateful fake
// of GET /review-today and the notebook's retry save; synthetic data only.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "../i18n";
import type { NotebookItem } from "../types/notebook";
import type { ReviewTodayItem, ReviewSchedule } from "../types/reviewToday";
import type { SpeakingQueueItem, SpeakingQueueReason } from "../types/speaking";
import { ReviewToday } from "./ReviewToday";
import { resetReviewTodayMemory } from "./reviewTodayMemory";

beforeEach(() => resetReviewTodayMemory());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

const sched = (completed: [string, number], missed: [string, number], cls: ReviewSchedule["class"] = "review"): ReviewSchedule => ({
  class: cls,
  due_day: "2026-11-20",
  rule: "ladder n=1 +1d from 2026-11-18 (last attempt), overdue: due today",
  if_completed: { day: completed[0], interval_days: completed[1], rule: "ladder n=2 +3d from 2026-11-20 (last attempt)" },
  if_missed: { day: missed[0], interval_days: missed[1], rule: "missed: ladder n=1 +1d from 2026-11-20 (last attempt)" },
});

const nb = (entry: number, item = 2): NotebookItem => ({
  entry_id: entry, capture_id: `listening-7-900-${entry}`, saved_at: "2026-11-18T09:00:00Z", skill: "listening",
  source: { type: "listening_item", record_id: 900, item, attempt: null },
  title: "Inscription au cours de français", prompt: `Question ${item} : pourquoi choisit-elle le cours du soir ?`, category: "detail", quote: null,
  reference: "Parce qu'elle travaille la journée.", explanation_en: "e", explanation_zh: "z", hint_en: null, hint_zh: null,
  link: { listening_material_id: 7, listening_exercise_id: 900, listening_transcript_version: 2 },
  record: { original_input: "x", original_context: "y" }, retry: { marked: true, since: "2026-11-18T10:00:00Z" },
  source_status: "resolved", reference_origin: "authored", generator: "authored:flh_listening_script_pack_v1", latest_version: null,
});
const step = (reason: SpeakingQueueReason, ex: number, take: number | null = 1): SpeakingQueueItem => ({
  reason, priority: 0, prompt_id: `sp-${ex}`, title: `Exercice ${ex}`, exercise_id: ex, take_id: take ? ex * 10 + take : null, take_number: take ?? 0,
  state: "awaiting_feedback", improvements: 1, since: "2026-11-18T08:00:00Z", request: reason.includes("transcript") ? "transcription" : "feedback",
  request_enabled: false, pack_status: "current",
});
const notebookRow = (entry: number, also?: number[], item = 2): ReviewTodayItem => ({
  key: `notebook:entry:${entry}`, source: "notebook", reason: "retry_marked", priority: 6, since: "2026-11-18T10:00:00Z", since_day: "2026-11-18",
  speaking: null, notebook: nb(entry, item), also_entry_ids: also, schedule: sched(["2026-11-23", 3], ["2026-11-21", 1]),
});
const speakingRow = (reason: SpeakingQueueReason, ex: number): ReviewTodayItem => ({
  key: `speaking:exercise:${ex}`, source: "speaking", reason, priority: 1, since: "2026-11-18T08:00:00Z", since_day: "2026-11-18",
  speaking: step(reason, ex), notebook: null,
});

interface Fake {
  items: ReviewTodayItem[];
  fail?: (entry: number, n: number) => boolean; // fail the n-th PUT for this entry
}
// Like the backend: a row shows while any record it stands for is marked; it is
// led by the newest marked record, the others listed in also_entry_ids.
function serve(state: Fake) {
  const calls: string[] = [];
  const puts = new Map<number, number>();
  const unmarked = new Set<number>();
  const visible = () =>
    state.items.flatMap((it) => {
      if (!it.notebook) return [it];
      const marked = [it.notebook.entry_id, ...(it.also_entry_ids ?? [])].filter((id) => !unmarked.has(id)).sort((a, b) => b - a);
      if (!marked.length) return [];
      const [lead, ...also] = marked;
      return [{ ...it, key: `notebook:entry:${lead}`, notebook: { ...it.notebook, entry_id: lead }, also_entry_ids: also.length ? also : undefined }];
    });
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push(`${method} ${url.pathname}`);
    const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    if (method === "GET" && url.pathname === "/api/review-today")
      return json(200, { schema_version: "review_today_v1", generated_at: "t", today: "2026-11-20", items: visible(),
        history: { notebook_items: 9, speaking_exercises: 2, speaking_takes: 3 }, sources: { speaking: true, notebook: true } });
    const m = /^\/api\/mistake-notebook\/items\/(\d+)\/retry$/.exec(url.pathname);
    if (method === "PUT" && m) {
      const id = Number(m[1]);
      const n = (puts.get(id) ?? 0) + 1;
      puts.set(id, n);
      if (state.fail?.(id, n)) return json(500, { error: "could not record the retry decision" });
      const changed = !unmarked.has(id);
      unmarked.add(id);
      return json(200, { item: nb(id), changed });
    }
    return json(404, { error: "not found" });
  }) as unknown as typeof fetch;
  return calls;
}

const renderPage = () => {
  const props = { onOpenSpeaking: vi.fn(), onOpenSource: vi.fn(), onShow: vi.fn() };
  const r = render(
    <LocaleProvider>
      <ReviewToday {...props} />
    </LocaleProvider>,
  );
  return { props, ...r };
};
const queue = () => screen.findByRole("list", { name: "Due now" });
const keysOf = (q: HTMLElement) => [...q.querySelectorAll(":scope > li")].map((r) => r.getAttribute("data-key"));

describe("Review Today (R4)", () => {
  it("gives every supported item a readable reason and its action, never a raw code (R4-WB-006)", async () => {
    const reasons: SpeakingQueueReason[] = ["check_unknown_outcome", "request_failed", "confirm_transcript", "add_transcript", "request_feedback",
      "review_without_feedback", "answer_again", "start_first_take", "request_in_progress"];
    serve({ items: [...reasons.map((r, i) => speakingRow(r, i + 1)), notebookRow(41)] });
    renderPage();
    const rows = within(await queue()).getAllByRole("listitem");
    expect(rows).toHaveLength(reasons.length + 1);
    for (const row of rows) {
      const reason = row.getAttribute("data-reason")!;
      const text = row.querySelector("p:nth-of-type(2)")!.textContent ?? "";
      expect([reason, text.length > 20, text.includes(reason)]).toEqual([reason, true, false]);
      expect(within(row).getAllByRole("button")[0].className).toContain("primary");
    }
  });

  it("keeps the backend's order across reloads, equal priorities included (R4-WB-007)", async () => {
    serve({ items: [notebookRow(41, undefined, 1), notebookRow(42, undefined, 2), notebookRow(43, undefined, 3)] });
    const first = renderPage();
    const a = keysOf(await queue());
    first.unmount();
    renderPage();
    expect(keysOf(await queue())).toEqual(a);
    expect(a).toEqual(["notebook:entry:41", "notebook:entry:42", "notebook:entry:43"]);
  });

  it("shows one row for a question saved from two revisions, and Done for today clears both records (R4-WB-008)", async () => {
    const calls = serve({ items: [notebookRow(52, [51]), notebookRow(60, undefined, 3)] });
    renderPage();
    const q = await queue();
    const row = within(q).getAllByRole("listitem")[0];
    expect(row).toHaveTextContent("You also saved this question once from another revision of the lesson. Done for today clears both.");
    expect(within(q).getAllByRole("button", { name: "Open the lesson" })).toHaveLength(2);
    fireEvent.click(within(row).getByRole("button", { name: "Done for today" }));
    await waitFor(() => expect(keysOf(q)).toEqual(["notebook:entry:60"]));
    expect(calls.filter((c) => c.startsWith("PUT"))).toEqual(["PUT /api/mistake-notebook/items/52/retry", "PUT /api/mistake-notebook/items/51/retry"]);
    await waitFor(() => expect(within(within(q).getByRole("listitem")).getByRole("button", { name: "Open the lesson" })).toHaveFocus());
  });

  it("comes back from a lesson to the same item, with hidden steps still hidden (R4-WB-005, R4-WB-009, R4-WB-061)", async () => {
    serve({ items: [speakingRow("review_without_feedback", 3), notebookRow(41), notebookRow(42, undefined, 3)] });
    const first = renderPage();
    const q = await queue();
    fireEvent.click(within(within(q).getAllByRole("listitem")[0]).getByRole("button", { name: "Hide for this visit" }));
    await waitFor(() => expect(keysOf(q)).toEqual(["notebook:entry:41", "notebook:entry:42"]));
    fireEvent.click(within(within(q).getAllByRole("listitem")[1]).getByRole("button", { name: "Open the lesson" }));
    expect(first.props.onOpenSource).toHaveBeenCalled();
    // the workbench shows the lesson: Review Today unmounts; Back remounts it
    first.unmount();
    renderPage();
    const back = await queue();
    expect(keysOf(back)).toEqual(["notebook:entry:41", "notebook:entry:42"]);
    expect(screen.getByText("1 item hidden for this visit (nothing deleted).")).toBeInTheDocument();
    await waitFor(() => expect(within(within(back).getAllByRole("listitem")[1]).getByRole("button", { name: "Open the lesson" })).toHaveFocus());
  });

  it("returns focus to the heading when the opened item left the queue meanwhile", async () => {
    const state: Fake = { items: [notebookRow(41)] };
    serve(state);
    const first = renderPage();
    fireEvent.click(within(await queue()).getByRole("button", { name: "Open the lesson" }));
    first.unmount();
    state.items = [];
    renderPage();
    await screen.findByText(/All done for now/);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Review Today" })).toHaveFocus());
  });

  it("never sends focus to a button that is still disabled (a browser would refuse it)", async () => {
    const focusedDisabled: string[] = [];
    const real = HTMLElement.prototype.focus;
    vi.spyOn(HTMLElement.prototype, "focus").mockImplementation(function (this: HTMLElement, opts?: FocusOptions) {
      if (this instanceof HTMLButtonElement && this.disabled) focusedDisabled.push(this.textContent ?? "");
      return real.call(this, opts);
    });
    serve({ items: [notebookRow(41), notebookRow(42, undefined, 3)], fail: (id, n) => id === 41 && n === 1 });
    renderPage();
    const q = await queue();
    fireEvent.click(within(q.querySelector(":scope > li") as HTMLElement).getByRole("button", { name: "Done for today" }));
    await screen.findByRole("alert");
    await waitFor(() => expect(within(q.querySelector(":scope > li") as HTMLElement).getByRole("button", { name: "Done for today" })).toHaveFocus());
    fireEvent.click(within(q.querySelector(":scope > li") as HTMLElement).getByRole("button", { name: "Done for today" }));
    await waitFor(() => expect(keysOf(q)).toEqual(["notebook:entry:42"]));
    await waitFor(() => expect(within(q).getByRole("button", { name: "Open the lesson" })).toHaveFocus());
    expect(focusedDisabled).toEqual([]);
  });

  it("keeps a failed save's row and focus, and the same button then succeeds (R4-WB-010, R4-WB-062)", async () => {
    const calls = serve({ items: [notebookRow(41), notebookRow(42, undefined, 3)], fail: (id, n) => id === 41 && n === 1 });
    renderPage();
    const q = await queue();
    const button = within(within(q).getAllByRole("listitem")[0]).getByRole("button", { name: "Done for today" });
    fireEvent.click(button);
    (document.querySelector("h2") as HTMLElement).focus(); // a browser drops focus from the disabled button
    expect(await screen.findByRole("alert")).toHaveTextContent("Not changed: could not record the retry decision");
    expect(keysOf(q)).toEqual(["notebook:entry:41", "notebook:entry:42"]);
    await waitFor(() => expect(within(within(q).getAllByRole("listitem")[0]).getByRole("button", { name: "Done for today" })).toHaveFocus());
    fireEvent.click(within(within(q).getAllByRole("listitem")[0]).getByRole("button", { name: "Done for today" }));
    await waitFor(() => expect(keysOf(q)).toEqual(["notebook:entry:42"]));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(calls.filter((c) => c.startsWith("PUT"))).toHaveLength(2);
    await waitFor(() => expect(within(q).getByRole("button", { name: "Open the lesson" })).toHaveFocus());
  });

  it("when part of a group fails, re-reads so the row tells the truth, keeps it and its focus", async () => {
    serve({ items: [notebookRow(52, [51])], fail: (id) => id === 51 });
    renderPage();
    const q = await queue();
    fireEvent.click(within(q).getByRole("button", { name: "Done for today" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Not changed: could not record the retry decision");
    // 52 was cleared, 51 is still marked: the row now stands for 51 alone
    await waitFor(() => expect(keysOf(q)).toEqual(["notebook:entry:51"]));
    expect(q.querySelector(":scope > li")).not.toHaveTextContent("You also saved this question");
    await waitFor(() => expect(within(q).getByRole("button", { name: "Done for today" })).toHaveFocus());
  });

  it("explains the next review now, after a completed attempt and after a missed one (R4-WB-011, R4-WB-014)", async () => {
    const stuck = { ...speakingRow("check_unknown_outcome", 4), schedule: { ...sched(["2026-11-27", 7], ["2026-11-20", 0], "recovery"), rule: "recovery: due today" } };
    serve({ items: [stuck, notebookRow(41)] });
    renderPage();
    const rows = within(await queue()).getAllByRole("listitem");
    const s = rows[1].querySelector('[data-schedule="review"]')!;
    expect(s.querySelector("summary")).toHaveTextContent("When to review it next");
    expect(s.querySelector('[data-if="completed"]')).toHaveTextContent("If you complete it today: next review on 2026-11-23 (in 3 days).");
    expect(s.querySelector('[data-if="missed"]')).toHaveTextContent("If you miss it today: next review on 2026-11-21 (in 1 day).");
    expect(s).toHaveTextContent("Rules: if completed, ladder n=2 +3d from 2026-11-20 (last attempt); if missed, missed: ladder n=1 +1d from 2026-11-20 (last attempt)");
    const r = rows[0].querySelector('[data-schedule="recovery"]')!;
    expect(r.querySelector("summary")).toHaveTextContent("Due until it is unstuck; then when to review it next");
    expect(r.querySelector('[data-if="missed"]')).toHaveTextContent("If it is still stuck after today's attempt, it stays due today.");
  });

  for (const [loc, failed, retry] of [
    ["en", "Could not load Review Today: ", "Retry"],
    ["zh-CN", "无法加载今日复习：", "重试"],
  ] as const) {
    it(`retries a failed load from its own button, then shows the queue (${loc}, R4-WB-002)`, async () => {
      if (loc === "zh-CN") window.localStorage.setItem("flh.ui-locale.v1", "zh-CN");
      const state: Fake = { items: [notebookRow(41)] };
      serve(state);
      const ok = globalThis.fetch;
      let first = true;
      globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
        if (first && String(input).includes("/api/review-today")) {
          first = false;
          return new Response(JSON.stringify({ error: "review today is not available on this server" }), { status: 503, headers: { "Content-Type": "application/json" } });
        }
        return ok(input, init);
      }) as unknown as typeof fetch;
      renderPage();
      const alert = await screen.findByRole("alert");
      expect(alert.textContent).toContain(failed);
      expect(alert.textContent).toContain("review today is not available on this server");
      fireEvent.click(within(alert).getByRole("button", { name: retry }));
      const q = await screen.findByRole("list");
      expect(keysOf(q)).toEqual(["notebook:entry:41"]);
    });
  }

  it("never shows a slow, stale response over newer data, and returns to the last item opened (R4-WB-059)", async () => {
    const state: Fake = { items: [notebookRow(41)] };
    serve(state);
    const ok = globalThis.fetch;
    let release: () => void = () => undefined;
    let first = true;
    globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      if (first && String(input).includes("/api/review-today")) {
        first = false;
        const stale = await ok(input, init); // the queue as it was: [41]
        await new Promise<void>((r) => (release = r));
        return stale;
      }
      return ok(input, init);
    }) as unknown as typeof fetch;
    const a = renderPage();
    a.unmount(); // the learner left before the slow read arrived
    state.items = [notebookRow(42, undefined, 3), notebookRow(43, undefined, 4)];
    const b = renderPage();
    const q = await queue();
    expect(keysOf(q)).toEqual(["notebook:entry:42", "notebook:entry:43"]);
    await act(async () => release());
    expect(keysOf(q)).toEqual(["notebook:entry:42", "notebook:entry:43"]);
    // two items opened in quick succession: the way back leads to the last one
    const opens = within(q).getAllByRole("button", { name: "Open the lesson" });
    fireEvent.click(opens[0]);
    fireEvent.click(opens[1]);
    expect(b.props.onOpenSource).toHaveBeenCalledTimes(2);
    b.unmount();
    renderPage();
    const back = await queue();
    await waitFor(() => expect(within(back.querySelector('li[data-key="notebook:entry:43"]') as HTMLElement).getByRole("button", { name: "Open the lesson" })).toHaveFocus());
  });

  it("renders the failure, empty and schedule paths in Chinese with every placeholder filled (R4-WB-002, R4-WB-017, R4-WB-063)", async () => {
    window.localStorage.setItem("flh.ui-locale.v1", "zh-CN");
    const state: Fake = { items: [notebookRow(52, [51])], fail: (id, n) => id === 52 && n === 1 };
    serve(state);
    const first = renderPage();
    const q = await screen.findByRole("list", { name: "现在待处理" });
    const row = within(q).getByRole("listitem");
    expect(row).toHaveTextContent("你还从这节课的其他修订版本中保存过 1 次这个问题。“今天完成了”会全部清除。");
    expect(row.querySelector('[data-if="completed"]')).toHaveTextContent("如果你今天完成：下次复习在 2026-11-23（3 天后）。");
    expect(row.textContent).toMatch(/你在 .+ 把它标记为重做。/);
    fireEvent.click(within(row).getAllByRole("button")[1]);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("could not record the retry decision");
    expect(alert.textContent).not.toMatch(/[{}]/);
    expect(document.body.textContent).not.toMatch(/\{[a-z]+\}/);
    first.unmount();
    state.items = [];
    renderPage();
    await waitFor(() => expect(document.querySelector('[data-empty="all-done"]')).not.toBeNull());
    expect(document.querySelector('[data-empty="all-done"]')!.textContent).not.toMatch(/[{}]|All done/);
    await act(async () => undefined);
  });
});
