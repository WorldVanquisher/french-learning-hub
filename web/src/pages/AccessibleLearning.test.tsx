// Accessible learning UI (Review Today batch 061–070) on the new private
// paths, in jsdom: a keyboard path through the queue, focus kept in place when
// an item leaves or a preview closes, an accessible name on every control,
// statuses that do not rely on colour, and Chinese copy with every
// placeholder filled. Layout at 320 px and the browser smoke are in the
// learning-day walkthrough (real Chromium).
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "../i18n";
import type { ListeningRevisionRow } from "../types/listening";
import type { ReviewToday as Today } from "../types/reviewToday";
import type { SpeakingQueueItem } from "../types/speaking";
import { NotebookPractice } from "./NotebookPractice";
import { accentItem } from "./practiceDraft.fixture";
import { ReviewToday } from "./ReviewToday";
import { RevisionStudio } from "./RevisionStudio";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

const step = (exercise: number, title: string): SpeakingQueueItem => ({
  reason: "review_without_feedback", priority: 5, prompt_id: `sp-${exercise}`, title, exercise_id: exercise, take_id: exercise * 10, take_number: 1,
  state: "awaiting_feedback", improvements: 0, since: "2026-11-18T08:00:00Z", request: "feedback", request_enabled: false, pack_status: "current",
});
const today = (): Today => ({
  schema_version: "review_today_v1", generated_at: "t", zone: "Asia/Shanghai", today: "2026-11-19",
  items: [
    { key: "speaking:exercise:3", source: "speaking", reason: "review_without_feedback", priority: 5, since: "2026-11-18T08:00:00Z", since_day: "2026-11-18", speaking: step(3, "Répondre à une invitation"), notebook: null },
    { key: "speaking:exercise:4", source: "speaking", reason: "review_without_feedback", priority: 5, since: "2026-11-18T09:00:00Z", since_day: "2026-11-18", speaking: step(4, "Demander des renseignements à la mairie de Saint-Étienne-du-Rouvray"), notebook: null },
    { key: "notebook:entry:2", source: "notebook", reason: "retry_marked", priority: 6, since: "2026-11-18T10:00:00Z", since_day: "2026-11-18", speaking: null, notebook: accentItem(2, { retry: { marked: true, since: "2026-11-18T10:00:00Z" } }) },
  ],
  history: { notebook_items: 1, speaking_exercises: 2, speaking_takes: 2 },
  sources: { speaking: true, notebook: true },
});
const week = {
  schema_version: "learning_week_v1", generated_at: "t", zone: "Asia/Shanghai", from: "2026-11-13", to: "2026-11-19",
  days: ["13", "14", "15", "16", "17", "18", "19"].map((d) => ({ day: `2026-11-${d}`, production: 1, reviewed: 0, own_corrections: 0, provider_feedback: 0 })),
  totals: { production: 7, reviewed: 0, own_corrections: 0, provider_feedback: 0, distinct_exercises: 2, active_days: 7, duplicates_ignored: 0 },
  sparse: true, min_for_shares: 20, production_share: null, corrections: [], sources: { speaking: true, writing: true, notebook: true },
};
const rev = (n: number, current: boolean): ListeningRevisionRow => ({
  revision: n, current, created_at: "2026-11-18T09:00:00Z", fingerprint: `sha256:${String(n).repeat(64)}`, transcript_id: n, lines: 2, exercise_id: 20 + n,
  generator: "authored:flh_listening_script_pack_v1", questions: 1, audio: "none", linked_records: [],
});
const ref = (n: number) => ({ revision: n, fingerprint: `sha256:${String(n).repeat(64)}`, exercise_id: 20 + n, created_at: "t" });
const blocks = [
  { kind: "same", before_line: "s1", after_line: "s1", before: { id: "s1", speaker: "A", text: "Bonjour." }, after: { id: "s1", speaker: "A", text: "Bonjour." }, speaker_changed: false, words: [] },
  { kind: "changed", before_line: "s2", after_line: "s2", before: { id: "s2", speaker: "B", text: "À 17 h." }, after: { id: "s2", speaker: "B", text: "À 18 h." }, speaker_changed: false,
    words: [{ op: "same", text: "À " }, { op: "removed", text: "17" }, { op: "inserted", text: "18" }, { op: "same", text: " h." }] },
];

