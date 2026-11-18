// Revisions of an imported workbook script in the private workbench: a pack
// correction is announced but never applied on load; the learner reads a
// preview and confirms it; a stale preview is replaced; a lost response is
// safe to confirm again; an old Mistake Notebook item opens the revision it was
// saved from. A stateful fake server stands in for the backend contract
// (internal/transport/http/listening_script_revision.go).
import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { NotebookItem } from "../types/notebook";
import type {
  ListeningExercise,
  ListeningItem,
  ListeningLesson,
  ListeningMaterial,
  ListeningScriptSummary,
  ListeningScriptUpdatePreview,
  TranscriptSegment,
} from "../types/listening";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

const TITLE = "À l'accueil de la Maison des langues";
const FP1 = "sha256:" + "1".repeat(64);
const FP2 = "sha256:" + "2".repeat(64);
const FP3 = "sha256:" + "3".repeat(64);

const material: ListeningMaterial = {
  id: 7,
  source_kind: "authored_script",
  video_id: null,
  source_url: null,
  pack_script_id: "flh_listening_script_pack_v1/ls-wb1-u05",
  title: TITLE,
  created_at: "2026-11-11T08:00:00Z",
};

const lines = (revision: number): TranscriptSegment[] => [
  { index: 1, start_seconds: null, speaker: "Mei", text: "Bonjour, je voudrais m'inscrire au cours du soir de français." },
  { index: 2, start_seconds: null, speaker: "Agent", text: revision === 1 ? "Le cours est le lundi et le mercredi. Voilà." : "Le cours est le lundi et le mercredi." },
];

const OLD_WHY = "Work ends before the 18:30 class.";
const NEW_WHY = "She finishes work at 17:30 and the course is in the evening (s1, s2).";

const item = (revision: number): ListeningItem => ({
  id: "u05-l04",
  kind: "inference",
  question: "Pourquoi Mei choisit-elle le cours du soir ?",
  expected_answer: "Elle travaille la journée.",
  rationale_en: revision === 1 ? OLD_WHY : NEW_WHY,
  rationale_zh: revision === 1 ? "旧解释" : "新解释",
  segments: [1],
  evidence: [{ segment: 1, excerpt: "cours du soir" }],
});

const exercise = (revision: number): ListeningExercise => ({
  id: 900 + revision - 1,
  transcript_id: 500 + revision - 1,
  status: "completed",
  failure_code: null,
  generator: "authored:flh_listening_script_pack_v1",
  created_at: "2026-11-11T08:00:00Z",
  content: {
    items: [
      { id: "u05-l01", kind: "main_idea", question: "Que veut Mei ?", expected_answer: "S'inscrire.", rationale_en: "s1.", rationale_zh: "s1。", segments: [1], evidence: [{ segment: 1, excerpt: "m'inscrire" }] },
      item(revision),
    ],
    annotations: [],
  },
});

type Call = { method: string; path: string; body: string };
type Server = {
  revision: number;
  calls: Call[];
  packFingerprint: string;
  // The next confirmation: lost after it was applied, or refused as stale.
  loseNextUpdate?: boolean;
  staleNextUpdate?: boolean;
  notebook?: NotebookItem[];
  // The preview's change list, when a case needs another one.
  changes?: ListeningScriptUpdatePreview["changes"];
};

const fingerprint = (revision: number) => (revision === 1 ? FP1 : FP2);

const lessonOf = (server: Server): ListeningLesson => ({
  material,
  transcript: { id: 500 + server.revision - 1, version: server.revision, has_timestamps: false, segments: lines(server.revision), created_at: "t" },
  exercises: Array.from({ length: server.revision }, (_, i) => exercise(server.revision - i)),
  current_exercise_id: exercise(server.revision).id,
  script_revision: {
    script_id: "ls-wb1-u05",
    revision: server.revision,
    fingerprint: fingerprint(server.revision),
    pack_status: fingerprint(server.revision) === server.packFingerprint ? "up_to_date" : "update_available",
    pack_fingerprint: server.packFingerprint,
  },
  generation: { enabled: false, generator: null },
  state: "prepared",
  in_playlist: false,
  preparations: [],
  notifications: [],
  notification: { enabled: false, channel: null },
});

