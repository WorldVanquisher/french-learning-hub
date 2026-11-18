// Speaking v1 in the private workbench, against a stateful fake server built
// from the authored fixture (test/speakingFixture), with a fake microphone and
// MediaRecorder. jsdom cannot record or play audio; the real-browser walkthrough
// (synthetic audio through Chromium's fake capture device) covers that.
import { StrictMode } from "react";
import { webcrypto } from "node:crypto";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import PublicDemoApp from "../PublicDemoApp";
import { exampleTranscript, feedbackV1, machineTranscript, notice, prompts, transcriptV1, transcriptV2 } from "../test/speakingFixture";
import { practiceFromWalk } from "../test/speakingPracticeFixture";
import type { SpeakingExerciseView, SpeakingFeedback, SpeakingPractice, SpeakingQueueItem, SpeakingRequest, SpeakingTranscript, SpeakingTranscription } from "../types/speaking";
import { followThrough, shownAsGrounded } from "./Speaking";
import { canonicalAudioType, classifyRecordingError } from "./speakingRecorder";
import { countWords } from "./Writing";

const TRANSCRIBER = "openai:fake-transcribe:speaking_transcription_v1";
const GENERATOR = "openai:fake-model:speaking_feedback_v1";
// A synthetic "recording": the WebM magic bytes and a short payload.
const WEBM = new Uint8Array([0x1a, 0x45, 0xdf, 0xa3, 1, 2, 3, 4, 5, 6, 7, 8]);
const WEBM_B64 = btoa(String.fromCharCode(...WEBM));

type Mode = "ok" | "fail" | "disabled";
type Call = { method: string; path: string; body: string; key: string | null };
type Server = {
  exercises: SpeakingExerciseView[];
  // Source items already saved as records (Mistake Notebook): type:record:item → entry.
  savedSources: Map<string, number>;
  transcription: Mode;
  feedback: Mode;
  calls: Call[];
  ids: number;
  // The practice overview to answer; by default a minimal one built from the exercises.
  practice?: SpeakingPractice;
  // Failure injection for the next POST whose path matches: `lose` handles it,
  // then the answer never arrives; `drop` never reaches the server.
  lose?: RegExp;
  drop?: RegExp;
};

const newServer = (over: Partial<Server> = {}): Server => ({ exercises: [], savedSources: new Map(), transcription: "ok", feedback: "ok", calls: [], ids: 1000, ...over });
const invitation = prompts[0];
const limits = {
  max_audio_bytes: 8 << 20,
  max_duration_ms: 120_000,
  accepted_types: ["audio/webm", "audio/mp4", "audio/mpeg", "audio/wav"],
  max_transcript_chars: 2000,
  max_takes: 20,
  max_transcript_versions: 10,
};

function exerciseView(id: number): SpeakingExerciseView {
  return {
    exercise: {
      id,
      prompt_id: invitation.id,
      title: invitation.title,
      situation: invitation.situation,
      requirements: invitation.requirements,
      seconds_min: invitation.seconds_min,
      seconds_max: invitation.seconds_max,
      created_at: "t",
      prompt_set: "flh_speaking_prompts_v1",
      content_fingerprint: "f".repeat(64),
      pack_status: "current",
    },
    takes: [],
    transcriptions: [],
    transcription_requests: [],
    transcripts: [],
    feedback: [],
    feedback_requests: [],
    example_transcript: exampleTranscript,
    providers: { transcription: { enabled: true, name: TRANSCRIBER }, feedback: { enabled: true, name: GENERATOR } },
    limits,
    word_convention: "w",
  };
}

// withTypedTake builds an exercise whose take 1 has confirmed transcripts.
function withTypedTake(id: number, texts: string[]): SpeakingExerciseView {
  const v = exerciseView(id);
  v.takes.push({ id: 11, number: 1, audio_source: "none", audio_mime: null, audio_bytes: null, audio_sha256: null, duration_ms: null, created_at: "t" });
  texts.forEach((text, i) => v.transcripts.push({ id: 21 + i, take_id: 11, version: i + 1, text, word_count: countWords(text), origin: i ? "corrected" : "typed", transcription_id: null, created_at: "t" }));
  return v;
}

