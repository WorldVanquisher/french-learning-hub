// Revision studio against a stateful fake of the four revision routes:
// what belongs to each revision, the one-revision view, block comparison with
// labelled word edits and folded unchanged lines (the source revisions always
// named), long French text kept exactly, a restore previewed then confirmed
// once, and a second editor's stale preview replaced by a fresh one.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "../i18n";
import type { ListeningLineBlock, ListeningRestorePreview, ListeningRevisionRow } from "../types/listening";
import { RevisionStudio } from "./RevisionStudio";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const LONG = "« Bonjour ! » dit Hélène.\nElle explique, très lentement, qu’elle finit le travail à 17 h 30… puis elle court à l’école Saint-Éloi ; c’est loin ? Oui.";
const row = (n: number, current: boolean, records: number, today = 0): ListeningRevisionRow => ({
  revision: n,
  current,
  created_at: `2026-11-1${n}T09:00:00Z`,
  fingerprint: `sha256:${String(n).repeat(64)}`,
  transcript_id: 10 + n,
  lines: 6,
  exercise_id: 20 + n,
  generator: "authored:flh_listening_script_pack_v1",
  questions: 4,
  audio: "none",
  linked_records: Array.from({ length: records }, (_, i) => ({ entry_id: 40 + i, item: i + 1, in_review_today: i < today })),
});
const same = (n: number, text = `Ligne ${n}.`): ListeningLineBlock => ({
  kind: "same",
  before_line: `s${n}`,
  after_line: `s${n}`,
  before: { id: `s${n}`, speaker: "A", text },
  after: { id: `s${n}`, speaker: "A", text },
  speaker_changed: false,
  words: [],
});
const blocks: ListeningLineBlock[] = [
  same(1, LONG),
  same(2),
  same(3),
  {
    kind: "changed",
    before_line: "s4",
    after_line: "s4",
    before: { id: "s4", speaker: "B", text: "Je finis à 17 h 30." },
    after: { id: "s4", speaker: "B", text: "Je finis à 18 h." },
    speaker_changed: false,
    words: [
      { op: "same", text: "Je finis à " },
      { op: "removed", text: "17" },
      { op: "inserted", text: "18" },
      { op: "same", text: " h" },
      { op: "removed", text: " 30" },
      { op: "same", text: "." },
    ],
  },
  same(5),
  { kind: "added", before_line: null, after_line: "s6", before: null, after: { id: "s6", speaker: "A", text: "Bon, à demain !" }, speaker_changed: false, words: [] },
];
const changes = { lines: [], lines_renumbered: [], questions: [], annotations_changed: false };
const ref = (n: number) => ({ revision: n, fingerprint: `sha256:${String(n).repeat(64)}`, exercise_id: 20 + n, created_at: "t" });
const preview = (current: number, target: number): ListeningRestorePreview => ({
  material_id: 7,
  current_revision: current,
  from: ref(current),
  to: ref(target),
  blocks,
  changes,
  target_revision: target,
  target_fingerprint: ref(target).fingerprint,
  next_revision: current + 1,
  blocked: null,
  current_exercise_id: 20 + current,
  records_on_current: [],
});

