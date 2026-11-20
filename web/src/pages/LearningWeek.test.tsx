// "This week" and the traceable queue on Review Today, against a fake of
// GET /review-today and GET /learning-week: both reads send the same learner
// zone; production and reviewed work, own corrections and provider feedback
// are counted apart; a sparse week shows counts only; a correction reopens
// its take at its version; each queue item names the record it is based on;
// a Speaking step can be hidden for this visit without deleting anything.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "../i18n";
import type { LearningWeek as Week, ReviewToday as Today } from "../types/reviewToday";
import type { SpeakingQueueItem } from "../types/speaking";
import { accentItem } from "./practiceDraft.fixture";
import { ReviewToday } from "./ReviewToday";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const days = ["2026-11-13", "2026-11-14", "2026-11-15", "2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19"];
const week = (over: Partial<Week> = {}): Week => ({
  schema_version: "learning_week_v1",
  generated_at: "t",
  zone: "Europe/Paris",
  from: days[0],
  to: days[6],
  // The handwritten sequence of docs/validation/LEARNING-WEEK.md.
  days: [
    { day: days[0], production: 1, reviewed: 0, own_corrections: 1, provider_feedback: 0 },
    { day: days[1], production: 0, reviewed: 0, own_corrections: 0, provider_feedback: 1 },
    { day: days[2], production: 0, reviewed: 0, own_corrections: 0, provider_feedback: 0 },
    { day: days[3], production: 0, reviewed: 0, own_corrections: 0, provider_feedback: 0 },
    { day: days[4], production: 1, reviewed: 0, own_corrections: 1, provider_feedback: 0 },
    { day: days[5], production: 0, reviewed: 1, own_corrections: 0, provider_feedback: 0 },
    { day: days[6], production: 1, reviewed: 2, own_corrections: 0, provider_feedback: 0 },
  ],
  totals: { production: 3, reviewed: 3, own_corrections: 2, provider_feedback: 1, distinct_exercises: 3, active_days: 5, duplicates_ignored: 2 },
  sparse: true,
  min_for_shares: 20,
  production_share: null,
  corrections: [
    { skill: "writing", title: "Lettre à Éloïse", version: 2, prior_version: 1, day: days[4], at: "t", task_id: 2 },
    { skill: "speaking", title: "Répondre à une invitation", version: 1, prior_version: 0, day: days[0], at: "t", exercise_id: 1, take_id: 11, take_number: 1 },
  ],
  sources: { speaking: true, writing: true, notebook: true },
  ...over,
});
const step: SpeakingQueueItem = {
  reason: "review_without_feedback", priority: 5, prompt_id: "sp-invitation-reponse", title: "Répondre à une invitation", exercise_id: 3,
  take_id: 31, take_number: 2, state: "awaiting_feedback", improvements: 0, since: "2026-11-18T08:00:00Z", request: "feedback",
  request_enabled: false, pack_status: "current",
};
const today = (): Today => ({
  schema_version: "review_today_v1",
  generated_at: "t",
  zone: "Europe/Paris",
  today: days[6],
  items: [
    { key: "speaking:exercise:3", source: "speaking", reason: "review_without_feedback", priority: 5, since: "2026-11-18T08:00:00Z", since_day: "2026-11-18", speaking: step, notebook: null },
    { key: "notebook:entry:2", source: "notebook", reason: "retry_marked", priority: 6, since: "2026-11-18T23:30:00Z", since_day: "2026-11-19", speaking: null, notebook: accentItem(2, { retry: { marked: true, since: "2026-11-18T23:30:00Z" } }) },
  ],
  history: { notebook_items: 2, speaking_exercises: 1, speaking_takes: 2 },
  sources: { speaking: true, notebook: true },
});

