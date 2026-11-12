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
    changes: available
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
    expect(document.querySelector(".notebook-origin")).toHaveTextContent("(transcript version 1). Question 2 is marked below.");
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
