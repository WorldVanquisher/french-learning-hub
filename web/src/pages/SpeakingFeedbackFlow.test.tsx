// Speaking after feedback (demo-refresh frontend batch): the next take with the
// report's points in mind, the before/after evidence beside the word
// comparison, and an unsaved recording told apart from saved takes.
import { webcrypto } from "node:crypto";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { exampleTranscript, feedbackV1, notice, prompts, transcriptV1, transcriptV2 } from "../test/speakingFixture";
import type { SpeakingExerciseView } from "../types/speaking";
import { countWords } from "./Writing";

const invitation = prompts[0];
const limits = { max_audio_bytes: 8 << 20, max_duration_ms: 120_000, accepted_types: ["audio/webm", "audio/mp4", "audio/mpeg", "audio/wav"], max_transcript_chars: 2000, max_takes: 20, max_transcript_versions: 10 };
const providers = { transcription: { enabled: false, name: null }, feedback: { enabled: true, name: "openai:local-fixture:speaking_feedback_v1" } };

// Fields a newer Speaking API adds; optional on read for this page (see
// SpeakingRecorder.test.tsx), sent so the tests hold for both API versions.
const promptIdentity = { prompt_set: "flh_speaking_prompts_v1", content_fingerprint: "f".repeat(64), pack_status: "current" };

function exercise(): SpeakingExerciseView {
  return {
    exercise: { id: 1, prompt_id: invitation.id, title: invitation.title, situation: invitation.situation, requirements: invitation.requirements, seconds_min: invitation.seconds_min, seconds_max: invitation.seconds_max, created_at: "t", ...promptIdentity } as SpeakingExerciseView["exercise"],
    takes: [
      { id: 11, number: 1, audio_source: "recording", audio_mime: "audio/webm", audio_bytes: 9000, audio_sha256: "a".repeat(64), duration_ms: 42_000, created_at: "t" },
      { id: 12, number: 2, audio_source: "none", audio_mime: null, audio_bytes: null, audio_sha256: null, duration_ms: null, created_at: "t" },
    ],
    transcriptions: [],
    transcription_requests: [],
    transcripts: [
      { id: 21, take_id: 11, version: 1, text: transcriptV1, word_count: countWords(transcriptV1), origin: "typed", transcription_id: null, created_at: "t" },
      { id: 22, take_id: 12, version: 1, text: transcriptV2, word_count: countWords(transcriptV2), origin: "typed", transcription_id: null, created_at: "t" },
    ],
    feedback: [{ id: 31, transcript_id: 21, status: "completed", failure_code: null, generator: "openai:local-fixture:speaking_feedback_v1", created_at: "t", content: feedbackV1 }],
    feedback_requests: [],
    example_transcript: exampleTranscript,
    providers,
    limits,
    word_convention: "w",
  };
}

beforeEach(() => {
  if (!globalThis.crypto?.subtle) vi.stubGlobal("crypto", webcrypto);
  URL.createObjectURL = vi.fn(() => "blob:take");
  URL.revokeObjectURL = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  globalThis.fetch = vi.fn(async (input: string | URL | Request) => {
    const p = new URL(String(input), "http://localhost").pathname;
    if (p === "/api/speaking/prompts") return json(200, { set: "flh_speaking_prompts_v1", notice, prompts: prompts.map((x) => ({ ...x, started_exercise_id: x.id === invitation.id ? 1 : null })), providers, limits });
    if (p === "/api/speaking/exercises") return json(200, { providers, exercises: [{ exercise: exercise().exercise, takes: 2 }] });
    if (p === "/api/speaking/exercises/1") return json(200, exercise());
    if (p === "/api/speaking/practice") return json(404, { error: "not found" });
    if (p === "/api/reviewable-units") return json(200, { reviewable_units: [] });
    return json(200, { concepts: [] });
  }) as unknown as typeof fetch;
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: undefined });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function open() {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Speaking" }));
  const row = (await within(await screen.findByRole("region", { name: "Speaking prompts" })).findByText(invitation.title)).closest("li")!;
  fireEvent.click(within(row).getByRole("button", { name: "Open" }));
  await screen.findByRole("heading", { name: invitation.title });
}

describe("Speaking after feedback", () => {
  it("records the next take with the report's grounded points in mind, until they are hidden", async () => {
    await open();
    fireEvent.click(within(screen.getByRole("group", { name: "Choose a take" })).getByRole("button", { name: "Take 1" }));
    const report = await screen.findByRole("group", { name: "Feedback report for take 1, version 1" });
    fireEvent.click(within(report).getByRole("button", { name: "Record take 3 with these points in mind" }));
    const recorder = screen.getByRole("region", { name: "New take" });
    const points = within(recorder).getByRole("group", { name: "Points to keep in mind" });
    expect(points).toHaveTextContent("Keep in mind (from the feedback on take 1, version 1):");
    expect(points).toHaveTextContent("« je suis arrivé vers midi et demi »");
    expect(points).toHaveTextContent("« Je vais amener un dessert »");
    // A quote that is not in the transcript is never offered as a point.
    expect(points).not.toHaveTextContent("je viendrai avec plaisir");
    await waitFor(() => expect(document.activeElement).toBe(points));
    // The exercise's own prompt stays on the page above the recorder.
    expect(screen.getByRole("heading", { name: invitation.title })).toBeInTheDocument();
    fireEvent.click(within(points).getByRole("button", { name: "Hide these points" }));
    expect(within(recorder).queryByRole("group", { name: "Points to keep in mind" })).toBeNull();
  });

  it("sets two transcripts side by side on what is recorded about them, without a score", async () => {
    await open();
    const compare = await screen.findByRole("region", { name: "Compare confirmed transcripts" });
    const table = within(compare).getByRole("table");
    const rows = within(table)
      .getAllByRole("row")
      .map((r) => [...r.querySelectorAll("th, td")].map((c) => c.textContent));
    expect(rows).toEqual([
      ["Recorded", "Take 1 · v1", "Take 2 · v1"],
      ["Recorded length", "0:42", "no audio (typed)"],
      ["Words", `${countWords(transcriptV1)} words`, `${countWords(transcriptV2)} words`],
      ["Task", "Content points partly covered", "no feedback yet"],
      ["Points raised", "4 points", "—"],
    ]);
    expect(table).toHaveTextContent("Ratings are practice feedback, not scores.");
  });
});
