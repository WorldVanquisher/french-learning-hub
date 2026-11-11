// Exam Listening Lesson v1 and Daily Listening in the private workbench, against
// a stateful fake server built from the authored French fixture
// (test/listeningFixture).
import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import PublicDemoApp from "../PublicDemoApp";
import {
  completed,
  content,
  lesson,
  material,
  notificationAttempt,
  parseTranscript,
  preparation,
  segments,
  transcriptText,
} from "../test/listeningFixture";
import type {
  ListeningDaily,
  ListeningExercise,
  ListeningLesson,
  ListeningNotification,
  ListeningPreparationResult,
  ListeningPullRun,
} from "../types/listening";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

type Call = { method: string; path: string; body: string; key: string | null };
type Server = {
  lessons: ListeningLesson[];
  prepare: "ok" | "invalid_output" | "disabled" | "timeout" | "lost";
  calls: Call[];
  // Daily Listening; off when absent.
  daily?: ListeningDaily;
  pull?: "ok" | "busy" | "lost";
  notify?: "ok";
  // Attempts and runs recorded under their keys.
  prepared?: Map<string, ListeningPreparationResult>;
  runs?: Map<string, ListeningPullRun>;
  sent?: Map<string, ListeningNotification>;
};

const dailyOff: ListeningDaily = {
  pull_enabled: false,
  source: { enabled: false, name: null },
  preparation: { enabled: false, generator: null, daily_cap: 1, timezone: "UTC", today: "2026-11-09", used_today: 0 },
  notification: { enabled: false, channel: null },
  last_run: null,
};
const dailyOn: ListeningDaily = {
  pull_enabled: true,
  source: { enabled: true, name: "youtube-data-api-v3:playlistItems" },
  preparation: { enabled: true, generator: "openai:fake-model:listening_exercise_v1", daily_cap: 1, timezone: "Europe/Paris", today: "2026-11-09", used_today: 0 },
  notification: { enabled: true, channel: "telegram" },
  last_run: null,
};

const pullRun = (id: number, key: string, overrides: Partial<ListeningPullRun> = {}): ListeningPullRun => ({
  id,
  operation_id: key,
  trigger: "manual",
  status: "finished",
  started_at: "2026-11-09T07:30:00Z",
  lease_expires_at: "2026-11-09T07:33:00Z",
  finished_at: "2026-11-09T07:30:02Z",
  source: { outcome: "ok", failure: null },
  items: { seen: 1, created: 1, known: 0, skipped: 0 },
  preparation: { outcome: "nothing_to_prepare", attempt: null },
  notification: { outcome: "nothing_ready", attempt: null },
  ...overrides,
});

// stateOf derives a material's state the way the backend does.
function stateOf(l: ListeningLesson): ListeningLesson["state"] {
  if (!l.transcript) return "waiting_for_transcript";
  const p = l.preparations[0];
  if (p?.state === "in_progress") return "in_progress";
  if (p?.state === "unknown") return "outcome_unknown";
  const ex = l.exercises.filter((e) => e.transcript_id === l.transcript!.id);
  if (ex.some((e) => e.status === "completed")) return "prepared";
  return ex[0]?.status === "failed" ? "failed" : "ready_to_prepare";
}