const previewOf = (server: Server): ListeningScriptUpdatePreview => {
  const available = fingerprint(server.revision) !== server.packFingerprint;
  return {
    material_id: 7,
    script_id: "ls-wb1-u05",
    current_revision: server.revision,
    current_fingerprint: fingerprint(server.revision),
    pack_status: available ? "update_available" : "up_to_date",
    pack_fingerprint: server.packFingerprint,
    next_revision: available ? server.revision + 1 : null,
    changes: available && server.changes
      ? server.changes
      : available
      ? {
          lines: [{ line: "s2", change: "changed", before: { id: "s2", speaker: "Agent", text: lines(1)[1].text }, after: { id: "s2", speaker: "Agent", text: lines(2)[1].text } }],
          questions: [{ item_id: "u05-l04", change: "changed", before_position: 2, after_position: 2, fields: ["rationale", "evidence"], before: item(1), after: item(2) }],
          annotations_changed: false,
        }
      : { lines: [], questions: [], annotations_changed: false },
  };
};

const summary = (server: Server): ListeningScriptSummary => ({
  id: "ls-wb1-u05",
  title: TITLE,
  genre: "dialogue",
  style_level: "A2",
  source_pack: "flh_workbook_reading_listening_v1",
  notice: "Synthetic listening script (unreviewed).",
  lines: 2,
  questions: 2,
  imported_material_id: 7,
  imported_revision: server.revision,
  pack_status: lessonOf(server).script_revision!.pack_status,
});

const oldMistake: NotebookItem = {
  entry_id: 41,
  capture_id: "listening-7-900-2",
  saved_at: "2026-11-11T09:00:00Z",
  skill: "listening",
  source: { type: "listening_item", record_id: 900, item: 2, attempt: "Parce qu'il est moins cher." },
  title: TITLE,
  prompt: item(1).question,
  category: "inference",
  quote: null,
  reference: item(1).expected_answer,
  explanation_en: OLD_WHY,
  explanation_zh: "旧解释",
  hint_en: null,
  hint_zh: null,
  retry: { marked: false, since: null },
  source_status: "resolved",
  reference_origin: "authored",
  generator: "authored:flh_listening_script_pack_v1",
  latest_version: 2,
  link: { listening_material_id: 7, listening_exercise_id: 900, listening_transcript_version: 1 },
  record: { original_input: "Je n'ai pas compris pourquoi.", original_context: "Listening exercise" },
};

function serve(server: Server) {
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const body = String(init?.body ?? "");
    const p = url.pathname;
    server.calls.push({ method, path: p, body });
    if (method === "GET" && p === "/api/listening/scripts") return json(200, { pack: "flh_listening_script_pack_v1", scripts: [summary(server)] });
    if (method === "GET" && p === "/api/listening/materials")
      return json(200, {
        generation: { enabled: false, generator: null },
        materials: [{ material, transcript_version: server.revision, segment_count: 2, latest_exercise: { ...exercise(server.revision), content: null }, state: "prepared", in_playlist: false }],
      });
    if (method === "GET" && p === "/api/listening/materials/7") return json(200, lessonOf(server));
    if (method === "GET" && p === "/api/listening/materials/7/script-update") return json(200, previewOf(server));
    if (method === "POST" && p === "/api/listening/materials/7/script-update") {
      const req = JSON.parse(body) as { from_revision: number; pack_fingerprint: string };
      if (server.staleNextUpdate) {
        server.staleNextUpdate = false;
        server.packFingerprint = FP3; // the server's pack changed after the preview
      }
      if (req.pack_fingerprint !== server.packFingerprint || (req.from_revision !== server.revision && fingerprint(server.revision) !== server.packFingerprint))
        return json(409, { error: "stale", code: "stale_preview", preview: previewOf(server) });
      const replayed = fingerprint(server.revision) === server.packFingerprint;
      if (!replayed) server.revision++;
      if (server.loseNextUpdate) {
        server.loseNextUpdate = false;
        throw new TypeError("network down"); // applied, but the response is lost
      }
      return json(replayed ? 200 : 201, { revision: server.revision, replayed, lesson: lessonOf(server) });
    }
    if (method === "GET" && p === "/api/listening/materials/7/revisions/1")
      return json(200, {
        material_id: 7,
        revision: 1,
        current_revision: server.revision,
        fingerprint: FP1,
        transcript: { id: 500, version: 1, has_timestamps: false, segments: lines(1), created_at: "t" },
        exercise: exercise(1),
      });
    if (method === "GET" && p === "/api/listening/daily")
      return json(200, {
        pull_enabled: false,
        source: { enabled: false, name: null },
        preparation: { enabled: false, generator: null, daily_cap: 1, timezone: "UTC", today: "2026-11-11", used_today: 0 },
        notification: { enabled: false, channel: null },
        last_run: null,
      });
    if (method === "GET" && p === "/api/mistake-notebook/items") return json(200, { items: server.notebook ?? [], unlinked_notice: "n" });
    if (p === "/api/reviewable-units") return json(200, { reviewable_units: [] });
    if (p === "/api/learning-records") return json(200, { records: [], next_before_entry_id: null });
    return json(200, { concepts: [] });
  }) as unknown as typeof fetch;
}

