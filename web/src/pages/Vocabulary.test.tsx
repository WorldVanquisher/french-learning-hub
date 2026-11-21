// Vocabulary (VOC) against a stateful fake of the vocabulary, Concept-kind,
// Knowledge Library concept and source reads: save from an approved item, see
// it at once and after a remount, its meaning and the learner's own words, open
// its source and come back with the query kept, review it with Recall
// Practice, remove it with focus moving on, and the failure paths. Synthetic
// French only.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "../i18n";
import type { VocabularyItem } from "../types/vocabulary";
import { VocabularyBook } from "./Vocabulary";
import { resetVocabularyMemory } from "./vocabularyMemory";

beforeEach(() => resetVocabularyMemory());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

const concepts = [
  { id: 12, target: "apporter", scope: "", units: [{ id: 101, entry: 7, canonical: "apporter", meaning: "to bring (a thing)", zh: "带来（东西）" }] },
  { id: 14, target: "faire la grasse matinée", scope: "", units: [{ id: 103, entry: 9, canonical: "faire  la grasse matinée", meaning: "to sleep in", zh: null }] },
  { id: 15, target: "<img src=x onerror=alert(1)>", scope: "", units: [{ id: 104, entry: 10, canonical: "<b>pas du HTML</b>", meaning: "not HTML", zh: null }] },
  { id: 16, target: "anticonstitutionnellement-très-long-mot-composé-sans-espace", scope: "", units: [] },
  { id: 17, target: "ancien", scope: "", support: 0, units: [{ id: 107, entry: 13, canonical: "ancien", meaning: "former / old", zh: null }] },
  { id: 13, target: "amener", scope: "", units: [{ id: 105, entry: 11, canonical: "amener", meaning: "to bring (a person)", zh: "带（人）来" }, { id: 106, entry: 12, canonical: "amener", meaning: "to take someone along", zh: "带上某人" }] },
];
const questions: Record<number, string> = {
  7: "Comment dit-on « bring » quand on va dîner chez des amis ?",
  9: "Que veut dire « faire la grasse matinée » ?",
  10: "Est-ce que <b> s'affiche ?",
  11: "Amener ou apporter pour un ami ?",
  12: "J'amène mon frère à la fête : correct ?",
  13: "« mon ancien prof » : vieux ou ex ?",
};

interface Fake {
  saved: Map<number, number[]>; // concept → example unit ids (current saves)
  everSaved: Set<number>;
  failPut?: (n: number) => "network" | "500" | null;
  failDelete?: (n: number) => "network" | "500" | null;
}

