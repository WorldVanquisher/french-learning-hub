import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import App from "./App";
import { deriveRecordStage, type AnalysisFacts, type ExtractionFacts } from "./components/recordStage";

// Daily workflow v1.0 RC: the record's stage summary and the cross-view links of
// the daily journey (record → filed unit → Concept → source → record; AI
// suggestion → record / Concept → back). Synthetic content authored for these
// tests; the "server" is a local router. Every link is a read: no test here may
// observe a write request.

afterEach(cleanup);
beforeEach(() => window.localStorage.clear());

// ---------------------------------------------------------------- stage logic

const analysisReady = (resolution: "unreviewed" | "accepted" | "corrected" | "rejected" | null): AnalysisFacts =>
  ({ status: "ready", latest: resolution === null ? null : { version: 2, resolution } });
const extraction = (
  current: { units: number[] } | null,
  awaiting: number[] | null,
  decided: Record<number, "resolved" | "invalid" | "unresolved" | null> = {},
  anyStored = current !== null,
): ExtractionFacts => ({
  status: "ready",
  anyStored,
  current: current ? { id: 30, version: 3, unitIds: current.units } : null,
  awaiting,
  decided,
});

describe("deriveRecordStage", () => {
  it("asks for an analysis first", () => {
    const s = deriveRecordStage(analysisReady(null), extraction(null, null));
    expect(s.next).toEqual({ kind: "analyze" });
    expect(s.analysis.state).toBe("pending");
  });

  it("blocks on a rejected latest analysis whatever was extracted before", () => {
    const s = deriveRecordStage(analysisReady("rejected"), extraction({ units: [1] }, [1]));
    expect(s.next).toEqual({ kind: "reanalyze", version: 2 });
    expect(s.analysis.state).toBe("blocked");
  });

  it("recommends reviewing an unreviewed analysis before extracting, and extracting after review", () => {
    expect(deriveRecordStage(analysisReady("unreviewed"), extraction(null, null)).next).toEqual({ kind: "reviewAnalysis", version: 2 });
    expect(deriveRecordStage(analysisReady("accepted"), extraction(null, null)).next).toEqual({ kind: "extract" });
    expect(deriveRecordStage(analysisReady("corrected"), extraction(null, null, {}, true)).next).toEqual({ kind: "selectExtraction" });
  });

  it("distinguishes zero units, units awaiting a decision and completed decisions", () => {
    expect(deriveRecordStage(analysisReady("accepted"), extraction({ units: [] }, [])).next).toEqual({ kind: "zeroUnits", version: 3 });

    const waiting = deriveRecordStage(analysisReady("accepted"), extraction({ units: [7, 8, 9] }, [9, 8], { 7: "resolved" }));
    expect(waiting.next).toEqual({ kind: "reviewUnit", unitId: 8, extractionId: 30, extractionVersion: 3, awaiting: 2, total: 3 });
    expect(waiting.decisions).toMatchObject({ state: "pending", awaiting: 2, total: 3, filed: 1, invalid: 0 });

    const done = deriveRecordStage(analysisReady("accepted"), extraction({ units: [7, 8] }, [], { 7: "resolved", 8: "invalid" }));
    expect(done.next).toEqual({ kind: "complete", total: 2, filed: 1, invalid: 1 });
    expect(done.decisions.state).toBe("done");
  });

  it("does not guess counts or completion from unread data", () => {
    const unread = deriveRecordStage(analysisReady("accepted"), extraction({ units: [7] }, [], { 7: null }));
    expect(unread.next).toEqual({ kind: "complete", total: 1, filed: null, invalid: null });
    const unknownReview = deriveRecordStage(analysisReady("accepted"), extraction({ units: [7] }, null));
    expect(unknownReview.next).toEqual({ kind: "unknown" });
    expect(deriveRecordStage({ status: "unknown" }, extraction(null, null)).next).toEqual({ kind: "unknown" });
    expect(deriveRecordStage(analysisReady("accepted"), { status: "loading" }).next).toEqual({ kind: "loading" });
  });

  it("keeps a pending analysis review visible next to later steps without blocking them", () => {
    const s = deriveRecordStage(analysisReady("unreviewed"), extraction({ units: [7] }, [7]));
    expect(s.next.kind).toBe("reviewUnit");
    expect(s.analysisReviewPending).toBe(true);
  });
});

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

