// Speaking recorder (demo-refresh frontend batch): microphone permission shown
// before recording, a busy microphone told apart, a silent take flagged, the
// saving state shown with the recording kept, and a failed or lost save that
// never costs the learner the recording. A small stateful fake of the Speaking
// routes (Appendix A.19) and a fake microphone; jsdom has no Web Audio, so the
// level meter itself is covered by the real-browser walkthrough.
import { webcrypto } from "node:crypto";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { exampleTranscript, notice, prompts } from "../test/speakingFixture";
import type { SpeakingExerciseView } from "../types/speaking";
import { classifyRecordingError, microphonePermission } from "./speakingRecorder";

const WEBM = new Uint8Array([0x1a, 0x45, 0xdf, 0xa3, 1, 2, 3, 4]);
const invitation = prompts[0];
const limits = { max_audio_bytes: 8 << 20, max_duration_ms: 120_000, accepted_types: ["audio/webm", "audio/mp4", "audio/mpeg", "audio/wav"], max_transcript_chars: 2000, max_takes: 20, max_transcript_versions: 10 };
const providers = { transcription: { enabled: false, name: null }, feedback: { enabled: false, name: null } };

type SaveMode = "ok" | "server_error" | "lost_but_saved" | "lost_not_saved";
let exercise: SpeakingExerciseView;
let saveMode: SaveMode;
let calls: string[];

function view(): SpeakingExerciseView {
  return exercise;
}

// Fields a newer Speaking API adds (prompt identity, the saved take's ID). They
// are optional on read for this page, so the fake sends them: the tests then
// hold for both API versions (batch-5 contract: new fields are additive).
const promptIdentity = { prompt_set: "flh_speaking_prompts_v1", content_fingerprint: "f".repeat(64), pack_status: "current" };

function serve() {
  calls = [];
  exercise = {
    exercise: { id: 1, prompt_id: invitation.id, title: invitation.title, situation: invitation.situation, requirements: invitation.requirements, seconds_min: invitation.seconds_min, seconds_max: invitation.seconds_max, created_at: "t", ...promptIdentity } as SpeakingExerciseView["exercise"],
    takes: [], transcriptions: [], transcription_requests: [], transcripts: [], feedback: [], feedback_requests: [],
    example_transcript: exampleTranscript, providers, limits, word_convention: "w",
  };
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push(`${method} ${url.pathname}`);
    const p = url.pathname;
    if (method === "GET" && p === "/api/speaking/prompts") return json(200, { set: "flh_speaking_prompts_v1", notice, prompts: prompts.map((x) => ({ ...x, started_exercise_id: x.id === invitation.id ? 1 : null })), providers, limits });
    if (method === "GET" && p === "/api/speaking/exercises") return json(200, { providers, exercises: [{ exercise: exercise.exercise, takes: exercise.takes.length }] });
    if (method === "GET" && p === "/api/speaking/exercises/1") return json(200, view());
    if (method === "POST" && p === "/api/speaking/exercises/1/takes") {
      if (saveMode === "server_error") return json(500, { error: "could not save the take" });
      const t = JSON.parse(String(init?.body)) as { audio_source: "recording"; audio_mime: string; audio_bytes: number; audio_sha256: string; duration_ms: number };
      if (saveMode !== "lost_not_saved") exercise.takes.push({ id: 100 + exercise.takes.length, number: exercise.takes.length + 1, audio_source: t.audio_source, audio_mime: "audio/webm", audio_bytes: t.audio_bytes, audio_sha256: t.audio_sha256, duration_ms: t.duration_ms, created_at: "t" });
      if (saveMode.startsWith("lost")) {
        saveMode = "ok";
        throw new TypeError("Failed to fetch");
      }
      return json(201, { ...view(), take_id: exercise.takes[exercise.takes.length - 1].id, replayed: false });
    }
    // A newer API's practice overview is not part of these tests.
    if (p === "/api/speaking/practice") return json(404, { error: "not found" });
    if (p === "/api/reviewable-units") return json(200, { reviewable_units: [] });
    return json(200, { concepts: [] });
  }) as unknown as typeof fetch;
}

