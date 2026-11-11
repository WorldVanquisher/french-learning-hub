// Mistake Notebook v1 in the private workbench, against a stateful fake server:
// items from all four skills (as the backend resolves them from stored source
// items), explicit retry marks, a retry session across skills, exact source
// links into the skill views, the Grammar/Vocabulary views and a record's
// source line.
import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import PublicDemoApp from "../PublicDemoApp";
import { RecordSource } from "../components/RecordSource";
import { LocaleProvider } from "../i18n";
import { sourceOpen, type KindConcept, type NotebookItem } from "../types/notebook";
import type { SpeakingExerciseView } from "../types/speaking";
import type { WritingTaskView } from "../types/writing";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

const base = { capture_id: "c", saved_at: "2026-11-09T10:00:00Z", explanation_zh: "原因", hint_en: null, hint_zh: null, retry: { marked: false, since: null } };
const ITEMS: NotebookItem[] = [
  {
    ...base,
    entry_id: 41,
    skill: "speaking",
    source: { type: "speaking_improvement", record_id: 9, item: 1, attempt: null },
    title: "Répondre à une invitation",
    prompt: "Votre amie Léa vous a laissé un message…",
    category: "grammar",
    quote: "je suis arrivé vers midi et demi",
    reference: "j'arriverai vers midi et demi",
    explanation_en: "A future arrival needs the future tense.",
    hint_en: "Which tense describes an arrival that has not happened yet?",
    hint_zh: "应该用哪个时态？",
    link: { speaking_exercise_id: 2, speaking_take_id: 3, speaking_take_number: 1, speaking_transcript_id: 7, speaking_transcript_version: 1, speaking_feedback_id: 9 },
    record: { original_input: "« je suis arrivé » → « j'arriverai »", original_context: "Speaking exercise #2" },
  },
  {
    ...base,
    entry_id: 40,
    skill: "writing",
    source: { type: "writing_correction", record_id: 500, item: 1, attempt: null },
    title: "Répondre à une invitation (courriel)",
    prompt: "Votre collègue Sophie vous invite…",
    category: "grammar",
    quote: "Je suis arrivé vers 20 heures",
    reference: "J'arriverai vers 20 heures",
    explanation_en: "Future tense for a future arrival.",
    hint_en: "The party is on Saturday.",
    hint_zh: "聚会在周六。",
    link: { writing_task_id: 1, writing_draft_id: 101, writing_draft_version: 1, writing_feedback_id: 500 },
    record: { original_input: "« Je suis arrivé » → « J'arriverai »", original_context: "Writing task #1" },
  },
  {
    ...base,
    entry_id: 39,
    skill: "reading",
    source: { type: "reading_item", record_id: 5, item: 2, attempt: "Le lundi." },
    title: "Piscine municipale : horaires d'été",
    prompt: "Quel jour la piscine est-elle fermée ?",
    category: "detail",
    quote: null,
    reference: "Le mardi.",
    explanation_en: "Paragraph 2 says Tuesday.",
    link: { reading_lesson_id: 4, reading_passage_version: 1, reading_exercise_id: 5 },
    record: { original_input: "J'ai confondu lundi et mardi.", original_context: "Reading lesson #4" },
  },
  {
    ...base,
    entry_id: 38,
    skill: "listening",
    source: { type: "listening_item", record_id: 100, item: 2, attempt: null },
    title: "Annonce en gare",
    prompt: "Combien de minutes de retard ?",
    category: "detail",
    quote: null,
    reference: "Vingt minutes.",
    explanation_en: "Segment 1 says twenty.",
    link: { listening_material_id: 7, listening_exercise_id: 100, listening_transcript_version: 1 },
    record: { original_input: "J'ai entendu « dix ».", original_context: "Listening exercise" },
  },
];
const CONCEPTS: Record<string, KindConcept[]> = {
  grammar: [{ concept_id: 11, target: "accord du participe passé", pedagogical_intent: "grammar", scope: "", state: "active", class: "grammar", reason: null, kinds: ["grammar"], supporting_unit_count: 2, match_tier: "browse" }],
  vocabulary: [{ concept_id: 12, target: "apporter", pedagogical_intent: "vocabulary", scope: "", state: "active", class: "vocabulary", reason: null, kinds: ["vocabulary"], supporting_unit_count: 1, match_tier: "browse" }],
  unclassified: [
    { concept_id: 13, target: "venir au futur", pedagogical_intent: "grammar", scope: "", state: "active", class: "unclassified", reason: "mixed_kinds", kinds: ["grammar", "vocabulary"], supporting_unit_count: 2, match_tier: "browse" },
  ],
};

