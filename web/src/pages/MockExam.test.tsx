// Mock Exam v1 in the private workbench, against a stateful fake server that
// owns the clock, the frozen questions, the answers and the submission.
import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import PublicDemoApp from "../PublicDemoApp";
import { LocaleProvider } from "../i18n";
import type { ExamView } from "../types/exam";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
  window.localStorage.clear();
});

const PASSAGE = {
  id: "rd-annonce-ligne-b",
  title: "Travaux sur la ligne B : week-end du 18 et 19",
  format: "announcement",
  style_level: "A2",
  segments: [
    { id: "p1", text: "La ligne B sera fermée entre Gare du Nord et Saint-Michel le samedi 18 et le dimanche 19." },
    { id: "p2", text: "Des bus de remplacement circuleront toutes les dix minutes." },
  ],
};
const QUESTIONS = [
  { position: 1, passage_id: PASSAGE.id, kind: "main_idea", question: "De quoi parle l'annonce ?", choices: ["D'une grève.", "De travaux le week-end."] },
  { position: 2, passage_id: PASSAGE.id, kind: "detail", question: "Quelle est la fréquence des bus ?", choices: ["Toutes les dix minutes.", "Toutes les heures."] },
];
const KEYS = [1, 0];
const ITEMS = QUESTIONS.map((q, i) => ({
  position: q.position,
  key: KEYS[i],
  explanation_en: `Explanation ${q.position}.`,
  explanation_zh: `解析 ${q.position}。`,
  why: { en: `Reason ${q.position}.`, zh: `原因 ${q.position}。` },
  evidence: [{ segment: i === 0 ? "p1" : "p2", excerpt: i === 0 ? "sera fermée" : "toutes les dix minutes" }],
  source: { pack: "flh_reading_pack_v1", passage_id: PASSAGE.id, question_id: `${PASSAGE.id}:q${q.position}`, pack_item: q.position, content_sha256: "a".repeat(64) },
}));

type Call = { method: string; path: string; body: string; key: string | null };