function serve() {
  globalThis.fetch = vi.fn(async (input: string | URL | Request) => {
    const url = new URL(String(input), "http://localhost");
    const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    const p = url.pathname;
    if (p === "/api/review-today") return json(200, today());
    if (p === "/api/learning-week") return json(200, week);
    if (p === "/api/mistake-notebook/items") return json(200, { items: [accentItem(1), accentItem(2)], unlinked_notice: "n" });
    if (p === "/api/listening/materials/7/revisions")
      return json(200, { material_id: 7, title: "T", script_id: "s", current_revision: 2, pack_status: "up_to_date", pack_fingerprint: null, revisions: [rev(1, false), rev(2, true)] });
    if (p === "/api/listening/materials/7/revision-compare") return json(200, { material_id: 7, current_revision: 2, from: ref(1), to: ref(2), blocks, changes: { lines: [], questions: [], annotations_changed: false } });
    if (p === "/api/listening/materials/7/restore")
      return json(200, { material_id: 7, current_revision: 2, from: ref(2), to: ref(1), blocks, changes: { lines: [], questions: [], annotations_changed: false },
        target_revision: 1, target_fingerprint: ref(1).fingerprint, next_revision: 3, blocked: null, current_exercise_id: 22, records_on_current: [] });
    return json(404, { error: "not found" });
  }) as unknown as typeof fetch;
}

const page = (node: JSX.Element) => render(<LocaleProvider>{node}</LocaleProvider>);
const noop = { onOpenSpeaking: vi.fn(), onOpenSource: vi.fn(), onShow: vi.fn() };

// Every control a user can operate has a name a screen reader can say.
function expectNamedControls(root: HTMLElement) {
  const controls = [...root.querySelectorAll<HTMLElement>("button, select, textarea, input, a[href]")];
  expect(controls.length).toBeGreaterThan(0);
  for (const c of controls) expect(c).toHaveAccessibleName();
}

