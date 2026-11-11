// Workbook listening scripts in the private workbench: import, repeat import,
// reopening, answer reveal and an explicit "save learning record", against a
// stateful fake server. The script is excerpted from the synthetic workbook
// unit u05 (internal/listening/pack). It has no link, video, audio or timestamp.
import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { ListeningExercise, ListeningLesson, ListeningMaterial, ListeningScriptSummary, TranscriptSegment } from "../types/listening";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

const PACK_ID = "flh_listening_script_pack_v1/ls-wb1-u05";
const TITLE = "À l'accueil de la Maison des langues";

const scriptMaterial = (id: number): ListeningMaterial => ({
  id,
  source_kind: "authored_script",
  video_id: null,
  source_url: null,
  pack_script_id: PACK_ID,
  title: TITLE,
  created_at: "2026-11-11T08:00:00Z",
});

const lines: TranscriptSegment[] = [
  { index: 1, start_seconds: null, speaker: "Mei, future élève", text: "Bonjour, je voudrais m'inscrire au cours du soir de français." },
  { index: 2, start_seconds: null, speaker: "Agent d'accueil", text: "Bonjour ! Vous avez déjà passé le test de niveau ?" },
  { index: 3, start_seconds: null, speaker: "Mei, future élève", text: "Oui, la semaine dernière. Le professeur m'a dit que j'étais en A2." },
  {
    index: 4,
    start_seconds: null,
    speaker: "Agent d'accueil",
    text: "Très bien. Pour l'A2, il reste de la place le lundi et le mercredi. Le mardi et le jeudi, c'est complet.",
  },
];

const authoredExercise = (id: number): ListeningExercise => ({
  id,
  transcript_id: 500,
  status: "completed",
  failure_code: null,
  generator: "authored:flh_listening_script_pack_v1",
  created_at: "2026-11-11T08:00:00Z",
  content: {
    items: [
      {
        id: "u05-l01",
        kind: "main_idea",
        question: "Que fait Mei à l'accueil ?",
        expected_answer: "Elle s'inscrit au cours du soir de français.",
        rationale_en: "She says she wants to enrol (s1).",
        rationale_zh: "她说她想报名（s1）。",
        segments: [1],
        choices: ["Elle demande un remboursement.", "Elle s'inscrit au cours du soir de français.", "Elle passe le test de niveau."],
        wrong_answers: [
          { answer: "Elle demande un remboursement.", why_wrong_en: "No refund is mentioned (s1).", why_wrong_zh: "没有提到退款（s1）。" },
          { answer: "Elle passe le test de niveau.", why_wrong_en: "She took it last week (s3).", why_wrong_zh: "她上周已经考过了（s3）。" },
        ],
        evidence: [{ segment: 1, excerpt: "je voudrais m'inscrire au cours du soir" }],
      },
      {
        id: "u05-l03",
        kind: "detail",
        question: "Quels jours reste-t-il de la place en A2 ?",
        expected_answer: "le lundi et le mercredi",
        accepted_alternatives: ["lundi et mercredi"],
        rationale_en: "Monday and Wednesday.",
        rationale_zh: "周一和周三。",
        segments: [4],
        evidence: [{ segment: 4, excerpt: "il reste de la place le lundi et le mercredi" }],
      },
    ],
    annotations: [],
  },
});

type Call = { method: string; path: string; body: string };
type Server = { imported: ListeningLesson | null; calls: Call[]; loseNextImport?: boolean; imports: number };

const summary = (server: Server): ListeningScriptSummary => ({
  id: "ls-wb1-u05",
  title: TITLE,
  genre: "dialogue",
  style_level: "A2",
  source_pack: "flh_workbook_reading_listening_v1",
  notice: "Synthetic listening script (unreviewed). Written text only: no audio, no video, no timestamps.",
  lines: lines.length,
  questions: 2,
  imported_material_id: server.imported ? server.imported.material.id : null,
});