function serve(state: { revisions: ListeningRevisionRow[]; current: number; staleOnce?: boolean }) {
  const calls: { method: string; path: string; body: string }[] = [];
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ method, path: url.pathname + url.search, body: String(init?.body ?? "") });
    const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    const p = url.pathname;
    if (method === "GET" && p === "/api/listening/materials/7/revisions")
      return json(200, { material_id: 7, title: "T", script_id: "ls-wb1-u05", current_revision: state.current, pack_status: "up_to_date", pack_fingerprint: null, revisions: state.revisions });
    if (method === "GET" && p === "/api/listening/materials/7/revision-compare") {
      const from = Number(url.searchParams.get("from")), to = Number(url.searchParams.get("to"));
      return json(200, { material_id: 7, current_revision: state.current, from: ref(from), to: ref(to), blocks, changes });
    }
    if (method === "GET" && p === "/api/listening/materials/7/restore") return json(200, preview(state.current, Number(url.searchParams.get("revision"))));
    if (method === "POST" && p === "/api/listening/materials/7/restore") {
      const body = JSON.parse(String(init?.body));
      if (state.staleOnce) {
        // Another editor restored first: the lesson moved on.
        state.staleOnce = false;
        state.current += 1;
        return json(409, { error: "stale", code: "stale_preview", preview: preview(state.current, body.revision) });
      }
      if (body.from_revision !== state.current) return json(409, { error: "stale", code: "stale_preview", preview: preview(state.current, body.revision) });
      state.current += 1;
      return json(201, { revision: state.current, restored_from: body.revision, replayed: false, lesson: {} });
    }
    return json(404, { error: "not found" });
  }) as unknown as typeof fetch;
  return calls;
}

const renderStudio = (current: number) => {
  const onRestored = vi.fn();
  render(
    <LocaleProvider>
      <RevisionStudio materialId={7} currentRevision={current} answered={2} onRestored={onRestored} />
    </LocaleProvider>,
  );
  return onRestored;
};

