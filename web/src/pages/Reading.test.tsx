// Exam Reading v1 in the private workbench, against a stateful fake server
// built from the authored fixture (test/readingFixture, generated from the
// embedded pack).
import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import PublicDemoApp from "../PublicDemoApp";
import { authoredExercise, generatedItems, items, lessonView, passageText, segments } from "../test/readingFixture";
import type { ReadingExercise, ReadingLessonView, ReadingPreparation } from "../types/reading";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

type Call = { method: string; path: string; body: string; key: string | null };
type Server = {
  lessons: ReadingLessonView[];
  prepare: "ok" | "lost" | "disabled";
  calls: Call[];
  prepared: Map<string, { preparation: ReadingPreparation; exercise: ReadingExercise }>;
};

const newServer = (lessons: ReadingLessonView[] = [], prepare: Server["prepare"] = "ok"): Server => ({ lessons, prepare, calls: [], prepared: new Map() });

function serve(server: Server) {
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const body = String(init?.body ?? "");
    const key = (init?.headers as Record<string, string> | undefined)?.["Idempotency-Key"] ?? null;
    server.calls.push({ method, path: url.pathname, body, key });
    const p = url.pathname;
    const generation = server.prepare === "disabled" ? { enabled: false, generator: null } : { enabled: true, generator: "openai:fake-model:reading_exercise_v1" };
    const view = (l: ReadingLessonView) => ({ ...l, generation });
    const find = (id: number) => server.lessons.find((l) => l.lesson.id === id);
    let m: RegExpExecArray | null;
    if (method === "GET" && p === "/api/reading/lessons")
      return json(200, {
        generation,
        lessons: server.lessons.map((l) => ({ lesson: l.lesson, passage_version: l.passage.version, paragraphs: l.passage.segments.length, state: l.state })),
      });
    if (method === "GET" && p === "/api/reading/examples")
      return json(200, {
        pack: "flh_reading_pack_v1",
        notice: "Authored practice material: not an official exam item, no certified CEFR level.",
        examples: [
          { id: "rd-email-chaudiere", title: "Objet : visite d'entretien de la chaudière", format: "email", style_level: "B1", paragraphs: 4, questions: 3, has_inference: true,
            imported_lesson_id: server.lessons.find((l) => l.lesson.pack_passage_id?.endsWith("rd-email-chaudiere"))?.lesson.id ?? null },
        ],
      });
    if (method === "POST" && p === "/api/reading/examples/rd-email-chaudiere") {
      const existing = server.lessons.find((l) => l.lesson.pack_passage_id?.endsWith("rd-email-chaudiere"));
      if (existing) return json(200, view(existing));
      const l = lessonView({ lesson: { ...lessonView().lesson, id: server.lessons.length + 1 } });
      server.lessons.push(l);
      return json(201, view(l));
    }
    if (method === "POST" && p === "/api/reading/lessons") {
      const req = JSON.parse(body) as { title: string; text: string; source_url: string };
      const id = server.lessons.length + 1;
      const l: ReadingLessonView = {
        ...lessonView(),
        lesson: { id, title: req.title, source_url: req.source_url || null, origin: "learner", pack_passage_id: null, created_at: "t" },
        passage: { id: id * 10, version: 1, segments: req.text.split(/\n\s*\n/).map((text, i) => ({ id: `p${i + 1}`, text: text.trim() })), created_at: "t" },
        exercises: [],
        state: "ready_to_prepare",
      };
      server.lessons.push(l);
      return json(201, view(l));
    }
    if ((m = /^\/api\/reading\/lessons\/(\d+)$/.exec(p)) && method === "GET") {
      const l = find(Number(m[1]));
      return l ? json(200, view(l)) : json(404, { error: "not found" });
    }
    if ((m = /^\/api\/reading\/lessons\/(\d+)\/exercises$/.exec(p)) && method === "POST") {
      const l = find(Number(m[1]))!;
      if (server.prepare === "disabled") return json(503, { error: "reading exercise generation is not enabled (READING_PROVIDER)" });
      if (key && server.prepared.has(key)) return json(200, server.prepared.get(key));
      const confirm = body.includes('"confirm_unknown_retry":true');
      if (l.preparations[0]?.state === "unknown" && !confirm) return json(409, { code: "outcome_unknown", error: "unknown", preparation: l.preparations[0] });
      const ex: ReadingExercise = { ...authoredExercise(100 + l.exercises.length, l.passage.id), generator: "openai:fake-model:reading_exercise_v1", content: { items: generatedItems } };
      const prep: ReadingPreparation = { id: 50 + l.preparations.length, operation_id: key ?? "k", passage_id: l.passage.id, after_unknown: confirm, started_at: "t", deadline_at: "t", finished_at: "t", state: "completed", exercise_id: ex.id };
      l.exercises.unshift(ex);
      l.preparations.unshift(prep);
      l.state = "prepared";
      const result = { preparation: prep, exercise: { ...ex, content: null } };
      server.prepared.set(key ?? "k", result);
      if (server.prepare === "lost") throw new TypeError("network down");
      return json(201, result);
    }
    if ((m = /^\/api\/reading\/preparations\/(.+)$/.exec(p)) && method === "GET") {
      const r = server.prepared.get(decodeURIComponent(m[1]));
      return r ? json(200, r) : json(404, { error: "no preparation is recorded under this key" });
    }
    if (p === "/api/captures" && method === "POST") {
      const doc = JSON.parse(body) as { capture_id: string };
      return json(201, { capture_id: doc.capture_id, entry_id: 88, analysis_id: null, created: true });
    }
    if (p === "/api/knowledge-library/demo")
      return json(200, {
        schema_version: "knowledge_library_public_demo_v1", read_only: true, data: "synthetic",
        artifact: { version: "v", manifest_sha256: "m", vector_source: "mechanical-test", real_model: false, vector_generator: "g", model_id: "x",
          dimensions: 4, document_representation: "d", query_representation: "q", release_status: "blocked", notice: "n", domain_fingerprint_sha256: "f" },
        query_policy: "presets only", presets: [], counters: { preset_vector_lookups: 0, refused_vector_lookups: 0 },
      });
    if (p === "/api/knowledge-library/concepts")
      return json(200, { schema_version: "knowledge_library_search_v1", query: "", tokens: [], state: "all", limit: 20, total_matches: 0, truncated: false, results: [] });
    if (p === "/api/reviewable-units") return json(200, { reviewable_units: [] });
    if (p === "/api/learning-records") return json(200, { records: [], next_before_entry_id: null });
    return json(200, { concepts: [] });
  }) as unknown as typeof fetch;
}