function serve(server: Server) {
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const body = String(init?.body ?? "");
    const p = url.pathname;
    server.calls.push({ method, path: p, body });
    const view = (l: ListeningLesson) => l;
    if (method === "GET" && p === "/api/listening/scripts") return json(200, { pack: "flh_listening_script_pack_v1", scripts: [summary(server)] });
    if (method === "POST" && p === "/api/listening/scripts/ls-wb1-u05") {
      // The server is idempotent: the first import stores, later ones replay.
      const created = server.imported === null;
      if (created) {
        server.imports++;
        server.imported = {
          material: scriptMaterial(7),
          transcript: { id: 500, version: 1, has_timestamps: false, segments: lines, created_at: "2026-11-11T08:00:00Z" },
          exercises: [authoredExercise(900)],
          generation: { enabled: false, generator: null },
          state: "prepared",
          in_playlist: false,
          preparations: [],
          notifications: [],
          notification: { enabled: false, channel: null },
        };
      }
      if (server.loseNextImport) {
        server.loseNextImport = false;
        throw new TypeError("network down"); // stored, but the response is lost
      }
      return json(created ? 201 : 200, view(server.imported!));
    }
    if (method === "GET" && p === "/api/listening/materials")
      return json(200, {
        generation: { enabled: false, generator: null },
        materials: server.imported
          ? [{ material: server.imported.material, transcript_version: 1, segment_count: lines.length, latest_exercise: { ...server.imported.exercises[0], content: null }, state: "prepared", in_playlist: false }]
          : [],
      });
    if (method === "GET" && p === "/api/listening/materials/7") return server.imported ? json(200, view(server.imported)) : json(404, { error: "listening material not found" });
    if (method === "GET" && p === "/api/listening/daily")
      return json(200, {
        pull_enabled: false,
        source: { enabled: false, name: null },
        preparation: { enabled: false, generator: null, daily_cap: 1, timezone: "UTC", today: "2026-11-11", used_today: 0 },
        notification: { enabled: false, channel: null },
        last_run: null,
      });
    if (method === "POST" && p === "/api/captures") {
      const doc = JSON.parse(body) as { capture_id: string };
      return json(201, { capture_id: doc.capture_id, entry_id: 41, analysis_id: null, created: true });
    }
    if (p === "/api/reviewable-units") return json(200, { reviewable_units: [] });
    if (p === "/api/learning-records") return json(200, { records: [], next_before_entry_id: null });
    return json(200, { concepts: [] });
  }) as unknown as typeof fetch;
}

const writes = (server: Server) => server.calls.filter((c) => c.method !== "GET");

async function openScripts() {
  render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Listening" }));
  return await screen.findByRole("region", { name: "Workbook listening scripts" });
}