const writingTask = (): WritingTaskView => ({
  task: { id: 1, title: "Répondre à une invitation (courriel)", prompt: "Votre collègue Sophie vous invite…", requirements: [], word_min: 60, word_max: 90, origin: "authored", prompt_id: "wr-invitation-anniversaire", created_at: "t" },
  drafts: [
    { id: 101, version: 1, text: "Je suis arrivé vers 20 heures.", word_count: 6, created_at: "t" },
    { id: 102, version: 2, text: "J'arriverai vers 20 heures.", word_count: 5, created_at: "t" },
  ],
  feedback: [],
  requests: [],
  generation: { enabled: false, generator: null },
  word_convention: "w",
});
const speakingExercise = (): SpeakingExerciseView => ({
  exercise: { id: 2, prompt_id: "sp-invitation-reponse", title: "Répondre à une invitation", situation: "Votre amie Léa…", requirements: ["Remerciez Léa."], seconds_min: 30, seconds_max: 90, created_at: "t" },
  takes: [
    { id: 3, number: 1, audio_source: "none", audio_mime: null, audio_bytes: null, audio_sha256: null, duration_ms: null, created_at: "t" },
    { id: 4, number: 2, audio_source: "none", audio_mime: null, audio_bytes: null, audio_sha256: null, duration_ms: null, created_at: "t" },
  ],
  transcriptions: [],
  transcription_requests: [],
  transcripts: [
    { id: 7, take_id: 3, version: 1, text: "Salut Léa, je suis arrivé vers midi et demi.", word_count: 9, origin: "typed", transcription_id: null, created_at: "t" },
    { id: 8, take_id: 3, version: 2, text: "Salut Léa, je suis arrivé vers midi.", word_count: 7, origin: "corrected", transcription_id: null, created_at: "t" },
    { id: 9, take_id: 4, version: 1, text: "Salut Léa, j'arriverai vers midi et demi.", word_count: 7, origin: "typed", transcription_id: null, created_at: "t" },
  ],
  feedback: [],
  feedback_requests: [],
  example_transcript: "",
  providers: { transcription: { enabled: false, name: null }, feedback: { enabled: false, name: null } },
  limits: { max_audio_bytes: 8 << 20, max_duration_ms: 120_000, accepted_types: ["audio/webm"], max_transcript_chars: 2000, max_takes: 20, max_transcript_versions: 10 },
  word_convention: "w",
});