class FakeRecorder {
  static isTypeSupported = (t: string) => t.startsWith("audio/webm");
  state: "inactive" | "recording" = "inactive";
  mimeType: string;
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(_s: unknown, opts?: { mimeType?: string }) {
    this.mimeType = opts?.mimeType ?? "audio/webm";
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

// The level the fake analyser reads next (installAudio sets it; a test may change it).
let currentLevel = 0;

// A fake Web Audio analyser whose level is `level` (RMS) on every read.
function installAudio(level: number | null) {
  if (level === null) {
    vi.stubGlobal("AudioContext", undefined);
    return;
  }
  currentLevel = level;
  class FakeContext {
    createAnalyser() {
      return { fftSize: 1024, getFloatTimeDomainData: (buf: Float32Array) => buf.fill(currentLevel) };
    }
    createMediaStreamSource() {
      return { connect: () => undefined };
    }
    close() {
      return Promise.resolve();
    }
  }
  vi.stubGlobal("AudioContext", FakeContext);
}

function installMedia(error?: string, permission: PermissionState | "none" = "prompt") {
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn(async () => {
        if (error) throw Object.assign(new Error(error), { name: error });
        return { getTracks: () => [{ stop: () => undefined }] };
      }),
    },
  });
  Object.defineProperty(navigator, "permissions", {
    configurable: true,
    value: permission === "none" ? undefined : { query: vi.fn(async () => ({ state: permission, onchange: null })) },
  });
  vi.stubGlobal("MediaRecorder", FakeRecorder);
}