describe("Workbook listening scripts (private workbench)", () => {
  it("imports a script as a script-only lesson: no video, link or timestamp, and no provider call", async () => {
    const server: Server = { imported: null, calls: [], imports: 0 };
    serve(server);
    const panel = await openScripts();
    expect(within(panel).getByText(TITLE)).toBeInTheDocument();
    expect(within(panel).getByText("Script only · no audio")).toBeInTheDocument();
    expect(within(panel).getByText(/target level A2 \(not certified\) · 4 lines · 2 questions/)).toBeInTheDocument();
    expect(writes(server)).toEqual([]); // listing imports nothing

    fireEvent.click(within(panel).getByRole("button", { name: `Import ${TITLE}` }));
    expect(await screen.findByRole("heading", { name: TITLE })).toBeInTheDocument();
    expect(screen.getByText(/There is no audio, no video and no timestamp/)).toBeInTheDocument();
    expect(screen.getByText("Script: 4 lines, without timestamps.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /YouTube/ })).toBeNull();
    const header = screen.getByRole("region", { name: "Listening lesson" });
    expect(within(header).queryByText(/YouTube/)).toBeNull();
    expect(document.querySelector('a[href*="youtube"]')).toBeNull();
    expect(screen.queryByRole("button", { name: "Prepare exercise" })).toBeNull();
    expect(screen.queryByRole("form", { name: "Waiting for a transcript" })).toBeNull();
    expect(screen.getByRole("region", { name: "Listening exercise" })).toBeInTheDocument();
    expect(writes(server).map((c) => c.path)).toEqual(["/api/listening/scripts/ls-wb1-u05"]);
  });

  it("repeat import after a lost response and reopening open the same lesson; nothing is stored twice", async () => {
    const server: Server = { imported: null, calls: [], imports: 0, loseNextImport: true };
    serve(server);
    const panel = await openScripts();
    fireEvent.click(within(panel).getByRole("button", { name: `Import ${TITLE}` }));
    expect(await within(panel).findByText(/it is unknown whether this script was imported\. Importing again is safe/)).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: `Import ${TITLE}` }));
    expect(await screen.findByRole("heading", { name: TITLE })).toBeInTheDocument();
    expect(server.imports).toBe(1);

    fireEvent.click(screen.getByRole("button", { name: "← All listening material" }));
    const again = await screen.findByRole("region", { name: "Workbook listening scripts" });
    fireEvent.click(await within(again).findByRole("button", { name: `Open ${TITLE}` }));
    expect(await screen.findByRole("heading", { name: TITLE })).toBeInTheDocument();
    const list = screen.queryByRole("region", { name: "Saved listening material" });
    expect(list).toBeNull();
    expect(server.imports).toBe(1);
    expect(writes(server).map((c) => c.path)).toEqual(["/api/listening/scripts/ls-wb1-u05", "/api/listening/scripts/ls-wb1-u05"]);
    expect(server.calls.filter((c) => c.path === "/api/listening/materials/7").length).toBeGreaterThan(0);
  });

  it("hides answers, evidence and the script until asked; the reader view shows the script only; reveal shows the key and reasons", async () => {
    const server: Server = { imported: null, calls: [], imports: 0 };
    serve(server);
    const panel = await openScripts();
    fireEvent.click(within(panel).getByRole("button", { name: `Import ${TITLE}` }));
    await screen.findByRole("heading", { name: TITLE });
    const exercise = screen.getByRole("region", { name: "Listening exercise" });
    const content = authoredExercise(900).content!;

    // Before reveal: questions and choices only.
    expect(within(exercise).getByText(content.items[0].question)).toBeInTheDocument();
    const choices = within(exercise).getByRole("group", { name: "Your choice for question 1" });
    expect(within(choices).getAllByRole("radio")).toHaveLength(3);
    for (const hidden of [
      ...lines.map((l) => l.text),
      content.items[0].rationale_en,
      content.items[0].wrong_answers![0].why_wrong_en,
      content.items[1].expected_answer,
      "Reference answer:",
    ])
      expect(screen.queryByText(hidden, { exact: false })).toBeNull();

    // The reader view shows the script with speakers, still no key.
    fireEvent.click(within(exercise).getByRole("button", { name: "Show the script to the person reading it aloud" }));
    const reader = within(exercise).getByRole("region", { name: "Script to read aloud" });
    for (const l of lines) expect(within(reader).getByText(l.text)).toBeInTheDocument();
    expect(within(reader).getAllByText("Agent d'accueil :")).toHaveLength(2);
    expect(screen.queryByText("Reference answer:")).toBeNull();
    fireEvent.click(within(exercise).getByRole("button", { name: "Hide the script" }));
    expect(within(exercise).queryByRole("region", { name: "Script to read aloud" })).toBeNull();
    // A reader who reached the end hides it there; focus returns to the toggle.
    const toggle = within(exercise).getByRole("button", { name: "Show the script to the person reading it aloud" });
    fireEvent.click(toggle);
    fireEvent.click(within(within(exercise).getByRole("region", { name: "Script to read aloud" })).getByRole("button", { name: "End of the script: hide it" }));
    expect(within(exercise).queryByRole("region", { name: "Script to read aloud" })).toBeNull();
    expect(toggle).toHaveFocus();
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(within(choices).getByRole("radio", { name: content.items[0].choices![0] }));
    fireEvent.change(within(exercise).getByLabelText("Your answer to question 2"), { target: { value: "mardi-secret" } });
    expect(writes(server)).toHaveLength(1); // answering sends nothing
    fireEvent.click(within(exercise).getByRole("button", { name: "Reveal answers and evidence" }));

    const first = screen.getByRole("group", { name: "Reference for question 1" });
    expect(within(first).getByText(content.items[0].expected_answer)).toBeInTheDocument();
    expect(within(first).getByText("Why not « Elle demande un remboursement. »:")).toBeInTheDocument();
    expect(within(first).getByText("No refund is mentioned (s1).")).toBeInTheDocument();
    expect(within(first).getByText("From the script:")).toBeInTheDocument();
    expect(within(first).getByText("Exact words in line 1:")).toBeInTheDocument();
    expect(within(first).getByText("« je voudrais m'inscrire au cours du soir »")).toBeInTheDocument();
    const second = screen.getByRole("group", { name: "Reference for question 2" });
    expect(within(second).getByText("Also accepted:")).toBeInTheDocument();
    expect(within(second).getByText("lundi et mercredi")).toBeInTheDocument();
    expect(within(second).getByText(lines[3].text)).toBeInTheDocument();
    expect(within(exercise).queryByRole("link")).toBeNull(); // no video position for a script line
    expect(screen.queryByText("Vocabulary and grammar notes")).toBeNull(); // no notes for this script
    expect(screen.getByText(/The key is the workbook's own; no teacher has reviewed it/)).toBeInTheDocument();
    expect(within(choices).getByRole("radio", { name: content.items[0].choices![0] })).toBeChecked();
    expect(writes(server)).toHaveLength(1);
    expect(server.calls.some((c) => c.body.includes("mardi-secret"))).toBe(false);
  });

  it("saves a missed point only on explicit confirmation, citing the authored script and no video", async () => {
    const server: Server = { imported: null, calls: [], imports: 0 };
    serve(server);
    const panel = await openScripts();
    fireEvent.click(within(panel).getByRole("button", { name: `Import ${TITLE}` }));
    await screen.findByRole("heading", { name: TITLE });
    fireEvent.click(screen.getByRole("button", { name: "Reveal answers and evidence" }));
    const second = screen.getByRole("group", { name: "Reference for question 2" });
    fireEvent.click(within(second).getByRole("button", { name: "Save as a learning question…" }));
    const form = screen.getByRole("form", { name: "Save a missed point from question 2" });
    expect(within(form).getByText(/Source: authored script, no audio or video \(flh_listening_script_pack_v1\/ls-wb1-u05\)/)).toBeInTheDocument();
    expect(writes(server)).toHaveLength(1); // only the import so far

    const question = "Pourquoi « il reste de la place » veut dire que ce n'est pas complet ?";
    fireEvent.change(within(form).getByLabelText("What did you miss, or what do you want to ask?"), { target: { value: question } });
    fireEvent.click(within(form).getByRole("button", { name: "Save learning record" }));
    expect(await screen.findByText("Saved as learning record #41.")).toBeInTheDocument();

    const posts = writes(server).filter((c) => c.path === "/api/captures");
    expect(posts).toHaveLength(1);
    const doc = JSON.parse(posts[0].body) as Record<string, string>;
    expect(doc.source).toBe("manual");
    expect(doc.original_input).toBe(question);
    expect(doc.capture_id).toMatch(/^listening-7-900-2-/);
    expect(doc.original_context).toBe(
      [
        `Listening exercise: ${TITLE}`,
        `Source: authored script, no audio or video (${PACK_ID})`,
        "Question u05-l03 (detail): Quels jours reste-t-il de la place en A2 ?",
        `Excerpt (segment 4, Agent d'accueil): « ${lines[3].text} »`,
      ].join("\n"),
    );
    expect(doc.original_context).not.toMatch(/youtube|Video:|\d:\d\d/);
    // With the Mistake Notebook (private stack), a capture also names its exact
    // source item; for a script it is the authored exercise's item, like any
    // listening item.
    const { source_ref: ref, ...rest } = JSON.parse(posts[0].body) as Record<string, unknown>;
    expect(Object.keys(rest).sort()).toEqual(["capture_id", "original_context", "original_input", "schema_version", "source"]);
    if (ref !== undefined) expect(ref).toEqual({ type: "listening_item", record_id: 900, item: 2 });
  });

  it("back on the list, your own lessons come first and the imported script is marked", async () => {
    const server: Server = { imported: null, calls: [], imports: 0 };
    serve(server);
    const panel = await openScripts();
    expect(within(panel).getByText(/^0 of 1 scripts imported\./)).toBeInTheDocument();
    expect(within(panel).queryByText("Imported")).toBeNull();
    const saved = screen.getByRole("region", { name: "Saved listening material" });
    // Your own material precedes the catalogue of workbook scripts.
    expect(saved.compareDocumentPosition(panel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(saved).getByText("No listening material yet. Add a YouTube link above, or import a workbook script below.")).toBeInTheDocument();

    fireEvent.click(within(panel).getByRole("button", { name: `Import ${TITLE}` }));
    await screen.findByRole("heading", { name: TITLE });
    fireEvent.click(screen.getByRole("button", { name: "← All listening material" }));
    const again = await screen.findByRole("region", { name: "Workbook listening scripts" });
    expect(await within(again).findByText(/^1 of 1 scripts imported\./)).toBeInTheDocument();
    const row = within(again).getByRole("button", { name: `Open ${TITLE}` }).closest("li")!;
    expect(within(row).getByText("Imported")).toBeInTheDocument();
    expect(within(again).queryByRole("button", { name: `Import ${TITLE}` })).toBeNull();
    const savedAgain = screen.getByRole("region", { name: "Saved listening material" });
    expect(within(savedAgain).getByRole("button", { name: TITLE })).toBeInTheDocument();
    expect(savedAgain.compareDocumentPosition(again) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("labels the scripts in Simplified Chinese without translating the French", async () => {
    window.localStorage.setItem("flh.ui-locale.v1", "zh-CN");
    const server: Server = { imported: null, calls: [], imports: 0 };
    serve(server);
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "听力" }));
    const panel = await screen.findByRole("region", { name: "练习册听力脚本" });
    expect(within(panel).getByText(TITLE)).toBeInTheDocument();
    expect(within(panel).getByText("仅脚本 · 无音频")).toBeInTheDocument();
  });
});