type Call = { method: string; path: string; search: string; body: string };
function serve(items: NotebookItem[]) {
  const calls: Call[] = [];
  const state = items.map((it) => ({ ...it, retry: { ...it.retry } }));
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const body = String(init?.body ?? "");
    calls.push({ method, path: url.pathname, search: url.search, body });
    const p = url.pathname;
    let m: RegExpExecArray | null;
    if (p === "/api/mistake-notebook/items" && method === "GET") {
      const skill = url.searchParams.get("skill");
      const marked = url.searchParams.get("marked") === "true";
      return json(200, { items: state.filter((it) => (!skill || it.skill === skill) && (!marked || it.retry.marked)), unlinked_notice: "n" });
    }
    if ((m = /^\/api\/mistake-notebook\/items\/(\d+)\/retry$/.exec(p)) && method === "PUT") {
      const it = state.find((x) => x.entry_id === Number(m![1]))!;
      const marked = (JSON.parse(body) as { marked: boolean }).marked;
      const changed = it.retry.marked !== marked;
      it.retry = { marked, since: "t" };
      return json(200, { item: it, changed });
    }
    if (p === "/api/mistake-notebook/concepts") {
      const kind = url.searchParams.get("kind")!;
      const q = url.searchParams.get("q") ?? "";
      const rows = CONCEPTS[kind].filter((c) => c.target.includes(q));
      return json(200, { rule: "concept_kind_view_v1", kind, query: q, tokens: [], classified: 3, truncated: false, concepts: rows });
    }
    if ((m = /^\/api\/entries\/(\d+)\/source$/.exec(p))) {
      const it = state.find((x) => x.entry_id === Number(m![1]));
      return json(200, it ? { entry_id: it.entry_id, linked: true, item: it } : { entry_id: Number(m[1]), linked: false, notice: "n" });
    }
    if (p === "/api/writing/tasks/1") return json(200, writingTask());
    if (p === "/api/writing/prompts") return json(200, { set: "s", notice: "n", prompts: [] });
    if (p === "/api/writing/tasks") return json(200, { tasks: [], generation: { enabled: false, generator: null } });
    if (p === "/api/speaking/exercises/2") return json(200, speakingExercise());
    if (p === "/api/speaking/prompts") return json(200, { set: "s", notice: "n", prompts: [], providers: speakingExercise().providers, limits: speakingExercise().limits });
    if (p === "/api/speaking/exercises") return json(200, { exercises: [], providers: speakingExercise().providers });
    if (p.startsWith("/api/knowledge-library/concepts/")) return json(404, { error: "concept not found" });
    if (p === "/api/knowledge-library/concepts")
      return json(200, { schema_version: "knowledge_library_search_v1", query: "", tokens: [], state: "all", limit: 20, total_matches: 0, truncated: false, results: [] });
    if (p === "/api/knowledge-library/demo")
      return json(200, {
        schema_version: "knowledge_library_public_demo_v1", read_only: true, data: "synthetic",
        artifact: { version: "v", manifest_sha256: "m", vector_source: "mechanical-test", real_model: false, vector_generator: "g", model_id: "x",
          dimensions: 4, document_representation: "d", query_representation: "q", release_status: "blocked", notice: "n", domain_fingerprint_sha256: "f" },
        query_policy: "presets only", presets: [], counters: { preset_vector_lookups: 0, refused_vector_lookups: 0 },
      });
    if (p === "/api/reviewable-units") return json(200, { reviewable_units: [] });
    if (p === "/api/learning-records") return json(200, { records: [], next_before_entry_id: null });
    return json(200, { concepts: [] });
  }) as unknown as typeof fetch;
  return { calls, state };
}

async function openNotebook() {
  render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Mistake Notebook" }));
  return await screen.findByRole("region", { name: "Saved mistakes" });
}

describe("Mistake Notebook helpers", () => {
  it("opens each skill's exact source item from the stored link", () => {
    expect(sourceOpen(ITEMS[0])).toEqual({ skill: "speaking", exerciseId: 2, takeId: 3, transcriptVersion: 1 });
    expect(sourceOpen(ITEMS[1])).toEqual({ skill: "writing", taskId: 1, draftVersion: 1 });
    expect(sourceOpen(ITEMS[2])).toEqual({ skill: "reading", lessonId: 4 });
    expect(sourceOpen(ITEMS[3])).toEqual({ skill: "listening", materialId: 7 });
    expect(sourceOpen({ ...ITEMS[1], link: {} })).toBeNull();
  });
});

