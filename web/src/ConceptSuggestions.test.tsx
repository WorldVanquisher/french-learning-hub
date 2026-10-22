import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { ConceptSuggestions } from "./pages/ConceptSuggestions";

afterEach(cleanup);
beforeEach(() => window.localStorage.clear());

// FLH-097: AI-assisted Concept suggestions inside Concept Review. Synthetic
// content authored for these tests; the "server" is a local router.

type Reply = { status?: number; body: unknown } | "network";
type Handler = unknown | (() => Reply);
type Call = { method: string; path: string; body: unknown; key: string | null; storedAtSend: string | null };

function router(handlers: Record<string, Handler>) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const path = new URL(String(url), "http://localhost").pathname;
    const headers = (init?.headers ?? {}) as Record<string, string>;
    calls.push({
      method, path, body: init?.body ? JSON.parse(String(init.body)) : undefined,
      key: headers["Idempotency-Key"] ?? null,
      storedAtSend: window.localStorage.getItem("flh.concept-suggestion-requests.v1"),
    });
    const h = handlers[`${method} ${path}`];
    const reply: Reply = h === undefined ? { status: 404, body: { error: "not found" } } : typeof h === "function" ? (h as () => Reply)() : { body: h };
    if (reply === "network") throw new TypeError("network down");
    return new Response(JSON.stringify(reply.body), { status: reply.status ?? 200, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
  return calls;
}

const writes = (calls: Call[]) => calls.filter((c) => c.method !== "GET");

function unit(id: number, canonical: string, statement: string) {
  return {
    unit_id: id, kind: "grammar", canonical, statement, statements: { en: null, zh: null }, example: null, confidence: 0.9,
    candidate_identity: { target: canonical, pedagogical_intent: "grammar", scope: "", identity_features: {} }, signature: "s", entry_id: 5,
  };
}

const U1 = unit(101, "parler langue sans article", "After « parler », a language takes no article.");
const U2 = unit(102, "vouloir présent", "« vouloir » in the present tense.");

const limits = { max_units: 2, candidates_per_unit: 5, member_examples: 2, max_unit_text_chars: 1200, max_concept_text_chars: 800, max_reason_chars: 500 };
const overview = (enabled = true, runs: unknown[] = []) => ({
  enabled, generator: enabled ? "openai:m:concept_suggestion_v1" : null, candidate_policy: "concept_suggestion_candidates_v1", limits, runs,
});
const queue = { reviewable_units: [U1, U2, unit(103, "xylophone", "« xylophone » is masculine.")], next_cursor: null, limit: 50 };

function item(state: string, extra: Record<string, unknown> = {}) {
  return {
    id: 900, run_id: 7, ordinal: 1, unit_id: 101, entry_id: 5, source_extraction_id: 3, outcome: "suggested",
    suggested_concept_id: 40, reason: "Both teach « parler » + language without an article.",
    candidates: [{ concept_id: 40, rank: 1, source: "exact_signature", signature: "s", target: "parler + langue" }],
    state, stale_reasons: [], current_concept_id: null, confirmation: null, unit: U1, created_at: "2026-10-21T10:00:00Z", ...extra,
  };
}
function run(items: unknown[], extra: Record<string, unknown> = {}) {
  return {
    id: 7, operation_id: "00000000-0000-4000-8000-000000000000", status: "completed", failure_code: null,
    generator: "openai:m:concept_suggestion_v1", candidate_policy: "concept_suggestion_candidates_v1", candidate_limit: 5,
    provider_called: true, unit_ids: [101], item_count: items.length, suggested_count: 1, created_at: "2026-10-21T10:00:00Z",
    items, ...extra,
  };
}

const base = { "GET /api/concept-suggestion-runs": overview(), "GET /api/reviewable-units": queue };

describe("ConceptSuggestions", () => {
  it("selecting sends nothing, the batch is bounded, and Generate stores its key before one keyed request", async () => {
    const calls = router({ ...base, "POST /api/concept-suggestion-runs": () => ({ status: 201, body: run([item("open")]) }) });
    render(<ConceptSuggestions />);
    const generate = await screen.findByRole("button", { name: "Generate suggestions" });
    await screen.findByText("parler langue sans article");
    expect(generate).toBeDisabled();
    const boxes = screen.getAllByRole("checkbox");
    fireEvent.click(boxes[0]);
    fireEvent.click(boxes[1]);
    expect(boxes[2]).toBeDisabled(); // max_units = 2
    expect(screen.getByText("2 of at most 2 selected")).toBeInTheDocument();
    expect(writes(calls)).toHaveLength(0);

    fireEvent.click(generate);
    await screen.findByText("Suggestion run #7");
    const post = writes(calls);
    expect(post).toHaveLength(1);
    expect(post[0].body).toEqual({ unit_ids: [101, 102] });
    expect(post[0].key).toMatch(/^[0-9a-f-]{36}$/);
    expect(post[0].storedAtSend).toContain(post[0].key!);
    expect(window.localStorage.getItem("flh.concept-suggestion-requests.v1")).toContain('"pending":null');
    expect(screen.getByText("Both teach « parler » + language without an article.")).toBeInTheDocument();
    expect(screen.getByText(/does not prove that no Concept in the catalog fits/)).toBeInTheDocument();
    // No bulk acceptance exists.
    expect(screen.queryByRole("button", { name: /all/i })).toBeNull();
  });

  it("disabled server: Generate is unavailable and says why", async () => {
    router({ ...base, "GET /api/concept-suggestion-runs": overview(false) });
    render(<ConceptSuggestions />);
    expect(await screen.findByText(/AI suggestions are not enabled/)).toBeInTheDocument();
    fireEvent.click((await screen.findAllByRole("checkbox"))[0]);
    expect(screen.getByRole("button", { name: "Generate suggestions" })).toBeDisabled();
  });

  it("a lost answer stays pending across a reload and is looked up, not resent", async () => {
    const calls = router({ ...base, "POST /api/concept-suggestion-runs": () => "network" });
    render(<ConceptSuggestions />);
    fireEvent.click((await screen.findAllByRole("checkbox"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Generate suggestions" }));
    expect(await screen.findByText(/may or may not have been stored; check/)).toBeInTheDocument();
    const key = writes(calls)[0].key!;
    cleanup();

    // Reload: the pending request is shown; Generate is blocked until it is resolved.
    const calls2 = router({ ...base, [`GET /api/concept-suggestion-runs/operations/${key}`]: run([item("open")], { operation_id: key }) });
    render(<ConceptSuggestions />);
    expect(await screen.findByText("Earlier request: outcome unknown")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check for a stored result" }));
    expect(await screen.findByText("Found the stored result: run #7.")).toBeInTheDocument();
    expect(writes(calls2)).toHaveLength(0);
    expect(screen.queryByText("Earlier request: outcome unknown")).toBeNull();
  });

  it("resending a pending request reuses its key", async () => {
    const key = "11111111-2222-4333-8444-555555555555";
    window.localStorage.setItem("flh.concept-suggestion-requests.v1", JSON.stringify({ version: 1, pending: { operationId: key, unitIds: [101] } }));
    const calls = router({ ...base, "POST /api/concept-suggestion-runs": () => ({ status: 201, body: run([item("open")], { operation_id: key }) }) });
    render(<ConceptSuggestions />);
    fireEvent.click(await screen.findByRole("button", { name: "Send the same request again" }));
    await screen.findByText("Suggestion run #7");
    expect(writes(calls)).toEqual([expect.objectContaining({ key, body: { unit_ids: [101] } })]);
  });

  it("a provider failure shows the stored failed run and clears the pending request", async () => {
    router({
      ...base,
      "POST /api/concept-suggestion-runs": () => ({ status: 502, body: { error: "suggestion provider returned invalid output", run: run([], { status: "failed", failure_code: "invalid_output" }) } }),
    });
    render(<ConceptSuggestions />);
    fireEvent.click((await screen.findAllByRole("checkbox"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Generate suggestions" }));
    expect(await screen.findByText(/This run failed \(invalid_output\)/)).toBeInTheDocument();
    expect(screen.queryByText("Earlier request: outcome unknown")).toBeNull();
    expect(window.localStorage.getItem("flh.concept-suggestion-requests.v1")).toContain('"pending":null');
  });

  it("confirms one item explicitly; Leave unused records nothing", async () => {
    const second = item("open", { id: 901, unit_id: 102, unit: U2, suggested_concept_id: 41, reason: "Same verb and tense." });
    const confirmed = item("confirmed", { confirmation: { id: 1, link_id: 77, created_at: "t", still_current: true } });
    const calls = router({
      ...base,
      "GET /api/concept-suggestion-runs": overview(true, [run([])]),
      "GET /api/concept-suggestion-runs/7": run([item("open"), second]),
      "POST /api/concept-suggestion-items/900/confirm": () => ({ status: 201, body: { item: confirmed, link: { id: 77 }, replayed: false } }),
    });
    render(<ConceptSuggestions />);
    fireEvent.click(await screen.findByRole("button", { name: /Run #7/ }));
    const first = await screen.findByRole("article", { name: "Suggestion for unit 101" });
    const other = screen.getByRole("article", { name: "Suggestion for unit 102" });

    fireEvent.click(within(other).getByRole("button", { name: "Leave unused" }));
    expect(within(other).getByText("Left unused. Nothing was recorded.")).toBeInTheDocument();
    expect(writes(calls)).toHaveLength(0);

    fireEvent.click(within(first).getByRole("button", { name: "Confirm SAME to Concept #40" }));
    expect(await within(first).findByText("Recorded as human SAME event #77.")).toBeInTheDocument();
    expect(writes(calls)).toEqual([expect.objectContaining({ path: "/api/concept-suggestion-items/900/confirm", body: { concept_id: 40 } })]);
    expect(within(first).queryByRole("button", { name: /Confirm SAME/ })).toBeNull();
  });

  it("a stale item explains why and offers no confirmation; a stale refusal re-reads the run", async () => {
    let reads = 0;
    const stale = item("stale", { id: 902, stale_reasons: ["unit_has_current_same"], current_concept_id: 12 });
    router({
      ...base,
      "GET /api/concept-suggestion-runs": overview(true, [run([])]),
      "GET /api/concept-suggestion-runs/7": () => {
        reads++;
        return { body: run(reads === 1 ? [item("open")] : [stale]) };
      },
      "POST /api/concept-suggestion-items/900/confirm": () => ({ status: 409, body: { error: "suggestion is stale", stale_reasons: ["unit_has_current_same"] } }),
    });
    render(<ConceptSuggestions />);
    fireEvent.click(await screen.findByRole("button", { name: /Run #7/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm SAME to Concept #40" }));
    expect(await screen.findByText(/The unit already has a CURRENT SAME/)).toBeInTheDocument();
    expect(screen.getByText("Stale: cannot be confirmed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Confirm SAME/ })).toBeNull();
    await waitFor(() => expect(reads).toBe(2));
  });

  it("refuses to send when browser storage cannot record the key", async () => {
    const calls = router(base);
    render(<ConceptSuggestions />);
    fireEvent.click((await screen.findAllByRole("checkbox"))[0]);
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate suggestions" }));
    expect(await screen.findByText(/Browser storage is unavailable.*Nothing was sent/)).toBeInTheDocument();
    spy.mockRestore();
    expect(writes(calls)).toHaveLength(0);
  });

  it("a same-key resend that finds a failed run says so, and retrying is an explicit new request with a new key", async () => {
    const oldKey = "11111111-2222-4333-8444-555555555555";
    window.localStorage.setItem("flh.concept-suggestion-requests.v1", JSON.stringify({ version: 1, pending: { operationId: oldKey, unitIds: [101] } }));
    let posts = 0;
    const calls = router({
      ...base,
      "POST /api/concept-suggestion-runs": () => {
        posts++;
        return posts === 1
          ? { status: 201, body: run([], { operation_id: oldKey, status: "failed", failure_code: "provider_timeout", unit_ids: [101] }) }
          : { status: 201, body: run([item("open")], { id: 8 }) };
      },
    });
    render(<ConceptSuggestions />);
    fireEvent.click(await screen.findByRole("button", { name: "Send the same request again" }));
    expect(await screen.findByText(/The model call failed/)).toBeInTheDocument();
    expect(screen.queryByText(/Suggestions stored as run/)).toBeNull();
    expect(screen.getByText(/This run failed \(provider_timeout\)/)).toBeInTheDocument();
    expect(writes(calls)).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Generate again as a new request" }));
    await screen.findByText("Suggestion run #8");
    const sent = writes(calls);
    expect(sent).toHaveLength(2);
    expect(sent[1].body).toEqual({ unit_ids: [101] });
    expect(sent[1].key).not.toBe(oldKey);
    expect(sent[1].storedAtSend).toContain(sent[1].key!);
  });

  it("a confirmation that was later corrected is shown as historical, not current", async () => {
    const superseded = item("confirmed", {
      confirmation: { id: 1, link_id: 77, created_at: "t", still_current: false },
      stale_reasons: ["unit_has_current_same"], current_concept_id: 12,
    });
    router({ ...base, "GET /api/concept-suggestion-runs": overview(true, [run([])]), "GET /api/concept-suggestion-runs/7": run([superseded]) });
    render(<ConceptSuggestions />);
    fireEvent.click(await screen.findByRole("button", { name: /Run #7/ }));
    expect(await screen.findByText(/no longer the unit's CURRENT SAME/)).toBeInTheDocument();
    expect(screen.queryByText(/The unit already has a CURRENT SAME/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Confirm SAME/ })).toBeNull();
  });
});