beforeEach(() => {
  if (!globalThis.crypto?.subtle) vi.stubGlobal("crypto", webcrypto);
  URL.createObjectURL = vi.fn(() => "blob:take");
  URL.revokeObjectURL = vi.fn();
  saveMode = "ok";
  serve();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function openPanel() {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Speaking" }));
  const promptsRegion = await screen.findByRole("region", { name: "Speaking prompts" });
  const row = (await within(promptsRegion).findByText(invitation.title)).closest("li")!;
  fireEvent.click(within(row).getByRole("button", { name: "Open" }));
  await screen.findByRole("heading", { name: invitation.title });
  return screen.getByRole("region", { name: "New take" });
}

async function recordOnce(panel: HTMLElement) {
  fireEvent.click(within(panel).getByRole("button", { name: "Start recording" }));
  fireEvent.click(await within(panel).findByRole("button", { name: "Stop" }));
  return within(panel).findByRole("group", { name: "Recorded take, not saved yet" });
}

describe("recorder helpers", () => {
  it("tells a busy microphone from a refusal, a missing device and anything else", () => {
    expect(classifyRecordingError({ name: "NotReadableError" })).toBe("busy");
    expect(classifyRecordingError({ name: "AbortError" })).toBe("busy");
    expect(classifyRecordingError({ name: "NotAllowedError" })).toBe("denied");
    expect(classifyRecordingError({ name: "NotFoundError" })).toBe("no_device");
    expect(classifyRecordingError({ name: "TypeError" })).toBe("failed");
  });

  it("reads the microphone permission without asking, and says unknown when the browser cannot tell", async () => {
    installMedia(undefined, "denied");
    expect(await microphonePermission()).toBe("denied");
    installMedia(undefined, "none");
    expect(await microphonePermission()).toBe("unknown");
    Object.defineProperty(navigator, "permissions", { configurable: true, value: { query: vi.fn(async () => Promise.reject(new TypeError("microphone is not a permission name"))) } });
    expect(await microphonePermission()).toBe("unknown");
  });
});

describe("Speaking recorder panel", () => {
  it("states the microphone permission before recording", async () => {
    installMedia(undefined, "denied");
    installAudio(null);
    const panel = await openPanel();
    expect(await within(panel).findByText(/Microphone: blocked for this page/)).toBeInTheDocument();
  });

  it("says when another application holds the microphone", async () => {
    installMedia("NotReadableError", "granted");
    installAudio(null);
    const panel = await openPanel();
    fireEvent.click(within(panel).getByRole("button", { name: "Start recording" }));
    expect(await within(panel).findByRole("alert")).toHaveTextContent("The microphone is in use by another application");
    expect(within(panel).getByRole("button", { name: "Type what you said instead" })).toBeEnabled();
  });

  it("announces start and stop discretely, flags a silent take and still allows using it", async () => {
    installMedia(undefined, "granted");
    installAudio(0);
    const panel = await openPanel();
    fireEvent.click(within(panel).getByRole("button", { name: "Start recording" }));
    await within(panel).findByRole("button", { name: "Stop" });
    const live = panel.querySelector(".speaking-announce")!;
    expect(live).toHaveTextContent("Recording started. It stops by itself at 2:00.");
    expect(live).toHaveAttribute("aria-live", "polite");
    // The running timer is not a live region.
    expect(panel.querySelector(".speaking-timer")!.closest("[aria-live],[role=status]")).toBeNull();
    fireEvent.click(within(panel).getByRole("button", { name: "Stop" }));
    const preview = await within(panel).findByRole("group", { name: "Recorded take, not saved yet" });
    expect(within(preview).getByRole("note")).toHaveTextContent("This take seems silent");
    expect(live).toHaveTextContent("No sound reached the microphone.");
    expect(within(preview).getByText(/Saving sends only the take's length, size, type and digest/)).toBeInTheDocument();
    expect(within(preview).getByRole("button", { name: "Use as take 1" })).toBeEnabled();
  });

  it("keeps saying sound reaches the microphone through a pause once it was heard", async () => {
    installMedia(undefined, "granted");
    installAudio(0);
    const panel = await openPanel();
    fireEvent.click(within(panel).getByRole("button", { name: "Start recording" }));
    expect(await within(panel).findByText("No sound is reaching the microphone yet.")).toBeInTheDocument();
    currentLevel = 0.2;
    expect(await within(panel).findByText("Sound is reaching the microphone.")).toBeInTheDocument();
    currentLevel = 0;
    await new Promise((r) => setTimeout(r, 500));
    expect(within(panel).getByText("Sound is reaching the microphone.")).toBeInTheDocument();
    expect(within(panel).getByLabelText("Input level")).toHaveAttribute("value", "0");
    fireEvent.click(within(panel).getByRole("button", { name: "Stop" }));
    const preview = await within(panel).findByRole("group", { name: "Recorded take, not saved yet" });
    expect(within(preview).queryByRole("note")).toBeNull();
  });

  it("does not flag a take the microphone heard", async () => {
    installMedia(undefined, "granted");
    installAudio(0.2);
    const panel = await openPanel();
    const preview = await recordOnce(panel);
    expect(within(preview).queryByRole("note")).toBeNull();
  });

  it("keeps the recording after a failed save and saves it on the next try", async () => {
    installMedia(undefined, "granted");
    installAudio(null);
    saveMode = "server_error";
    const panel = await openPanel();
    const preview = await recordOnce(panel);
    fireEvent.click(within(preview).getByRole("button", { name: "Use as take 1" }));
    expect(await within(panel).findByRole("alert")).toHaveTextContent("The take was not saved: (500) could not save the take Your recording is still here.");
    const kept = within(panel).getByRole("group", { name: "Recorded take, not saved yet" });
    expect(within(kept).getByLabelText("Play back this take")).toBeInTheDocument();
    saveMode = "ok";
    fireEvent.click(within(kept).getByRole("button", { name: "Use as take 1" }));
    expect(await screen.findByRole("region", { name: "Take 1" })).toBeInTheDocument();
    expect(panel.querySelector(".speaking-announce")).toHaveTextContent("Saved as take 1.");
  });

  it("after a lost answer, checks whether the take was saved instead of saving it twice", async () => {
    installMedia(undefined, "granted");
    installAudio(null);
    saveMode = "lost_but_saved";
    const panel = await openPanel();
    const preview = await recordOnce(panel);
    fireEvent.click(within(preview).getByRole("button", { name: "Use as take 1" }));
    expect(await within(panel).findByRole("alert")).toHaveTextContent("No answer arrived, so the take may or may not have been saved. Check before saving it again.");
    expect(within(panel).queryByText("Listen to it as often as you like. Nothing has been sent.")).toBeNull();
    expect(within(panel).queryByRole("button", { name: "Use as take 1" })).toBeNull();
    const posts = () => calls.filter((c) => c === "POST /api/speaking/exercises/1/takes").length;
    expect(posts()).toBe(1);
    await act(async () => {
      fireEvent.click(within(panel).getByRole("button", { name: "Check whether it was saved" }));
    });
    expect(await screen.findByRole("region", { name: "Take 1" })).toBeInTheDocument();
    expect(posts()).toBe(1);
    expect(exercise.takes).toHaveLength(1);
  });

  it("after a lost answer for a take that was not saved, says so and lets it be saved", async () => {
    installMedia(undefined, "granted");
    installAudio(null);
    saveMode = "lost_not_saved";
    const panel = await openPanel();
    const preview = await recordOnce(panel);
    fireEvent.click(within(preview).getByRole("button", { name: "Use as take 1" }));
    fireEvent.click(await within(panel).findByRole("button", { name: "Check whether it was saved" }));
    await waitFor(() => expect(within(panel).getByRole("alert")).toHaveTextContent("It was not saved. Use it again to save it as take 1."));
    fireEvent.click(within(panel).getByRole("button", { name: "Use as take 1" }));
    expect(await screen.findByRole("region", { name: "Take 1" })).toBeInTheDocument();
    expect(exercise.takes).toHaveLength(1);
  });
});
