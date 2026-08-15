import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ReviewQueue } from "./ReviewQueue";

afterEach(cleanup);

// routeFetch is a minimal router over the backend endpoints the queue touches on
// load, so we can render the component against realistic mocked data without a
// server. It matches the "/api"-prefixed paths the client builds.
function routeFetch(handlers: Record<string, unknown>) {
  return vi.fn(async (url: string | URL | Request) => {
    const path = new URL(String(url), "http://localhost").pathname;
    const body = handlers[path];
    const status = body === undefined ? 404 : 200;
    return new Response(body === undefined ? JSON.stringify({ error: "not found" }) : JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }) as unknown as typeof fetch;
}

// methodRouteFetch is a method-aware router used by the interaction tests. Handlers
// are keyed "METHOD /api/path" and may be a static body or a function of the parsed
// request body. The returned fetch also records each call so tests can assert exactly
// which endpoint a button invoked. GET reads default to a body only when registered.
function methodRouteFetch(
  handlers: Record<string, unknown | ((body: unknown) => { status?: number; body: unknown })>,
) {
  const calls: Array<{ method: string; path: string; body: unknown }> = [];
  const impl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const path = new URL(String(url), "http://localhost").pathname;
    const reqBody = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path, body: reqBody });
    const handler = handlers[`${method} ${path}`];
    if (handler === undefined) {
      return new Response(JSON.stringify({ error: "not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      });
    }
    const resolved = typeof handler === "function" ? (handler as (b: unknown) => { status?: number; body: unknown })(reqBody) : { body: handler };
    return new Response(JSON.stringify(resolved.body), {
      status: resolved.status ?? 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as unknown as typeof fetch;
  return { impl, calls };
}

// grammarUnit builds a reviewable unit fixture.
function reviewableUnitFixture(unitId: number) {
  return {
    unit_id: unitId,
    kind: "grammar",
    canonical: "vouloir + infinitif",
    statement: "On emploie vouloir suivi d'un infinitif.",
    example: "Je veux partir.",
    confidence: 0.91,
    candidate_identity: {
      target: "vouloir + infinitive",
      pedagogical_intent: "grammar",
      scope: "",
      identity_features: {},
    },
    signature: "{...}",
  };
}

function conceptFixture(id: number, target: string) {
  return {
    id,
    identity_schema_version: "fr_l2_concept_identity_v1",
    target,
    pedagogical_intent: "grammar",
    scope: "",
    identity_features: {},
    signature: "{...}",
    preferred_unit_id: null,
    state: "orphaned",
    lifecycle_state: "normal",
    support_state: "orphaned",
    created_at: "t",
    updated_at: "t",
  };
}

describe("ReviewQueue rendering", () => {
  it("renders the first reviewable unit with its French text and candidate identity", async () => {
    const unit = {
      unit_id: 5,
      kind: "grammar",
      canonical: "vouloir + infinitif",
      statement: "On emploie vouloir suivi d'un infinitif.",
      example: "Je veux partir.",
      confidence: 0.91,
      candidate_identity: {
        target: "vouloir + infinitive",
        pedagogical_intent: "grammar",
        scope: "",
        identity_features: {},
      },
      signature: "{...}",
    };
    globalThis.fetch = routeFetch({
      "/api/reviewable-units": { reviewable_units: [unit] },
      "/api/concepts": { concepts: [] },
      "/api/knowledge-units/5/concept-membership": { unit_id: 5, current_membership: null },
      "/api/knowledge-units/5/concept-resolution": {
        unit_id: 5,
        candidate_identity: unit.candidate_identity,
        signature: unit.signature,
        decision: "no_match",
        matches: [],
      },
    });

    render(<ReviewQueue />);

    // The unit's French statement and example render.
    expect(await screen.findByText("On emploie vouloir suivi d'un infinitif.")).toBeInTheDocument();
    expect(screen.getByText("Je veux partir.")).toBeInTheDocument();

    // The current membership authority shows "no current SAME membership" for an
    // unresolved unit, and the seven actions are present.
    await waitFor(() => {
      expect(screen.getByText(/No current SAME membership/i)).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /NEW CONCEPT/ })).toBeInTheDocument();
    expect(screen.getByText("BROADER")).toBeInTheDocument();
    expect(screen.getByText("INVALID")).toBeInTheDocument();

    // Position indicator shows we are on the first of one unit.
    expect(screen.getByText(/unit 1 of 1/)).toBeInTheDocument();
  });

  it("shows an empty state when nothing is awaiting review", async () => {
    globalThis.fetch = routeFetch({
      "/api/reviewable-units": { reviewable_units: [] },
      "/api/concepts": { concepts: [] },
    });
    render(<ReviewQueue />);
    expect(await screen.findByText(/No units are awaiting review/)).toBeInTheDocument();
  });
});

describe("ReviewQueue milestone 10.6 actions", () => {
  it("enables INVALID for a freshly unresolved unit and calls the unit-level endpoint, advancing the queue", async () => {
    const unit = reviewableUnitFixture(5);
    const { impl, calls } = methodRouteFetch({
      "GET /api/reviewable-units": { reviewable_units: [unit] },
      "GET /api/concepts": { concepts: [] },
      "GET /api/knowledge-units/5/concept-membership": { unit_id: 5, current_membership: null },
      "GET /api/knowledge-units/5/concept-resolution": {
        unit_id: 5,
        candidate_identity: unit.candidate_identity,
        signature: unit.signature,
        decision: "no_match",
        matches: [],
      },
      "POST /api/knowledge-units/5/invalid": {
        unit_id: 5,
        invalid: true,
        current_membership: null,
        judgment: { id: 1, unit_id: 5, judgment: "invalid", decision_source: "human", note: "", evidence: "{}", created_at: "t" },
      },
    });
    globalThis.fetch = impl;

    render(<ReviewQueue />);
    await screen.findByText("On emploie vouloir suivi d'un infinitif.");

    // INVALID is enabled even though the unresolved unit has no membership.
    const invalidBtn = screen.getByRole("button", { name: "INVALID" });
    expect(invalidBtn).toBeEnabled();

    fireEvent.click(invalidBtn);

    // It calls the dedicated unit-level endpoint (NOT the membership-level reject).
    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.path === "/api/knowledge-units/5/invalid")).toBe(true);
    });
    expect(calls.some((c) => c.path === "/api/knowledge-units/5/concept-membership/reject")).toBe(false);

    // The queue advances: the only unit is removed and the empty state shows.
    expect(await screen.findByText(/No units are awaiting review/)).toBeInTheDocument();
  });

  it("keeps an unresolved unit in the queue after DISTINCT, then lets NEW CONCEPT resolve it", async () => {
    const unit = reviewableUnitFixture(5);
    const candidate = conceptFixture(42, "vouloir + infinitive");
    const { impl, calls } = methodRouteFetch({
      "GET /api/reviewable-units": { reviewable_units: [unit] },
      "GET /api/concepts": { concepts: [] },
      "GET /api/knowledge-units/5/concept-membership": { unit_id: 5, current_membership: null },
      // A single exact-signature match is returned and auto-selected, enabling DISTINCT.
      "GET /api/knowledge-units/5/concept-resolution": {
        unit_id: 5,
        candidate_identity: unit.candidate_identity,
        signature: unit.signature,
        decision: "matched",
        matches: [candidate],
      },
      "POST /api/knowledge-units/5/concept-distinctions": {
        id: 3,
        unit_id: 5,
        concept_id: 42,
        decision_source: "human",
        resolver_version: "concept_resolver_v1",
        evidence: "{}",
        created_at: "t",
      },
      // Creating a NEW concept seeds SAME for the (still unresolved) unit.
      "POST /api/concepts": { concept: conceptFixture(99, "vouloir + infinitive"), link: { id: 20, unit_id: 5, concept_id: 99, relation: "same", status: "accepted" } },
    });
    globalThis.fetch = impl;

    render(<ReviewQueue />);
    await screen.findByText("On emploie vouloir suivi d'un infinitif.");

    // The lone candidate is auto-selected, so DISTINCT is enabled.
    const distinctBtn = await screen.findByRole("button", { name: "DISTINCT" });
    await waitFor(() => expect(distinctBtn).toBeEnabled());

    fireEvent.click(distinctBtn);

    // DISTINCT is recorded against the selected concept.
    await waitFor(() => {
      const d = calls.find((c) => c.method === "POST" && c.path === "/api/knowledge-units/5/concept-distinctions");
      expect(d).toBeTruthy();
      expect(d?.body).toEqual({ concept_id: 42 });
    });

    // The unit is NOT removed from the queue: still on "unit 1 of 1".
    expect(screen.getByText(/unit 1 of 1/)).toBeInTheDocument();
    expect(screen.queryByText(/No units are awaiting review/)).not.toBeInTheDocument();

    // NEW CONCEPT after DISTINCT still works and resolves the unit (seeds SAME),
    // advancing the queue.
    const newBtn = screen.getByRole("button", { name: /NEW CONCEPT/ });
    fireEvent.click(newBtn);

    await waitFor(() => {
      const created = calls.find((c) => c.method === "POST" && c.path === "/api/concepts");
      expect(created).toBeTruthy();
      // Seeds SAME because the unit is unresolved.
      expect((created?.body as { link_seed_as_same: boolean }).link_seed_as_same).toBe(true);
    });
    expect(await screen.findByText(/No units are awaiting review/)).toBeInTheDocument();
  });
});