function serve(state: Fake) {
  const calls: { method: string; path: string; search: string; body: string }[] = [];
  let puts = 0;
  let dels = 0;
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const item = (id: number): VocabularyItem => {
    const c = concepts.find((x) => x.id === id)!;
    return {
      concept_id: id, saved: true, saved_at: "2026-11-21T08:00:00Z", first_saved_at: "2026-11-21T08:00:00Z",
      concept: { id, target: c.target, pedagogical_intent: "vocabulary", scope: c.scope, identity_features: {}, state: "active" },
      review_units: "support" in c ? (c as { support: number }).support : c.units.length,
      examples: (state.saved.get(id) ?? []).map((u) => {
        const unit = c.units.find((x) => x.id === u);
        if (!unit)
          return {
            unit_id: u, entry_id: 99, extraction_id: 99, extraction_version: 2, saved_at: "2026-11-21T08:00:00Z", status: "missing" as const,
            newer_extraction: false, term: null, kind: null, meaning: null, meanings: { en: null, zh: null }, sentence: null, extractor: null, source: null,
          };
        return {
          unit_id: u, entry_id: unit.entry, extraction_id: 50 + unit.entry, extraction_version: 1, saved_at: "2026-11-21T08:00:00Z",
          status: "current" as const, newer_extraction: false, term: unit.canonical, kind: "vocabulary", meaning: unit.meaning,
          meanings: { en: unit.zh === null ? null : unit.meaning, zh: unit.zh }, sentence: null, extractor: "stub:test:knowledge_extraction_v1",
          source: { entry_id: unit.entry, original_input: questions[unit.entry], original_context: "contexte synthétique", created_at: "2026-11-20T08:00:00Z" },
        };
      }),
    };
  };
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ method, path: url.pathname, search: url.search, body: String(init?.body ?? "") });
    const p = url.pathname;
    if (method === "GET" && p === "/api/vocabulary") {
      const q = (url.searchParams.get("q") ?? "").toLowerCase();
      const all = [...state.saved.keys()].sort((a, b) => a - b).map(item);
      const items = q ? all.filter((i) => (i.concept!.target + " " + i.examples.map((e) => e.meaning).join(" ")).toLowerCase().includes(q)) : all;
      return json(200, { schema_version: "vocabulary_v1", rule: "r", query: q, tokens: q ? [q] : [], saved: all.length, items });
    }
    let m = /^\/api\/vocabulary\/(\d+)$/.exec(p);
    if (m && method === "PUT") {
      const n = ++puts;
      const f = state.failPut?.(n);
      if (f === "network") throw new TypeError("network down");
      if (f === "500") return json(500, { error: "could not save the term" });
      const id = Number(m[1]);
      const unit = JSON.parse(String(init?.body)).unit_id as number;
      const had = state.saved.get(id);
      const savedNow = !had;
      const ex = had ?? [];
      const added = !ex.includes(unit);
      state.saved.set(id, added ? [...ex, unit] : ex);
      state.everSaved.add(id);
      return json(200, { item: item(id), changed: savedNow || added, saved_now: savedNow, example_added: added });
    }
    if (m && method === "DELETE") {
      const n = ++dels;
      const f = state.failDelete?.(n);
      if (f === "network") throw new TypeError("network down");
      if (f === "500") return json(500, { error: "could not remove the term" });
      const id = Number(m[1]);
      if (!state.everSaved.has(id)) return json(404, { error: "not found" });
      const changed = state.saved.delete(id);
      return json(200, { concept_id: id, saved: false, changed });
    }
    if (p === "/api/mistake-notebook/concepts")
      return json(200, {
        rule: "concept_kind_view_v1", kind: "vocabulary", query: "", tokens: [], classified: concepts.length, truncated: false,
        concepts: concepts.map((c) => ({ concept_id: c.id, target: c.target, pedagogical_intent: "vocabulary", scope: "", state: "active", class: "vocabulary", reason: null, kinds: ["vocabulary"], supporting_unit_count: c.units.length, match_tier: "browse" })),
      });
    m = /^\/api\/knowledge-library\/concepts\/(\d+)$/.exec(p);
    if (m) {
      const c = concepts.find((x) => x.id === Number(m![1]))!;
      const units = c.units.map((u) => ({ unit_id: u.id, kind: "vocabulary", canonical: u.canonical, statement: u.meaning, statements: { en: null, zh: null }, example: null, entry_id: u.entry, extraction_id: 50 + u.entry, extraction_version: 1, in_current_extraction: true, admission: "active" }));
      return json(200, {
        schema_version: "knowledge_library_concept_v1",
        concept: { id: c.id, identity_schema_version: "fr_l2_concept_identity_v1", target: c.target, pedagogical_intent: "vocabulary", scope: "", identity_features: {}, signature: "s", preferred_unit_id: null, state: "active", lifecycle_state: "normal", support_state: "supported", created_at: "t", updated_at: "t" },
        preferred_unit: null, supporting_units: units, non_supporting_members: [], current_relations: [], historical_units: [], history_event_count: 0,
      });
    }
    m = /^\/api\/knowledge-library\/units\/(\d+)\/source$/.exec(p);
    if (m) {
      const id = Number(m[1]);
      const c = concepts.find((x) => x.units.some((u) => u.id === id));
      if (!c) return json(404, { error: "unit not found" });
      const u = c.units.find((x) => x.id === id)!;
      return json(200, {
        schema_version: "knowledge_library_source_v1",
        unit: { unit_id: u.id, kind: "vocabulary", canonical: u.canonical, statement: u.meaning, statements: { en: null, zh: null }, example: null, entry_id: u.entry, extraction_id: 50 + u.entry, extraction_version: 1, in_current_extraction: true, admission: "active" },
        entry: { id: u.entry, original_input: questions[u.entry], original_context: "contexte synthétique", created_at: "t", updated_at: "t" },
        extraction: { id: 50 + u.entry, version: 1, extractor: "stub:test:knowledge_extraction_v1", source_analysis_id: 1, source_feedback_id: null, created_at: "t" },
        current_extraction: { extraction_id: 50 + u.entry, selection_mode: "automatic" },
        source_interpretation: { analysis: {}, feedback: null, effective: {} }, latest_analysis: null, annotation: { status: "resolved", current_concept_id: c.id },
      });
    }
    return json(404, { error: "not found" });
  }) as unknown as typeof fetch;
  return calls;
}

