import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import App from "./App";

// Record → extraction unit → Concept Review / Inspector → back to the record, through
// the real App in StrictMode (as main.tsx renders it), against a stateful fixture
// backend. Nothing here is a provider call; units come from stored fixtures.
afterEach(cleanup);

type Reply = { status?: number; body: unknown } | "network-error";
type Handler = Reply | ((body: unknown) => Reply | Promise<Reply>);

function deferred() {
  let resolve!: (reply: Reply) => void;
  const promise = new Promise<Reply>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

const extractedUnit = (id: number, canonical: string) => ({
  id,
  ordinal: 1,
  kind: "grammar",
  canonical,
  statement: `Énoncé ${canonical}`,
  example: null,
  confidence: 0.9,
  created_at: "t",
  admission: { ruleset: "knowledge_admission_v1", machine_state: "active", machine_reason: "default_active", effective_state: "active", latest_override: null },
});

const reviewableUnit = (id: number, canonical: string) => ({
  unit_id: id,
  kind: "grammar",
  canonical,
  statement: `Énoncé ${canonical}`,
  example: null,
  confidence: 0.9,
  candidate_identity: { target: canonical, pedagogical_intent: "grammar", scope: "", identity_features: {} },
  signature: "{...}",
});

const record = (entryId: number, state: string) => ({
  entry_id: entryId,
  original_input: `Question ${entryId}`,
  original_context: "",
  entry_created_at: "t",
  state,
  analysis_id: 11,
  analysis_version: 1,
  analyzer: "rule-based:v2:fr_l2_taxonomy_v1",
  confidence: 0.5,
  uncertainty: "",
  analysis_created_at: "t",
  original: { category: "grammar", explanation: "e" },
  effective: { category: "grammar", explanation: "e" },
  feedback_id: null,
});

const annotation = (unitId: number, extractionId: number, status: string) => ({
  unit: { id: unitId, extraction_id: extractionId, ordinal: 1, kind: "grammar", canonical: `unit ${unitId}`, statement: `Énoncé unit ${unitId}`, example: null, confidence: 0.9, created_at: "t" },
  snapshot: { unit_id: unitId, status, latest_unit_judgment: null, current_same: null, distinctions: [], relations: [] },
});

// Entry 1: v1 (extraction 10, historical) has unit 101; v2 (extraction 20,
// current, automatic) has unit 201 (awaiting review) and unit 202 (resolved).
function fixtureBackend() {
  const reviewable = new Set([201]);
  const calls: Array<{ method: string; url: string }> = [];
  const handlers: Record<string, Handler> = {
    "GET /api/learning-records?limit=20": { body: { records: [record(2, "unanalyzed"), record(1, "unreviewed")], next_before_entry_id: null } },
    "GET /api/learning-records?state=unreviewed&limit=20": { body: { records: [record(1, "unreviewed")], next_before_entry_id: null } },
    "GET /api/entries/1": { body: { id: 1, original_input: "Question 1", original_context: "contexte", created_at: "t", updated_at: "t" } },
    "GET /api/entries/1/analyses": {
      body: { analyses: [{ id: 11, entry_id: 1, version: 1, category: "grammar", explanation: "e", confidence: 0.5, uncertainty: "", analyzer: "rule-based:v2:fr_l2_taxonomy_v1", created_at: "t" }] },
    },
    "GET /api/analyses/11/effective": {
      body: { analysis_id: 11, entry_id: 1, version: 1, original: { category: "grammar", explanation: "e" }, effective: { category: "grammar", explanation: "e" }, resolution: "unreviewed", feedback_id: null },
    },
    "GET /api/analyses/11/feedback": { body: { feedback: [] } },
    "GET /api/entries/1/extractions": {
      body: {
        extractions: [
          { id: 20, entry_id: 1, version: 2, source_analysis_id: 11, source_feedback_id: null, extractor: "x", created_at: "t", units: [extractedUnit(201, "unit 201"), extractedUnit(202, "unit 202")] },
          { id: 10, entry_id: 1, version: 1, source_analysis_id: 11, source_feedback_id: null, extractor: "x", created_at: "t", units: [extractedUnit(101, "unit 101")] },
        ],
      },
    },
    "GET /api/entries/1/current-extraction": { body: { entry_id: 1, current_extraction_id: 20, selection_mode: "automatic" } },
    "GET /api/reviewable-units?entry_id=1": () => ({ body: { reviewable_units: [...reviewable].map((id) => reviewableUnit(id, `unit ${id}`)) } }),
    "GET /api/reviewable-units": { body: { reviewable_units: [] } },
    "GET /api/concepts": { body: { concepts: [] } },
    "GET /api/knowledge-units/201/concept-membership": { body: { unit_id: 201, current_membership: null } },
    "GET /api/knowledge-units/201/concept-resolution": { body: { unit_id: 201, decision: "no_match", matches: [] } },
    "POST /api/knowledge-units/201/invalid": () => {
      reviewable.delete(201);
      return { body: { unit_id: 201, invalid: true, current_membership: null, judgment: { id: 1, unit_id: 201, judgment: "invalid", decision_source: "human", note: "", evidence: "{}", created_at: "t" } } };
    },
    "GET /api/knowledge-units/201/effective-annotation": () => ({ body: annotation(201, 20, reviewable.has(201) ? "unresolved" : "invalid") }),
    "GET /api/knowledge-units/202/effective-annotation": { body: annotation(202, 20, "resolved") },
    "GET /api/knowledge-units/101/effective-annotation": { body: annotation(101, 10, "unresolved") },
  };
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = String(input);
    calls.push({ method, url });
    const handler = handlers[`${method} ${url}`];
    const reply = handler === undefined ? { status: 404, body: { error: "not found" } } : typeof handler === "function" ? await handler(undefined) : handler;
    if (reply === "network-error") throw new TypeError("Failed to fetch");
    return new Response(JSON.stringify(reply.body), { status: reply.status ?? 200, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
  const count = (method: string, url: string) => calls.filter((c) => c.method === method && c.url === url).length;
  return { handlers, reviewable, calls, count };
}

const records = () => screen.getByRole("list", { name: "Learning records", hidden: true });
// Concept Review's own unit card. The hidden Records view stays mounted and also
// contains the unit's text, so text checks are scoped to the visible card.
const reviewCard = () => screen.queryByRole("heading", { name: "Knowledge Unit (evidence)" })?.closest(".panel") ?? null;
const versions = () => within(screen.getByRole("group", { name: "Stored extraction versions" }));

// Opens record 1 under the "unreviewed" filter, as a reader would.
async function openRecordOne() {
  render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Learning Records" }));
  await screen.findByText("Showing 2 records.");
  fireEvent.change(screen.getByLabelText("Record state"), { target: { value: "unreviewed" } });
  await screen.findByText("Showing 1 record.");
  fireEvent.click(screen.getByRole("button", { name: "Open record #1" }));
  await screen.findByLabelText("Viewed extraction");
}

describe("Record → unit → other view → back", () => {
  it("inspects a historical unit read-only and returns to the same record, version, filter, and unit", async () => {
    const backend = fixtureBackend();
    await openRecordOne();
    fireEvent.click(versions().getByRole("button", { name: "v1" }));
    const listReads = backend.calls.filter((c) => c.url.startsWith("/api/learning-records")).length;

    fireEvent.click(screen.getByRole("button", { name: "Inspect stored labels of unit #101" }));
    expect(await screen.findByRole("heading", { name: "Unit #101 from record #1" })).toHaveFocus();
    expect(await screen.findByLabelText("Unit currency")).toHaveTextContent(
      "Historical unit. It belongs to extraction #10, which is not the record's current extraction (#20, automatic selection).",
    );
    // Its stored status is "unresolved", but it is never offered for review.
    expect(screen.queryByRole("button", { name: /in Concept Review/ })).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Unit #101" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "← Back to record #1" }));
    await waitFor(() => expect(document.getElementById("extracted-unit-101")).toHaveFocus());
    expect(versions().getByRole("button", { name: "v1" })).toHaveAttribute("aria-pressed", "true");
    // The hidden list kept its filter and rows; it was not re-fetched.
    expect(screen.getByLabelText("Record state", { selector: "select" })).toHaveValue("unreviewed");
    expect(within(records()).getAllByRole("heading", { hidden: true }).map((h) => h.textContent)).toEqual(["Record #1"]);
    expect(backend.calls.filter((c) => c.url.startsWith("/api/learning-records")).length).toBe(listReads);
    expect(backend.calls.some((c) => c.method !== "GET")).toBe(false);
  });

  it("reviews a current unit in a record-scoped queue and returns with refreshed review status", async () => {
    const backend = fixtureBackend();
    await openRecordOne();
    await screen.findByText("Awaiting concept review.");
    const reviewReads = backend.count("GET", "/api/reviewable-units?entry_id=1");
    // App starts on the global Concept Review, so that queue was read before.
    const globalReads = backend.count("GET", "/api/reviewable-units");

    fireEvent.click(screen.getByRole("button", { name: "Review unit #201 in Concept Review" }));
    expect(await screen.findByRole("heading", { name: "Concept Review for record #1" })).toHaveFocus();
    await screen.findByRole("heading", { name: "Knowledge Unit (evidence)" });
    expect(reviewCard()).toHaveTextContent("Énoncé unit 201");
    expect(screen.getByText("unit 1 of 1")).toBeInTheDocument();
    // Focus mode read only the record's reviewable units, never the global queue.
    expect(backend.count("GET", "/api/reviewable-units")).toBe(globalReads);

    fireEvent.click(screen.getByRole("button", { name: "INVALID" }));
    expect(await screen.findByText("No units of record #1 are awaiting review.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "← Back to record #1" }));
    await waitFor(() => expect(document.getElementById("extracted-unit-201")).toHaveFocus());
    await waitFor(() => expect(backend.count("GET", "/api/reviewable-units?entry_id=1")).toBeGreaterThan(reviewReads + 1));
    const unit201 = document.getElementById("extracted-unit-201") as HTMLElement;
    await waitFor(() => expect(unit201).toHaveTextContent("Not awaiting review (already resolved or marked INVALID)."));
    expect(within(unit201).queryByRole("button", { name: /Concept Review/ })).not.toBeInTheDocument();
    expect(backend.calls.filter((c) => c.method !== "GET").map((c) => `${c.method} ${c.url}`)).toEqual([
      "POST /api/knowledge-units/201/invalid",
    ]);
  });

  it("explains a unit that stopped awaiting review and offers inspection instead", async () => {
    const backend = fixtureBackend();
    await openRecordOne();
    await screen.findByText("Awaiting concept review.");
    // Resolved elsewhere between showing the record and opening the queue.
    backend.reviewable.delete(201);

    fireEvent.click(screen.getByRole("button", { name: "Review unit #201 in Concept Review" }));
    const missing = await screen.findByRole("alert");
    expect(missing).toHaveTextContent("Unit #201 is not awaiting review.");
    expect(missing).toHaveTextContent("It is not shown as a review candidate.");
    expect(reviewCard()).toBeNull();

    fireEvent.click(within(missing).getByRole("button", { name: "Inspect unit #201" }));
    expect(await screen.findByLabelText("Unit currency")).toHaveTextContent(
      "This unit belongs to the record's current extraction (automatic selection). It is invalid, so it is not awaiting review.",
    );
    fireEvent.click(screen.getByRole("button", { name: "← Back to record #1" }));
    await waitFor(() => expect(document.getElementById("extracted-unit-201")).toHaveFocus());
  });

  it("reports a unit that no longer exists, with a way back", async () => {
    const backend = fixtureBackend();
    backend.handlers["GET /api/knowledge-units/202/effective-annotation"] = { status: 404, body: { error: "knowledge unit not found" } };
    await openRecordOne();
    await screen.findByText("Not awaiting review (already resolved or marked INVALID).");
    fireEvent.click(screen.getByRole("button", { name: "Inspect unit #202" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Unit #202 was not found on the server. Return to the record and reload its extractions.",
    );
    fireEvent.click(screen.getByRole("button", { name: "← Back to record #1" }));
    await waitFor(() => expect(document.getElementById("extracted-unit-202")).toHaveFocus());
  });

  it("leaves focus mode when the reader switches tabs directly", async () => {
    const backend = fixtureBackend();
    await openRecordOne();
    await screen.findByText("Awaiting concept review.");
    fireEvent.click(screen.getByRole("button", { name: "Review unit #201 in Concept Review" }));
    await screen.findByRole("heading", { name: "Concept Review for record #1" });
    const globalReads = backend.count("GET", "/api/reviewable-units");

    fireEvent.click(screen.getByRole("button", { name: "Concept Review" }));
    await waitFor(() => expect(backend.count("GET", "/api/reviewable-units")).toBeGreaterThan(globalReads));
    expect(screen.queryByRole("region", { name: "Record context" })).not.toBeInTheDocument();

    // The record is still open where it was left.
    fireEvent.click(screen.getByRole("button", { name: "Learning Records" }));
    expect(screen.getByRole("heading", { name: "Record #1", level: 2 })).toBeVisible();
  });

  it("ignores an inspection response that arrives after the reader went back", async () => {
    const backend = fixtureBackend();
    const slow = deferred();
    backend.handlers["GET /api/knowledge-units/202/effective-annotation"] = () => slow.promise;
    await openRecordOne();
    await screen.findByText("Not awaiting review (already resolved or marked INVALID).");
    fireEvent.click(screen.getByRole("button", { name: "Inspect unit #202" }));
    await screen.findByText("Loading the unit's annotation…");
    fireEvent.click(screen.getByRole("button", { name: "← Back to record #1" }));
    await waitFor(() => expect(document.getElementById("extracted-unit-202")).toHaveFocus());

    await act(async () => {
      slow.resolve({ body: annotation(202, 20, "resolved") });
    });
    expect(screen.queryByLabelText("Unit currency")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Record #1", level: 2 })).toBeVisible();
  });
});

describe("Focused inspection header", () => {
  it("does not describe a unit opened from a record as a current-extraction unit", async () => {
    fixtureBackend();
    await openRecordOne();
    fireEvent.click(versions().getByRole("button", { name: "v1" }));
    fireEvent.click(screen.getByRole("button", { name: "Inspect stored labels of unit #101" }));
    expect(await screen.findByRole("heading", { name: "Unit Inspection", level: 1 })).toBeInTheDocument();
    expect(screen.queryByText(/for current-extraction units/)).not.toBeInTheDocument();
  });
});