function serve(server: Server) {
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const providers = () => ({
    transcription: server.transcription === "disabled" ? { enabled: false, name: null } : { enabled: true, name: TRANSCRIBER },
    feedback: server.feedback === "disabled" ? { enabled: false, name: null } : { enabled: true, name: GENERATOR },
  });
  const view = (v: SpeakingExerciseView) => ({ ...v, providers: providers() });
  const byTake = (takeId: number) => server.exercises.find((v) => v.takes.some((k) => k.id === takeId))!;
  const byTranscript = (id: number) => server.exercises.find((v) => v.transcripts.some((s) => s.id === id))!;
  const byKey = new Map<string, unknown>();
  const handle = async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const body = String(init?.body ?? "");
    const key = (init?.headers as Record<string, string> | undefined)?.["Idempotency-Key"] ?? null;
    server.calls.push({ method, path: url.pathname, body, key });
    const p = url.pathname;
    let m: RegExpExecArray | null;
    if (method === "GET" && p === "/api/speaking/prompts")
      return json(200, {
        set: "flh_speaking_prompts_v1",
        notice,
        prompts: prompts.map((x) => ({ ...x, started_exercise_id: server.exercises.find((v) => v.exercise.prompt_id === x.id)?.exercise.id ?? null })),
        providers: providers(),
        limits,
      });
    if ((m = /^\/api\/speaking\/prompts\/(.+)$/.exec(p)) && method === "POST") {
      const existing = server.exercises.find((v) => v.exercise.prompt_id === m![1]);
      if (existing) return json(200, view(existing));
      const v = exerciseView(server.exercises.length + 1);
      server.exercises.push(v);
      return json(201, view(v));
    }
    if (method === "GET" && p === "/api/speaking/practice") {
      const takes = server.exercises.reduce((n, v) => n + v.takes.length, 0);
      const fallback: SpeakingPractice = {
        schema_version: "speaking_practice_v1",
        generated_at: "t",
        summary: { prompts: prompts.length, started: server.exercises.length, takes, completed: 0, exercises_completed: 0, awaiting_transcript: takes, awaiting_feedback: 0, in_progress: 0, failed: 0, unknown: 0, last_completed_at: null },
        queue: prompts
          .filter((x) => !server.exercises.some((v) => v.exercise.prompt_id === x.id))
          .map((x) => ({ reason: "not_started" as const, priority: 9, prompt_id: x.id, title: x.title, exercise_id: null, take_id: null, take_number: null, state: null, improvements: 0, since: null, request: null, request_enabled: false, pack_status: null })),
        resume: null,
        exercises: [],
        providers: providers(),
      };
      return json(200, server.practice ?? fallback);
    }
    if (method === "GET" && p === "/api/speaking/exercises")
      return json(200, { providers: providers(), exercises: server.exercises.map((v) => ({ exercise: v.exercise, takes: v.takes.length })) });
    if ((m = /^\/api\/speaking\/exercises\/(\d+)$/.exec(p)) && method === "GET") {
      const v = server.exercises.find((x) => x.exercise.id === Number(m![1]));
      return v ? json(200, view(v)) : json(404, { error: "not found" });
    }
    if ((m = /^\/api\/speaking\/exercises\/(\d+)\/takes$/.exec(p)) && method === "POST") {
      const v = server.exercises.find((x) => x.exercise.id === Number(m![1]))!;
      const t = JSON.parse(body) as { audio_source: "recording" | "file" | "none"; audio_mime?: string; audio_bytes?: number; audio_sha256?: string; duration_ms?: number };
      // The backend's replay rules: the same audio, or a typed save while the
      // latest take is an empty typed take, names the existing take.
      const last = v.takes.at(-1);
      const same =
        t.audio_source === "none"
          ? last?.audio_source === "none" && !v.transcripts.some((s) => s.take_id === last.id)
            ? last
            : undefined
          : v.takes.find((k) => k.audio_sha256 === t.audio_sha256);
      if (same) return json(200, { ...view(v), take_id: same.id, replayed: true });
      v.takes.push({
        id: ++server.ids,
        number: v.takes.length + 1,
        audio_source: t.audio_source,
        audio_mime: t.audio_mime ? canonicalAudioType(t.audio_mime) : null,
        audio_bytes: t.audio_bytes ?? null,
        audio_sha256: t.audio_sha256 ?? null,
        duration_ms: t.duration_ms ?? null,
        created_at: "t",
      });
      return json(201, { ...view(v), take_id: server.ids, replayed: false });
    }
    if ((m = /^\/api\/speaking\/takes\/(\d+)\/transcriptions$/.exec(p)) && method === "POST") {
      const takeId = Number(m[1]);
      const v = byTake(takeId);
      if (server.transcription === "disabled") return json(503, { error: "speaking transcription is not enabled" });
      const failed = server.transcription === "fail";
      const tr: SpeakingTranscription = {
        id: ++server.ids,
        take_id: takeId,
        status: failed ? "failed" : "completed",
        failure_code: failed ? "provider_unavailable" : null,
        transcriber: TRANSCRIBER,
        text: failed ? null : machineTranscript,
        created_at: "t",
      };
      const req: SpeakingRequest = { id: ++server.ids, operation_id: key ?? "k", take_id: takeId, after_unknown: false, started_at: "t", deadline_at: "t", finished_at: "t", state: failed ? "failed" : "completed", result_id: tr.id };
      v.transcriptions.unshift(tr);
      v.transcription_requests.unshift(req);
      byKey.set(key ?? "k", { request: req, transcription: tr });
      return failed ? json(502, { error: "provider failed", request: req, transcription: tr }) : json(201, { request: req, transcription: tr });
    }
    if ((m = /^\/api\/speaking\/takes\/(\d+)\/transcripts$/.exec(p)) && method === "POST") {
      const takeId = Number(m[1]);
      const v = byTake(takeId);
      const req = JSON.parse(body) as { text: string; transcription_id: number | null };
      const versions = v.transcripts.filter((s) => s.take_id === takeId);
      if (versions.at(-1)?.text === req.text) return json(409, { code: "unchanged", error: "unchanged" });
      const machine = v.transcriptions.find((x) => x.id === req.transcription_id);
      const origin: SpeakingTranscript["origin"] = machine ? (machine.text === req.text ? "transcription" : "corrected") : versions.length ? "corrected" : "typed";
      v.transcripts.push({ id: ++server.ids, take_id: takeId, version: versions.length + 1, text: req.text, word_count: countWords(req.text), origin, transcription_id: req.transcription_id, created_at: "t" });
      v.transcripts.sort((a, b) => a.take_id - b.take_id || a.version - b.version);
      return json(201, view(v));
    }
    if ((m = /^\/api\/speaking\/transcripts\/(\d+)\/feedback$/.exec(p)) && method === "POST") {
      const id = Number(m[1]);
      const v = byTranscript(id);
      if (server.feedback === "disabled") return json(503, { error: "speaking feedback is not enabled" });
      const failed = server.feedback === "fail";
      const fb: SpeakingFeedback = {
        id: ++server.ids,
        transcript_id: id,
        status: failed ? "failed" : "completed",
        failure_code: failed ? "invalid_output" : null,
        generator: GENERATOR,
        created_at: "t",
        content: failed ? null : feedbackV1,
      };
      const req: SpeakingRequest = { id: ++server.ids, operation_id: key ?? "k", transcript_id: id, after_unknown: false, started_at: "t", deadline_at: "t", finished_at: "t", state: failed ? "failed" : "completed", result_id: fb.id };
      v.feedback.unshift(fb);
      v.feedback_requests.unshift(req);
      return failed ? json(502, { error: "provider failed", request: req, feedback: fb }) : json(201, { request: req, feedback: fb });
    }
    if ((m = /^\/api\/speaking\/(transcription|feedback)-requests\/(.+)$/.exec(p)) && method === "GET") {
      const r = byKey.get(decodeURIComponent(m[2]));
      return r ? json(200, r) : json(404, { error: "nothing recorded" });
    }
    if (p === "/api/captures" && method === "POST") {
      const doc = JSON.parse(body) as { capture_id: string; source_ref?: { type: string; record_id: number; item: number } };
      const key = doc.source_ref ? `${doc.source_ref.type}:${doc.source_ref.record_id}:${doc.source_ref.item}` : "";
      const existing = key ? server.savedSources.get(key) : undefined;
      if (existing !== undefined) return json(409, { error: "already saved", code: "source_already_saved", entry_id: existing });
      if (key) server.savedSources.set(key, 77);
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
  };
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const post = (init?.method ?? "GET").toUpperCase() === "POST";
    const path = new URL(String(input), "http://localhost").pathname;
    if (post && server.drop?.test(path)) {
      server.drop = undefined;
      throw new TypeError("Failed to fetch");
    }
    const res = await handle(input, init);
    if (post && server.lose?.test(path)) {
      server.lose = undefined;
      throw new TypeError("Failed to fetch");
    }
    return res;
  }) as unknown as typeof fetch;
}

// ---- a fake microphone and recorder ----

type Mic = { mode: "grant" | "deny" | "missing"; asked: number; recorders: FakeRecorder[] };
let mic: Mic;

class FakeRecorder {
  static isTypeSupported = (t: string) => t.startsWith("audio/webm");
  state: "inactive" | "recording" = "inactive";
  mimeType: string;
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(_stream: unknown, opts?: { mimeType?: string }) {
    this.mimeType = opts?.mimeType ?? "audio/webm";
    mic.recorders.push(this);
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob([WEBM], { type: this.mimeType }) });
    this.onstop?.();
  }
}