describe("ReviewQueue milestone 10.7 candidate discovery", () => {
  it("keeps exact matches separate, deduplicates them, and filters the searchable catalog", async () => {
    const unit = reviewableUnitFixture(5);
    const exact = conceptFixture(42, "vouloir + infinitive");
    const orphaned = {
      ...conceptFixture(43, "Être au Québec"),
      pedagogical_intent: "vocabulary",
      scope: "travel",
    };
    const retired = {
      ...conceptFixture(44, "Être Québec retired"),
      state: "retired",
      lifecycle_state: "retired",
    };
    globalThis.fetch = routeFetch({
      "/api/reviewable-units": { reviewable_units: [unit] },
      "/api/concepts": { concepts: [exact, orphaned, retired] },
      "/api/knowledge-units/5/concept-membership": { unit_id: 5, current_membership: null },
      "/api/knowledge-units/5/concept-resolution": {
        unit_id: 5,
        candidate_identity: unit.candidate_identity,
        signature: unit.signature,
        decision: "matched",
        matches: [exact],
      },
    });

    render(<ReviewQueue />);

    expect(await screen.findByRole("heading", { name: "Exact identity matches" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Search existing concepts" })).toBeInTheDocument();
    expect(screen.getByText(/Retrieval-only catalog search/i)).toBeInTheDocument();

    // The search is seeded from the candidate target, but the exact concept appears
    // only in the exact section even though it is also present in the catalog.
    const search = screen.getByRole("searchbox", { name: "Search existing concepts" });
    expect(search).toHaveValue("vouloir + infinitive");
    expect(await screen.findAllByText("vouloir + infinitive")).toHaveLength(1);

    // The reviewer can replace the query. Accent-insensitive discovery exposes the
    // orphaned durable identity, while a retired matching concept stays hidden.
    fireEvent.change(search, { target: { value: "etre quebec" } });
    expect(await screen.findByText("Être au Québec")).toBeInTheDocument();
    expect(screen.queryByText("Être Québec retired")).not.toBeInTheDocument();

    // Exact and discovery cards share one logical selection: choosing the
    // discovery result deselects the auto-selected exact match, and vice versa.
    const discoverySelect = screen.getByRole("button", { name: "select this concept" });
    fireEvent.click(discoverySelect);
    expect(discoverySelect).toHaveAttribute("aria-pressed", "true");
    const exactSelect = screen.getByRole("button", { name: "select this concept" });
    fireEvent.click(exactSelect);
    expect(exactSelect).toHaveAttribute("aria-pressed", "true");
    expect(discoverySelect).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(screen.getByRole("button", { name: "clear" }));
    expect(search).toHaveValue("");
  });

  it.each([
    {
      actionName: "SAME → selected",
      path: "/api/knowledge-units/5/concept-links/same",
      body: { concept_id: 77 },
      response: { id: 10, unit_id: 5, concept_id: 77, relation: "same", status: "accepted" },
    },
    {
      actionName: "DISTINCT",
      path: "/api/knowledge-units/5/concept-distinctions",
      body: { concept_id: 77 },
      response: { id: 11, unit_id: 5, concept_id: 77 },
    },
    {
      actionName: "BROADER",
      path: "/api/knowledge-units/5/concept-links/relation",
      body: { concept_id: 77, relation: "broader" },
      response: { id: 12, unit_id: 5, concept_id: 77, relation: "broader", status: "accepted" },
    },
  ])("routes explicit $actionName from a discovery selection through the existing endpoint", async ({
    actionName,
    path,
    body,
    response,
  }) => {
    const unit = reviewableUnitFixture(5);
    const discovered = conceptFixture(77, "vouloir + infinitive usage");
    const { impl, calls } = methodRouteFetch({
      "GET /api/reviewable-units": { reviewable_units: [unit] },
      "GET /api/concepts": { concepts: [discovered] },
      "GET /api/knowledge-units/5/concept-membership": { unit_id: 5, current_membership: null },
      "GET /api/knowledge-units/5/concept-resolution": {
        unit_id: 5,
        candidate_identity: unit.candidate_identity,
        signature: unit.signature,
        decision: "no_match",
        matches: [],
      },
      [`POST ${path}`]: response,
    });
    globalThis.fetch = impl;

    render(<ReviewQueue />);

    const select = await screen.findByRole("button", { name: "select this concept" });
    expect(select).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "SAME → selected" })).toBeDisabled();
    expect(calls.every((call) => call.method === "GET")).toBe(true);

    // Displaying and selecting retrieval candidates creates no annotation authority.
    fireEvent.click(select);
    expect(select).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "SAME → selected" })).toBeEnabled();
    expect(calls.every((call) => call.method === "GET")).toBe(true);

    // The same selectedConceptId drives the pre-existing explicit action route.
    fireEvent.click(screen.getByRole("button", { name: actionName }));
    await waitFor(() => {
      const write = calls.find((call) => call.method === "POST" && call.path === path);
      expect(write?.body).toEqual(body);
    });
  });
});
