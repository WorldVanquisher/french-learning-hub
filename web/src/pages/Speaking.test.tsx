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
import type { SpeakingExerciseView, SpeakingFeedback, SpeakingRequest, SpeakingTranscript, SpeakingTranscription } from "../types/speaking";
import { shownAsGrounded } from "./Speaking";
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
  transcription: Mode;
  feedback: Mode;
  calls: Call[];
  ids: number;
};

const newServer = (over: Partial<Server> = {}): Server => ({ exercises: [], transcription: "ok", feedback: "ok", calls: [], ids: 1000, ...over });
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
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
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
    if (method === "GET" && p === "/api/speaking/exercises")
      return json(200, { providers: providers(), exercises: server.exercises.map((v) => ({ exercise: v.exercise, takes: v.takes.length })) });
    if ((m = /^\/api\/speaking\/exercises\/(\d+)$/.exec(p)) && method === "GET") {
      const v = server.exercises.find((x) => x.exercise.id === Number(m![1]));
      return v ? json(200, view(v)) : json(404, { error: "not found" });
    }
    if ((m = /^\/api\/speaking\/exercises\/(\d+)\/takes$/.exec(p)) && method === "POST") {
      const v = server.exercises.find((x) => x.exercise.id === Number(m![1]))!;
      const t = JSON.parse(body) as { audio_source: "recording" | "file" | "none"; audio_mime?: string; audio_bytes?: number; audio_sha256?: string; duration_ms?: number };
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
      return json(201, view(v));
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
    // The record opens in Learning Records, with a way back to Speaking.
    fireEvent.click(within(item).getByRole("button", { name: "Open record #77 in Learning Records" }));
    fireEvent.click(await screen.findByRole("button", { name: "← Back to Speaking" }));
    expect(await screen.findByRole("region", { name: "Take 1" })).toBeInTheDocument();
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

  it("works with both providers off: typed transcripts and comparison, no transcription or feedback button", async () => {
    installMedia("grant");
    const server = newServer({ exercises: [withTypedTake(1, [transcriptV1])], transcription: "disabled", feedback: "disabled" });
    serve(server);
    await openExercise(server);
    const take = screen.getByRole("region", { name: "Take 1" });
    expect(within(take).getByText("Feedback is off (SPEAKING_PROVIDER). Recording, transcripts and comparison still work.")).toBeInTheDocument();
    expect(within(take).queryByRole("button", { name: /Request feedback/ })).toBeNull();
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