function installMedia(mode: Mic["mode"], recorder = true) {
  mic = { mode, asked: 0, recorders: [] };
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn(async () => {
        mic.asked++;
        if (mic.mode === "deny") throw Object.assign(new Error("Permission denied"), { name: "NotAllowedError" });
        if (mic.mode === "missing") throw Object.assign(new Error("Requested device not found"), { name: "NotFoundError" });
        return { getTracks: () => [{ stop: () => undefined }] };
      }),
    },
  });
  if (recorder) vi.stubGlobal("MediaRecorder", FakeRecorder);
  else vi.stubGlobal("MediaRecorder", undefined);
}

beforeEach(() => {
  if (!globalThis.crypto?.subtle) vi.stubGlobal("crypto", webcrypto);
  URL.createObjectURL = vi.fn(() => "blob:take");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

const writes = (s: Server) => s.calls.filter((c) => c.method !== "GET");
const speakingWrites = (s: Server) => writes(s).filter((c) => c.path.startsWith("/api/speaking"));

async function openExercise(server: Server) {
  render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Speaking" }));
  const promptsRegion = await screen.findByRole("region", { name: "Speaking prompts" });
  const row = (await within(promptsRegion).findByText(invitation.title)).closest("li")!;
  const started = server.exercises.length > 0;
  fireEvent.click(within(row).getByRole("button", { name: started ? "Open" : "Start" }));
  await screen.findByRole("heading", { name: invitation.title });
  return screen.getByRole("region", { name: "New take" });
}

describe("Speaking helpers", () => {
  it("accepts only audio types both provider pages list", () => {
    expect(canonicalAudioType("audio/webm;codecs=opus")).toBe("audio/webm");
    expect(canonicalAudioType("audio/x-m4a")).toBe("audio/mp4");
    expect(canonicalAudioType("audio/ogg;codecs=opus")).toBeNull();
    expect(canonicalAudioType("audio/flac")).toBeNull();
  });

  it("tells a refused permission from a missing device", () => {
    expect(classifyRecordingError({ name: "NotAllowedError" })).toBe("denied");
    expect(classifyRecordingError({ name: "NotFoundError" })).toBe("no_device");
    expect(classifyRecordingError(new Error("x"))).toBe("failed");
  });

  it("never shows a quote as grounded unless it occurs in the transcript as the server says", () => {
    const [located, , ambiguous, missing] = feedbackV1.improvements;
    expect(shownAsGrounded(transcriptV1, located)).toBe(true);
    expect(shownAsGrounded(transcriptV1, ambiguous)).toBe(true);
    expect(shownAsGrounded(transcriptV1, missing)).toBe(false);
    expect(shownAsGrounded(transcriptV1, { ...ambiguous, grounding: "located" })).toBe(false);
  });
});

describe("Speaking (private workbench)", () => {
  it("says so when microphone permission is refused, records nothing, sends nothing, and keeps both fallbacks", async () => {
    installMedia("deny");
    const server = newServer();
    serve(server);
    const panel = await openExercise(server);
    fireEvent.click(within(panel).getByRole("button", { name: "Start recording" }));
    expect(await within(panel).findByRole("alert")).toHaveTextContent("Microphone permission was refused, so nothing was recorded.");
    expect(mic.asked).toBe(1);
    expect(mic.recorders).toHaveLength(0);
    expect(within(panel).getByText("Upload an audio file")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Type what you said instead" })).toBeInTheDocument();
    expect(speakingWrites(server).map((c) => c.path)).toEqual(["/api/speaking/prompts/sp-invitation-reponse"]);

    // The typed fallback: a take with no audio, then the learner's own transcript.
    fireEvent.click(within(panel).getByRole("button", { name: "Type what you said instead" }));
    const editor = await screen.findByRole("form", { name: "Transcript of take 1" });
    expect(JSON.parse(speakingWrites(server)[1].body)).toEqual({ audio_source: "none" });
    expect(screen.getByText("Typed take: no audio.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /for transcription/ })).toBeNull();
    fireEvent.click(within(editor).getByRole("button", { name: "Use the example transcript" }));
    fireEvent.click(within(editor).getByRole("button", { name: "Confirm as version 1" }));
    expect(await screen.findByLabelText("Take 1, transcript version 1")).toHaveTextContent(exampleTranscript);
    expect(screen.getByRole("button", { name: "v1 · typed" })).toHaveAttribute("aria-pressed", "true");
  });

  it("offers the file and typed fallbacks in a browser that cannot record", async () => {
    installMedia("grant", false);
    const server = newServer();
    serve(server);
    const panel = await openExercise(server);
    expect(within(panel).getByRole("status")).toHaveTextContent("This browser cannot record audio here.");
    expect(within(panel).queryByRole("button", { name: "Start recording" })).toBeNull();
    // An ogg file is refused before anything is sent.
    const input = panel.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File([WEBM], "take.ogg", { type: "audio/ogg" })] } });
    expect(await within(panel).findByRole("alert")).toHaveTextContent("This file type is not accepted. Accepted: audio/webm, audio/mp4, audio/mpeg, audio/wav.");
    expect(speakingWrites(server)).toHaveLength(1);
  });

  it("records and plays back with no request, stores only metadata, and sends audio only after the confirmation panel", async () => {
    installMedia("grant");
    const server = newServer();
    serve(server);
    const panel = await openExercise(server);
    const before = server.calls.length;
    fireEvent.click(within(panel).getByRole("button", { name: "Start recording" }));
    fireEvent.click(await within(panel).findByRole("button", { name: "Stop" }));
    const preview = await within(panel).findByRole("group", { name: "Recorded take, not saved yet" });
    expect(within(preview).getByLabelText("Play back this take")).toHaveAttribute("src", "blob:take");
    expect(within(preview).getByText("Listen to it as often as you like. Nothing has been sent.")).toBeInTheDocument();
    // Recording and playback made no request at all.
    expect(server.calls.length).toBe(before);

    fireEvent.click(within(preview).getByRole("button", { name: "Use as take 1" }));
    const take = await screen.findByRole("region", { name: "Take 1" });
    const meta = JSON.parse(speakingWrites(server)[1].body);
    expect(meta).toEqual({ audio_source: "recording", audio_mime: "audio/webm;codecs=opus", audio_bytes: WEBM.length, audio_sha256: expect.stringMatching(/^[0-9a-f]{64}$/), duration_ms: expect.any(Number) });
    expect(speakingWrites(server)[1].body).not.toContain(WEBM_B64);
    expect(within(take).getByLabelText("Play back take 1")).toBeInTheDocument();

    // The transcription button opens a panel that says what is sent; Cancel sends nothing.
    fireEvent.click(within(take).getByRole("button", { name: "Send audio of take 1 for transcription…" }));
    const confirm = within(take).getByRole("alertdialog", { name: "Confirm sending audio" });
    expect(confirm).toHaveTextContent(`This sends the audio of take 1 (0:00, 1 KB, audio/webm) once to ${TRANSCRIBER}. The request may be billed.`);
    expect(confirm).toHaveTextContent("not stored on this server");
    fireEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(speakingWrites(server)).toHaveLength(2);
    fireEvent.click(within(take).getByRole("button", { name: "Send audio of take 1 for transcription…" }));
    fireEvent.click(within(take).getByRole("button", { name: "Send audio" }));
    // The editor is rebuilt once the machine transcript arrives; read it afresh.
    await waitFor(() => expect((screen.getByLabelText("Transcript of take 1, version 1") as HTMLTextAreaElement).value).toBe(machineTranscript));
    const editor = within(take).getByRole("form", { name: "Transcript of take 1" });
    const sent = speakingWrites(server)[2];
    expect(sent.path).toBe(`/api/speaking/takes/${server.exercises[0].takes[0].id}/transcriptions`);
    expect(sent.key).toMatch(/^[0-9a-f-]{36}$/);
    expect(JSON.parse(sent.body)).toEqual({ audio_base64: WEBM_B64, audio_mime: "audio/webm;codecs=opus", confirm_unknown_retry: false });

    // The machine transcript is prefilled; the learner corrects the slip and confirms.
    fireEvent.change(within(editor).getByLabelText("Transcript of take 1, version 1"), { target: { value: transcriptV1 } });
    fireEvent.click(within(editor).getByRole("button", { name: "Confirm as version 1" }));
    expect(await within(take).findByRole("button", { name: "v1 · corrected" })).toBeInTheDocument();
    const confirmed = JSON.parse(speakingWrites(server)[3].body);
    expect(confirmed).toEqual({ text: transcriptV1, transcription_id: server.exercises[0].transcriptions[0].id });
    // No feedback was requested by any of this.
    expect(server.calls.some((c) => c.path.endsWith("/feedback"))).toBe(false);
  });

  it("shows a failed request, keeps feedback on its version after a correction, and saves a mistake only on explicit confirmation", async () => {
    installMedia("grant");
    const server = newServer({ exercises: [withTypedTake(1, [transcriptV1])], feedback: "fail" });
    serve(server);
    await openExercise(server);
    const take = screen.getByRole("region", { name: "Take 1" });
    fireEvent.click(within(take).getByRole("button", { name: "Request feedback on version 1" }));
    expect(await within(take).findByText("The last request failed: the answer was not usable. Nothing was retried.")).toBeInTheDocument();
    expect(within(take).getByLabelText("Take 1, transcript version 1")).toHaveTextContent(transcriptV1);

    server.feedback = "ok";
    fireEvent.click(within(take).getByRole("button", { name: "Request feedback on version 1" }));
    const report = await within(take).findByRole("group", { name: "Feedback report for take 1, version 1" });
    expect(report).toHaveTextContent(`About take 1, transcript version 1 (${GENERATOR}).`);
    expect(report).toHaveTextContent("nothing here is about pronunciation");
    const i1 = within(report).getByRole("group", { name: "Improvement 1" });
    expect(within(i1).getByText(feedbackV1.improvements[0].hint_en)).toBeInTheDocument();
    expect(screen.queryByText(feedbackV1.improvements[0].suggestion)).toBeNull();
    fireEvent.click(within(i1).getByRole("button", { name: "Show in version 1" }));
    expect(within(take).getByLabelText("Take 1, transcript version 1").querySelector("mark")?.textContent).toBe(feedbackV1.improvements[0].quote);
    expect(within(report).queryByRole("group", { name: "Improvement 4" })).toBeNull();
    expect(within(report).getByRole("region", { name: "Not found in this transcript" })).toHaveTextContent(feedbackV1.improvements[3].quote);

    // Correct the transcript: version 2 has no feedback; version 1's report stays on version 1.
    const editor = within(take).getByRole("form", { name: "Transcript of take 1" });
    fireEvent.change(within(editor).getByLabelText("Transcript of take 1, version 2"), { target: { value: transcriptV2 } });
    fireEvent.click(within(editor).getByRole("button", { name: "Confirm as version 2" }));
    expect(await within(take).findByRole("button", { name: "v2 · corrected" })).toHaveAttribute("aria-pressed", "true");
    expect(within(take).queryByRole("group", { name: /Feedback report/ })).toBeNull();
    expect(within(take).getByText("Other versions of this take have their own feedback (v1). It is not shown here.")).toBeInTheDocument();
    fireEvent.click(within(take).getByRole("button", { name: "v1 · typed" }));
    const again = await within(take).findByRole("group", { name: "Feedback report for take 1, version 1" });
    expect(again).toHaveTextContent("About take 1, transcript version 1");
    const feedbackPosts = server.calls.filter((c) => c.method === "POST" && c.path.endsWith("/feedback"));
    expect(feedbackPosts.map((c) => c.path)).toEqual(["/api/speaking/transcripts/21/feedback", "/api/speaking/transcripts/21/feedback"]);

    // Revealing, highlighting and opening the form create nothing.
    const item = within(again).getByRole("group", { name: "Improvement 1" });
    fireEvent.click(within(item).getByRole("button", { name: "Show suggested wording" }));
    fireEvent.click(within(item).getByRole("button", { name: "Save this mistake…" }));
    expect(server.calls.some((c) => c.path === "/api/captures")).toBe(false);
    const form = within(item).getByRole("form", { name: "Save improvement 1 as a learning record" });
    fireEvent.change(within(form).getByLabelText("How you would say it now"), { target: { value: "j'arriverai vers midi et demi" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save learning record" }));
    expect(await within(item).findByText("Saved as learning record #77.")).toBeInTheDocument();
    const captures = server.calls.filter((c) => c.path === "/api/captures");
    expect(captures).toHaveLength(1);
    const doc = JSON.parse(captures[0].body);
    expect(doc.source).toBe("manual");
    expect(doc.capture_id).toMatch(/^speaking-1-21-\d+-1-/);
    expect(doc.original_input).toContain("« je suis arrivé vers midi et demi » → « j'arriverai vers midi et demi »");
    expect(doc.original_context).toContain(`Speaking exercise #1: ${invitation.title} (authored prompt ${invitation.id})`);
    expect(doc.original_context).toContain("Take 1, transcript version 1 (typed)");
    expect(doc.original_context).toContain("not a pronunciation judgment");
    // Mistake Notebook v1: the exact stored improvement, by report and position.
    const reportId = Number(/^speaking-1-21-(\d+)-1-/.exec(doc.capture_id)![1]);
    expect(doc.source_ref).toEqual({ type: "speaking_improvement", record_id: reportId, item: 1 });
    // The record opens in Learning Records, with a way back to Speaking.
    fireEvent.click(within(item).getByRole("button", { name: "Open record #77 in Learning Records" }));
    fireEvent.click(await screen.findByRole("button", { name: "← Back to Speaking" }));
    expect(await screen.findByRole("region", { name: "Take 1" })).toBeInTheDocument();
  });

  it("names the existing record when the same improvement was already saved, and saves nothing new", async () => {
    installMedia("grant");
    const v = withTypedTake(1, [transcriptV1]);
    v.feedback.push({ id: 900, transcript_id: 21, status: "completed", failure_code: null, generator: GENERATOR, created_at: "t", content: feedbackV1 });
    const server = newServer({ exercises: [v], savedSources: new Map([["speaking_improvement:900:1", 55]]) });
    serve(server);
    await openExercise(server);
    const item = within(screen.getByRole("group", { name: "Feedback report for take 1, version 1" })).getByRole("group", { name: "Improvement 1" });
    fireEvent.click(within(item).getByRole("button", { name: "Save this mistake…" }));
    const form = within(item).getByRole("form", { name: "Save improvement 1 as a learning record" });
    expect(form).toHaveTextContent("It is saved with a link to this exact item");
    fireEvent.change(within(form).getByLabelText("How you would say it now"), { target: { value: "j'arriverai" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save learning record" }));
    expect(await within(item).findByText("This item is already saved as learning record #55 (in your Mistake Notebook). Nothing new was saved.")).toBeInTheDocument();
    expect(within(item).getByRole("button", { name: "Open record #55 in Learning Records" })).toBeInTheDocument();
  });

  it("compares confirmed transcripts of two takes, from the earlier to the later", async () => {
    installMedia("grant");
    const v = withTypedTake(1, [transcriptV1]);
    v.takes.push({ id: 12, number: 2, audio_source: "none", audio_mime: null, audio_bytes: null, audio_sha256: null, duration_ms: null, created_at: "t" });
    const better = transcriptV1.replace("je suis arrivé vers midi et demi", "j'arriverai vers midi et demi");
    v.transcripts.push({ id: 31, take_id: 12, version: 1, text: better, word_count: countWords(better), origin: "typed", transcription_id: null, created_at: "t" });
    const server = newServer({ exercises: [v] });
    serve(server);
    await openExercise(server);
    const compare = screen.getByRole("region", { name: "Compare confirmed transcripts" });
    expect(within(compare).getByRole("heading")).toHaveTextContent("Compare: Take 1 · v1 → Take 2 · v1");
    const diff = within(compare).getByLabelText("Word differences");
    expect(diff.querySelector("del")?.textContent).toBe("je suis arrivé");
    expect(diff.querySelector("ins")?.textContent).toBe("j'arriverai");
    expect(speakingWrites(server)).toEqual([]);
  });

  it("looks each point of the earlier feedback up in the later transcript, as a text check only", async () => {
    installMedia("grant");
    const v = withTypedTake(1, [transcriptV1]);
    v.feedback.push({ id: 41, transcript_id: 21, status: "completed", failure_code: null, generator: GENERATOR, created_at: "t", content: feedbackV1 });
    v.takes.push({ id: 12, number: 2, audio_source: "none", audio_mime: null, audio_bytes: null, audio_sha256: null, duration_ms: null, created_at: "t" });
    // Take 2 uses two suggestions (one typed with a curly apostrophe) and keeps "très"; the last point
    // ("je viendrai avec plaisir") is in neither transcript.
    const later = transcriptV1
      .replace("je suis arrivé vers midi et demi", "j’arriverai vers midi et demi")
      .replace("Je vais amener un dessert", "Je vais apporter un dessert");
    v.transcripts.push({ id: 31, take_id: 12, version: 1, text: later, word_count: countWords(later), origin: "typed", transcription_id: null, created_at: "t" });
    const server = newServer({ exercises: [v] });
    serve(server);
    await openExercise(server);
    const compare = screen.getByRole("region", { name: "Compare confirmed transcripts" });
    const follow = within(compare).getByRole("region", { name: "Points from the feedback on Take 1 · v1, looked up in Take 2 · v1" });
    expect(follow).toHaveTextContent("A text check only: whether Take 2 · v1 contains the suggested wording, or still contains the quoted words.");
    const items = within(follow).getAllByRole("listitem");
    expect(items.map((li) => li.getAttribute("data-follow"))).toEqual(["used", "used", "still", "gone"]);
    expect(items[3]).toHaveTextContent("Neither appears: said differently, or left out.");
    expect(items[0]).toHaveTextContent("The suggested wording appears.");
    expect(items[2]).toHaveTextContent("The quoted words are still there.");
    // Reversing the choice keeps the direction: the earlier version's feedback, the later text.
    fireEvent.change(within(compare).getByLabelText("One"), { target: { value: "31" } });
    fireEvent.change(within(compare).getByLabelText("Other"), { target: { value: "21" } });
    expect(within(compare).getByRole("region", { name: "Points from the feedback on Take 1 · v1, looked up in Take 2 · v1" })).toBeInTheDocument();
    expect(speakingWrites(server)).toEqual([]);
  });

  it("follow-through: suggestion first, then the quote, with apostrophes and spaces normalised", () => {
    const k = (quote: string, suggestion: string) => ({ ...feedbackV1.improvements[0], quote, suggestion });
    expect(followThrough([k("au pomme", "aux pommes"), k("très", "vraiment"), k("amener", "apporter"), k("c'est", "")], "une tarte  aux pommes, très bon, c’est")).toEqual([
      "used",
      "still",
      "gone",
      "still",
    ]);
  });

  it("works with both providers off: typed transcripts and comparison, no transcription or feedback button", async () => {
    installMedia("grant");
    const server = newServer({ exercises: [withTypedTake(1, [transcriptV1])], transcription: "disabled", feedback: "disabled" });
    serve(server);
    await openExercise(server);
    const take = screen.getByRole("region", { name: "Take 1" });
    expect(within(take).getByText("Feedback is off (SPEAKING_PROVIDER). Recording, transcripts and comparison still work.")).toBeInTheDocument();
    expect(within(take).queryByRole("button", { name: /Request feedback/ })).toBeNull();
    // The next step is a self-review against the wording this exercise keeps, on this page only.
    const review = within(take).getByRole("group", { name: "Review take 1, version 1 yourself" });
    const boxes = within(review).getAllByRole("checkbox");
    expect(boxes).toHaveLength(invitation.requirements.length);
    expect(review).toHaveTextContent(invitation.requirements[0]);
    expect(review).toHaveTextContent("Then record take 2 at the top of this page, covering what is missing.");
    fireEvent.click(boxes[0]);
    expect(boxes[0]).toBeChecked();
    expect(speakingWrites(server)).toEqual([]);
  });

  it("is never offered in the public demo", async () => {
    installMedia("grant");
    serve(newServer());
    render(<PublicDemoApp />);
    await screen.findByText(/synthetic/i);
    expect(screen.queryByRole("button", { name: "Speaking" })).toBeNull();
    expect(screen.queryByText(/Record a take/)).toBeNull();
  });
});

// Queue steps as the backend sends them (speaking_practice_v1).
const addTypedTranscript: SpeakingQueueItem = {
  reason: "add_transcript", priority: 3, prompt_id: invitation.id, title: invitation.title, exercise_id: 1, take_id: 12, take_number: 2,
  state: "awaiting_transcript", improvements: 0, since: "t", request: null, request_enabled: false, pack_status: "current",
};
const notStarted: SpeakingQueueItem = {
  reason: "not_started", priority: 9, prompt_id: "sp-demande-renseignements", title: "Demander des renseignements", exercise_id: null, take_id: null,
  take_number: null, state: null, improvements: 0, since: null, request: null, request_enabled: false, pack_status: null,
};

describe("Speaking practice overview and attempt history", () => {
  const sha = async (bytes: Uint8Array) =>
    Array.from(new Uint8Array(await webcrypto.subtle.digest("SHA-256", bytes)), (b) => b.toString(16).padStart(2, "0")).join("");

  it("counts only completed takes, explains each next step, and opens the exercise at the take concerned", async () => {
    installMedia("grant");
    const v = withTypedTake(1, [transcriptV1]);
    v.takes.push({ id: 12, number: 2, audio_source: "none", audio_mime: null, audio_bytes: null, audio_sha256: null, duration_ms: null, created_at: "t" });
    const server = newServer({ exercises: [v] });
    server.practice = {
      schema_version: "speaking_practice_v1",
      generated_at: "t",
      summary: { prompts: 3, started: 1, takes: 2, completed: 1, exercises_completed: 1, awaiting_transcript: 1, awaiting_feedback: 0, in_progress: 0, failed: 0, unknown: 0, last_completed_at: "2026-11-17T10:00:00Z" },
      queue: [addTypedTranscript, notStarted],
      resume: addTypedTranscript,
      exercises: [],
      providers: { transcription: { enabled: true, name: TRANSCRIBER }, feedback: { enabled: true, name: GENERATOR } },
    };
    serve(server);
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Speaking" }));
    const overview = await screen.findByRole("region", { name: "Speaking practice overview" });
    expect(await within(overview).findByText("Completed takes (feedback on the latest checked transcript): 1 of 2")).toBeInTheDocument();
    expect(within(overview).getByText(/Waiting for a transcript: 1 · Waiting for feedback: 0/)).toBeInTheDocument();
    expect(within(overview).getByText(/Only a take whose latest checked transcript has feedback counts as completed/)).toBeInTheDocument();
    const items = within(overview).getAllByRole("listitem").filter((li) => li.hasAttribute("data-reason"));
    expect(items.map((li) => li.getAttribute("data-reason"))).toEqual(["add_transcript", "not_started"]);
    expect(items[0]).toHaveTextContent("Take 2: type what you said.");
    expect(within(items[1]).getByRole("button", { name: "Start" })).toBeInTheDocument();
    expect(within(overview).getByRole("link", { name: "Download all attempts (NDJSON)" })).toHaveAttribute("href", "/api/speaking/export");
    fireEvent.click(within(items[0]).getByRole("button", { name: "Open" }));
    await screen.findByRole("heading", { name: invitation.title });
    expect(within(screen.getByRole("group", { name: "Choose a take" })).getByRole("button", { name: "Take 2" })).toHaveAttribute("aria-pressed", "true");
    expect(speakingWrites(server)).toEqual([]);
  });

  it("keeps every started exercise actionable when feedback or transcription is off, failed, unknown or running", async () => {
    installMedia("grant");
    const server = newServer({ exercises: [withTypedTake(1, [transcriptV1])] });
    const item = (over: Partial<SpeakingQueueItem>): SpeakingQueueItem => ({ ...addTypedTranscript, ...over });
    const review = item({ reason: "review_without_feedback", priority: 5, take_id: 11, take_number: 1, state: "awaiting_feedback", request: "feedback", pack_status: "changed" });
    server.practice = {
      schema_version: "speaking_practice_v1",
      generated_at: "t",
      summary: { prompts: 3, started: 3, takes: 4, completed: 0, exercises_completed: 0, awaiting_transcript: 0, awaiting_feedback: 1, in_progress: 1, failed: 1, unknown: 1, last_completed_at: null },
      queue: [
        item({ reason: "check_unknown_outcome", priority: 0, prompt_id: "p-b", title: "B", exercise_id: 2, take_id: 21, take_number: 1, state: "transcription_unknown", request: "transcription" }),
        item({ reason: "request_failed", priority: 1, prompt_id: "p-c", title: "C", exercise_id: 3, take_id: 31, take_number: 2, state: "feedback_failed", request: "feedback" }),
        review,
        item({ reason: "request_in_progress", priority: 8, prompt_id: "p-d", title: "D", exercise_id: 4, take_id: 41, take_number: 1, state: "feedback_in_progress", request: "feedback", request_enabled: true }),
      ],
      resume: review,
      exercises: [],
      providers: { transcription: { enabled: false, name: null }, feedback: { enabled: false, name: null } },
    };
    serve(server);
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Speaking" }));
    const overview = await screen.findByRole("region", { name: "Speaking practice overview" });
    const items = (await within(overview).findAllByRole("listitem")).filter((li) => li.hasAttribute("data-reason"));
    expect(items.map((li) => li.getAttribute("data-reason"))).toEqual(["check_unknown_outcome", "request_failed", "review_without_feedback", "request_in_progress"]);
    expect(items[0]).toHaveTextContent("Take 1: the outcome of its transcription request is unknown, and transcription is off now. Type what you said instead.");
    expect(items[1]).toHaveTextContent("Take 2: its feedback request failed, and feedback is off now. Review your transcript against the prompt yourself, or answer again.");
    expect(items[2]).toHaveTextContent("Take 1: your checked transcript has no feedback, and feedback is off. Review it against the prompt's requirements yourself, then answer again.");
    expect(items[2]).toHaveTextContent("This exercise keeps the wording you answered; the prompt set has corrected it since.");
    expect(items[3]).toHaveTextContent("Take 1: its feedback is still being prepared. Check again in a moment.");
    for (const li of items) expect(within(li).getByRole("button", { name: "Open" })).toBeInTheDocument();
    // "Continue where you left off" opens the most recent incomplete exercise at its take.
    const resume = within(overview).getByRole("group", { name: "Continue where you left off" });
    expect(resume).toHaveTextContent("Take 1: your checked transcript has no feedback, and feedback is off.");
    fireEvent.click(within(resume).getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: invitation.title });
    expect(within(screen.getByRole("group", { name: "Choose a take" })).getByRole("button", { name: "Take 1" })).toHaveAttribute("aria-pressed", "true");
    // The take's section takes focus, so a phone lands on it rather than on the prompt.
    await waitFor(() => expect(screen.getByRole("heading", { name: "Take 1" })).toHaveFocus());
    expect(speakingWrites(server)).toEqual([]);
  });

  it("uses the plural for improvements and says when there is nothing to do", async () => {
    installMedia("grant");
    const server = newServer({ exercises: [withTypedTake(1, [transcriptV1])] });
    const base = { schema_version: "speaking_practice_v1" as const, generated_at: "t", exercises: [], providers: { transcription: { enabled: false, name: null }, feedback: { enabled: false, name: null } } };
    const summary = { prompts: 3, started: 1, takes: 1, completed: 1, exercises_completed: 1, awaiting_transcript: 0, awaiting_feedback: 0, in_progress: 0, failed: 0, unknown: 0, last_completed_at: null };
    server.practice = { ...base, summary, resume: null, queue: [{ ...addTypedTranscript, reason: "answer_again", priority: 6, take_id: 11, take_number: 1, state: "feedback_ready", improvements: 1 }] };
    serve(server);
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Speaking" }));
    const overview = await screen.findByRole("region", { name: "Speaking practice overview" });
    expect(await within(overview).findByText("Take 1: the feedback suggests 1 improvement. Answer again using it.")).toBeInTheDocument();
    cleanup();
    server.practice = { ...base, summary: { ...summary, takes: 0, completed: 0, started: 0, exercises_completed: 0 }, queue: [], resume: null };
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Speaking" }));
    const empty = await screen.findByRole("region", { name: "Speaking practice overview" });
    expect(await within(empty).findByText("Nothing to do right now.")).toBeInTheDocument();
    expect(within(empty).queryByRole("link", { name: /Download all attempts/ })).toBeNull();
  });

  it("lists each attempt with its state and the feedback that counts, and says when the prompt changed", async () => {
    installMedia("grant");
    const v = withTypedTake(1, [transcriptV1]);
    v.takes[0].state = "feedback_ready";
    v.feedback.push({ id: 41, transcript_id: 21, status: "completed", failure_code: null, generator: GENERATOR, created_at: "t", content: feedbackV1 });
    v.takes.push({ id: 12, number: 2, audio_source: "none", audio_mime: null, audio_bytes: null, audio_sha256: null, duration_ms: null, created_at: "t", state: "awaiting_transcript" });
    v.exercise.pack_status = "changed";
    v.example_transcript = null;
    const corrected = "Votre amie Léa organise un pique-nique dimanche prochain. Rappelez-la.";
    v.current_prompt = { ...v.exercise, situation: corrected, content_fingerprint: "c".repeat(64) };
    const server = newServer({ exercises: [v] });
    serve(server);
    await openExercise(server);
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent("This prompt was corrected in the set after you started it.");
    // The answered wording stays on top with its revision; the correction is beside it, read-only.
    expect(screen.getByText("The wording you answered (revision ffffffff):")).toBeInTheDocument();
    expect(screen.getByText(invitation.situation)).toBeInTheDocument();
    fireEvent.click(within(note).getByText("Show the corrected wording in the set (revision cccccccc)"));
    expect(within(note).getByText("Changed: situation.")).toBeInTheDocument();
    expect(within(note).getByText(corrected)).toBeInTheDocument();
    expect(within(note).getByText(/cannot be practised as a separate exercise yet/)).toBeInTheDocument();
    // Each attempt names the wording it answered.
    expect(screen.getByText("Every take here answered revision ffffffff: an exercise keeps the wording it was started with.")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Take 2" })).getByText(/Take 2 answered the wording at the top of this exercise \(revision ffffffff\)/)).toBeInTheDocument();
    const rows = within(screen.getByRole("list", { name: "Attempts" })).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent(`Content points partly covered; ${feedbackV1.improvements.length} improvements`);
    expect(rows[0]).toHaveTextContent("completed");
    expect(rows[0]).toHaveTextContent("version 1, typed");
    expect(rows[1]).toHaveTextContent("waiting for a transcript");
    expect(rows[1]).toHaveTextContent("typed");
    // Take 2 has no transcript: the set's example is not offered for an older wording.
    expect(screen.queryByRole("button", { name: "Use the example transcript" })).toBeNull();
  });

  it("takes back a take's audio after a reload only from a file with the same SHA-256, and sends nothing", async () => {
    installMedia("grant");
    const audio = new Uint8Array([0x52, 0x49, 0x46, 0x46, 9, 8, 7, 6, 5, 4, 3, 2, 1]);
    const v = exerciseView(1);
    v.takes.push({ id: 11, number: 1, audio_source: "file", audio_mime: "audio/wav", audio_bytes: audio.length, audio_sha256: await sha(audio), duration_ms: 1500, created_at: "t", state: "awaiting_transcript" });
    const server = newServer({ exercises: [v] });
    serve(server);
    await openExercise(server);
    const take = screen.getByRole("region", { name: "Take 1" });
    expect(within(take).getByText(/not in this browser any more/)).toBeInTheDocument();
    expect(within(take).queryByRole("button", { name: /Send audio/ })).toBeNull();
    const input = within(take).getByLabelText("Choose the same audio file again");
    fireEvent.change(input, { target: { files: [new File([new Uint8Array([1, 2, 3])], "other.wav", { type: "audio/wav" })] } });
    expect(await within(take).findByText("This file is not the audio of take 1 (its SHA-256 differs). Nothing was kept.")).toBeInTheDocument();
    fireEvent.change(input, { target: { files: [new File([audio], "take.wav", { type: "audio/wav" })] } });
    expect(await within(take).findByLabelText("Play back take 1")).toBeInTheDocument();
    expect(within(take).queryByText(/not in this browser any more/)).toBeNull();
    expect(speakingWrites(server)).toEqual([]);
  });
});

describe("Speaking: lost answers and retries never stack a second attempt", () => {
  const typedTake = (v: SpeakingExerciseView) => {
    v.takes.push({ id: 11, number: 1, audio_source: "none", audio_mime: null, audio_bytes: null, audio_sha256: null, duration_ms: null, created_at: "t", state: "awaiting_transcript" });
    return v;
  };

  it("checks a typed take whose answer was lost, and a resend names the same take", async () => {
    installMedia("grant");
    const server = newServer({ exercises: [exerciseView(1)] });
    serve(server);
    const panel = await openExercise(server);
    server.lose = /\/takes$/;
    fireEvent.click(within(panel).getByRole("button", { name: "Type what you said instead" }));
    const alert = await within(panel).findByRole("alert");
    expect(alert).toHaveTextContent("No answer arrived, so the take may or may not have been saved. Check before saving it again.");
    fireEvent.click(within(alert).getByRole("button", { name: "Check whether it was saved" }));
    expect(await screen.findByRole("region", { name: "Take 1" })).toBeInTheDocument();
    expect(server.exercises[0].takes).toHaveLength(1);
    // Saving a typed take again while take 1 is still empty names take 1.
    fireEvent.click(within(panel).getByRole("button", { name: "Type what you said instead" }));
    await waitFor(() => expect(server.calls.filter((c) => c.method === "POST" && c.path.endsWith("/takes"))).toHaveLength(2));
    expect(server.exercises[0].takes).toHaveLength(1);
    expect(within(screen.getByRole("group", { name: "Choose a take" })).getAllByRole("button")).toHaveLength(1);
  });

  it("says a typed take was not saved when the request never arrived, and saves it once on the next try", async () => {
    installMedia("grant");
    const server = newServer({ exercises: [exerciseView(1)] });
    serve(server);
    const panel = await openExercise(server);
    server.drop = /\/takes$/;
    fireEvent.click(within(panel).getByRole("button", { name: "Type what you said instead" }));
    fireEvent.click(within(await within(panel).findByRole("alert")).getByRole("button", { name: "Check whether it was saved" }));
    expect(await within(panel).findByText("It was not saved. Choose “Type what you said instead” again to save it as take 1.")).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: "Type what you said instead" }));
    expect(await screen.findByRole("region", { name: "Take 1" })).toBeInTheDocument();
    expect(server.exercises[0].takes).toHaveLength(1);
  });

  it("finds a confirmed transcript whose answer was lost, by checking or by confirming again", async () => {
    installMedia("grant");
    for (const how of ["check", "confirm again"] as const) {
      const server = newServer({ exercises: [typedTake(exerciseView(1))] });
      serve(server);
      await openExercise(server);
      const take = screen.getByRole("region", { name: "Take 1" });
      fireEvent.change(within(take).getByLabelText("Transcript of take 1, version 1"), { target: { value: transcriptV1 } });
      server.lose = /\/transcripts$/;
      fireEvent.click(within(take).getByRole("button", { name: "Confirm as version 1" }));
      const alert = await within(take).findByRole("alert");
      expect(alert).toHaveTextContent("No answer arrived, so this version may or may not have been saved. Check before confirming it again.");
      if (how === "check") fireEvent.click(within(alert).getByRole("button", { name: "Check whether it was saved" }));
      else fireEvent.click(within(take).getByRole("button", { name: "Confirm as version 1" }));
      expect(await within(screen.getByRole("region", { name: "Take 1" })).findByLabelText("Take 1, transcript version 1")).toHaveTextContent(transcriptV1);
      expect(screen.queryByText(/nothing was saved/)).toBeNull();
      expect(screen.getByRole("button", { name: "Confirm as version 2" })).toBeInTheDocument();
      expect(server.exercises[0].transcripts).toHaveLength(1);
      cleanup();
    }
  });

  it("says a transcript was not saved when the request never arrived, and keeps the text for the next try", async () => {
    installMedia("grant");
    const server = newServer({ exercises: [typedTake(exerciseView(1))] });
    serve(server);
    await openExercise(server);
    const take = screen.getByRole("region", { name: "Take 1" });
    fireEvent.change(within(take).getByLabelText("Transcript of take 1, version 1"), { target: { value: transcriptV1 } });
    server.drop = /\/transcripts$/;
    fireEvent.click(within(take).getByRole("button", { name: "Confirm as version 1" }));
    fireEvent.click(within(await within(take).findByRole("alert")).getByRole("button", { name: "Check whether it was saved" }));
    expect(await within(take).findByText("It was not saved. Confirm it again to save it as version 1.")).toBeInTheDocument();
    expect(within(take).getByLabelText("Transcript of take 1, version 1")).toHaveValue(transcriptV1);
    fireEvent.click(within(take).getByRole("button", { name: "Confirm as version 1" }));
    expect(await within(screen.getByRole("region", { name: "Take 1" })).findByLabelText("Take 1, transcript version 1")).toBeInTheDocument();
    expect(server.exercises[0].transcripts).toHaveLength(1);
  });

  it("after a reload, says how to retry a failed transcription and keeps the typing path open", async () => {
    installMedia("grant");
    const v = exerciseView(1);
    v.takes.push({ id: 11, number: 1, audio_source: "recording", audio_mime: "audio/webm", audio_bytes: WEBM.length, audio_sha256: "a".repeat(64), duration_ms: 1500, created_at: "t", state: "transcription_failed" });
    v.transcriptions.push({ id: 31, take_id: 11, status: "failed", failure_code: "provider_unavailable", transcriber: TRANSCRIBER, text: null, created_at: "t" });
    v.transcription_requests.push({ id: 32, operation_id: "k", take_id: 11, after_unknown: false, started_at: "t", deadline_at: "t", finished_at: "t", state: "failed", result_id: 31 });
    const server = newServer({ exercises: [v] });
    serve(server);
    await openExercise(server);
    const take = screen.getByRole("region", { name: "Take 1" });
    expect(within(take).getByText(/The last transcription failed/)).toBeInTheDocument();
    expect(within(take).getByText("To send this take for transcription, choose its audio file again above. You can also type what you said below.")).toBeInTheDocument();
    expect(within(take).getByLabelText("Choose the same audio file again")).toBeInTheDocument();
    expect(within(take).getByLabelText("Transcript of take 1, version 1")).toBeInTheDocument();
    expect(speakingWrites(server)).toEqual([]);
  });
});

describe("Speaking practice overview from the backend's own answer", () => {
  it("renders the end-to-end walk's overview: honest counts, reasons in the backend's order", async () => {
    installMedia("grant");
    const server = newServer({ exercises: [withTypedTake(1, [transcriptV1])] });
    server.practice = practiceFromWalk;
    serve(server);
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Speaking" }));
    const overview = await screen.findByRole("region", { name: "Speaking practice overview" });
    expect(await within(overview).findByText("Completed takes (feedback on the latest checked transcript): 1 of 3")).toBeInTheDocument();
    expect(within(overview).getByText("Waiting for a transcript: 1 · Waiting for feedback: 1 · In progress: 0 · Failed: 0 · Outcome unknown: 0")).toBeInTheDocument();
    const items = within(overview).getAllByRole("listitem").filter((li) => li.hasAttribute("data-reason"));
    expect(items.map((li) => li.getAttribute("data-reason"))).toEqual(practiceFromWalk.queue.map((q) => q.reason));
    expect(items[0]).toHaveTextContent("Take 3: a machine transcript is waiting for your check.");
    expect(speakingWrites(server)).toEqual([]);
  });
});
