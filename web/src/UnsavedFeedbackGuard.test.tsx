// Unsaved feedback on an open record is never discarded silently. Before the
// fix, opening another record from another view (Knowledge Library source →
// "Open record #3 in Learning Records") replaced record #1's detail and its
// draft was gone when the reader came back. Synthetic data, local router.
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import App from "./App";

afterEach(cleanup);
beforeEach(() => window.localStorage.clear());

// ---------------------------------------------------------------- app journey

type Reply = { status?: number; body: unknown };
type Handler = unknown | (() => Reply);
type Call = { method: string; url: string };

function router(handlers: Record<string, Handler>) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = String(input);
    calls.push({ method, url });
    const path = new URL(url, "http://localhost").pathname;
    const h = handlers[`${method} ${url}`] ?? handlers[`${method} ${path}`];
    const reply: Reply = h === undefined ? { status: 404, body: { error: "not found" } } : typeof h === "function" ? (h as () => Reply)() : { body: h };
    return new Response(JSON.stringify(reply.body), { status: reply.status ?? 200, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
  return calls;
}
const writes = (calls: Call[]) => calls.filter((c) => c.method !== "GET");

const admission = { ruleset: "knowledge_admission_v1", machine_state: "active", machine_reason: "default_active", effective_state: "active", latest_override: null };
const extractedUnit = (id: number, ordinal: number, canonical: string) => ({
  id, ordinal, kind: "grammar", canonical, statement: `Énoncé ${canonical}`, example: null, confidence: 0.9, created_at: "t", admission,
});
const reviewable = (id: number, canonical: string, entryId?: number) => ({
  unit_id: id, kind: "grammar", canonical, statement: `Énoncé ${canonical}`, example: null, confidence: 0.9,
  candidate_identity: { target: canonical, pedagogical_intent: "grammar", scope: "", identity_features: {} }, signature: "s",
  ...(entryId !== undefined ? { entry_id: entryId } : {}),
});
const annotation = (unitId: number, status: string, conceptId: number | null) => ({
  unit: { id: unitId, extraction_id: 20, ordinal: 1, kind: "grammar", canonical: `u${unitId}`, statement: "s", example: null, confidence: 0.9, created_at: "t" },
  snapshot: {
    unit_id: unitId, status, latest_unit_judgment: null, distinctions: [], relations: [],
    current_same: conceptId === null ? null : {
      membership: { concept_id: conceptId, link_id: 55, updated_at: "t" },
      decision: { id: 55, unit_id: unitId, concept_id: conceptId, relation: "same", status: "accepted", decision_source: "human", resolver_version: "v", score: null, evidence: "{}", supersedes_link_id: null, created_at: "t" },
    },
  },
});
const conceptRow = (id: number, target: string) => ({
  id, identity_schema_version: "fr_l2_concept_identity_v1", target, pedagogical_intent: "grammar", scope: "", identity_features: {},
  signature: "s", preferred_unit_id: null, state: "active", lifecycle_state: "normal", support_state: "supported", created_at: "t", updated_at: "t",
});
const libraryUnit = (id: number, entryId: number) => ({
  unit_id: id, kind: "grammar", canonical: `pronom en ${id}`, statement: `Énoncé ${id}`, example: null, entry_id: entryId,
  extraction_id: 20, extraction_version: 1, in_current_extraction: true, admission: "active",
});
const record = (entryId: number) => ({
  entry_id: entryId, original_input: `Question sur en ${entryId}`, original_context: "", entry_created_at: "t", state: "accepted",
  analysis_id: 11, analysis_version: 1, analyzer: "openai:m:fr_l2_taxonomy_v1", confidence: 0.8, uncertainty: "",
  analysis_created_at: "t", original: { category: "grammar", explanation: "e" }, effective: { category: "grammar", explanation: "e" }, feedback_id: 3,
});

// Record 1: accepted analysis v1; current extraction v1 with unit 201 (awaiting
// review) and unit 202 (CURRENT SAME → Concept 7). Concept 7 is supported by
// unit 202 (record 1) and unit 301 (record 3).
function journeyBackend(extra: Record<string, Handler> = {}) {
  return router({
    "GET /api/learning-records?limit=20": { records: [record(3), record(1)], next_before_entry_id: null },
    "GET /api/entries/1": { id: 1, original_input: "Question sur en 1", original_context: "", created_at: "t", updated_at: "t" },
    "GET /api/entries/3": { id: 3, original_input: "Question sur en 3", original_context: "", created_at: "t", updated_at: "t" },
    "GET /api/entries/1/analyses": { analyses: [{ id: 11, entry_id: 1, version: 1, category: "grammar", explanation: "e", confidence: 0.8, uncertainty: "", analyzer: "a", created_at: "t" }] },
    "GET /api/entries/3/analyses": { analyses: [] },
    "GET /api/analyses/11/effective": { analysis_id: 11, entry_id: 1, version: 1, original: { category: "grammar", explanation: "e" }, effective: { category: "grammar", explanation: "e" }, resolution: "accepted", feedback_id: 3 },
    "GET /api/analyses/11/feedback": { feedback: [{ id: 3, analysis_id: 11, status: "accepted", user_note: "", created_at: "t" }] },
    "GET /api/entries/1/extractions": { extractions: [{ id: 20, entry_id: 1, version: 1, source_analysis_id: 11, source_feedback_id: 3, extractor: "x", created_at: "t", units: [extractedUnit(201, 1, "y pronom"), extractedUnit(202, 2, "pronom en")] }] },
    "GET /api/entries/1/current-extraction": { entry_id: 1, current_extraction_id: 20, selection_mode: "automatic" },
    "GET /api/entries/3/extractions": { extractions: [] },
    "GET /api/entries/3/current-extraction": { entry_id: 3, current_extraction_id: null, selection_mode: "automatic" },
    "GET /api/reviewable-units?entry_id=1": { reviewable_units: [reviewable(201, "y pronom")] },
    "GET /api/reviewable-units?limit=50": { reviewable_units: [], next_cursor: null, limit: 50 },
    "GET /api/knowledge-units/202/effective-annotation": annotation(202, "resolved", 7),
    "GET /api/knowledge-library/concepts": { schema_version: "knowledge_library_search_v1", query: "", tokens: [], state: "all", limit: 20, total_matches: 0, truncated: false, results: [] },
    "GET /api/knowledge-library/concepts/7": {
      schema_version: "knowledge_library_concept_v1", concept: conceptRow(7, "en"), preferred_unit: null,
      supporting_units: [libraryUnit(202, 1), libraryUnit(301, 3)], non_supporting_members: [], current_relations: [], historical_units: [], history_event_count: 2,
    },
    "GET /api/knowledge-library/units/301/source": {
      schema_version: "knowledge_library_source_v1", unit: libraryUnit(301, 3),
      entry: { id: 3, original_input: "Question sur en 3", original_context: "", created_at: "t", updated_at: "t" },
      extraction: { id: 40, version: 1, extractor: "x", source_analysis_id: 31, source_feedback_id: null, created_at: "t" },
      current_extraction: { extraction_id: 40, selection_mode: "automatic" },
      source_interpretation: {
        analysis: { id: 31, entry_id: 3, version: 1, category: "grammar", explanation: "e", confidence: 0.8, uncertainty: "", analyzer: "a", created_at: "t" },
        feedback: null,
        effective: { analysis_id: 31, entry_id: 3, version: 1, original: { category: "grammar", explanation: "e" }, effective: { category: "grammar", explanation: "e" }, resolution: "unreviewed", feedback_id: null },
      },
      latest_analysis: { id: 31, version: 1, created_at: "t" },
      annotation: { status: "resolved", current_concept_id: 7 },
    },
    ...extra,
  });
}

function renderApp() {
  render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

async function openRecordOne() {
  renderApp();
  fireEvent.click(screen.getByRole("button", { name: "Learning Records" }));
  await screen.findByText("Showing 2 records.");
  fireEvent.click(screen.getByRole("button", { name: "Open record #1" }));
  await screen.findByRole("heading", { name: "Record #1" });
}


const NOTE = "brouillon: vérifier « en » avec ma prof";

async function draftThenOpenRecordThreeFromLibrary() {
  await openRecordOne();
  fireEvent.change(await screen.findByLabelText("Note (optional)"), { target: { value: NOTE } });
  fireEvent.click(await screen.findByRole("button", { name: "Open Concept #7 in Knowledge Library" }));
  fireEvent.click(await screen.findByRole("button", { name: "View source record #3" }));
  fireEvent.click(await screen.findByRole("button", { name: "Open record #3 in Learning Records" }));
}

describe("unsaved feedback across record changes", () => {
  it("asks before another view replaces a record that has an unsaved note, and keeps it on Stay", async () => {
    const calls = journeyBackend();
    await draftThenOpenRecordThreeFromLibrary();
    const ask = await screen.findByRole("alert");
    expect(ask).toHaveTextContent("Record #1 has unsaved feedback. Opening record #3 now would discard it.");
    expect(screen.getByRole("heading", { name: "Record #1" })).toBeVisible();
    fireEvent.click(within(ask).getByRole("button", { name: "Keep editing record #1" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Note (optional)")).toHaveValue(NOTE);
    // The cross-view trail is still there.
    expect(screen.getByRole("button", { name: "← Back to Knowledge Library" })).toBeInTheDocument();
    expect(writes(calls)).toEqual([]);
  });

  it("opens the requested record only after an explicit discard", async () => {
    const calls = journeyBackend();
    await draftThenOpenRecordThreeFromLibrary();
    fireEvent.click(within(await screen.findByRole("alert")).getByRole("button", { name: "Discard it and open record #3" }));
    expect(await screen.findByRole("heading", { name: "Record #3" })).toBeInTheDocument();
    // Record #3 has no draft, so going back to the list does not ask.
    fireEvent.click(screen.getByRole("button", { name: "← Back to records" }));
    expect(await screen.findByRole("button", { name: "Open record #1" })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(writes(calls)).toEqual([]);
  });

  it("asks before Back to records discards an unsaved note, and closes after an explicit discard", async () => {
    const calls = journeyBackend();
    await openRecordOne();
    fireEvent.change(await screen.findByLabelText("Note (optional)"), { target: { value: NOTE } });
    fireEvent.click(screen.getByRole("button", { name: "← Back to records" }));
    const ask = await screen.findByRole("alert");
    expect(ask).toHaveTextContent("Record #1 has unsaved feedback. Going back to the list now would discard it.");
    fireEvent.click(within(ask).getByRole("button", { name: "Discard it and go back" }));
    expect(await screen.findByRole("button", { name: "Open record #1" })).toBeVisible();
    expect(writes(calls)).toEqual([]);
  });

  it("does not ask when the note was cleared again", async () => {
    journeyBackend();
    await openRecordOne();
    const note = await screen.findByLabelText("Note (optional)");
    fireEvent.change(note, { target: { value: NOTE } });
    fireEvent.change(note, { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "← Back to records" }));
    expect(await screen.findByRole("button", { name: "Open record #1" })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
