import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import App from "./App";

// Record → unit inspection → explicit correction → back, through the real App in
// StrictMode against a stateful synthetic backend. No provider call is made and no
// real database is touched; every write is counted.
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

const extractedUnit = (id: number) => ({
  id,
  ordinal: 1,
  kind: "grammar",
  canonical: `unit ${id}`,
  statement: `Énoncé unit ${id}`,
  example: null,
  confidence: 0.9,
  created_at: "t",
  admission: { ruleset: "knowledge_admission_v1", machine_state: "active", machine_reason: "default_active", effective_state: "active", latest_override: null },
});

const concept = (id: number, target: string, lifecycle = "normal") => ({
  id,
  identity_schema_version: "fr_l2_concept_identity_v1",
  target,
  pedagogical_intent: "grammar",
  scope: "",
  identity_features: {},
  signature: `sig-${id}`,
  preferred_unit_id: null,
  state: lifecycle === "retired" ? "retired" : "active",
  lifecycle_state: lifecycle,
  support_state: "supported",
  created_at: "t",
  updated_at: "t",
});

const link = (id: number, unitId: number, conceptId: number) => ({
  id,
  unit_id: unitId,
  concept_id: conceptId,
  relation: "same",
  status: "accepted",
  decision_source: "human",
  resolver_version: "v1",
  score: null,
  evidence: "{}",
  supersedes_link_id: null,
  created_at: "t",
});

const judgment = (id: number, unitId: number, kind: "invalid" | "restored") => ({
  id, unit_id: unitId, judgment: kind, decision_source: "human", note: "", evidence: "{}", created_at: "t",
});

const record = {
  entry_id: 1,
  original_input: "Question 1",
  original_context: "",
  entry_created_at: "t",
  state: "unreviewed",
  analysis_id: 11,
  analysis_version: 1,
  analyzer: "rule-based:v2:fr_l2_taxonomy_v1",
  confidence: 0.5,
  uncertainty: "",
  analysis_created_at: "t",
  original: { category: "grammar", explanation: "e" },
  effective: { category: "grammar", explanation: "e" },
  feedback_id: null,
};