describe("Mistake Notebook (private workbench)", () => {
  it("lists misses from all four skills with prompt, attempt and record, hides the reference until shown, and filters by skill", async () => {
    const { calls } = serve(ITEMS);
    const list = await openNotebook();
    await within(list).findByText("4 items");
    const speaking = within(list).getByRole("group", { name: "Mistake, record #41" });
    expect(speaking).toHaveTextContent("Speaking");
    expect(speaking).toHaveTextContent("Your words « je suis arrivé vers midi et demi »");
    expect(speaking).toHaveTextContent("Speaking exercise #2, take 1, transcript version 1, feedback #9, improvement 1");
    expect(within(speaking).queryByText("j'arriverai vers midi et demi")).toBeNull();
    fireEvent.click(within(speaking).getByRole("button", { name: "Show reference" }));
    expect(within(speaking).getByText("j'arriverai vers midi et demi")).toBeInTheDocument();
    const reading = within(list).getByRole("group", { name: "Mistake, record #39" });
    expect(reading).toHaveTextContent("Your answer Le lundi.");
    expect(reading).toHaveTextContent("Reading lesson #4, passage version 1, exercise #5, question 2");
    const listening = within(list).getByRole("group", { name: "Mistake, record #38" });
    expect(listening).toHaveTextContent("Your answer was not saved with this item.");
    expect(list).toHaveTextContent("never linked here by guessing");

    fireEvent.click(within(list).getByRole("button", { name: "Writing" }));
    await waitFor(() => expect(within(list).getAllByRole("group", { name: /^Mistake, record/ })).toHaveLength(1));
    expect(calls.some((c) => c.path === "/api/mistake-notebook/items" && c.search === "?skill=writing")).toBe(true);
    expect(calls.filter((c) => c.method !== "GET")).toEqual([]);
  });

  it("marks items for retry explicitly and runs a retry session across skills with nothing sent but explicit removals", async () => {
    const { calls } = serve(ITEMS);
    const list = await openNotebook();
    await within(list).findByText("4 items");
    for (const id of [41, 39, 38]) {
      const item = within(list).getByRole("group", { name: `Mistake, record #${id}` });
      fireEvent.click(within(item).getByRole("button", { name: "Mark for retry" }));
      await within(item).findByRole("button", { name: "Marked for retry: remove" });
    }
    const puts = calls.filter((c) => c.method === "PUT");
    expect(puts.map((c) => [c.path, c.body])).toEqual([
      ["/api/mistake-notebook/items/41/retry", '{"marked":true}'],
      ["/api/mistake-notebook/items/39/retry", '{"marked":true}'],
      ["/api/mistake-notebook/items/38/retry", '{"marked":true}'],
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Retry session" }));
    const session = await screen.findByRole("region", { name: "Retry session" });
    expect(await within(session).findByText(/3 items are marked for retry\./)).toHaveTextContent("Skills: Listening, Reading, Speaking.");
    fireEvent.click(within(session).getByRole("button", { name: "Start retry session" }));
    const before = calls.length;
    const answers = ["réponse-retry-aaa", "réponse-retry-bbb", "réponse-retry-ccc"];
    for (let n = 1; n <= 3; n++) {
      const card = await within(session).findByRole("group", { name: `Retry item ${n}` });
      expect(within(card).queryByRole("group", { name: "Reference" })).toBeNull();
      fireEvent.change(within(card).getByLabelText("Try again (not saved)"), { target: { value: answers[n - 1] } });
      fireEvent.click(within(card).getByRole("button", { name: "Reveal reference" }));
      expect(within(card).getByRole("group", { name: "Reference" })).toBeInTheDocument();
      fireEvent.click(within(card).getByRole("button", { name: n === 2 ? "Not yet" : "I had it" }));
      expect(within(card).getByRole("button", { name: n === 2 ? "Not yet" : "I had it" })).toHaveAttribute("aria-pressed", "true");
      fireEvent.click(within(card).getByRole("button", { name: n < 3 ? "Next item" : "Finish" }));
    }
    expect(await within(session).findByText("You went through 3: 2 you had, 1 not yet.")).toBeInTheDocument();
    expect(calls.slice(before).filter((c) => c.method !== "GET")).toEqual([]);
    expect(calls.some((c) => answers.some((a) => c.body.includes(a) || c.search.includes(a)))).toBe(false);
    // Taking an item you had off the list is one explicit PUT.
    fireEvent.click(within(session).getAllByRole("button", { name: "Marked for retry: remove" })[0]);
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(4));
    expect(calls.filter((c) => c.method === "PUT").at(-1)!.body).toBe('{"marked":false}');
  });

  it("opens the exact source: the writing task at its draft version and the speaking take at its transcript version, with a way back", async () => {
    serve(ITEMS);
    const list = await openNotebook();
    await within(list).findByText("4 items");
    fireEvent.click(within(within(list).getByRole("group", { name: "Mistake, record #40" })).getByRole("button", { name: "Open source" }));
    const versions = await screen.findByRole("region", { name: "Saved versions" });
    expect(within(versions).getByRole("button", { name: "Version 1 · 6 words" })).toHaveAttribute("aria-pressed", "true");
    expect(within(versions).getByRole("button", { name: "Version 2 · 5 words" })).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: "← Back to Mistake Notebook" }));
    const again = await screen.findByRole("region", { name: "Saved mistakes" });
    fireEvent.click(within(within(again).getByRole("group", { name: "Mistake, record #41" })).getByRole("button", { name: "Open source" }));
    const take = await screen.findByRole("region", { name: "Take 1" });
    expect(screen.getByRole("region", { name: "Takes" }).querySelector('[aria-pressed="true"]')?.textContent).toBe("Take 1");
    expect(within(take).getByRole("button", { name: "v1 · typed" })).toHaveAttribute("aria-pressed", "true");
    expect(within(take).getByLabelText("Take 1, transcript version 1")).toHaveTextContent("je suis arrivé vers midi et demi");
    expect(screen.getByText("Opened from the Mistake Notebook.")).toBeInTheDocument();
  });

  it("shows Grammar, Vocabulary and Unclassified Concepts from the backend's classification, with reasons, and searches", async () => {
    const { calls } = serve(ITEMS);
    await openNotebook();
    fireEvent.click(screen.getByRole("button", { name: "Grammar" }));
    const g = await screen.findByRole("region", { name: "Grammar Concepts" });
    expect(await within(g).findByRole("button", { name: "accord du participe passé" })).toBeInTheDocument();
    expect(g).toHaveTextContent("all of the kind grammar");
    fireEvent.click(screen.getByRole("button", { name: "Unclassified" }));
    const u = await screen.findByRole("region", { name: "Unclassified Concepts" });
    expect(await within(u).findByText("mixed kinds")).toBeInTheDocument();
    expect(u).toHaveTextContent("Nothing is guessed.");
    fireEvent.click(screen.getByRole("button", { name: "Vocabulary" }));
    const v = await screen.findByRole("region", { name: "Vocabulary Concepts" });
    fireEvent.change(within(v).getByRole("searchbox", { name: "Search these Concepts" }), { target: { value: "apport" } });
    fireEvent.click(within(v).getByRole("button", { name: "Search" }));
    await within(v).findByRole("button", { name: "apporter" });
    expect(calls.some((c) => c.path === "/api/mistake-notebook/concepts" && c.search === "?kind=vocabulary&q=apport")).toBe(true);
    // Opening a Concept goes to the Knowledge Library by its ID.
    fireEvent.click(within(v).getByRole("button", { name: "apporter" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/knowledge-library/concepts/12")).toBe(true));
  });

  it("shows a record's source, or says honestly that it has none", async () => {
    serve(ITEMS);
    const onOpenSource = vi.fn();
    render(
      <LocaleProvider>
        <RecordSource entryId={40} onOpenSource={onOpenSource} />
        <RecordSource entryId={7} onOpenSource={onOpenSource} />
      </LocaleProvider>,
    );
    expect(await screen.findByText("Saved from Writing: Répondre à une invitation (courriel).")).toBeInTheDocument();
    expect(screen.getByText("Writing task #1, draft version 1, feedback #500, correction 1")).toBeInTheDocument();
    expect(await screen.findByText(/This record has no structured source link/)).toHaveTextContent("It is not linked by guessing.");
    fireEvent.click(screen.getByRole("button", { name: "Open source" }));
    expect(onOpenSource).toHaveBeenCalledWith({ skill: "writing", taskId: 1, draftVersion: 1 });
  });

  it("is never offered in the public demo", async () => {
    const { calls } = serve(ITEMS);
    render(<PublicDemoApp />);
    await screen.findByText(/synthetic/i);
    expect(screen.queryByRole("button", { name: "Mistake Notebook" })).toBeNull();
    expect(calls.some((c) => c.path.startsWith("/api/mistake-notebook") || c.path.endsWith("/source"))).toBe(false);
  });
});