// serve keeps lessons across renders (a "reload" re-reads the same state).
function serve(server: Server) {
  server.prepared ??= new Map();
  server.runs ??= new Map();
  server.sent ??= new Map();
  const json = (status: number, body: unknown) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const body = String(init?.body ?? "");
    const key = (init?.headers as Record<string, string> | undefined)?.["Idempotency-Key"] ?? null;
    server.calls.push({ method, path: url.pathname, body, key });
    const p = url.pathname;
    const generation = server.prepare === "disabled" ? { enabled: false, generator: null } : lesson().generation;
    const notification = { enabled: !!server.daily?.notification.enabled, channel: server.daily?.notification.channel ?? null };
    const view = (l: ListeningLesson) => ({ ...l, generation, notification, state: stateOf(l) });
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
          state: stateOf(l),
          in_playlist: l.in_playlist,
        })),
      });
    }
    if (method === "POST" && p === "/api/listening/materials") {
      const req = JSON.parse(body) as { source_url: string; title: string; transcript: string };
      const id = server.lessons.length + 1;
      const l: ListeningLesson = lesson({
        material: { ...material, id, title: req.title },
        transcript: req.transcript.trim() ? { id: id * 10, version: 1, has_timestamps: true, segments: parseTranscript(req.transcript), created_at: "t" } : null,
      });
      server.lessons.push(l);
      return json(201, view(l));
    }
    if ((m = /^\/api\/listening\/materials\/(\d+)$/.exec(p)) && method === "GET") {
      const l = find(Number(m[1]));
      return l ? json(200, view(l)) : json(404, { error: "listening material not found" });
    }
    if ((m = /^\/api\/listening\/materials\/(\d+)\/exercises$/.exec(p)) && method === "POST") {
      const l = find(Number(m[1]))!;
      if (server.prepare === "disabled") return json(503, { error: "listening exercise generation is not enabled (LISTENING_PROVIDER)" });
      if (!l.transcript) return json(409, { code: "no_transcript", error: "this material has no transcript, so no exercise can be prepared" });
      if (key && server.prepared!.has(key)) return json(200, server.prepared!.get(key));
      const confirm = body.includes('"confirm_unknown_retry":true');
      const latest = l.preparations[0];
      if (latest?.state === "unknown" && !confirm)
        return json(409, { code: "outcome_unknown", error: "unknown", preparation: latest, exercise: null });
      const n = 100 + l.exercises.length;
      const prep = preparation({ id: n, operation_id: key ?? "generated", material_id: l.material.id, transcript_id: l.transcript.id, trigger: "explicit", pull_run_id: null, after_unknown: confirm && latest?.state === "unknown", exercise_id: n });
      let ex: ListeningExercise = { ...completed(n), transcript_id: l.transcript.id };
      if (server.prepare === "invalid_output" || server.prepare === "timeout") {
        const timeout = server.prepare === "timeout";
        ex = { ...ex, status: "failed", failure_code: timeout ? "provider_timeout" : "invalid_output", content: null };
        prep.state = timeout ? "unknown" : "failed";
      }
      l.exercises.unshift(ex);
      l.preparations.unshift(prep);
      const result = { preparation: prep, exercise: { ...ex, content: null } };
      server.prepared!.set(key ?? "generated", result);
      if (server.prepare === "lost") throw new TypeError("network down"); // stored, but the response is lost
      if (prep.state === "failed") return json(502, { ...result, error: "the exercise provider returned output that does not fit the transcript; the material and transcript are kept" });
      if (prep.state === "unknown") return json(504, { ...result, error: "the exercise provider timed out, so the outcome is unknown" });
      return json(201, result);
    }
    if ((m = /^\/api\/listening\/preparations\/(.+)$/.exec(p)) && method === "GET") {
      const r = server.prepared!.get(decodeURIComponent(m[1]));
      return r ? json(200, r) : json(404, { error: "no preparation is recorded under this key" });
    }
    if (method === "GET" && p === "/api/listening/daily") return json(200, server.daily ?? dailyOff);
    if (method === "GET" && p === "/api/listening/scripts") return json(200, { pack: "flh_listening_script_pack_v1", scripts: [] });
    if (method === "POST" && p === "/api/listening/pull") {
      if (!key) return json(400, { error: "exactly one Idempotency-Key header is required" });
      if (server.runs!.has(key)) return json(200, server.runs!.get(key));
      if (server.pull === "busy")
        return json(409, { code: "busy", error: "another listening pull is running", run: pullRun(9, "other", { trigger: "scheduled", status: "running", finished_at: null }) });
      if (server.pull === "lost") {
        server.pull = "ok"; // the request never arrived; the next one will
        throw new TypeError("network down");
      }
      const id = server.lessons.length + 1;
      server.lessons.push(lesson({ material: { ...material, id, video_id: "FLHplayl01", title: "Vidéo de la playlist" }, transcript: null, in_playlist: true }));
      const run = pullRun(server.runs!.size + 1, key);
      server.runs!.set(key, run);
      return json(201, run);
    }
    if ((m = /^\/api\/listening\/pull-runs\/(.+)$/.exec(p)) && method === "GET") {
      const r = server.runs!.get(decodeURIComponent(m[1]));
      return r ? json(200, r) : json(404, { error: "no pull is recorded under this key" });
    }
    if ((m = /^\/api\/listening\/exercises\/(\d+)\/notifications$/.exec(p)) && method === "POST") {
      if (key && server.sent!.has(key)) return json(200, server.sent!.get(key));
      const l = server.lessons.find((x) => x.exercises.some((e) => e.id === Number(m![1])))!;
      const latest = l.notifications[0];
      const confirm = body.includes('"confirm_unknown_retry":true');
      if (latest?.state === "unknown" && !confirm) return json(409, { code: "outcome_unknown", error: "unknown", notification: latest });
      const n = notificationAttempt({ id: l.notifications.length + 1, operation_id: key!, trigger: "explicit", pull_run_id: null, after_unknown: confirm, state: "sent" });
      l.notifications.unshift(n);
      server.sent!.set(key!, n);
      return json(201, n);
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
    expect(Object.keys(doc).sort()).toEqual(["capture_id", "original_context", "original_input", "schema_version", "source", "source_ref"]);
    // Mistake Notebook v1: the exact stored item, never the typed answer unless the learner includes it.
    expect((doc as unknown as { source_ref: unknown }).source_ref).toEqual({ type: "listening_item", record_id: 100, item: 2 });
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

  it("Pull now records new playlist videos as waiting for a transcript, and prepares nothing for them", async () => {
    const server: Server = { lessons: [], prepare: "ok", calls: [], daily: dailyOn, pull: "ok" };
    serve(server);
    const list = await openListening();
    const daily = screen.getByRole("region", { name: "Daily listening" });
    expect(within(daily).getByText(/at most 1 lesson per day \(Europe\/Paris\); 0 used on 2026-11-09/)).toBeInTheDocument();
    expect(within(daily).getByText("Notification: telegram, only for a lesson a pull prepared.")).toBeInTheDocument();
    expect(within(daily).getByText("No pull has run yet.")).toBeInTheDocument();
    expect(writes(server)).toEqual([]); // opening Listening sends nothing

    fireEvent.click(within(daily).getByRole("button", { name: "Pull now" }));
    expect(await within(daily).findByText("Playlist: 1 new (waiting for a transcript), 0 already known, 0 skipped.")).toBeInTheDocument();
    expect(within(daily).getByText("Preparation: nothing to prepare. Playlist videos need your transcript first.")).toBeInTheDocument();
    expect(within(daily).getByText("Notification: nothing to announce.")).toBeInTheDocument();
    const row = (await within(list).findByRole("button", { name: "Vidéo de la playlist" })).closest("li")!;
    expect(within(row).getByText("Waiting for a transcript")).toBeInTheDocument();
    expect(within(row).getByText("From your playlist")).toBeInTheDocument();

    const posts = writes(server);
    expect(posts.map((c) => c.path)).toEqual(["/api/listening/pull"]);
    expect(posts[0].key).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(posts[0].body).toBe("");
    expect(exercisePosts(server)).toEqual([]);
  });

  it("after a lost pull response, looks the key up and sends the same request again only on request", async () => {
    const server: Server = { lessons: [], prepare: "ok", calls: [], daily: dailyOn, pull: "lost" };
    serve(server);
    await openListening();
    const daily = screen.getByRole("region", { name: "Daily listening" });
    fireEvent.click(within(daily).getByRole("button", { name: "Pull now" }));
    expect(await within(daily).findByText(/No answer arrived, and nothing is recorded under this request yet/)).toBeInTheDocument();
    const first = writes(server)[0];
    expect(server.calls.filter((c) => c.method === "GET" && c.path === `/api/listening/pull-runs/${first.key}`)).toHaveLength(1);
    expect(writes(server)).toHaveLength(1); // nothing was resent by itself

    fireEvent.click(within(daily).getByRole("button", { name: "Send the same request again" }));
    expect(await within(daily).findByText("Playlist: 1 new (waiting for a transcript), 0 already known, 0 skipped.")).toBeInTheDocument();
    const posts = writes(server);
    expect(posts).toHaveLength(2);
    expect(posts[1].key).toBe(first.key); // the same key: the server can only replay it
  });

  it("says another pull is running and that nothing was started", async () => {
    const server: Server = { lessons: [], prepare: "ok", calls: [], daily: dailyOn, pull: "busy" };
    serve(server);
    await openListening();
    const daily = screen.getByRole("region", { name: "Daily listening" });
    fireEvent.click(within(daily).getByRole("button", { name: "Pull now" }));
    expect(await within(daily).findByText(/Another pull is running \(by the timer, started .*\)\. Nothing was started\./)).toBeInTheDocument();
    expect(writes(server)).toHaveLength(1);
  });

  it("shows when daily listening is off and offers no pull", async () => {
    const server: Server = { lessons: [], prepare: "ok", calls: [] };
    serve(server);
    await openListening();
    const daily = screen.getByRole("region", { name: "Daily listening" });
    expect(within(daily).getByText(/Daily listening is off/)).toBeInTheDocument();
    expect(within(daily).queryByRole("button", { name: "Pull now" })).toBeNull();
  });

  it("after a lost Prepare response, finds the stored result by its key instead of asking again", async () => {
    const server: Server = { lessons: [lesson()], prepare: "lost", calls: [] };
    serve(server);
    await openLesson();
    fireEvent.click(screen.getByRole("button", { name: "Prepare exercise" }));
    expect(await screen.findByRole("region", { name: "Listening exercise" })).toBeInTheDocument();
    const posts = exercisePosts(server);
    expect(posts).toHaveLength(1);
    expect(server.calls.filter((c) => c.path === `/api/listening/preparations/${posts[0].key}`)).toHaveLength(1);
  });

  it("an unknown preparation outcome needs an acknowledged retry", async () => {
    const failed: ListeningExercise = { ...completed(100), status: "failed", failure_code: "provider_timeout", content: null };
    const server: Server = {
      lessons: [lesson({ exercises: [failed], preparations: [preparation({ state: "unknown", exercise_id: 100 })], in_playlist: true })],
      prepare: "ok",
      calls: [],
    };
    serve(server);
    const list = await openListening();
    expect(await within(list).findByText("Outcome unknown")).toBeInTheDocument();
    fireEvent.click(within(list).getByRole("button", { name: material.title }));
    expect(await screen.findByText(/The last preparation's outcome is unknown: .* It may have been processed and billed\./)).toBeInTheDocument();
    expect(screen.queryByText(/The last preparation failed/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Prepare exercise" })).toBeNull();
    expect(screen.getByText("This video is in your daily playlist.")).toBeInTheDocument();
    expect(writes(server)).toEqual([]);

    fireEvent.click(screen.getByRole("button", { name: "Retry preparation (may be billed again)" }));
    expect(await screen.findByRole("region", { name: "Listening exercise" })).toBeInTheDocument();
    const posts = exercisePosts(server);
    expect(posts).toHaveLength(1);
    expect(JSON.parse(posts[0].body)).toEqual({ confirm_unknown_retry: true });
  });

  it("states an unknown notification delivery, and sends again only on an acknowledged request", async () => {
    const server: Server = {
      lessons: [lesson({ exercises: [completed()], notifications: [notificationAttempt({ state: "unknown", failure_code: "no_response", finished_at: "t" })] })],
      prepare: "ok",
      calls: [],
      daily: dailyOn,
    };
    serve(server);
    await openLesson();
    const section = screen.getByRole("region", { name: "Notifications" });
    expect(within(section).getByText("delivery unknown")).toBeInTheDocument();
    expect(within(section).getByText(/it may have arrived\. Send it again only if it did not\./)).toBeInTheDocument();
    expect(writes(server)).toEqual([]);

    fireEvent.click(within(section).getByRole("button", { name: "Send again anyway (it may arrive twice)" }));
    await waitFor(() => expect(within(screen.getByRole("region", { name: "Notifications" })).getByText("sent")).toBeInTheDocument());
    const posts = writes(server);
    expect(posts.map((c) => c.path)).toEqual(["/api/listening/exercises/100/notifications"]);
    expect(JSON.parse(posts[0].body)).toEqual({ confirm_unknown_retry: true });
    expect(posts[0].key).toMatch(/^[0-9a-f-]{36}$/);
    expect(screen.queryByRole("button", { name: /Send/ })).toBeNull(); // nothing left to retry
  });
});