// Entry 1: v1 (extraction 10, historical) has unit 101, which still has a stored
// SAME to concept 7; v2 (extraction 20, current) has unit 201 (SAME to concept 7
// via link 70) and unit 202 (INVALID by judgment 5).
function fixtureBackend() {
  const state = {
    memberships: new Map<number, { concept: number; link: number }>([
      [101, { concept: 7, link: 60 }],
      [201, { concept: 7, link: 70 }],
    ]),
    judgments: new Map<number, ReturnType<typeof judgment>[]>([[202, [judgment(5, 202, "invalid")]]]),
    nextId: 100,
  };
  const extractionOf: Record<number, number> = { 101: 10, 201: 20, 202: 20 };
  const isInvalid = (unitId: number) => state.judgments.get(unitId)?.[0]?.judgment === "invalid";
  const annotation = (unitId: number) => {
    const m = state.memberships.get(unitId);
    const latest = state.judgments.get(unitId)?.[0] ?? null;
    return {
      unit: { ...extractedUnit(unitId), extraction_id: extractionOf[unitId], admission: undefined },
      snapshot: {
        unit_id: unitId,
        status: isInvalid(unitId) ? "invalid" : m ? "resolved" : "unresolved",
        latest_unit_judgment: latest,
        current_same: m ? { membership: { concept_id: m.concept, link_id: m.link, updated_at: "t" }, decision: link(m.link, unitId, m.concept) } : null,
        distinctions: [],
        relations: [],
      },
    };
  };
  const addJudgment = (unitId: number, kind: "invalid" | "restored") => {
    const j = judgment(++state.nextId, unitId, kind);
    state.judgments.set(unitId, [j, ...(state.judgments.get(unitId) ?? [])]);
    return j;
  };

  const calls: Array<{ method: string; url: string; body: unknown }> = [];
  const handlers: Record<string, Handler> = {
    "GET /api/learning-records?limit=20": { body: { records: [record], next_before_entry_id: null } },
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
          { id: 20, entry_id: 1, version: 2, source_analysis_id: 11, source_feedback_id: null, extractor: "x", created_at: "t", units: [extractedUnit(201), extractedUnit(202)] },
          { id: 10, entry_id: 1, version: 1, source_analysis_id: 11, source_feedback_id: null, extractor: "x", created_at: "t", units: [extractedUnit(101)] },
        ],
      },
    },
    "GET /api/entries/1/current-extraction": { body: { entry_id: 1, current_extraction_id: 20, selection_mode: "automatic" } },
    "GET /api/reviewable-units?entry_id=1": () => ({
      body: { reviewable_units: [201, 202].filter((id) => !isInvalid(id) && !state.memberships.has(id)).map((id) => ({ unit_id: id, kind: "grammar", canonical: `unit ${id}`, statement: "s", example: null, confidence: 0.9, candidate_identity: { target: `unit ${id}`, pedagogical_intent: "grammar", scope: "", identity_features: {} }, signature: "s" })) },
    }),
    "GET /api/reviewable-units": { body: { reviewable_units: [] } },
    "GET /api/concepts": { body: { concepts: [concept(7, "accord du participe"), concept(8, "participe passé avec avoir"), concept(9, "participe retiré", "retired")] } },
    "PUT /api/knowledge-units/201/concept-membership": (body) => {
      const target = (body as { concept_id: number }).concept_id;
      const id = ++state.nextId;
      state.memberships.set(201, { concept: target, link: id });
      return { body: link(id, 201, target) };
    },
    "POST /api/knowledge-units/201/invalid": () => {
      state.memberships.delete(201);
      return { body: { unit_id: 201, invalid: true, current_membership: null, judgment: addJudgment(201, "invalid") } };
    },
    "POST /api/knowledge-units/202/invalid/restore": () => ({
      body: { unit_id: 202, invalid: false, judgment: addJudgment(202, "restored") },
    }),
  };
  for (const id of [101, 201, 202]) {
    handlers[`GET /api/knowledge-units/${id}/effective-annotation`] = () => ({ body: annotation(id) });
    handlers[`GET /api/knowledge-units/${id}/concept-membership`] = () => {
      const m = state.memberships.get(id);
      return { body: { unit_id: id, current_membership: m ? { concept_id: m.concept, link_id: m.link, updated_at: "t" } : null } };
    };
    handlers[`GET /api/knowledge-units/${id}/invalid`] = () => ({
      body: { unit_id: id, invalid: isInvalid(id), history: state.judgments.get(id) ?? [] },
    });
  }

  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = String(input);
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ method, url, body });
    const handler = handlers[`${method} ${url}`];
    const reply = handler === undefined ? { status: 404, body: { error: "not found" } } : typeof handler === "function" ? await handler(body) : handler;
    if (reply === "network-error") throw new TypeError("Failed to fetch");
    return new Response(JSON.stringify(reply.body), { status: reply.status ?? 200, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
  const writes = () => calls.filter((c) => c.method !== "GET").map((c) => `${c.method} ${c.url}`);
  return { handlers, state, calls, writes };
}

const panel = () => screen.getByRole("region", { name: /Correct unit #\d+/ });
const versions = () => within(screen.getByRole("group", { name: "Stored extraction versions" }));

async function inspect(unitId: number, version?: string) {
  render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Learning Records" }));
  fireEvent.click(await screen.findByRole("button", { name: "Open record #1" }));
  await screen.findByLabelText("Viewed extraction");
  if (version) fireEvent.click(versions().getByRole("button", { name: version }));
  const name = version ? `Inspect stored labels of unit #${unitId}` : `Inspect unit #${unitId}`;
  fireEvent.click(await screen.findByRole("button", { name }));
  expect(await screen.findByRole("heading", { name: `Unit #${unitId} from record #1` })).toHaveFocus();
  await screen.findByRole("region", { name: `Correct unit #${unitId}` });
}

function selectTarget(conceptId: number) {
  const item = within(panel()).getByRole("listitem", { name: `Concept #${conceptId}` });
  fireEvent.click(within(item).getByRole("button", { name: "select this concept" }));
}

describe("Correcting a reviewed unit from the Inspector", () => {
  it("explains and reassigns an existing SAME membership once, then re-reads and returns focus", async () => {
    const backend = fixtureBackend();
    await inspect(201);
    expect(panel()).toHaveTextContent("Current backend state: resolved. CURRENT SAME membership is concept #7 (\"accord du participe\"), in force by SAME event #70.");
    // The current concept and retired concepts are not offered as targets.
    const targets = within(panel()).getByRole("list", { name: "Reassignment targets" });
    expect(within(targets).getAllByRole("listitem").map((li) => li.getAttribute("aria-label"))).toEqual(["Concept #8"]);
    expect(within(panel()).getByRole("button", { name: "Reassign SAME…" })).toBeDisabled();

    selectTarget(8);
    fireEvent.click(within(panel()).getByRole("button", { name: "Reassign SAME to concept #8…" }));
    const confirm = within(panel()).getByRole("group", { name: "Reassign SAME to concept #8" });
    expect(confirm).toHaveTextContent("Moves unit #201's CURRENT SAME membership from concept #7 (\"accord du participe\") to concept #8 (\"participe passé avec avoir\")");
    expect(confirm).toHaveTextContent("superseding event #70 is appended; the earlier event stays in history");
    expect(backend.writes()).toEqual([]);

    fireEvent.click(within(confirm).getByRole("button", { name: "Confirm reassignment to concept #8" }));
    expect(await within(panel()).findByText(/Moved unit #201's CURRENT SAME membership from concept #7 to concept #8 \(SAME event #101\)/)).toBeInTheDocument();
    expect(await within(panel()).findByText("Unit #201's annotation and the record's current extraction re-read from the server.")).toBeInTheDocument();
    expect(panel()).toHaveTextContent("CURRENT SAME membership is concept #8");
    expect(backend.writes()).toEqual(["PUT /api/knowledge-units/201/concept-membership"]);
    expect(backend.calls.find((c) => c.method === "PUT")?.body).toEqual({ concept_id: 8 });

    fireEvent.click(screen.getByRole("button", { name: "← Back to record #1" }));
    await waitFor(() => expect(document.getElementById("extracted-unit-201")).toHaveFocus());
    expect(backend.writes()).toEqual(["PUT /api/knowledge-units/201/concept-membership"]);
  });

  it("shows the reassignment target's current support before confirming, with reads only (FLH-093)", async () => {
    const backend = fixtureBackend();
    const supporting = { unit_id: 301, kind: "grammar", canonical: "avoir + participe", statement: "Avec avoir, le participe s'accorde avec le COD placé avant.", example: "Les lettres que j'ai écrites.", entry_id: 3, extraction_id: 30, extraction_version: 1, in_current_extraction: true, admission: "active" };
    backend.handlers["GET /api/knowledge-library/concepts/8"] = {
      body: { schema_version: "knowledge_library_concept_v1", concept: concept(8, "participe passé avec avoir"), preferred_unit: null, supporting_units: [supporting], non_supporting_members: [], current_relations: [], historical_units: [], history_event_count: 1 },
    };
    backend.handlers["GET /api/knowledge-library/units/301/source"] = {
      body: { schema_version: "knowledge_library_source_v1", unit: supporting, entry: { id: 3, original_input: "Pourquoi « écrites » avec -es ?", original_context: "", created_at: "t" }, extraction: { id: 30, version: 1, extractor: "x", source_analysis_id: 1, source_feedback_id: null, created_at: "t" }, current_extraction: { extraction_id: 30, selection_mode: "automatic" }, source_interpretation: {} },
    };
    await inspect(201);
    selectTarget(8);
    const content = await within(panel()).findByRole("region", { name: "Contents of concept #8" });
    expect(within(panel()).getByRole("heading", { name: "What concept #8 currently contains" })).toBeInTheDocument();
    expect(content).toHaveTextContent("Avec avoir, le participe s'accorde avec le COD placé avant.");
    fireEvent.click(within(content).getByRole("button", { name: "Show the original question for unit #301" }));
    expect(await within(content).findByText("Pourquoi « écrites » avec -es ?")).toBeInTheDocument();
    expect(backend.writes()).toEqual([]);

    fireEvent.click(within(panel()).getByRole("button", { name: "Reassign SAME to concept #8…" }));
    fireEvent.click(within(panel()).getByRole("button", { name: "Confirm reassignment to concept #8" }));
    await waitFor(() => expect(backend.writes()).toEqual(["PUT /api/knowledge-units/201/concept-membership"]));
    expect(backend.calls.find((c) => c.method === "PUT")?.body).toEqual({ concept_id: 8 });
  });

  it("marks a resolved unit INVALID, then offers only RESTORE", async () => {
    const backend = fixtureBackend();
    await inspect(201);
    fireEvent.click(within(panel()).getByRole("button", { name: "Mark unit #201 INVALID…" }));
    const confirm = within(panel()).getByRole("group", { name: "Mark unit #201 INVALID" });
    expect(confirm).toHaveTextContent("clears its CURRENT SAME membership to concept #7");
    expect(confirm).toHaveTextContent("RESTORE can later withdraw the INVALID judgment, but it does not bring this membership back.");
    fireEvent.click(within(confirm).getByRole("button", { name: "Confirm INVALID for unit #201" }));

    expect(await within(panel()).findByText(/Marked unit #201 INVALID \(judgment #101\)/)).toBeInTheDocument();
    await waitFor(() => expect(panel()).toHaveTextContent("Current backend state: invalid, by judgment #101."));
    expect(within(panel()).queryByRole("button", { name: /Reassign SAME/ })).not.toBeInTheDocument();
    expect(within(panel()).getByRole("button", { name: "Restore unit #201…" })).toBeEnabled();
    expect(backend.writes()).toEqual(["POST /api/knowledge-units/201/invalid"]);
  });

  it("restores an INVALID unit without recreating membership and links to Concept Review", async () => {
    const backend = fixtureBackend();
    await inspect(202);
    expect(panel()).toHaveTextContent("Current backend state: invalid, by judgment #5. It has no CURRENT SAME membership.");
    fireEvent.click(within(panel()).getByRole("button", { name: "Restore unit #202…" }));
    const confirm = within(panel()).getByRole("group", { name: "Restore unit #202" });
    expect(confirm).toHaveTextContent("withdraws INVALID judgment #5");
    expect(confirm).toHaveTextContent("No SAME membership is recreated");
    fireEvent.click(within(confirm).getByRole("button", { name: "Confirm RESTORE for unit #202" }));

    expect(await within(panel()).findByText(/Restored unit #202 \(judgment #101\)/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Open unit #202 in Concept Review" })).toBeInTheDocument();
    expect(panel()).toHaveTextContent("This unit has no CURRENT SAME membership and is not INVALID; review it in Concept Review.");
    expect(backend.writes()).toEqual(["POST /api/knowledge-units/202/invalid/restore"]);
  });

  it("keeps a historical unit read-only even though it has stored SAME", async () => {
    const backend = fixtureBackend();
    await inspect(101, "v1");
    expect(panel()).toHaveTextContent("Historical units are read-only here");
    expect(within(panel()).queryAllByRole("button")).toEqual([]);
    expect(backend.writes()).toEqual([]);
  });

  it("reports a server rejection, re-reads authority, and sends nothing again", async () => {
    const backend = fixtureBackend();
    backend.handlers["PUT /api/knowledge-units/201/concept-membership"] = { status: 409, body: { error: "effectively INVALID unit must be restored" } };
    await inspect(201);
    selectTarget(8);
    fireEvent.click(within(panel()).getByRole("button", { name: "Reassign SAME to concept #8…" }));
    fireEvent.click(within(panel()).getByRole("button", { name: "Confirm reassignment to concept #8" }));

    expect(await within(panel()).findByRole("alert")).toHaveTextContent(
      "The server did not record REASSIGN SAME concept #7 → concept #8 (409) effectively INVALID unit must be restored.",
    );
    await within(panel()).findByText("Unit #201's annotation and the record's current extraction re-read from the server.");
    expect(panel()).toHaveTextContent("CURRENT SAME membership is concept #7");
    expect(backend.writes()).toEqual(["PUT /api/knowledge-units/201/concept-membership"]);
  });

  it("treats a lost response as unknown, checks without resending, and ignores a stale check", async () => {
    const backend = fixtureBackend();
    backend.handlers["POST /api/knowledge-units/201/invalid"] = "network-error";
    const slowCheck = deferred();
    backend.handlers["GET /api/knowledge-units/201/invalid"] = () => slowCheck.promise;
    await inspect(201);
    fireEvent.click(within(panel()).getByRole("button", { name: "Mark unit #201 INVALID…" }));
    fireEvent.click(within(panel()).getByRole("button", { name: "Confirm INVALID for unit #201" }));

    expect(await within(panel()).findByText(/No response was received for INVALID on unit #201/)).toBeInTheDocument();
    expect(panel()).toHaveTextContent("Outcome unknown.");
    await within(panel()).findByText("Checking the server for INVALID on unit #201…");
    // Corrections wait while the outcome is unknown.
    expect(within(panel()).getByRole("button", { name: "Mark unit #201 INVALID…" })).toBeDisabled();

    // The request was stored after all; a newer check finds it.
    backend.state.memberships.delete(201);
    backend.state.judgments.set(201, [judgment(300, 201, "invalid")]);
    backend.handlers["GET /api/knowledge-units/201/invalid"] = { body: { unit_id: 201, invalid: true, history: [judgment(300, 201, "invalid")] } };
    fireEvent.click(within(panel()).getByRole("button", { name: "Check again" }));
    expect(await within(panel()).findByText(/Found on the server: The unit is INVALID \(judgment #300\)/)).toBeInTheDocument();
    await waitFor(() => expect(panel()).toHaveTextContent("Current backend state: invalid, by judgment #300."));

    // The first, older check answers late with the pre-write state: it is ignored.
    await act(async () => {
      slowCheck.resolve({ body: { unit_id: 201, invalid: false, history: [] } });
    });
    expect(within(panel()).queryByRole("region", { name: "Unknown correction outcome" })).not.toBeInTheDocument();
    expect(within(panel()).getByRole("button", { name: "Restore unit #201…" })).toBeEnabled();
    expect(backend.writes()).toEqual(["POST /api/knowledge-units/201/invalid"]);
  });

  it("blocks further corrections after an unknown outcome until explicitly allowed", async () => {
    const backend = fixtureBackend();
    backend.handlers["PUT /api/knowledge-units/201/concept-membership"] = "network-error";
    await inspect(201);
    selectTarget(8);
    fireEvent.click(within(panel()).getByRole("button", { name: "Reassign SAME to concept #8…" }));
    fireEvent.click(within(panel()).getByRole("button", { name: "Confirm reassignment to concept #8" }));
    const unknown = await within(panel()).findByRole("region", { name: "Unknown correction outcome" });
    expect(unknown).toHaveTextContent("The unit's CURRENT SAME membership is concept #7, not #8.");
    expect(within(panel()).getByRole("button", { name: "Mark unit #201 INVALID…" })).toBeDisabled();

    fireEvent.click(within(unknown).getByRole("button", { name: "Allow another correction for unit #201…" }));
    fireEvent.click(within(unknown).getByRole("button", { name: "Allow another correction" }));
    expect(await within(panel()).findByRole("button", { name: "Mark unit #201 INVALID…" })).toBeEnabled();
    expect(backend.writes()).toEqual(["PUT /api/knowledge-units/201/concept-membership"]);
  });

  it("sends nothing when the unit changed on the server after it was shown", async () => {
    const backend = fixtureBackend();
    await inspect(201);
    fireEvent.click(within(panel()).getByRole("button", { name: "Mark unit #201 INVALID…" }));
    // Another tab reassigned the unit meanwhile.
    backend.state.memberships.set(201, { concept: 8, link: 99 });
    fireEvent.click(within(panel()).getByRole("button", { name: "Confirm INVALID for unit #201" }));

    expect(await within(panel()).findByRole("alert")).toHaveTextContent(
      "Nothing was sent: unit #201 changed on the server since it was shown.",
    );
    expect(panel()).toHaveTextContent("CURRENT SAME membership is concept #8 (\"participe passé avec avoir\"), in force by SAME event #99.");
    expect(backend.writes()).toEqual([]);
  });

  it("sends nothing when the unit's extraction stopped being current", async () => {
    const backend = fixtureBackend();
    await inspect(201);
    fireEvent.click(within(panel()).getByRole("button", { name: "Mark unit #201 INVALID…" }));
    backend.handlers["GET /api/entries/1/current-extraction"] = { body: { entry_id: 1, current_extraction_id: 10, selection_mode: "pinned" } };
    fireEvent.click(within(panel()).getByRole("button", { name: "Confirm INVALID for unit #201" }));

    expect(await within(panel()).findByRole("alert")).toHaveTextContent("Nothing was sent");
    expect(panel()).toHaveTextContent("Historical units are read-only here");
    expect(screen.getByLabelText("Unit currency")).toHaveTextContent("Historical unit.");
    expect(backend.writes()).toEqual([]);
  });

  it("reports a failed re-read separately and keeps corrections disabled until a re-read succeeds", async () => {
    const backend = fixtureBackend();
    await inspect(202);
    const reads = { failed: false };
    backend.handlers["POST /api/knowledge-units/202/invalid/restore"] = () => {
      backend.state.judgments.set(202, [judgment(400, 202, "restored"), judgment(5, 202, "invalid")]);
      backend.handlers["GET /api/knowledge-units/202/effective-annotation"] = () => {
        reads.failed = true;
        return { status: 500, body: { error: "storage unavailable" } };
      };
      return { body: { unit_id: 202, invalid: false, judgment: judgment(400, 202, "restored") } };
    };
    fireEvent.click(within(panel()).getByRole("button", { name: "Restore unit #202…" }));
    fireEvent.click(within(panel()).getByRole("button", { name: "Confirm RESTORE for unit #202" }));

    expect(await within(panel()).findByText(/Restored unit #202 \(judgment #400\)/)).toBeInTheDocument();
    expect(await within(panel()).findByText(/Could not re-read unit #202's annotation/)).toBeInTheDocument();
    expect(reads.failed).toBe(true);
    // The shown (pre-write) state is not presented as current for another write.
    expect(within(panel()).getByRole("button", { name: "Restore unit #202…" })).toBeDisabled();
    expect(panel()).toHaveTextContent("Re-read the unit's state before another correction.");

    delete backend.handlers["GET /api/knowledge-units/202/effective-annotation"];
    backend.handlers["GET /api/knowledge-units/202/effective-annotation"] = {
      body: {
        unit: { ...extractedUnit(202), extraction_id: 20 },
        snapshot: { unit_id: 202, status: "unresolved", latest_unit_judgment: judgment(400, 202, "restored"), current_same: null, distinctions: [], relations: [] },
      },
    };
    fireEvent.click(within(panel()).getByRole("button", { name: "Re-read unit #202" }));
    await within(panel()).findByText("Unit #202's annotation and the record's current extraction re-read from the server.");
    expect(panel()).toHaveTextContent("review it in Concept Review");
    expect(backend.writes()).toEqual(["POST /api/knowledge-units/202/invalid/restore"]);
  });

  it("keeps the record navigation waiting while a correction is in flight", async () => {
    const backend = fixtureBackend();
    const slow = deferred();
    backend.handlers["POST /api/knowledge-units/202/invalid/restore"] = () => slow.promise;
    await inspect(202);
    fireEvent.click(within(panel()).getByRole("button", { name: "Restore unit #202…" }));
    fireEvent.click(within(panel()).getByRole("button", { name: "Confirm RESTORE for unit #202" }));
    await within(panel()).findByText(/Sending RESTORE for unit #202/);
    expect(screen.getByRole("button", { name: "← Back to record #1" })).toBeDisabled();
    expect(within(panel()).getByRole("button", { name: "Restore unit #202 — waiting for the server…" })).toBeDisabled();

    await act(async () => {
      backend.state.judgments.set(202, [judgment(401, 202, "restored"), judgment(5, 202, "invalid")]);
      slow.resolve({ body: { unit_id: 202, invalid: false, judgment: judgment(401, 202, "restored") } });
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "← Back to record #1" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "← Back to record #1" }));
    await waitFor(() => expect(document.getElementById("extracted-unit-202")).toHaveFocus());
    expect(backend.writes()).toEqual(["POST /api/knowledge-units/202/invalid/restore"]);
  });
});