describe("Daily journey across views", () => {
  it("shows the record's stage and next action from server reads only", async () => {
    const calls = journeyBackend();
    await openRecordOne();
    const stage = await screen.findByRole("region", { name: "Stage of record #1" });
    await within(stage).findByText("1 of 2 units await a decision in Concept Review.");
    expect(within(stage).getByText("Latest analysis v1: accepted.")).toBeInTheDocument();
    expect(within(stage).getByText("Current extraction v1: 2 units.")).toBeInTheDocument();
    expect(within(stage).getByText("1 of 2 units await a decision. Start with unit #201.")).toBeInTheDocument();
    expect(within(stage).getByRole("button", { name: "Open unit #201 in Concept Review" })).toBeInTheDocument();
    // The analysis and extraction panels say what each step produces.
    expect(screen.getByText(/An analysis describes and classifies your question/)).toBeInTheDocument();
    expect(screen.getByText(/Extraction produces the knowledge statements \(units\)/)).toBeInTheDocument();
    // The decided unit says where it is filed now, and that this can become history.
    expect(await screen.findByText(/^Filed under Concept #7 \(CURRENT SAME, event #55, human\)\. A later correction can move it; this decision then remains as history\.$/)).toBeInTheDocument();
    expect(writes(calls)).toEqual([]);
  });

  it("follows a filed unit to its Concept and source, then returns to the record with its state", async () => {
    const calls = journeyBackend();
    await openRecordOne();
    fireEvent.click(await screen.findByRole("button", { name: "Open Concept #7 in Knowledge Library" }));

    // The Concept opens directly, with a way back to the record.
    expect(await screen.findByRole("heading", { name: /^en\b/ })).toBeInTheDocument();
    const trail = screen.getByRole("navigation", { name: "Return to the previous view" });
    expect(trail).toHaveTextContent("Opened from record #1.");
    // Both members stay traceable to their own records.
    expect(screen.getByRole("button", { name: "View source record #1" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View source record #3" }));
    expect(await screen.findByText("Question sur en 3")).toBeInTheDocument();

    // The source opens its record in Learning Records; the library is kept.
    fireEvent.click(screen.getByRole("button", { name: "Open record #3 in Learning Records" }));
    expect(await screen.findByRole("heading", { name: "Record #3" })).toBeInTheDocument();
    const stage = await screen.findByRole("region", { name: "Stage of record #3" });
    await within(stage).findByText(/Request analysis below/);
    fireEvent.click(screen.getByRole("button", { name: "← Back to Knowledge Library" }));
    expect(await screen.findByRole("heading", { name: "Where unit #301 came from: learning record #3" })).toBeInTheDocument();

    // Back to the original record through the library's own navigation and the tab.
    fireEvent.click(screen.getByRole("button", { name: "Learning Records" }));
    expect(screen.getByRole("heading", { name: "Record #3" })).toBeInTheDocument();
    expect(writes(calls)).toEqual([]);
  });

  it("returns from the Concept to the same record and re-reads its review status", async () => {
    const calls = journeyBackend();
    await openRecordOne();
    fireEvent.click(await screen.findByRole("button", { name: "Open Concept #7 in Knowledge Library" }));
    await screen.findByRole("heading", { name: /^en\b/ });
    const reviewReads = calls.filter((c) => c.url === "/api/reviewable-units?entry_id=1").length;
    fireEvent.click(screen.getByRole("button", { name: "← Back to record #1" }));
    expect(await screen.findByRole("heading", { name: "Record #1" })).toBeVisible();
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/reviewable-units?entry_id=1").length).toBeGreaterThan(reviewReads));
    await waitFor(() => expect(document.activeElement?.id).toBe("extracted-unit-202"));
    expect(screen.queryByRole("navigation", { name: "Return to the previous view" })).not.toBeInTheDocument();
    expect(writes(calls)).toEqual([]);
  });
});

describe("AI suggestions in the daily journey", () => {
  const limits = { max_units: 10, candidates_per_unit: 5, member_examples: 2, max_unit_text_chars: 1200, max_concept_text_chars: 800, max_reason_chars: 500 };
  const suggestionItem = (id: number, unitId: number, entryId: number, state: string, extra: Record<string, unknown> = {}) => ({
    id, run_id: 5, ordinal: id, unit_id: unitId, entry_id: entryId, source_extraction_id: 20, outcome: "suggested",
    suggested_concept_id: 7, reason: "Same use of « en ».",
    candidates: [{ concept_id: 7, rank: 1, source: "bm25", signature: "s", target: "en" }],
    state, stale_reasons: [], current_concept_id: null, confirmation: null, unit: reviewable(unitId, `u${unitId}`, entryId), created_at: "t", ...extra,
  });
  const run = () => ({
    id: 5, operation_id: "op", status: "completed", failure_code: null, generator: "openai:m:concept_suggestion_v1",
    candidate_policy: "concept_suggestion_candidates_v1", candidate_limit: 5, provider_called: true, unit_ids: [301, 401],
    item_count: 2, suggested_count: 2, created_at: "t",
    items: [
      suggestionItem(1, 301, 3, "confirmed", { current_concept_id: 7, confirmation: { id: 9, link_id: 66, created_at: "t", still_current: true } }),
      suggestionItem(2, 401, 4, "open"),
    ],
  });

  it("states that suggestions are advisory and links a confirmed item to its Concept and record, then returns", async () => {
    let runReads = 0;
    const calls = journeyBackend({
      "GET /api/concept-suggestion-runs": { enabled: true, generator: "openai:m:concept_suggestion_v1", candidate_policy: "concept_suggestion_candidates_v1", limits, runs: [{ ...run(), items: undefined }] },
      "GET /api/concept-suggestion-runs/5": () => {
        runReads += 1;
        return { body: run() };
      },
    });
    renderApp();
    fireEvent.click(screen.getByRole("button", { name: "AI suggestions" }));
    fireEvent.click(await screen.findByRole("button", { name: /^Run #5/ }));
    await screen.findByRole("heading", { name: "Suggestion run #5" });
    expect(screen.getByText(/These suggestions are advisory\. Generating them recorded nothing/)).toBeInTheDocument();

    const confirmed = screen.getByRole("article", { name: "Suggestion for unit 301" });
    expect(within(confirmed).getByText(/This is the unit's CURRENT SAME now\. A later correction can move the unit/)).toBeInTheDocument();

    // Leaving the open item unused sends nothing and says it is no judgment.
    const open = screen.getByRole("article", { name: "Suggestion for unit 401" });
    fireEvent.click(within(open).getByRole("button", { name: "Leave unused" }));
    expect(within(open).getByText(/leaving it is not DISTINCT or any other judgment/)).toBeInTheDocument();

    fireEvent.click(within(confirmed).getByRole("button", { name: "Open Concept #7 in Knowledge Library" }));
    expect(await screen.findByRole("heading", { name: /^en\b/ })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Return to the previous view" })).toHaveTextContent("Opened from AI suggestions.");
    fireEvent.click(screen.getByRole("button", { name: "← Back to AI suggestions" }));

    // The run is still open and is re-read on return; "left unused" stays local.
    expect(await screen.findByRole("heading", { name: "Suggestion run #5" })).toBeVisible();
    await waitFor(() => expect(runReads).toBe(2));
    expect(within(screen.getByRole("article", { name: "Suggestion for unit 401" })).getByText("Left unused. Nothing was recorded.")).toBeInTheDocument();

    fireEvent.click(within(screen.getByRole("article", { name: "Suggestion for unit 301" })).getByRole("button", { name: "Open record #3" }));
    expect(await screen.findByRole("heading", { name: "Record #3" })).toBeVisible();
    expect(screen.getByRole("navigation", { name: "Return to the previous view" })).toHaveTextContent("Opened from AI suggestions.");
    expect(writes(calls)).toEqual([]);
  });
});