function serve(opts: { loseSubmitResponse?: boolean } = {}) {
  const calls: Call[] = [];
  let now = Date.parse("2026-11-10T09:00:00Z");
  const sessions: { id: number; key: string; kind: "exam" | "retry"; deadline: number; answers: Record<number, number | null>; submitted: Record<number, number | null> | null; submittedAt: number }[] = [];
  let lose = !!opts.loseSubmitResponse;
  const iso = (ms: number) => new Date(ms).toISOString();
  const view = (s: (typeof sessions)[number], extra: Partial<ExamView> = {}): ExamView => {
    const state = s.submitted ? "submitted" : now > s.deadline ? "expired" : "in_progress";
    const final = s.submitted ?? (state === "expired" ? s.answers : null);
    const qs = s.kind === "retry" ? [QUESTIONS[1]].map((q) => ({ ...q, position: 1 })) : QUESTIONS;
    return {
      session: { id: s.id, kind: s.kind, form_id: "ce-entrainement-express", title: "Compréhension écrite — entraînement express",
        retry_of: s.kind === "retry" ? { session_id: 1, position: 1 } : null, duration_seconds: 90, started_at: iso(s.deadline - 90000),
        deadline_at: iso(s.deadline), forms_sha256: "f", pack_sha256: "p" },
      state, server_now: iso(now), remaining_seconds: state === "in_progress" ? Math.ceil((s.deadline - now) / 1000) : 0,
      notice: "Authored practice exam; not an official exam.", passages: [PASSAGE], questions: qs,
      answers: Object.entries(s.answers).map(([p, c]) => ({ position: Number(p), choice: c, saved_at: iso(now) })),
      result: final
        ? { closed: state, closed_at: iso(s.submitted ? s.submittedAt : s.deadline),
            correct: qs.filter((q, i) => final[q.position] === KEYS[i]).length, total: qs.length,
            items: qs.map((q, i) => ({ position: q.position, choice: final[q.position] ?? null, key: KEYS[i], correct: final[q.position] === KEYS[i],
              explanation_en: ITEMS[i].explanation_en, explanation_zh: ITEMS[i].explanation_zh,
              why_wrong: final[q.position] !== undefined && final[q.position] !== null && final[q.position] !== KEYS[i] ? ITEMS[i].why : null,
              evidence: ITEMS[i].evidence, source: ITEMS[i].source })) }
        : null,
      ...extra,
    };
  };
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const body = String(init?.body ?? "");
    const key = (init?.headers as Record<string, string> | undefined)?.["Idempotency-Key"] ?? null;
    calls.push({ method, path: url.pathname, body, key });
    const p = url.pathname;
    let m: RegExpExecArray | null;
    if (p === "/api/exam/forms")
      return json(200, { schema_version: "flh_mock_exam_forms_v1", notice: "Authored practice exam; not an official exam.", pack: "flh_reading_pack_v1",
        forms: [{ id: "ce-entrainement-express", title: "Compréhension écrite — entraînement express", section: "reading", duration_seconds: 90, description: "One announcement.", question_count: 2 }] });
    if (p === "/api/exam/sessions" && method === "GET")
      return json(200, { server_now: iso(now), sessions: [...sessions].reverse().map((s) => {
        const v = view(s);
        return { id: s.id, kind: s.kind, form_id: "ce-entrainement-express", title: v.session.title, retry_of: v.session.retry_of, state: v.state,
          started_at: v.session.started_at, deadline_at: v.session.deadline_at, question_count: v.questions.length, result: v.result ? { correct: v.result.correct, total: v.result.total } : null };
      }) });
    if (p === "/api/exam/sessions" && method === "POST") {
      const found = sessions.find((s) => s.key === key);
      if (found) return json(200, view(found));
      const s = { id: sessions.length + 1, key: key!, kind: "exam" as const, deadline: now + 90000, answers: {}, submitted: null, submittedAt: 0 };
      sessions.push(s);
      return json(201, view(s));
    }
    if ((m = /^\/api\/exam\/sessions\/(\d+)$/.exec(p))) return json(200, view(sessions[Number(m[1]) - 1]));
    if ((m = /^\/api\/exam\/sessions\/(\d+)\/answers\/(\d+)$/.exec(p))) {
      const s = sessions[Number(m[1]) - 1];
      if (s.submitted) return json(409, { error: "submitted", code: "exam_submitted", exam: view(s) });
      if (now > s.deadline) return json(409, { error: "expired", code: "exam_expired", exam: view(s) });
      s.answers[Number(m[2])] = (JSON.parse(body) as { choice: number | null }).choice;
      return json(200, { position: Number(m[2]), choice: s.answers[Number(m[2])], saved_at: iso(now), server_now: iso(now), remaining_seconds: Math.ceil((s.deadline - now) / 1000) });
    }
    if ((m = /^\/api\/exam\/sessions\/(\d+)\/submit$/.exec(p))) {
      const s = sessions[Number(m[1]) - 1];
      const answers = (JSON.parse(body) as { answers: Record<string, number | null> }).answers;
      const final = { ...s.answers, ...Object.fromEntries(Object.entries(answers).map(([k, v]) => [Number(k), v])) };
      if (s.submitted) {
        const same = JSON.stringify(final) === JSON.stringify(s.submitted);
        return same ? json(200, view(s, { replayed: true })) : json(409, { error: "already", code: "already_submitted", exam: view(s) });
      }
      if (now > s.deadline) return json(409, { error: "expired", code: "exam_expired", exam: view(s) });
      s.answers = final;
      s.submitted = final;
      s.submittedAt = now;
      if (lose) {
        lose = false;
        throw new TypeError("network down");
      }
      return json(200, view(s, { replayed: false }));
    }
    if ((m = /^\/api\/exam\/sessions\/(\d+)\/retries$/.exec(p))) {
      const found = sessions.find((s) => s.key === key);
      if (found) return json(200, view(found));
      const s = { id: sessions.length + 1, key: key!, kind: "retry" as const, deadline: now + 120000, answers: {}, submitted: null, submittedAt: 0 };
      sessions.push(s);
      return json(201, view(s));
    }
    if (p === "/api/reading/examples/rd-annonce-ligne-b")
      return json(201, { lesson: { id: 3 }, passage: { id: 4, version: 1 }, exercises: [{ id: 9, passage_id: 4, generator: "authored:flh_reading_pack_v1", status: "completed" }] });
    if (p === "/api/captures" && method === "POST") return json(201, { entry_id: 77, created: true });
    if (p === "/api/reviewable-units") return json(200, { reviewable_units: [] });
    if (p === "/api/learning-records") return json(200, { records: [], next_before_entry_id: null });
    return json(200, { concepts: [] });
  }) as unknown as typeof fetch;
  return { calls, sessions, advance: (ms: number) => (now += ms) };
}