describe("Revision studio", () => {
  it("reads nothing until opened, then shows what belongs to each revision", async () => {
    const calls = serve({ revisions: [row(1, false, 2, 1), row(2, false, 0), row(3, true, 0)], current: 3 });
    renderStudio(3);
    expect(calls).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Revision history (current: revision 3)" }));
    const list = await screen.findByRole("list", { name: "Stored revisions" });
    const first = within(list).getAllByRole("listitem")[0];
    expect(first).toHaveTextContent("6 lines (transcript #11)");
    expect(first).toHaveTextContent("4 questions (exercise #21)");
    expect(first).toHaveTextContent("Authored key in exercise #21: authored:flh_listening_script_pack_v1");
    expect(first).toHaveTextContent("None: a workbook script is read, never recorded.");
    expect(first).toHaveTextContent("2 records saved from this revision (1 in Review Today). They keep this revision's wording.");
    expect(within(list).getAllByRole("listitem")[2]).toHaveTextContent("Current");
    expect(calls.every((c) => c.method === "GET")).toBe(true);
  });

  it("makes a one-revision history useful from one screen", async () => {
    const calls = serve({ revisions: [row(1, true, 0)], current: 1 });
    renderStudio(1);
    fireEvent.click(screen.getByRole("button", { name: "Revision history (current: revision 1)" }));
    expect(await screen.findByText(/Revision 1 is the only revision of this script/)).toBeInTheDocument();
    expect(screen.getByText("No record was saved from this revision.")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Compare revisions" })).toBeNull();
    expect(calls.map((c) => c.path)).toEqual(["/api/listening/materials/7/revisions"]);
  });

  it("compares block by block: folded unchanged lines, labelled word edits, both revisions always named, text kept exactly", async () => {
    serve({ revisions: [row(1, false, 0), row(2, false, 0), row(3, true, 0)], current: 3 });
    renderStudio(3);
    fireEvent.click(screen.getByRole("button", { name: "Revision history (current: revision 3)" }));
    const lines = await screen.findByRole("list", { name: "Lines of revision 2 and revision 3" });
    // Folded: s1–s3 and s5 behind buttons; the changed and added lines shown.
    expect(within(lines).getByRole("button", { name: "3 unchanged lines (s1–s3): show" })).toBeInTheDocument();
    expect(within(lines).getByRole("button", { name: "1 unchanged line (s5): show" })).toBeInTheDocument();
    const changed = lines.querySelector('[data-kind="changed"]')!;
    expect(changed).toHaveTextContent("Changed line s4 → s4");
    expect([...changed.querySelectorAll("del")].map((d) => d.textContent)).toEqual(["removed: 17", "removed:  30"]);
    expect([...changed.querySelectorAll("ins")].map((d) => d.textContent)).toEqual(["inserted: 18"]);
    expect(lines.querySelector('[data-kind="added"]')).toHaveTextContent("Added line s6");
    expect(screen.getByText("Revision 2 → revision 3.")).toBeInTheDocument();
    // Unfold one run: the long French line keeps its line break, guillemets and non-breaking spaces.
    fireEvent.click(within(lines).getByRole("button", { name: "3 unchanged lines (s1–s3): show" }));
    const first = lines.querySelector('[data-kind="same"] .studio-text')!;
    expect(first.textContent).toBe(LONG);
    // Showing everything keeps the header naming both revisions.
    fireEvent.click(screen.getByLabelText("Fold unchanged lines"));
    expect(lines.querySelectorAll("li[data-kind]").length).toBe(6);
    expect(screen.getByText("Revision 2 → revision 3.")).toBeInTheDocument();
    // Another pair from the selectors.
    fireEvent.change(screen.getByLabelText("Older"), { target: { value: "1" } });
    expect(await screen.findByText("Revision 1 → revision 3.")).toBeInTheDocument();
  });

  it("previews a restore with its effects and writes only on the explicit confirm, once", async () => {
    const state = { revisions: [row(1, false, 0), row(2, false, 0), row(3, true, 1)], current: 3 };
    const calls = serve(state);
    const onRestored = renderStudio(3);
    fireEvent.click(screen.getByRole("button", { name: "Revision history (current: revision 3)" }));
    fireEvent.click(await screen.findByRole("button", { name: "Preview restoring revision 1" }));
    const heading = await screen.findByRole("heading", { name: "Restore revision 1 over revision 3?" });
    await waitFor(() => expect(heading).toHaveFocus());
    const impact = screen.getByRole("list", { name: "What a restore changes" });
    expect(impact).toHaveTextContent("Revision 4 is added with revision 1's lines, questions and answer key. No revision is changed or deleted.");
    expect(impact).toHaveTextContent("The lesson's questions move from exercise #23 (revision 3) to a new exercise.");
    expect(screen.getByText(/You have answered 2 questions on this page/)).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toEqual([]);
    const confirm = screen.getByRole("button", { name: "Restore revision 1 as revision 4" });
    await act(async () => {
      fireEvent.click(confirm);
      fireEvent.click(confirm);
    });
    await waitFor(() => expect(onRestored).toHaveBeenCalledWith(3, 4, false));
    const posts = calls.filter((c) => c.method === "POST");
    expect(posts).toHaveLength(1);
    expect(JSON.parse(posts[0].body)).toEqual({ from_revision: 3, revision: 1, fingerprint: `sha256:${"1".repeat(64)}` });
  });

  it("replaces a second editor's stale preview with a fresh one and writes nothing until confirmed again", async () => {
    const state = { revisions: [row(1, false, 0), row(2, false, 0), row(3, true, 0)], current: 3, staleOnce: true };
    const calls = serve(state);
    const onRestored = renderStudio(3);
    fireEvent.click(screen.getByRole("button", { name: "Revision history (current: revision 3)" }));
    fireEvent.click(await screen.findByRole("button", { name: "Preview restoring revision 2" }));
    fireEvent.click(await screen.findByRole("button", { name: "Restore revision 2 as revision 4" }));
    expect(await screen.findByText(/The lesson changed since that preview \(another tab or device\); it is now at revision 4\. Nothing was restored\./)).toBeInTheDocument();
    expect(onRestored).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Restore revision 2 over revision 4?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Restore revision 2 as revision 5" }));
    await waitFor(() => expect(onRestored).toHaveBeenCalledWith(4, 5, false));
    expect(calls.filter((c) => c.method === "POST").map((c) => JSON.parse(c.body).from_revision)).toEqual([3, 4]);
  });
});