describe("Accessible learning UI", () => {
  it("moves between queue items with the arrow keys, Home and End", async () => {
    serve();
    page(<ReviewToday {...noop} />);
    const queue = await screen.findByRole("list", { name: "Due now" });
    expect(screen.getByText("Keys: ↑ and ↓ move between items; Home and End go to the first and last.")).toBeInTheDocument();
    const firsts = within(queue).getAllByRole("listitem").map((li) => li.querySelector("button")!);
    firsts[0].focus();
    fireEvent.keyDown(firsts[0], { key: "ArrowDown" });
    expect(firsts[1]).toHaveFocus();
    fireEvent.keyDown(firsts[1], { key: "End" });
    expect(firsts[2]).toHaveFocus();
    fireEvent.keyDown(firsts[2], { key: "ArrowDown" });
    expect(firsts[2]).toHaveFocus();
    fireEvent.keyDown(firsts[2], { key: "Home" });
    expect(firsts[0]).toHaveFocus();
    fireEvent.keyDown(firsts[0], { key: "ArrowUp" });
    expect(firsts[0]).toHaveFocus();
  });

  it("keeps focus in place when a queue item is hidden and when a restore preview closes", async () => {
    serve();
    page(<ReviewToday {...noop} />);
    const queue = await screen.findByRole("list", { name: "Due now" });
    fireEvent.click(within(within(queue).getAllByRole("listitem")[0]).getByRole("button", { name: "Hide for this visit" }));
    // The item that took its place gets focus (its first button).
    await waitFor(() => expect(within(within(queue).getAllByRole("listitem")[0]).getByRole("button", { name: "Resume take 1" })).toHaveFocus());
    expect(within(queue).getAllByRole("listitem")[0]).toHaveAttribute("data-key", "speaking:exercise:4");
    cleanup();
    serve();
    page(<RevisionStudio materialId={7} currentRevision={2} onRestored={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Revision history (current: revision 2)" }));
    const opener = await screen.findByRole("button", { name: "Preview restoring revision 1" });
    fireEvent.click(opener);
    await screen.findByRole("heading", { name: "Restore revision 1 over revision 2?" });
    fireEvent.click(screen.getByRole("button", { name: "Not now" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Preview restoring revision 1" })).toHaveFocus());
  });

  it("names every control on the queue, the practice drafts, and the revision comparison and restore preview", async () => {
    serve();
    const a = page(<ReviewToday {...noop} />);
    await screen.findByRole("table");
    expectNamedControls(a.container);
    cleanup();
    serve();
    const b = page(<NotebookPractice />);
    await screen.findByRole("heading", { name: "Make practice from your notes" });
    expectNamedControls(b.container);
    for (const cb of screen.getAllByRole("checkbox")) fireEvent.click(cb);
    fireEvent.click(screen.getByRole("button", { name: "Preview 2 drafts" }));
    await screen.findByRole("heading", { name: "2 practice drafts" });
    expectNamedControls(b.container);
    cleanup();
    serve();
    const c = page(<RevisionStudio materialId={7} currentRevision={2} onRestored={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Revision history (current: revision 2)" }));
    await screen.findByText("Revision 1 → revision 2.");
    fireEvent.click(screen.getByRole("button", { name: "Preview restoring revision 1" }));
    await screen.findByRole("heading", { name: "Restore revision 1 over revision 2?" });
    expectNamedControls(c.container);
    expect(screen.getByLabelText("Older")).toHaveAccessibleName("Older");
    expect(screen.getByLabelText("Newer")).toHaveAccessibleName("Newer");
  });

  it("never conveys a change or a status by colour alone", async () => {
    serve();
    const c = page(<RevisionStudio materialId={7} currentRevision={2} onRestored={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Revision history (current: revision 2)" }));
    await screen.findByText("Revision 1 → revision 2.");
    const changed = c.container.querySelector('.studio-compare [data-kind="changed"]')!;
    expect(changed.querySelector(".tag")).toHaveTextContent("Changed line s2 → s2");
    expect(changed.querySelector("del")).toHaveTextContent("removed: 17");
    expect(changed.querySelector("ins")).toHaveTextContent("inserted: 18");
    // Queue rows name their source in words beside any styling.
    cleanup();
    serve();
    const q = page(<ReviewToday {...noop} />);
    const queue = await screen.findByRole("list", { name: "Due now" });
    for (const li of within(queue).getAllByRole("listitem")) expect(li.querySelector(".tag")!.textContent!.trim().length).toBeGreaterThan(0);
    expect(q.container.querySelectorAll("[style*='color']").length).toBe(0);
  });

  it("renders the new paths in Chinese with every number and date placeholder filled", async () => {
    window.localStorage.setItem("flh.ui-locale.v1", "zh-CN");
    serve();
    const a = page(<ReviewToday {...noop} />);
    const region = await screen.findByRole("region", { name: "本周" });
    await within(region).findByRole("table");
    expect(region.querySelector("h3")!.textContent).toMatch(/^本周：.*11.*13.* 至 .*11.*19/);
    expect(within(region).getByText("本周：产出练习 7 次（涉及 2 个练习）· 已复习 0 项 · 你的修改 0 处 · 收到反馈 0 份 · 有活动的天数 7/7。")).toBeInTheDocument();
    expect(a.container.textContent).not.toMatch(/\{[a-z]+\}/);
    cleanup();
    window.localStorage.setItem("flh.ui-locale.v1", "zh-CN");
    serve();
    const b = page(<NotebookPractice />);
    await screen.findByRole("heading", { name: "从你的笔记制作练习" });
    for (const cb of screen.getAllByRole("checkbox")) fireEvent.click(cb);
    fireEvent.click(screen.getByRole("button", { name: "预览 2 份草稿" }));
    await screen.findByRole("heading", { name: "2 份练习草稿" });
    expect(b.container.textContent).not.toMatch(/\{[a-z]+\}/);
    // French learner content is never translated.
    expect(b.container.textContent).toContain("Pourquoi Hélène choisit-elle le cours du soir à l'école Saint-Éloi ?");
  });
});