const writes = (calls: Call[]) => calls.filter((c) => c.method !== "GET");

async function openExam() {
  render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Mock Exam" }));
  return await screen.findByRole("region", { name: "Start an exam" });
}

async function startExpress() {
  const forms = await openExam();
  fireEvent.click(within(forms).getByRole("button", { name: "Start “Compréhension écrite — entraînement express”" }));
  return await screen.findByRole("timer", { name: "Time remaining" });
}

describe("Mock Exam (private workbench)", () => {
  it("starts under a key, shows no answer key, saves each answer as chosen and resumes from the server after a reload", async () => {
    const s = serve();
    const timer = await startExpress();
    expect(timer.textContent).toBe("Time remaining: 1:30");
    const start = s.calls.find((c) => c.method === "POST" && c.path === "/api/exam/sessions")!;
    expect(start.key).toMatch(/^[0-9a-f-]{36}$/);
    expect(document.body.textContent).not.toContain("Explanation 1.");
    expect(document.body.textContent).not.toContain("Reason 1.");
    fireEvent.click(screen.getByRole("radio", { name: "De travaux le week-end." }));
    await screen.findByText("Saved.");
    expect(writes(s.calls).map((c) => [c.method, c.path, c.body])).toEqual([
      ["POST", "/api/exam/sessions", JSON.stringify({ form_id: "ce-entrainement-express" })],
      ["PUT", "/api/exam/sessions/1/answers/1", JSON.stringify({ choice: 1 })],
    ]);
    // A reload: a fresh page finds the exam in progress on the server.
    cleanup();
    s.advance(30000);
    await openExam();
    fireEvent.click(await screen.findByRole("button", { name: "Resume exam #1" }));
    expect((await screen.findByRole("timer", { name: "Time remaining" })).textContent).toBe("Time remaining: 1:00");
    expect((screen.getByRole("radio", { name: "De travaux le week-end." }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText("1 of 2 answered.")).toBeTruthy();
  });

  it("asks before submitting, explains every question against the text, and replays a repeated submission", async () => {
    const s = serve();
    await startExpress();
    fireEvent.click(screen.getByRole("radio", { name: "De travaux le week-end." }));
    fireEvent.click(screen.getByRole("radio", { name: "Toutes les heures." }));
    await waitFor(() => expect(screen.getAllByText("Saved.").length).toBe(2));
    fireEvent.click(screen.getByRole("button", { name: "Submit my answers" }));
    expect(writes(s.calls).filter((c) => c.path.endsWith("/submit"))).toEqual([]);
    const dialog = screen.getByRole("alertdialog", { name: "Confirm submission" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Submit now" }));
    expect(await screen.findByText("1 of 2 correct")).toBeTruthy();
    expect(screen.getByText("Authored practice: this is not an official score, a level or a grade.")).toBeTruthy();
    const q2 = screen.getByRole("group", { name: "Question 2" });
    expect(q2.textContent).toContain("Toutes les dix minutes.");
    expect(q2.textContent).toContain("Reason 2.");
    expect(q2.textContent).toContain("Explanation 2.");
    expect(q2.textContent).toContain("rd-annonce-ligne-b:q2");
    fireEvent.click(within(q2).getByRole("button", { name: "Show evidence in p2" }));
    expect(document.querySelector("mark")?.textContent).toBe("toutes les dix minutes");
    // A second submission of the same answers (e.g. from another tab) replays.
    const again = await fetch("/api/exam/sessions/1/submit", { method: "POST", body: JSON.stringify({ answers: { "1": 1, "2": 1 } }) });
    expect(((await again.json()) as ExamView).replayed).toBe(true);
    expect(s.sessions[0].submitted).toEqual({ 1: 1, 2: 1 });
  });

  it("after a lost submission response, checks the status and shows the result without a second submission", async () => {
    const s = serve({ loseSubmitResponse: true });
    await startExpress();
    fireEvent.click(screen.getByRole("radio", { name: "De travaux le week-end." }));
    await screen.findByText("Saved.");
    fireEvent.click(screen.getByRole("button", { name: "Submit my answers" }));
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Submit now" }));
    expect(await screen.findByText(/We could not confirm your submission/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Check status" }));
    expect(await screen.findByText("1 of 2 correct")).toBeTruthy();
    expect(s.calls.filter((c) => c.path.endsWith("/submit")).length).toBe(1);
  });

  it("follows the server's deadline: a late answer is refused and the expired result counts only answers saved in time", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const s = serve();
    await startExpress();
    fireEvent.click(screen.getByRole("radio", { name: "De travaux le week-end." }));
    await screen.findByText("Saved.");
    s.advance(91000);
    fireEvent.click(screen.getByRole("radio", { name: "Toutes les dix minutes." }));
    expect(await screen.findByText(/Time ran out at/)).toBeTruthy();
    expect(screen.getByText("1 of 2 correct")).toBeTruthy();
    expect(screen.getByRole("group", { name: "Question 2" }).textContent).toContain("Not answered");
    expect(s.sessions[0].submitted).toBeNull();
  });

  it("submits by itself when the countdown reaches zero, and the server decides", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const s = serve();
    await startExpress();
    s.advance(91000);
    await act(async () => {
      vi.advanceTimersByTime(92000);
    });
    expect(await screen.findByText(/Time ran out at/)).toBeTruthy();
    expect(s.calls.filter((c) => c.path.endsWith("/submit")).length).toBe(1);
  });

  it("saves a missed point only after confirmation, linked to the same authored item, and opens a related question", async () => {
    const s = serve();
    await startExpress();
    fireEvent.click(screen.getByRole("radio", { name: "D'une grève." }));
    await screen.findByText("Saved.");
    fireEvent.click(screen.getByRole("button", { name: "Submit my answers" }));
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Submit now" }));
    const q1 = await screen.findByRole("group", { name: "Question 1" });
    const before = writes(s.calls).length;
    fireEvent.click(within(q1).getByRole("button", { name: "Save this missed point…" }));
    const form = screen.getByRole("form", { name: "Save the missed point of question 1" });
    expect(writes(s.calls).length).toBe(before);
    fireEvent.change(within(form).getByRole("textbox"), { target: { value: "J'ai cru que c'était une grève." } });
    fireEvent.click(within(form).getByRole("button", { name: /Save as learning record|Confirm|Save/ }));
    expect(await screen.findByText("Saved as learning record #77.")).toBeTruthy();
    const capture = s.calls.find((c) => c.path === "/api/captures")!;
    const doc = JSON.parse(JSON.parse(JSON.stringify(capture.body))) as { source_ref: unknown; original_context: string };
    expect(doc.source_ref).toEqual({ type: "reading_item", record_id: 9, item: 1 });
    expect(doc.original_context).toContain("question 1");
    fireEvent.click(within(q1).getByRole("button", { name: "Practise a related question" }));
    expect(await screen.findByRole("heading", { name: "Related question for question 1 of exam #1" })).toBeTruthy();
    expect(s.calls.find((c) => c.path === "/api/exam/sessions/1/retries")!.key).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("is offered in Simplified Chinese, with the French kept as written", async () => {
    serve();
    window.localStorage.setItem("flh.ui-locale.v1", "zh-CN");
    render(
      <LocaleProvider>
        <App />
      </LocaleProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "模拟考试" }));
    const forms = await screen.findByRole("region", { name: "开始考试" });
    expect(within(forms).getByRole("heading", { name: "Compréhension écrite — entraînement express" })).toBeTruthy();
    fireEvent.click(within(forms).getByRole("button", { name: "开始“Compréhension écrite — entraînement express”" }));
    expect((await screen.findByRole("timer", { name: "剩余时间" })).textContent).toBe("剩余时间：1:30");
  });

  it("is not part of the public demo", async () => {
    globalThis.fetch = vi.fn(async () => new Response(JSON.stringify({}), { status: 200 })) as unknown as typeof fetch;
    render(<PublicDemoApp />);
    expect(screen.queryByRole("button", { name: "Mock Exam" })).toBeNull();
  });
});
