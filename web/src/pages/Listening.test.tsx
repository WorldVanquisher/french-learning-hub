// Exam Listening Lesson v1 in the private workbench, against a stateful fake
// server built from the authored French fixture (test/listeningFixture).
import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import PublicDemoApp from "../PublicDemoApp";
import { completed, content, lesson, material, parseTranscript, segments, transcriptText } from "../test/listeningFixture";
import type { ListeningExercise, ListeningLesson } from "../types/listening";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

type Call = { method: string; path: string; body: string };
type Server = {
  lessons: ListeningLesson[];
  prepare: "ok" | "invalid_output" | "disabled";
  calls: Call[];
};

// serve keeps lessons across renders (a "reload" re-reads the same state).
function serve(server: Server) {
  const json = (status: number, body: unknown) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const body = String(init?.body ?? "");
    server.calls.push({ method, path: url.pathname, body });
    const p = url.pathname;
    const generation = server.prepare === "disabled" ? { enabled: false, generator: null } : lesson().generation;
    const find = (id: number) => server.lessons.find((l) => l.material.id === id);
    let m: RegExpExecArray | null;
    if (method === "GET" && p === "/api/listening/materials") {
      return json(200, {
        generation,
        materials: server.lessons.map((l) => ({
          material: l.material,
          transcript_version: l.transcript?.version ?? null,
          segment_count: l.transcript?.segments.length ?? 0,
          latest_exercise: l.exercises[0] ? { ...l.exercises[0], content: null } : null,
        })),
      });
    }
    if (method === "POST" && p === "/api/listening/materials") {
      const req = JSON.parse(body) as { source_url: string; title: string; transcript: string };
      const id = server.lessons.length + 1;
      const l: ListeningLesson = {
        material: { ...material, id, title: req.title },
        transcript: req.transcript.trim() ? { id: id * 10, version: 1, has_timestamps: true, segments: parseTranscript(req.transcript), created_at: "t" } : null,
        exercises: [],
        generation,
      };
      server.lessons.push(l);
      return json(201, l);
    }
    if ((m = /^\/api\/listening\/materials\/(\d+)$/.exec(p)) && method === "GET") {
      const l = find(Number(m[1]));
      return l ? json(200, { ...l, generation }) : json(404, { error: "listening material not found" });
    }
    if ((m = /^\/api\/listening\/materials\/(\d+)\/exercises$/.exec(p)) && method === "POST") {
      const l = find(Number(m[1]))!;
      if (server.prepare === "disabled") return json(503, { error: "listening exercise generation is not enabled (LISTENING_PROVIDER)" });
      if (!l.transcript) return json(409, { error: "this material has no transcript, so no exercise can be prepared" });
      if (server.prepare === "invalid_output") {
        const failed: ListeningExercise = { ...completed(200 + l.exercises.length), transcript_id: l.transcript.id, status: "failed", failure_code: "invalid_output", content: null };
        l.exercises.unshift(failed);
        return json(502, { error: "the exercise provider returned output that does not fit the transcript; the material and transcript are kept", exercise: failed });
      }
      const ex = { ...completed(100 + l.exercises.length), transcript_id: l.transcript.id };
      l.exercises.unshift(ex);
      return json(201, ex);
    }
    if (p === "/api/captures" && method === "POST") {
      const doc = JSON.parse(body) as { capture_id: string };
      return json(201, { capture_id: doc.capture_id, entry_id: 77, analysis_id: null, created: true });
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

const writes = (server: Server) => server.calls.filter((c) => c.method !== "GET");
const exercisePosts = (server: Server) => server.calls.filter((c) => c.method === "POST" && c.path.endsWith("/exercises"));

async function openListening() {
  render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Listening" }));
  return await screen.findByRole("region", { name: "Saved listening material" });
}

async function openLesson(title = material.title) {
  const list = await openListening();
  fireEvent.click(await within(list).findByRole("button", { name: title }));
  return await screen.findByRole("heading", { name: title });
}

const exerciseRegion = () => screen.getByRole("region", { name: "Listening exercise" });

describe("Listening (private workbench)", () => {
  it("saves a link without a transcript as waiting, and never prepares a lesson for it", async () => {
    const server: Server = { lessons: [], prepare: "ok", calls: [] };
    serve(server);
    await openListening();
    fireEvent.change(screen.getByLabelText("YouTube video link"), { target: { value: "https://youtu.be/FLHlisten01" } });
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Sans transcription" } });
    fireEvent.click(screen.getByRole("button", { name: "Save material" }));
    expect(await screen.findByRole("heading", { name: "Sans transcription" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Waiting for a transcript" })).toBeInTheDocument();
    expect(screen.getByText("No transcript yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Prepare exercise" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Listening exercise" })).toBeNull();
    expect(exercisePosts(server)).toEqual([]);
    expect(writes(server).map((c) => c.path)).toEqual(["/api/listening/materials"]);
  });

  it("prepares only on request, hides the transcript, answers and notes until reveal, and browsing or playback calls nothing", async () => {
    const server: Server = { lessons: [lesson()], prepare: "ok", calls: [] };
    serve(server);
    await openLesson();
    const video = screen.getByRole("link", { name: "Open the video on YouTube ↗" });
    expect(video).toHaveAttribute("href", "https://www.youtube.com/watch?v=FLHlisten01");
    expect(video).toHaveAttribute("target", "_blank");
    expect(video).toHaveAttribute("rel", "noopener noreferrer");
    fireEvent.click(video);
    expect(writes(server)).toEqual([]); // browsing and opening the video sent nothing but GETs

    fireEvent.click(screen.getByRole("button", { name: "Prepare exercise" }));
    await screen.findByRole("region", { name: "Listening exercise" });
    expect(exercisePosts(server)).toHaveLength(1);

    // Default exercise view: the French questions only.
    for (const item of content.items) expect(within(exerciseRegion()).getByText(item.question)).toBeInTheDocument();
    for (const hidden of [
      ...segments.map((s) => s.text),
      ...content.items.flatMap((i) => [i.expected_answer, i.rationale_en, i.rationale_zh]),
      ...content.annotations.flatMap((a) => [a.note_en, a.note_zh]),
    ])
      expect(screen.queryByText(hidden, { exact: false })).toBeNull();

    fireEvent.change(screen.getByLabelText("Your answer to question 2"), { target: { value: "une carte d'identité" } });
    fireEvent.click(screen.getByRole("button", { name: "Reveal answers and evidence" }));

    const second = screen.getByRole("group", { name: "Reference for question 2" });
    expect(within(second).getByText("Un justificatif de domicile.")).toBeInTheDocument();
    expect(within(second).getByText("Segment 4 states the condition.")).toBeInTheDocument();
    expect(within(second).getByText("第4段说明了条件。")).toBeInTheDocument();
    expect(within(second).getByText(segments[3].text)).toBeInTheDocument(); // the cited French, as supplied
    expect(within(second).getByRole("link", { name: "0:16" })).toHaveAttribute("href", "https://www.youtube.com/watch?v=FLHlisten01&t=16s");
    expect(screen.getByLabelText("Your answer to question 2")).toHaveValue("une carte d'identité");
    expect(screen.getByText("proof of address")).toBeInTheDocument();
    expect(screen.getByText(/not an official exam score or a CEFR level/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show the full transcript" }));
    const full = screen.getByRole("region", { name: "Full transcript" });
    for (const s of segments) expect(within(full).getByText(s.text)).toBeInTheDocument();
    expect(exercisePosts(server)).toHaveLength(1);
    expect(writes(server)).toHaveLength(1);
  });

  it("saves one missed point as a normal learning record only after explicit confirmation", async () => {
    const server: Server = { lessons: [lesson({ exercises: [completed()] })], prepare: "ok", calls: [] };
    serve(server);
    const stored = vi.spyOn(Storage.prototype, "setItem");
    await openLesson();
    fireEvent.change(screen.getByLabelText("Your answer to question 2"), { target: { value: "réponse-secrète-xyz" } });
    fireEvent.click(screen.getByRole("button", { name: "Reveal answers and evidence" }));
    const second = screen.getByRole("group", { name: "Reference for question 2" });
    fireEvent.click(within(second).getByRole("button", { name: "I missed it" }));
    fireEvent.click(within(second).getByRole("button", { name: "Save as a learning question…" }));

    const form = screen.getByRole("form", { name: "Save a missed point from question 2" });
    expect(within(form).getByText(/Video: https:\/\/www\.youtube\.com\/watch\?v=FLHlisten01&t=16s/)).toBeInTheDocument();
    expect(within(form).getByText(/Excerpt \(segment 4, 0:16\): « L'inscription est gratuite/)).toBeInTheDocument();
    expect(within(form).getByRole("button", { name: "Save learning record" })).toBeDisabled();
    expect(writes(server)).toEqual([]); // opening the form and self-checking sent nothing

    const mistake = "J'ai compris « justificatif d'identité » au lieu de « justificatif de domicile ».";
    fireEvent.change(within(form).getByLabelText("What did you miss, or what do you want to ask?"), { target: { value: mistake } });
    fireEvent.click(within(form).getByRole("button", { name: "Save learning record" }));
    expect(await screen.findByText("Saved as learning record #77.")).toBeInTheDocument();

    const posts = writes(server);
    expect(posts.map((c) => c.path)).toEqual(["/api/captures"]);
    const doc = JSON.parse(posts[0].body) as Record<string, string>;
    expect(doc.schema_version).toBe("learning_capture_v1");
    expect(doc.source).toBe("manual");
    expect(doc.capture_id).toMatch(/^listening-1-100-2-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(doc.original_input).toBe(mistake);
    expect(doc.original_context).toContain("https://www.youtube.com/watch?v=FLHlisten01&t=16s");
    expect(doc.original_context).toContain(segments[3].text);
    expect(doc.original_context).toContain(content.items[1].question);
    expect(Object.keys(doc).sort()).toEqual(["capture_id", "original_context", "original_input", "schema_version", "source"]);
    // Typed answers and self-checks never leave the page.
    expect(server.calls.some((c) => c.body.includes("réponse-secrète-xyz"))).toBe(false);
    expect(stored.mock.calls.some((args) => JSON.stringify(args).includes("réponse-secrète-xyz"))).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Open record #77 in Learning Records" }));
    expect(await screen.findByText("Opened from a listening lesson.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "← Back to Listening" }));
    expect(screen.getByLabelText("Your answer to question 2")).toHaveValue("réponse-secrète-xyz"); // kept while mounted
  });

  it("states a stored provider failure honestly and keeps the material and transcript", async () => {
    const server: Server = { lessons: [lesson()], prepare: "invalid_output", calls: [] };
    serve(server);
    await openLesson();
    fireEvent.click(screen.getByRole("button", { name: "Prepare exercise" }));
    expect(await screen.findByText(/The last preparation failed: the provider's output did not fit your transcript/)).toBeInTheDocument();
    expect(screen.getByText("Transcript version 1: 8 lines, with timestamps from your source.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Prepare exercise" })).toBeEnabled(); // a new attempt is the learner's explicit choice
    expect(screen.queryByRole("region", { name: "Listening exercise" })).toBeNull();
    expect(exercisePosts(server)).toHaveLength(1); // no automatic retry
  });

  it("says when preparation is off and offers no provider action", async () => {
    const server: Server = { lessons: [lesson()], prepare: "disabled", calls: [] };
    serve(server);
    await openLesson();
    expect(screen.getByText(/Exercise preparation is off \(LISTENING_PROVIDER=disabled\)/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Prepare exercise" })).toBeNull();
  });

  it("opens the same lesson again after a reload", async () => {
    const server: Server = { lessons: [], prepare: "ok", calls: [] };
    serve(server);
    await openListening();
    fireEvent.change(screen.getByLabelText("YouTube video link"), { target: { value: "https://www.youtube.com/watch?v=FLHlisten01" } });
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: material.title } });
    fireEvent.change(screen.getByLabelText("French transcript (optional)"), { target: { value: transcriptText } });
    fireEvent.click(screen.getByRole("button", { name: "Save material" }));
    fireEvent.click(await screen.findByRole("button", { name: "Prepare exercise" }));
    await screen.findByRole("region", { name: "Listening exercise" });
    cleanup(); // the page goes away; only the server keeps state

    await openLesson();
    expect(await screen.findByRole("region", { name: "Listening exercise" })).toBeInTheDocument();
    expect(screen.getByText(content.items[0].question)).toBeInTheDocument();
    expect(screen.queryByText(content.items[0].expected_answer)).toBeNull(); // hidden again after reload
    expect(exercisePosts(server)).toHaveLength(1);
  });

  it("is offered in Simplified Chinese", async () => {
    window.localStorage.setItem("flh.ui-locale.v1", "zh-CN");
    serve({ lessons: [lesson({ exercises: [completed()] })], prepare: "ok", calls: [] });
    render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
    fireEvent.click(screen.getByRole("button", { name: "听力" }));
    fireEvent.click(await screen.findByRole("button", { name: material.title }));
    expect(await screen.findByRole("button", { name: "显示答案和依据" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "在 YouTube 上打开视频 ↗" })).toBeInTheDocument();
    expect(screen.getByText(content.items[0].question)).toBeInTheDocument(); // the French stays French
  });

  it("is not part of the public demo", async () => {
    const server: Server = { lessons: [lesson()], prepare: "ok", calls: [] };
    serve(server);
    render(
      <StrictMode>
        <PublicDemoApp />
      </StrictMode>,
    );
    expect(await screen.findByRole("search")).toBeInTheDocument(); // the demo's Knowledge Library rendered
    expect(screen.queryByRole("button", { name: "Listening" })).toBeNull();
    expect(screen.queryByText(/Listening/)).toBeNull();
    expect(server.calls.filter((c) => c.path.startsWith("/api/listening"))).toEqual([]);
  });
});