const writes = (s: Server) => s.calls.filter((c) => c.method !== "GET");
const passageRegion = () => screen.getByRole("region", { name: "Passage" });

async function openReading() {
  render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Reading" }));
  return await screen.findByRole("region", { name: "Saved reading lessons" });
}

describe("Reading (private workbench)", () => {
  it("imports an authored example without a provider call, keeps the passage visible and hides answers and evidence until reveal", async () => {
    const server = newServer();
    serve(server);
    await openReading();
    const examples = screen.getByRole("region", { name: "Authored examples" });
    expect(within(examples).getByText(/not official exam items and carry no certified level/)).toBeInTheDocument();
    fireEvent.click(within(examples).getByRole("button", { name: "Use this example" }));
    await screen.findByRole("region", { name: "Reading exercise" });
    expect(writes(server).map((c) => c.path)).toEqual(["/api/reading/examples/rd-email-chaudiere"]);
    expect(server.calls.some((c) => c.path.endsWith("/exercises"))).toBe(false);

    // The passage is visible while answering, with paragraph IDs and no highlight.
    for (const s of segments) expect(within(passageRegion()).getByText(s.text)).toBeInTheDocument();
    expect(within(passageRegion()).getByText("p3")).toBeInTheDocument();
    expect(passageRegion().querySelector("mark")).toBeNull();
    expect(screen.getByText(/this is not an official exam assessment/)).toBeInTheDocument();
    expect(screen.getByText("Inference — not stated directly in the text")).toBeInTheDocument();
    for (const hidden of [items[1].reference_answer, items[1].explanation_en, items[1].explanation_zh, items[1].wrong_answers[0].answer, items[0].accepted_alternatives[0]])
      expect(screen.queryByText(hidden, { exact: false })).toBeNull();

    fireEvent.change(screen.getByLabelText("Your answer to question 2"), { target: { value: "Appeler l'entreprise." } });
    fireEvent.click(screen.getByRole("button", { name: "Reveal answers and evidence" }));
    const q2 = screen.getByRole("group", { name: "Reference for question 2" });
    expect(within(q2).getByText(items[1].reference_answer)).toBeInTheDocument();
    expect(within(q2).getByText(items[1].accepted_alternatives.join(" / "))).toBeInTheDocument();
    expect(within(q2).getByText(items[1].explanation_en)).toBeInTheDocument();
    expect(within(q2).getByText(items[1].explanation_zh)).toBeInTheDocument();
    expect(within(q2).getByText(items[1].wrong_answers[0].answer)).toBeInTheDocument();
    expect(screen.getByLabelText("Your answer to question 2")).toHaveValue("Appeler l'entreprise.");

    // Jump to the cited excerpt: it is marked inside its paragraph.
    fireEvent.click(within(q2).getByRole("button", { name: "Show in the passage (p3)" }));
    const mark = passageRegion().querySelector("mark");
    expect(mark?.textContent).toBe(items[1].evidence[0].excerpt);
    expect(mark?.closest("p")?.id).toBe("reading-1-p3");
    expect(writes(server)).toHaveLength(1); // reading, answering, revealing and highlighting sent nothing
  });

  it("follows the explanation-language preference", async () => {
    window.localStorage.setItem("flh.explanation-language.v1", "zh");
    serve(newServer([lessonView()]));
    await openReading();
    fireEvent.click(await screen.findByRole("button", { name: lessonView().lesson.title }));
    fireEvent.click(await screen.findByRole("button", { name: "Reveal answers and evidence" }));
    const q2 = screen.getByRole("group", { name: "Reference for question 2" });
    expect(within(q2).getByText(items[1].explanation_zh)).toBeInTheDocument();
    expect(within(q2).queryByText(items[1].explanation_en)).toBeNull();
  });

  it("saves a missed point only after explicit confirmation, with the question, source and excerpt, and a way back", async () => {
    const server = newServer([lessonView()]);
    serve(server);
    const stored = vi.spyOn(Storage.prototype, "setItem");
    await openReading();
    fireEvent.click(await screen.findByRole("button", { name: lessonView().lesson.title }));
    fireEvent.change(await screen.findByLabelText("Your answer to question 3"), { target: { value: "réponse-privée-123" } });
    fireEvent.click(screen.getByRole("button", { name: "Reveal answers and evidence" }));
    const q3 = screen.getByRole("group", { name: "Reference for question 3" });
    fireEvent.click(within(q3).getByRole("button", { name: "I missed it" }));
    fireEvent.click(within(q3).getByRole("button", { name: "Save as a learning question…" }));
    const form = screen.getByRole("form", { name: "Save a missed point from question 3" });
    expect(within(form).getByText(/Excerpt \(p3\): « le technicien ne reviendra pas/)).toBeInTheDocument();
    expect(writes(server)).toEqual([]); // opening the form and self-checking sent nothing
    fireEvent.change(within(form).getByLabelText("What did you miss, or what do you want to ask?"), { target: { value: "« Passé ce délai » : je n'ai pas compris." } });
    fireEvent.click(within(form).getByRole("button", { name: "Save learning record" }));
    expect(await screen.findByText("Saved as learning record #88.")).toBeInTheDocument();
    const posts = writes(server);
    expect(posts.map((c) => c.path)).toEqual(["/api/captures"]);
    const doc = JSON.parse(posts[0].body) as Record<string, string>;
    expect(Object.keys(doc).sort()).toEqual(["capture_id", "original_context", "original_input", "schema_version", "source", "source_ref"]);
    // Mistake Notebook v1: the exact stored item, never the typed answer unless the learner includes it.
    expect((doc as unknown as { source_ref: unknown }).source_ref).toEqual({ type: "reading_item", record_id: 1, item: 3 });
    expect(doc.source).toBe("manual");
    expect(doc.capture_id).toMatch(/^reading-1-1-3-[0-9a-f-]{36}$/);
    expect(doc.original_context).toContain("Reading lesson #1:");
    expect(doc.original_context).toContain("authored example flh_reading_pack_v1/rd-email-chaudiere");
    expect(doc.original_context).toContain(items[2].question);
    expect(server.calls.some((c) => c.body.includes("réponse-privée-123"))).toBe(false);
    expect(stored.mock.calls.some((args) => JSON.stringify(args).includes("réponse-privée-123"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Open record #88 in Learning Records" }));
    expect(await screen.findByText("Opened from a reading lesson.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "← Back to Reading" }));
    expect(screen.getByLabelText("Your answer to question 3")).toHaveValue("réponse-privée-123");
  });

  it("sends the typed answer with the record only when the learner ticks it (Mistake Notebook)", async () => {
    const server = newServer([lessonView()]);
    serve(server);
    await openReading();
    fireEvent.click(await screen.findByRole("button", { name: lessonView().lesson.title }));
    fireEvent.change(await screen.findByLabelText("Your answer to question 3"), { target: { value: "Le technicien revient demain." } });
    fireEvent.click(screen.getByRole("button", { name: "Reveal answers and evidence" }));
    const q3 = screen.getByRole("group", { name: "Reference for question 3" });
    fireEvent.click(within(q3).getByRole("button", { name: "Save as a learning question…" }));
    const form = screen.getByRole("form", { name: "Save a missed point from question 3" });
    const include = within(form).getByRole("checkbox", { name: "Include my answer in the record: Le technicien revient demain." });
    expect(include).not.toBeChecked();
    fireEvent.click(include);
    fireEvent.change(within(form).getByLabelText("What did you miss, or what do you want to ask?"), { target: { value: "Le délai m'a échappé." } });
    fireEvent.click(within(form).getByRole("button", { name: "Save learning record" }));
    expect(await screen.findByText("Saved as learning record #88.")).toBeInTheDocument();
    const doc = JSON.parse(writes(server)[0].body) as { source_ref: unknown };
    expect(doc.source_ref).toEqual({ type: "reading_item", record_id: 1, item: 3, attempt: "Le technicien revient demain." });
  });

  it("prepares an exercise for a learner passage under a key and, after a lost response, finds it by that key", async () => {
    const server = newServer([], "lost");
    serve(server);
    await openReading();
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Mon courriel" } });
    fireEvent.change(screen.getByLabelText("Source link (optional, https)"), { target: { value: "https://example.org/courriel" } });
    fireEvent.change(screen.getByLabelText("French passage"), { target: { value: passageText } });
    fireEvent.click(screen.getByRole("button", { name: "Save passage" }));
    expect(await screen.findByText("Passage version 1: 4 paragraphs.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the source ↗" })).toHaveAttribute("rel", "noopener noreferrer");
    fireEvent.click(screen.getByRole("button", { name: "Prepare exercise" }));
    expect(await screen.findByRole("region", { name: "Reading exercise" })).toBeInTheDocument();
    const prepares = server.calls.filter((c) => c.method === "POST" && c.path.endsWith("/exercises"));
    expect(prepares).toHaveLength(1);
    expect(prepares[0].key).toMatch(/^[0-9a-f-]{36}$/);
    expect(server.calls.filter((c) => c.path === `/api/reading/preparations/${prepares[0].key}`)).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Reveal answers and evidence" }));
    expect(screen.getByText(/Prepared by/)).toBeInTheDocument();
  });

  it("an unknown preparation outcome needs an acknowledged retry", async () => {
    const unknown: ReadingPreparation = { id: 9, operation_id: "x", passage_id: 1, after_unknown: false, started_at: "t", deadline_at: "t", finished_at: "t", state: "unknown", exercise_id: 3 };
    const failed: ReadingExercise = { ...authoredExercise(3), status: "failed", failure_code: "provider_timeout", content: null, generator: "openai:fake-model:reading_exercise_v1" };
    const server = newServer([lessonView({ lesson: { ...lessonView().lesson, origin: "learner", pack_passage_id: null }, exercises: [failed], preparations: [unknown], state: "outcome_unknown" })]);
    serve(server);
    const list = await openReading();
    expect(await within(list).findByText("Outcome unknown")).toBeInTheDocument();
    fireEvent.click(within(list).getByRole("button", { name: lessonView().lesson.title }));
    expect(await screen.findByText(/It may have been processed and billed/)).toBeInTheDocument();
    expect(screen.queryByText(/The last preparation failed/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry preparation (may be billed again)" }));
    await screen.findByRole("region", { name: "Reading exercise" });
    const posts = writes(server);
    expect(posts).toHaveLength(1);
    expect(JSON.parse(posts[0].body)).toEqual({ confirm_unknown_retry: true });
  });

  it("says when preparation is off, while authored examples still work", async () => {
    const server = newServer([lessonView({ lesson: { ...lessonView().lesson, origin: "learner", pack_passage_id: null }, exercises: [], state: "ready_to_prepare" })], "disabled");
    serve(server);
    await openReading();
    fireEvent.click(await screen.findByRole("button", { name: lessonView().lesson.title }));
    expect(await screen.findByText(/Exercise preparation is off \(READING_PROVIDER=disabled\)/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Prepare exercise" })).toBeNull();
  });

  it("is offered in Simplified Chinese, with the French kept as written", async () => {
    window.localStorage.setItem("flh.ui-locale.v1", "zh-CN");
    serve(newServer([lessonView()]));
    render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
    fireEvent.click(screen.getByRole("button", { name: "阅读" }));
    fireEvent.click(await screen.findByRole("button", { name: lessonView().lesson.title }));
    expect(await screen.findByRole("button", { name: "显示答案和依据" })).toBeInTheDocument();
    expect(screen.getByText("推断——文中没有直接说明")).toBeInTheDocument();
    expect(screen.getByText(items[0].question)).toBeInTheDocument();
  });

  it("is not part of the public demo", async () => {
    const server = newServer([lessonView()]);
    serve(server);
    render(
      <StrictMode>
        <PublicDemoApp />
      </StrictMode>,
    );
    expect(await screen.findByRole("search")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reading" })).toBeNull();
    await waitFor(() => expect(server.calls.length).toBeGreaterThan(0));
    expect(server.calls.filter((c) => c.path.startsWith("/api/reading"))).toEqual([]);
  });
});