const updates = (server: Server) => server.calls.filter((c) => c.method === "POST" && c.path.endsWith("/script-update"));
const writes = (server: Server) => server.calls.filter((c) => c.method !== "GET");

async function openLesson(locale?: "zh-CN") {
  if (locale) window.localStorage.setItem("flh.ui-locale.v1", locale);
  render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  fireEvent.click(screen.getByRole("button", { name: locale ? "听力" : "Listening" }));
  const scripts = await screen.findByRole("region", { name: locale ? "练习册听力脚本" : "Workbook listening scripts" });
  return scripts;
}

describe("Workbook script revisions (private workbench)", () => {
  it("announces a corrected pack without changing the lesson; the update happens only after the preview is confirmed", async () => {
    const server: Server = { revision: 1, calls: [], packFingerprint: FP2 };
    serve(server);
    const scripts = await openLesson();
    expect(await within(scripts).findByText("Update available")).toBeInTheDocument();
    expect(within(scripts).getByText("Revision 1")).toBeInTheDocument();
    fireEvent.click(within(scripts).getByRole("button", { name: `Open ${TITLE}` }));
    expect(await screen.findByRole("heading", { name: TITLE })).toBeInTheDocument();
    // On load: a notice and a way to read the changes, no update button, nothing written or previewed.
    const notice = await screen.findByRole("region", { name: "Script update" });
    expect(notice).toHaveTextContent("A corrected version of this script is available. This lesson stays as it is (revision 1)");
    expect(screen.queryByRole("button", { name: /Update this lesson/ })).toBeNull();
    expect(server.calls.some((c) => c.path.endsWith("/script-update"))).toBe(false);
    expect(writes(server)).toEqual([]);

    fireEvent.click(within(notice).getByRole("button", { name: "Review the changes" }));
    expect(await within(notice).findByRole("heading", { name: "What the update changes: revision 1 → 2" })).toHaveFocus();
    expect(notice).toHaveTextContent("Your earlier practice stays with revision 1: items you saved keep their wording, your answer and their Mistake Notebook link, and the update only adds revision 2.");
    expect(within(notice).getByText("Line s2: the wording changed.")).toBeInTheDocument();
    expect(within(notice).getByText("explanation")).toBeInTheDocument();
    expect(within(notice).getByText("cited words")).toBeInTheDocument();
    // The script and the key stay behind an explicit disclosure.
    expect(notice.querySelector("details")).not.toHaveAttribute("open");
    expect(writes(server)).toEqual([]);

    fireEvent.click(within(notice).getByRole("button", { name: "Update this lesson to revision 2" }));
    expect(await screen.findByText("This lesson now shows revision 2. Items you saved from revision 1 stay in the Mistake Notebook exactly as you saved them.")).toBeInTheDocument();
    expect(updates(server).map((c) => JSON.parse(c.body))).toEqual([{ from_revision: 1, pack_fingerprint: FP2 }]);
    await waitFor(() => expect(screen.queryByRole("region", { name: "Script update" })).toBeNull());
    expect(screen.getByText("Revision 2")).toBeInTheDocument();
  });

  it("'Not now' writes nothing and gives focus back to 'Review the changes'; after the update its outcome takes focus", async () => {
    const server: Server = { revision: 1, calls: [], packFingerprint: FP2 };
    serve(server);
    const scripts = await openLesson();
    fireEvent.click(await within(scripts).findByRole("button", { name: `Open ${TITLE}` }));
    const notice = await screen.findByRole("region", { name: "Script update" });
    fireEvent.click(within(notice).getByRole("button", { name: "Review the changes" }));
    fireEvent.click(await within(notice).findByRole("button", { name: "Not now" }));
    await waitFor(() => expect(within(notice).getByRole("button", { name: "Review the changes" })).toHaveFocus());
    expect(within(notice).queryByRole("heading", { name: /What the update changes/ })).toBeNull();
    expect(writes(server)).toEqual([]);
    fireEvent.click(within(notice).getByRole("button", { name: "Review the changes" }));
    fireEvent.click(await within(notice).findByRole("button", { name: "Update this lesson to revision 2" }));
    // The lesson reloads after the update (a phone is back at the top of the page): the outcome takes focus.
    const outcome = await screen.findByText("This lesson now shows revision 2. Items you saved from revision 1 stay in the Mistake Notebook exactly as you saved them.");
    await waitFor(() => expect(outcome).toHaveFocus());
    expect(outcome).toHaveAttribute("role", "status");
  });

  it("names a moved question by both numbers and a removed one by its old number; the details show every changed field", async () => {
    const moved: ListeningItem = { ...item(1), id: "u05-l03", question: "Quels jours a-t-elle cours ?", segments: [2], evidence: [{ segment: 2, excerpt: "le lundi et le mercredi" }] };
    const reordered = (choices: string[]): ListeningItem => ({ ...item(2), choices, wrong_answers: [{ answer: "Elle étudie le matin.", why_wrong_en: "Not said.", why_wrong_zh: "没有说。" }] });
    const server: Server = {
      revision: 1,
      calls: [],
      packFingerprint: FP2,
      changes: {
        lines: [],
        questions: [
          {
            item_id: "u05-l04",
            change: "changed",
            before_position: 3,
            after_position: 2,
            fields: ["choices", "evidence", "position"],
            before: { ...reordered(["Elle travaille la journée.", "Elle étudie le matin."]), evidence: [{ segment: 1, excerpt: "cours du soir" }] },
            after: { ...reordered(["Elle étudie le matin.", "Elle travaille la journée."]), evidence: [{ segment: 1, excerpt: "je voudrais m'inscrire" }] },
          },
          { item_id: "u05-l03", change: "changed", before_position: 4, after_position: 3, fields: ["position"], before: moved, after: moved },
          { item_id: "u05-l02", change: "removed", before_position: 2, after_position: null, fields: [], before: item(1), after: null },
        ],
        annotations_changed: false,
      },
    };
    serve(server);
    const scripts = await openLesson();
    fireEvent.click(await within(scripts).findByRole("button", { name: `Open ${TITLE}` }));
    const notice = await screen.findByRole("region", { name: "Script update" });
    fireEvent.click(within(notice).getByRole("button", { name: "Review the changes" }));
    await within(notice).findByRole("heading", { name: "What the update changes: revision 1 → 2" });
    const list = notice.querySelector("ul.listening-revision-changes")!;
    const entries = [...list.querySelectorAll(":scope > li")];
    expect(entries.slice(0, 2).map((li) => li.textContent)).toEqual([
      "Question 2 (question 3 of revision 1) changed: options cited words",
      "Question 2 of revision 1 is removed.",
    ]);
    // Question 4 only moved up because question 2 was removed: an ordinary shift.
    expect(entries[2].firstChild!.textContent).toBe("1 other question is renumbered; nothing else in it changes.");
    expect([...entries[2].querySelectorAll("details.listening-revision-shifts li")].map((li) => li.textContent)).toEqual(["Question 4 of revision 1 is now question 3."]);
    const details = notice.querySelector("details.listening-revision-details")!;
    expect(details).toHaveTextContent("Question 2 (question 3 of revision 1)");
    expect(details).not.toHaveTextContent("question 4 of revision 1");
    expect(details).toHaveTextContent("Question 2 of revision 1");
    // The options and the cited words, before and after: what the list says changed.
    const options = [...details.querySelectorAll("ol.listening-revision-options")].map((ol) => [...ol.querySelectorAll("li")].map((li) => li.textContent));
    expect(options).toEqual([
      ["Elle travaille la journée.", "Elle étudie le matin."],
      ["Elle étudie le matin.", "Elle travaille la journée."],
    ]);
    expect(details).toHaveTextContent("Exact words in line 1: « cours du soir »");
    expect(details).toHaveTextContent("Exact words in line 1: « je voudrais m'inscrire »");
    expect(writes(server)).toEqual([]);
  });

  it("shows each retry card's revision before reveal; old and new cards resolve to their own revisions", async () => {
    const marked = (it: NotebookItem): NotebookItem => ({ ...it, retry: { marked: true, since: "t" } });
    const newMistake: NotebookItem = {
      ...oldMistake,
      entry_id: 42,
      capture_id: "listening-7-901-2",
      source: { ...oldMistake.source, record_id: 901 },
      explanation_en: NEW_WHY,
      explanation_zh: "新解释",
      latest_version: null,
      link: { listening_material_id: 7, listening_exercise_id: 901, listening_transcript_version: 2 },
    };
    const startRetry = async () => {
      const server: Server = { revision: 2, calls: [], packFingerprint: FP2, notebook: [marked(oldMistake), marked(newMistake)] };
      serve(server);
      render(
        <StrictMode>
          <App />
        </StrictMode>,
      );
      fireEvent.click(screen.getByRole("button", { name: "Mistake Notebook" }));
      fireEvent.click(await screen.findByRole("button", { name: "Retry session" }));
      fireEvent.click(await screen.findByRole("button", { name: "Start retry session" }));
      return server;
    };
    const server = await startRetry();
    // Same title, prompt and answer: before reveal only the revision tells them apart, and no answer shows.
    let card = await screen.findByRole("group", { name: "Retry item 1" });
    expect(card).toHaveTextContent("Workbook script, revision 1, question 2");
    expect(card).not.toHaveTextContent(item(1).expected_answer);
    expect(card).not.toHaveTextContent(OLD_WHY);
    fireEvent.click(within(card).getByRole("button", { name: "Reveal reference" }));
    expect(card).toHaveTextContent(OLD_WHY);
    fireEvent.click(screen.getByRole("button", { name: "Next item" }));
    card = await screen.findByRole("group", { name: "Retry item 2" });
    expect(card).toHaveTextContent("Workbook script, revision 2, question 2");
    expect(card).not.toHaveTextContent(NEW_WHY);
    fireEvent.click(within(card).getByRole("button", { name: "Reveal reference" }));
    expect(card).toHaveTextContent(NEW_WHY);
    expect(card).not.toHaveTextContent(OLD_WHY);
    // The revision-2 card opens the lesson's current revision, its question marked.
    fireEvent.click(within(card).getByRole("button", { name: "Open source" }));
    await screen.findByRole("heading", { name: TITLE });
    await waitFor(() => expect(document.querySelector("#listening-item-901-2")).toHaveClass("notebook-target"));
    expect(screen.queryByRole("region", { name: "The revision you saved from" })).toBeNull();
    expect(document.querySelector(".notebook-origin")).toHaveTextContent("question 2 of revision 2. Question 2 is marked below.");
    expect(writes(server)).toEqual([]);
    cleanup();
    // The revision-1 card opens revision 1.
    await startRetry();
    card = await screen.findByRole("group", { name: "Retry item 1" });
    fireEvent.click(within(card).getByRole("button", { name: "Open source" }));
    const earlier = await screen.findByRole("region", { name: "The revision you saved from" });
    expect(within(earlier).getByRole("heading", { name: "Revision 1: the version you saved from" })).toBeInTheDocument();
    expect(earlier.querySelector("#listening-item-900-2")).toHaveClass("notebook-target");
  });

  it("warns that unsaved answers reset on update; Not now and a stale refusal keep them", async () => {
    const server: Server = { revision: 1, calls: [], packFingerprint: FP2, staleNextUpdate: true };
    serve(server);
    const scripts = await openLesson();
    fireEvent.click(await within(scripts).findByRole("button", { name: `Open ${TITLE}` }));
    const notice = await screen.findByRole("region", { name: "Script update" });
    // Nothing answered: no warning.
    fireEvent.click(within(notice).getByRole("button", { name: "Review the changes" }));
    await within(notice).findByRole("heading", { name: "What the update changes: revision 1 → 2" });
    expect(within(notice).queryByRole("note")).toBeNull();
    fireEvent.click(within(notice).getByRole("button", { name: "Not now" }));
    const a1 = screen.getByLabelText("Your answer to question 1") as HTMLInputElement;
    const a2 = screen.getByLabelText("Your answer to question 2") as HTMLInputElement;
    fireEvent.change(a1, { target: { value: "S'inscrire." } });
    fireEvent.change(a2, { target: { value: "Elle travaille." } });
    const warning = "You have answered 2 questions on this page. Answers are not stored, so updating clears your answers: save any missed points you want to keep first.";
    fireEvent.click(within(notice).getByRole("button", { name: "Review the changes" }));
    await within(notice).findByRole("heading", { name: "What the update changes: revision 1 → 2" });
    expect(within(notice).getByRole("note")).toHaveTextContent(warning);
    fireEvent.click(within(notice).getByRole("button", { name: "Not now" }));
    expect([a1.value, a2.value]).toEqual(["S'inscrire.", "Elle travaille."]);
    fireEvent.click(within(notice).getByRole("button", { name: "Review the changes" }));
    fireEvent.click(await within(notice).findByRole("button", { name: "Update this lesson to revision 2" }));
    expect(await within(notice).findByText(/changed after you opened these changes, so nothing was updated/)).toBeInTheDocument();
    expect([a1.value, a2.value]).toEqual(["S'inscrire.", "Elle travaille."]);
    expect(within(notice).getByRole("note")).toHaveTextContent(warning);
    fireEvent.click(within(notice).getByRole("button", { name: "Update this lesson to revision 2" }));
    expect(await screen.findByText(/This lesson now shows revision 2\./)).toBeInTheDocument();
    await waitFor(() => expect((screen.getByLabelText("Your answer to question 1") as HTMLInputElement).value).toBe(""));
  });

  it("collapses the renumbering a deletion causes, lists a true reordering one by one, and tells them apart in a mix", async () => {
    const q = (id: string): ListeningItem => ({ ...item(1), id, question: `Question ${id} ?` });
    const moveOnly = (id: string, before: number, after: number) => ({
      item_id: id,
      change: "changed" as const,
      before_position: before,
      after_position: after,
      fields: ["position" as const],
      before: q(id),
      after: q(id),
    });
    const removed = (id: string, before: number) => ({ item_id: id, change: "removed" as const, before_position: before, after_position: null, fields: [], before: q(id), after: null });
    const preview = async (questions: NonNullable<Server["changes"]>["questions"]) => {
      cleanup();
      serve({ revision: 1, calls: [], packFingerprint: FP2, changes: { lines: [], questions, annotations_changed: false } });
      const scripts = await openLesson();
      fireEvent.click(await within(scripts).findByRole("button", { name: `Open ${TITLE}` }));
      const notice = await screen.findByRole("region", { name: "Script update" });
      fireEvent.click(within(notice).getByRole("button", { name: "Review the changes" }));
      await within(notice).findByRole("heading", { name: "What the update changes: revision 1 → 2" });
      const entries = [...notice.querySelectorAll("ul.listening-revision-changes > li")];
      return {
        top: entries.map((li) => li.firstChild!.textContent),
        shifts: [...notice.querySelectorAll("details.listening-revision-shifts li")].map((li) => li.textContent),
        pairs: [...notice.querySelectorAll("details.listening-revision-details .listening-revision-pair > p.label")].map((p) => p.textContent),
      };
    };
    // A deletion: the later questions only move up. One summary line; the numbers in order on expansion.
    let r = await preview([removed("u05-l02", 2), moveOnly("u05-l05", 5, 4), moveOnly("u05-l03", 3, 2), moveOnly("u05-l04", 4, 3)]);
    expect(r.top).toEqual(["Question 2 of revision 1 is removed.", "3 other questions are renumbered; nothing else in them changes."]);
    expect(r.shifts).toEqual([
      "Question 3 of revision 1 is now question 2.",
      "Question 4 of revision 1 is now question 3.",
      "Question 5 of revision 1 is now question 4.",
    ]);
    expect(r.pairs).toEqual(["Question 2 of revision 1"]);
    // A true reordering (two questions swap): each listed, no summary.
    r = await preview([moveOnly("u05-l04", 4, 3), moveOnly("u05-l03", 3, 4)]);
    expect(r.top).toEqual(["Question 4 of revision 1 is now question 3.", "Question 3 of revision 1 is now question 4."]);
    expect(r.shifts).toEqual([]);
    // Both: question 5 moved ahead of question 4 after question 2 was removed.
    r = await preview([moveOnly("u05-l03", 3, 2), moveOnly("u05-l05", 5, 3), removed("u05-l02", 2)]);
    expect(r.top).toEqual([
      "Question 5 of revision 1 is now question 3.",
      "Question 2 of revision 1 is removed.",
      "1 other question is renumbered; nothing else in it changes.",
    ]);
    expect(r.shifts).toEqual(["Question 3 of revision 1 is now question 2."]);
  });

  it("reports a removed line once and folds the lines it renumbers; a line that changed and moved names both numbers", async () => {
    const line = (id: string, text: string) => ({ id, speaker: "Mei", text });
    const moves = Array.from({ length: 7 }, (_, i) => ({ before: `s${i + 4}`, after: `s${i + 3}` })).filter((m) => m.before !== "s8");
    serve({
      revision: 1,
      calls: [],
      packFingerprint: FP2,
      changes: {
        lines: [
          { line: "s3", change: "removed", before_line: "s3", after_line: null, before: line("s3", "Ligne trois."), after: null },
          { line: "s7", change: "changed", before_line: "s8", after_line: "s7", before: line("s8", "Ligne huit."), after: line("s7", "Ligne huit, corrigée.") },
        ],
        lines_renumbered: moves,
        questions: [],
        annotations_changed: false,
      },
    });
    const scripts = await openLesson();
    fireEvent.click(await within(scripts).findByRole("button", { name: `Open ${TITLE}` }));
    const notice = await screen.findByRole("region", { name: "Script update" });
    fireEvent.click(within(notice).getByRole("button", { name: "Review the changes" }));
    await within(notice).findByRole("heading", { name: "What the update changes: revision 1 → 2" });
    const top = [...notice.querySelectorAll("ul.listening-revision-changes > li")].map((li) => li.firstChild!.textContent);
    expect(top).toEqual([
      "Line s3 is removed.",
      "Line s7 (line s8 in revision 1): the wording changed.",
      "6 other lines are renumbered; their wording does not change.",
    ]);
    const shifts = [...notice.querySelectorAll("details.listening-revision-shifts li")].map((li) => li.textContent);
    expect(shifts).toEqual(moves.map((m) => `Line ${m.before} is now line ${m.after}.`));
  });

  it("replaces a stale preview with a fresh one and updates only on the second confirmation", async () => {
    const server: Server = { revision: 1, calls: [], packFingerprint: FP2, staleNextUpdate: true };
    serve(server);
    const scripts = await openLesson();
    fireEvent.click(await within(scripts).findByRole("button", { name: `Open ${TITLE}` }));
    const notice = await screen.findByRole("region", { name: "Script update" });
    fireEvent.click(within(notice).getByRole("button", { name: "Review the changes" }));
    fireEvent.click(await within(notice).findByRole("button", { name: "Update this lesson to revision 2" }));
    expect(await within(notice).findByText(/changed after you opened these changes, so nothing was updated/)).toBeInTheDocument();
    expect(server.revision).toBe(1);
    fireEvent.click(within(notice).getByRole("button", { name: "Update this lesson to revision 2" }));
    expect(await screen.findByText(/This lesson now shows revision 2\./)).toBeInTheDocument();
    expect(updates(server).map((c) => JSON.parse(c.body).pack_fingerprint)).toEqual([FP2, FP3]);
  });

  it("after a lost response, confirming again is safe: the server replays and no second revision is added", async () => {
    const server: Server = { revision: 1, calls: [], packFingerprint: FP2, loseNextUpdate: true };
    serve(server);
    const scripts = await openLesson();
    fireEvent.click(await within(scripts).findByRole("button", { name: `Open ${TITLE}` }));
    const notice = await screen.findByRole("region", { name: "Script update" });
    fireEvent.click(within(notice).getByRole("button", { name: "Review the changes" }));
    fireEvent.click(await within(notice).findByRole("button", { name: "Update this lesson to revision 2" }));
    expect(await within(notice).findByText(/it is unknown whether the lesson was updated\. Confirming again is safe/)).toBeInTheDocument();
    fireEvent.click(within(notice).getByRole("button", { name: "Confirm the update again" }));
    expect(await screen.findByText("This lesson already shows revision 2, the current version, so nothing was changed again.")).toBeInTheDocument();
    const bodies = updates(server).map((c) => c.body);
    expect(bodies).toHaveLength(2);
    expect(bodies[1]).toBe(bodies[0]); // the identical confirmation
    expect(server.revision).toBe(2);
  });

  it("when another tab updated first, reviewing says so, writes nothing and keeps unsaved answers and saved mistakes", async () => {
    const server: Server = { revision: 1, calls: [], packFingerprint: FP2, notebook: [oldMistake] };
    serve(server);
    const scripts = await openLesson();
    fireEvent.click(await within(scripts).findByRole("button", { name: `Open ${TITLE}` }));
    const notice = await screen.findByRole("region", { name: "Script update" });
    const a1 = screen.getByLabelText("Your answer to question 1") as HTMLInputElement;
    fireEvent.change(a1, { target: { value: "S'inscrire." } });
    server.revision = 2; // another tab confirmed the update meanwhile
    fireEvent.click(within(notice).getByRole("button", { name: "Review the changes" }));
    expect(await within(notice).findByText(/This lesson was updated to revision 2 elsewhere \(another tab or device\)\. This page still shows revision 1/)).toBeInTheDocument();
    expect(within(notice).queryByRole("button", { name: /Update this lesson to revision/ })).toBeNull();
    expect(within(notice).queryByRole("heading", { name: /What the update changes/ })).toBeNull();
    expect(a1.value).toBe("S'inscrire.");
    expect(updates(server)).toEqual([]);
    expect(writes(server)).toEqual([]);
    // Showing the current lesson is the learner's choice; the saved mistake keeps revision 1.
    fireEvent.click(within(notice).getByRole("button", { name: "Show the current lesson" }));
    await waitFor(() => expect(document.querySelector("#listening-item-901-1")).not.toBeNull());
    expect(server.notebook![0].link.listening_transcript_version).toBe(1);
  });

  it("opens an old Mistake Notebook item on the revision it was saved from, after the lesson moved on", async () => {
    const server: Server = { revision: 2, calls: [], packFingerprint: FP2, notebook: [oldMistake] };
    serve(server);
    render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Mistake Notebook" }));
    const list = await screen.findByRole("region", { name: "Saved mistakes" });
    fireEvent.click(await within(list).findByRole("button", { name: "Open source" }));
    const earlier = await screen.findByRole("region", { name: "The revision you saved from" });
    expect(within(earlier).getByRole("heading", { name: "Revision 1: the version you saved from" })).toBeInTheDocument();
    expect(earlier).toHaveTextContent("The lesson below shows revision 2.");
    const marked = earlier.querySelector("#listening-item-900-2")!;
    expect(marked).toHaveClass("notebook-target");
    expect(marked).toHaveTextContent(item(1).question);
    expect(document.querySelector(".notebook-origin")).toHaveTextContent("Opened from the Mistake Notebook for question 2 of revision 1. Question 2 is marked below.");
    // The current revision is still the lesson's exercise below it.
    expect(document.querySelector("#listening-item-901-2")).not.toBeNull();
    expect(server.calls.some((c) => c.path === "/api/listening/materials/7/revisions/1")).toBe(true);
    expect(writes(server)).toEqual([]);
  });

  it("is offered in Simplified Chinese", async () => {
    const server: Server = { revision: 1, calls: [], packFingerprint: FP2 };
    serve(server);
    const scripts = await openLesson("zh-CN");
    expect(await within(scripts).findByText("有更新")).toBeInTheDocument();
    fireEvent.click(within(scripts).getByRole("button", { name: `打开 ${TITLE}` }));
    const notice = await screen.findByRole("region", { name: "脚本更新" });
    fireEvent.click(within(notice).getByRole("button", { name: "查看改动" }));
    expect(await within(notice).findByRole("heading", { name: "更新会改动什么：第 1 版 → 第 2 版" })).toBeInTheDocument();
    expect(notice).toHaveTextContent("你之前的练习留在第 1 版");
    fireEvent.click(within(notice).getByRole("button", { name: "把这节课更新到第 2 版" }));
    expect(await screen.findByText("这节课现在显示第 2 版。你从第 1 版保存的条目在错题本中按原样保留。")).toBeInTheDocument();
  });
});