function serve(w: Week) {
  const calls: string[] = [];
  globalThis.fetch = vi.fn(async (input: string | URL | Request) => {
    const url = new URL(String(input), "http://localhost");
    calls.push(url.pathname + url.search);
    const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    if (url.pathname === "/api/review-today") return json(200, today());
    if (url.pathname === "/api/learning-week") return json(200, w);
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

describe("This week and a traceable queue", () => {
  it("sends one learner zone to both reads and shows each kind of work apart, with counts only for a sparse week", async () => {
    const calls = serve(week());
    const props = renderPage();
    const region = await screen.findByRole("region", { name: "This week" });
    await within(region).findByRole("table");
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    expect(calls).toContain(`/api/review-today?zone=${encodeURIComponent(zone)}`);
    expect(calls).toContain(`/api/learning-week?zone=${encodeURIComponent(zone)}`);
    const rows = within(region).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.getAttribute("data-day"))).toEqual(days);
    expect([...rows[6].querySelectorAll("td")].map((c) => c.textContent)).toEqual(["1", "2", "0", "0"]);
    expect(within(region).getByText("This week: production practice 3 (in 3 exercises) · reviewed 3 · your corrections 2 · feedback received 1 · active days 5 of 7.")).toBeInTheDocument();
    // Definitions tell production practice from reviewed material, and own corrections from provider feedback.
    expect(region).toHaveTextContent("A Speaking take whose transcript you confirmed, or a first Writing draft.");
    expect(region).toHaveTextContent("A report written by a feedback provider, kept apart from your own corrections.");
    // A sparse week: no percentage anywhere.
    expect(within(region).getByText("Too little activity for percentages (fewer than 20 counted actions): counts only.")).toBeInTheDocument();
    expect(region.textContent).not.toMatch(/\d+\s*%/);
    expect(within(region).getByText("2 repeated saves of the same item on the same day were counted once.")).toBeInTheDocument();
    // A correction reopens its source at its version.
    const list = within(region).getByRole("list", { name: "Your corrections this week" });
    const [writingRow, speakingRow] = within(list).getAllByRole("listitem");
    expect(speakingRow).toHaveTextContent("Speaking · Répondre à une invitation: take 1, version 1 corrects the machine transcript");
    fireEvent.click(within(speakingRow).getByRole("button", { name: "Open take 1, version 1" }));
    expect(props.onOpenSource).toHaveBeenCalledWith({ skill: "speaking", exerciseId: 1, takeId: 11, transcriptVersion: 1 });
    fireEvent.click(within(writingRow).getByRole("button", { name: "Open draft 2" }));
    expect(props.onOpenSource).toHaveBeenCalledWith({ skill: "writing", taskId: 2, draftVersion: 2 });
  });

  it("shows a share only for a week with enough actions", async () => {
    serve(week({ sparse: false, production_share: 75, totals: { production: 15, reviewed: 5, own_corrections: 0, provider_feedback: 0, distinct_exercises: 4, active_days: 3, duplicates_ignored: 0 } }));
    renderPage();
    expect(await screen.findByText("Production practice was 75% of your 20 counted actions.")).toBeInTheDocument();
  });

  it("names the record each queue item is based on, in the learner's local day", async () => {
    serve(week());
    renderPage();
    const queue = await screen.findByRole("list", { name: "Due now" });
    const [speaking, notebook] = within(queue).getAllByRole("listitem");
    expect(speaking.querySelector('[data-based-on="speaking"]')).toHaveTextContent("Based on: Speaking exercise #3, take 2, reason review_without_feedback, since 2026-11-18.");
    // 23:30 UTC on the 18th is the 19th in Paris: the server's local day is shown.
    expect(notebook.querySelector('[data-based-on="notebook"]')).toHaveTextContent("Based on: notebook record #2 (listening_item #900, item 2), marked for retry on 2026-11-19.");
  });

  it("hides a Speaking step for this visit without deleting anything, and shows it again", async () => {
    const calls = serve(week());
    renderPage();
    const queue = await screen.findByRole("list", { name: "Due now" });
    const before = calls.length;
    fireEvent.click(within(within(queue).getAllByRole("listitem")[0]).getByRole("button", { name: "Hide for this visit" }));
    await waitFor(() => expect(within(queue).getAllByRole("listitem")).toHaveLength(1));
    expect(screen.getByText("Hidden for this visit: Répondre à une invitation. Nothing was deleted; it comes back when you reload.")).toBeInTheDocument();
    expect(screen.getByText(/1 item hidden for this visit \(nothing deleted\)\./)).toBeInTheDocument();
    expect(calls.length).toBe(before); // no request: nothing stored or deleted
    fireEvent.click(screen.getByRole("button", { name: "Show hidden items" }));
    await waitFor(() => expect(within(screen.getByRole("list", { name: "Due now" })).getAllByRole("listitem")).toHaveLength(2));
  });
});