const renderBook = (onOpenConcept = vi.fn()) => {
  const r = render(
    <LocaleProvider>
      <VocabularyBook onOpenConcept={onOpenConcept} />
    </LocaleProvider>,
  );
  return { onOpenConcept, ...r };
};
const mine = () => screen.findByRole("region", { name: "My vocabulary" });
const approved = () => screen.findByRole("region", { name: "Vocabulary Concepts" });
const savedRows = () => [...document.querySelectorAll<HTMLElement>("li[data-concept]")];
const fresh = (): Fake => ({ saved: new Map(), everSaved: new Set() });

describe("Vocabulary (VOC)", () => {
  it("saves an approved term, shows it at once and after a remount, with its meaning and the learner's words (VOC-006 to VOC-008, VOC-021, VOC-082)", async () => {
    const state = fresh();
    const calls = serve(state);
    const a = renderBook();
    expect(await within(await mine()).findByText("You have not saved any term yet. Save one from the approved vocabulary below.")).toBeInTheDocument();
    const list = await approved();
    fireEvent.click(await within(list).findByRole("button", { name: "Save apporter to my vocabulary" }));
    // VOC-021: visible immediately, focus on the new row's heading
    await waitFor(() => expect(savedRows().map((r) => r.dataset.concept)).toEqual(["12"]));
    await waitFor(() => expect(screen.getByRole("heading", { name: "apporter", level: 3 })).toHaveFocus());
    expect(calls.filter((c) => c.method === "PUT")).toEqual([{ method: "PUT", path: "/api/vocabulary/12", search: "", body: '{"unit_id":101}' }]);
    const row = savedRows()[0];
    expect(row).toHaveTextContent("to bring (a thing)");
    expect(row).toHaveTextContent("带来（东西）");
    expect(row).toHaveTextContent("Meaning (generated by stub:test:knowledge_extraction_v1)");
    expect(row).toHaveTextContent("Your own words, exactly as written");
    expect(row).toHaveTextContent("Comment dit-on « bring » quand on va dîner chez des amis ?");
    expect(row).toHaveTextContent("From record #7, extraction version 1.");
    expect(within(await approved()).getByText("In my vocabulary")).toBeInTheDocument();
    // the shell's contract: each saved word's open control has a stable id
    const open = document.getElementById("vocabulary-word-12")!;
    expect(open).toHaveAccessibleName("Open apporter in the Knowledge Library");
    fireEvent.click(open);
    expect(a.onOpenConcept).toHaveBeenCalledWith(12);
    expect(document.getElementById("vocabulary-approved-12")).toHaveTextContent("apporter");
    expect(new Set([...document.querySelectorAll("[id]")].map((e) => e.id)).size).toBe(document.querySelectorAll("[id]").length);
    // VOC-007: a remount (a reload of the page) reads it again from the server
    a.unmount();
    renderBook();
    await waitFor(() => expect(savedRows().map((r) => r.dataset.concept)).toEqual(["12"]));
  });

  it("never shows a duplicate row after repeat saves; a timeout is retried safely (VOC-022, VOC-023, VOC-038, VOC-081, VOC-112)", async () => {
    const state = fresh();
    state.failPut = (n) => (n === 1 ? "network" : null);
    serve(state);
    renderBook();
    const list = await approved();
    fireEvent.click(await within(list).findByRole("button", { name: "Save apporter to my vocabulary" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The server did not answer, so the save may or may not have been recorded. Retrying is safe");
    await waitFor(() => expect(within(list).getByRole("button", { name: "Save apporter to my vocabulary" })).toHaveFocus());
    fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(savedRows()).toHaveLength(1));
    // the same save again through "Add an example": nothing new to add, still one row
    fireEvent.click(within(savedRows()[0]).getByRole("button", { name: "Add an example to apporter" }));
    expect(await screen.findByText("Every approved example of this term is already saved.")).toBeInTheDocument();
    expect(savedRows()).toHaveLength(1);
    expect(state.saved.get(12)).toEqual([101]);
  });

  it("adds a second example from another record to the same saved term (VOC-015, VOC-055)", async () => {
    const state = fresh();
    state.saved.set(13, [105]);
    state.everSaved = new Set([13]);
    const calls = serve(state);
    renderBook();
    await waitFor(() => expect(savedRows()).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Add an example to amener" }));
    const group = await screen.findByRole("group", { name: "Add an example to amener" });
    expect(await within(group).findByText("J'amène mon frère à la fête : correct ?")).toBeInTheDocument();
    fireEvent.click(within(group).getByRole("button", { name: "Add this example" }));
    await waitFor(() => expect(savedRows()[0].querySelectorAll("li[data-unit]")).toHaveLength(2));
    expect(calls.filter((c) => c.method === "PUT").map((c) => c.body)).toEqual(['{"unit_id":106}']);
    expect(savedRows()).toHaveLength(1);
    expect(savedRows()[0]).toHaveTextContent("From record #11");
    expect(savedRows()[0]).toHaveTextContent("From record #12");
  });

  it("sends one save for a rapid double click, and reads the list independently while a save is pending (VOC-112, VOC-113)", async () => {
    const state = fresh();
    state.saved.set(14, [103]);
    state.everSaved = new Set([14]);
    const calls = serve(state);
    const ok = globalThis.fetch;
    let release: () => void = () => undefined;
    globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      if ((init?.method ?? "GET").toUpperCase() === "PUT") await new Promise<void>((r) => (release = r));
      return ok(input, init);
    }) as unknown as typeof fetch;
    renderBook();
    await waitFor(() => expect(savedRows()).toHaveLength(1));
    const button = await within(await approved()).findByRole("button", { name: "Save apporter to my vocabulary" });
    fireEvent.click(button);
    fireEvent.click(button); // a second click while saving does nothing
    expect(button).toBeDisabled();
    // an independent read (a search) answers while the save is pending
    fireEvent.change(within(await mine()).getByRole("searchbox", { name: "Search my vocabulary" }), { target: { value: "grasse" } });
    fireEvent.click(within(await mine()).getByRole("button", { name: "Search" }));
    await waitFor(() => expect(calls.some((c) => c.search === "?q=grasse")).toBe(true));
    await waitFor(() => expect(savedRows().map((r) => r.dataset.concept)).toEqual(["14"]));
    await act(async () => release());
    await waitFor(() => expect(state.saved.has(12)).toBe(true));
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1);
    // the searched list keeps its query; clearing it shows both, once each
    fireEvent.change(within(await mine()).getByRole("searchbox", { name: "Search my vocabulary" }), { target: { value: "" } });
    fireEvent.click(within(await mine()).getByRole("button", { name: "Search" }));
    await waitFor(() => expect(savedRows().map((r) => r.dataset.concept)).toEqual(["12", "14"]));
  });

  it("starts a fresh session when a review is left unfinished and started again (VOC-127)", async () => {
    const state = fresh();
    state.saved.set(13, [105, 106]);
    state.everSaved = new Set([13]);
    serve(state);
    renderBook();
    await waitFor(() => expect(savedRows()).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Review amener" }));
    let practice = await screen.findByRole("region", { name: "Recall practice" });
    fireEvent.click((await within(practice).findAllByRole("checkbox"))[0]);
    fireEvent.click(within(practice).getByRole("button", { name: "Start practice with 1 question" }));
    await within(practice).findByRole("button", { name: "Reveal stored explanation" });
    fireEvent.click(within(practice).getByRole("button", { name: "← End the review and return to my vocabulary" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Review amener" })).toHaveFocus());
    fireEvent.click(screen.getByRole("button", { name: "Review amener" }));
    practice = await screen.findByRole("region", { name: "Recall practice" });
    const boxes = await within(practice).findAllByRole("checkbox");
    expect(boxes.every((b) => !(b as HTMLInputElement).checked)).toBe(true);
    expect(within(practice).queryByRole("button", { name: "Reveal stored explanation" })).toBeNull();
  });

  it("tells the workspace shell that it manages its own focus: every control is inside [data-focus-managed]", async () => {
    const state = fresh();
    state.saved.set(13, [105, 106]);
    state.everSaved = new Set([13]);
    serve(state);
    renderBook();
    await waitFor(() => expect(savedRows()).toHaveLength(1));
    const managed = (el: Element) => el.closest("[data-focus-managed]") !== null;
    expect(managed(screen.getByRole("button", { name: "Remove amener from my vocabulary" }))).toBe(true);
    expect(managed(within(await approved()).getByRole("button", { name: "Save apporter to my vocabulary" }))).toBe(true);
    expect(managed(within(await mine()).getByRole("searchbox", { name: "Search my vocabulary" }))).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Review amener" }));
    const practice = await screen.findByRole("region", { name: "Recall practice" });
    expect(managed(within(practice).getByRole("button", { name: "← End the review and return to my vocabulary" }))).toBe(true);
  });

  it("works with the Frontend contract's minimal mount: no onOpenConcept, names as plain text (VOC-135)", async () => {
    serve(fresh());
    render(
      <LocaleProvider>
        <VocabularyBook />
      </LocaleProvider>,
    );
    const list = await approved();
    expect(await within(list).findByText("apporter")).toBeInTheDocument();
    expect(within(list).queryByRole("button", { name: "apporter" })).toBeNull();
    expect(within(list).getByRole("button", { name: "Save apporter to my vocabulary" })).toBeInTheDocument();
  });

  it("explains a refused save instead of doing nothing (VOC-024, VOC-025, VOC-047)", async () => {
    const state = fresh();
    state.failPut = () => "500";
    serve(state);
    renderBook();
    const list = await approved();
    fireEvent.click(await within(list).findByRole("button", { name: "Save faire la grasse matinée to my vocabulary" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Not saved: (500) could not save the term");
    // a Concept with no approved example says so (no silent click)
    fireEvent.click(within(list).getByRole("button", { name: "Save anticonstitutionnellement-très-long-mot-composé-sans-espace to my vocabulary" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("has no approved example to save with right now.");
  });

  it("opens an example's source and comes back with the query kept (VOC-009, VOC-037, VOC-084)", async () => {
    const state = fresh();
    state.saved.set(12, [101]);
    state.saved.set(14, [103]);
    state.everSaved = new Set([12, 14]);
    const calls = serve(state);
    renderBook();
    const box = within(await mine()).getByRole("searchbox", { name: "Search my vocabulary" });
    fireEvent.change(box, { target: { value: "grasse" } });
    fireEvent.click(within(await mine()).getByRole("button", { name: "Search" }));
    await waitFor(() => expect(savedRows().map((r) => r.dataset.concept)).toEqual(["14"]));
    expect(calls.some((c) => c.path === "/api/vocabulary" && c.search === "?q=grasse")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Open the source of faire la grasse matinée" }));
    const src = await screen.findByRole("region", { name: "Source of a saved term" });
    expect(src).toHaveTextContent("Que veut dire « faire la grasse matinée » ?");
    expect(src).toHaveTextContent("version 1, by stub:test:knowledge_extraction_v1; current extraction: yes");
    await waitFor(() => expect(within(src).getByRole("heading", { name: "Where this example comes from" })).toHaveFocus());
    fireEvent.click(within(src).getByRole("button", { name: "← Back to my vocabulary" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Open the source of faire la grasse matinée" })).toHaveFocus());
    expect(within(await mine()).getByRole("searchbox", { name: "Search my vocabulary" })).toHaveValue("grasse");
    expect(savedRows().map((r) => r.dataset.concept)).toEqual(["14"]);
    // leaving the page (another notebook view) and coming back keeps the search too
    cleanup();
    renderBook();
    expect(within(await mine()).getByRole("searchbox", { name: "Search my vocabulary" })).toHaveValue("grasse");
    await waitFor(() => expect(savedRows().map((r) => r.dataset.concept)).toEqual(["14"]));
  });

  it("starts the existing Recall Practice from a saved term and returns to it (VOC-010, VOC-043, VOC-046, VOC-085)", async () => {
    const state = fresh();
    state.saved.set(12, [101]);
    state.everSaved = new Set([12]);
    serve(state);
    renderBook();
    await waitFor(() => expect(savedRows()).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Review apporter" }));
    const practice = await screen.findByRole("region", { name: "Recall practice" });
    expect(within(practice).getByRole("heading", { name: "Recall practice · Concept #12" })).toBeInTheDocument();
    expect(await within(practice).findByText(/Comment dit-on « bring »/)).toBeInTheDocument();
    fireEvent.click(within(practice).getByRole("button", { name: "← End the review and return to my vocabulary" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Review apporter" })).toHaveFocus());
  });

  it("shows the learner's question as the cue, reveals the answer, then opens its source and comes back to the card (VOC-044, VOC-045, VOC-121, VOC-122)", async () => {
    const state = fresh();
    state.saved.set(12, [101]);
    state.everSaved = new Set([12]);
    serve(state);
    renderBook();
    await waitFor(() => expect(savedRows()).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Review apporter" }));
    const practice = await screen.findByRole("region", { name: "Recall practice" });
    fireEvent.click((await within(practice).findAllByRole("checkbox"))[0]);
    fireEvent.click(within(practice).getByRole("button", { name: "Start practice with 1 question" }));
    // the cue is the learner's own question; the stored answer is not on the page yet
    expect(await within(practice).findByText("Comment dit-on « bring » quand on va dîner chez des amis ?")).toBeInTheDocument();
    expect(practice).not.toHaveTextContent("to bring (a thing)");
    expect(within(practice).queryByRole("button", { name: /Open the original source/ })).toBeNull();
    fireEvent.click(within(practice).getByRole("button", { name: "Reveal stored explanation" }));
    expect(await within(practice).findByText("to bring (a thing)")).toBeInTheDocument();
    fireEvent.click(within(practice).getByRole("button", { name: "Open the original source (record #7)" }));
    const src = await screen.findByRole("region", { name: "Source of a saved term" });
    expect(src).toHaveTextContent("Comment dit-on « bring »");
    fireEvent.click(within(src).getByRole("button", { name: "← Back to the review" }));
    const back = await screen.findByRole("region", { name: "Recall practice" });
    expect(within(back).getByText("to bring (a thing)")).toBeInTheDocument();
  });

  it("shows an unreadable example and a missing source kindly, without hiding the rest (VOC-053, VOC-054, VOC-059, VOC-118)", async () => {
    const state = fresh();
    state.saved.set(12, [101, 999]);
    state.everSaved = new Set([12]);
    serve(state);
    renderBook();
    await waitFor(() => expect(savedRows()).toHaveLength(1));
    const exs = savedRows()[0].querySelectorAll("li[data-unit]");
    expect(exs).toHaveLength(2);
    expect(exs[0]).toHaveTextContent("to bring (a thing)"); // the first example stays first and complete
    expect(exs[1]).toHaveAttribute("data-status", "missing");
    expect(exs[1]).toHaveTextContent("This example (record #99, extraction version 2) can no longer be read. The rest of the term is unchanged.");
    fireEvent.click(within(exs[1] as HTMLElement).getByRole("button", { name: "Open the source of apporter" }));
    const src = await screen.findByRole("region", { name: "Source of a saved term" });
    expect(await within(src).findByText("This source can no longer be read. Your saved term is unchanged.")).toBeInTheDocument();
    fireEvent.click(within(src).getByRole("button", { name: "← Back to my vocabulary" }));
    await waitFor(() => expect(savedRows()).toHaveLength(1));
  });

  it("says plainly when a saved term has no eligible review (VOC-047)", async () => {
    const state = fresh();
    state.saved.set(17, [107]);
    state.everSaved = new Set([17]);
    serve(state);
    renderBook();
    await waitFor(() => expect(savedRows()).toHaveLength(1));
    expect(within(savedRows()[0]).queryByRole("button", { name: "Review ancien" })).toBeNull();
    expect(savedRows()[0]).toHaveTextContent("No review is available now: no approved example supports this term at the moment.");
  });

  it("runs a two-question review with one recalled and one missed answer; only the missed one comes back (VOC-050, VOC-124, VOC-126)", async () => {
    const state = fresh();
    state.saved.set(13, [105, 106]);
    state.everSaved = new Set([13]);
    serve(state);
    renderBook();
    await waitFor(() => expect(savedRows()).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Review amener" }));
    const practice = await screen.findByRole("region", { name: "Recall practice" });
    const boxes = await within(practice).findAllByRole("checkbox");
    fireEvent.click(boxes[0]);
    fireEvent.click(boxes[1]);
    fireEvent.click(within(practice).getByRole("button", { name: "Start practice with 2 questions" }));
    const answer = async (result: "Recalled" | "Try again") => {
      fireEvent.click(await within(practice).findByRole("button", { name: "Reveal stored explanation" }));
      const check = await within(practice).findByRole("button", { name: result });
      fireEvent.click(check);
      fireEvent.click(check); // a repeated press records nothing twice
    };
    await answer("Recalled");
    const next = within(practice).queryByRole("button", { name: /Next/ });
    if (next) fireEvent.click(next);
    await answer("Try again");
    const fin = within(practice).queryByRole("button", { name: /Next|Finish|See/ });
    if (fin) fireEvent.click(fin);
    expect(await within(practice).findByText("Recalled: 1 · Try again: 1 · Skipped: 0")).toBeInTheDocument();
    expect(within(practice).getByRole("button", { name: "Second pass over the 1 question marked Try again" })).toBeInTheDocument();
  });

  it("removes a term, keeps focus on a sensible row, and is safe to repeat or fail (VOC-026, VOC-028, VOC-029, VOC-078, VOC-114, VOC-115)", async () => {
    const state = fresh();
    state.saved.set(12, [101]);
    state.saved.set(14, [103]);
    state.everSaved = new Set([12, 14]);
    state.failDelete = (n) => (n === 1 ? "500" : null);
    serve(state);
    renderBook();
    await waitFor(() => expect(savedRows()).toHaveLength(2));
    fireEvent.click(screen.getByRole("button", { name: "Remove apporter from my vocabulary" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Not removed: (500) could not remove the term");
    expect(savedRows()).toHaveLength(2);
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove apporter from my vocabulary" })).toHaveFocus());
    fireEvent.click(screen.getByRole("button", { name: "Remove apporter from my vocabulary" }));
    await waitFor(() => expect(savedRows().map((r) => r.dataset.concept)).toEqual(["14"]));
    await waitFor(() => expect(screen.getByRole("heading", { name: "faire la grasse matinée", level: 3 })).toHaveFocus());
    // the last row: the empty book, focus on the heading
    fireEvent.click(screen.getByRole("button", { name: "Remove faire la grasse matinée from my vocabulary" }));
    expect(await screen.findByText("You have not saved any term yet. Save one from the approved vocabulary below.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("heading", { name: "My vocabulary", level: 2 })).toHaveFocus());
    expect(state.everSaved.has(12)).toBe(true);
  });

  it("shows a failed read with Retry, which then lists the terms (VOC-083)", async () => {
    const state = fresh();
    state.saved.set(12, [101]);
    state.everSaved = new Set([12]);
    serve(state);
    const ok = globalThis.fetch;
    let first = true;
    globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      if (first && String(input).includes("/api/vocabulary")) {
        first = false;
        return new Response(JSON.stringify({ error: "could not read the vocabulary" }), { status: 500, headers: { "Content-Type": "application/json" } });
      }
      return ok(input, init);
    }) as unknown as typeof fetch;
    renderBook();
    const alert = await within(await mine()).findByRole("alert");
    expect(alert).toHaveTextContent("Could not read your vocabulary: (500) could not read the vocabulary");
    fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(savedRows()).toHaveLength(1));
  });

  it("keeps zero results apart from an empty book, and filters the approved list to saved terms (VOC-035, VOC-036, VOC-083)", async () => {
    const state = fresh();
    state.saved.set(12, [101]);
    state.everSaved = new Set([12]);
    serve(state);
    renderBook();
    await waitFor(() => expect(savedRows()).toHaveLength(1));
    fireEvent.change(within(await mine()).getByRole("searchbox", { name: "Search my vocabulary" }), { target: { value: "zzz" } });
    fireEvent.click(within(await mine()).getByRole("button", { name: "Search" }));
    expect(await screen.findByText("No saved term matches “zzz”.")).toBeInTheDocument();
    expect(screen.queryByText(/You have not saved any term yet/)).toBeNull();
    const list = await approved();
    await within(list).findByRole("button", { name: "faire la grasse matinée" });
    fireEvent.click(within(list).getByRole("checkbox", { name: "Show only terms in my vocabulary" }));
    await waitFor(() => expect(within(list).queryByRole("button", { name: "faire la grasse matinée" })).toBeNull());
    expect(within(list).getByRole("button", { name: "apporter" })).toBeInTheDocument();
  });

  it("keeps nothing of the saved list, a search or the learner's words in browser storage (VOC-061, VOC-065)", async () => {
    const state = fresh();
    state.saved.set(12, [101]);
    state.everSaved = new Set([12]);
    serve(state);
    renderBook();
    await waitFor(() => expect(savedRows()).toHaveLength(1));
    fireEvent.change(within(await mine()).getByRole("searchbox", { name: "Search my vocabulary" }), { target: { value: "appor" } });
    fireEvent.click(within(await mine()).getByRole("button", { name: "Search" }));
    fireEvent.click(await within(await approved()).findByRole("button", { name: "Save faire la grasse matinée to my vocabulary" }));
    await waitFor(() => expect(state.saved.has(14)).toBe(true));
    const stored = [window.localStorage, window.sessionStorage].flatMap((st) => Object.keys(st).map((k) => `${k}=${st.getItem(k)}`)).join("\n");
    for (const s of ["apporter", "appor", "grasse", "bring", "vocab"]) expect([s, stored.includes(s)]).toEqual([s, false]);
  });

  it("renders learner and model text as text, never as HTML, and wraps long terms (VOC-039, VOC-064)", async () => {
    const state = fresh();
    state.saved.set(15, [104]);
    state.everSaved = new Set([15]);
    serve(state);
    renderBook();
    await waitFor(() => expect(savedRows()).toHaveLength(1));
    const row = savedRows()[0];
    expect(row.querySelector("img")).toBeNull();
    expect(row.querySelector("b")).toBeNull();
    expect(row).toHaveTextContent("<img src=x onerror=alert(1)>");
    expect(row).toHaveTextContent("<b>pas du HTML</b>");
    expect(row.querySelector("h3")!.className).toContain("vocabulary-term");
  });

  it("renders in Chinese with every placeholder filled; French stays as written (VOC-079)", async () => {
    window.localStorage.setItem("flh.ui-locale.v1", "zh-CN");
    const state = fresh();
    state.saved.set(14, [103]);
    state.everSaved = new Set([14]);
    serve(state);
    renderBook();
    const region = await screen.findByRole("region", { name: "我的词汇" });
    await waitFor(() => expect(savedRows()).toHaveLength(1));
    expect(region).toHaveTextContent("faire la grasse matinée");
    expect(region).toHaveTextContent("（未记录它的语言）");
    expect(region.textContent).not.toMatch(/\{[a-z]+\}/);
    await act(async () => undefined);
  });
});
