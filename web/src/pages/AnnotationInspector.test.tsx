import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnnotationInspector } from "./AnnotationInspector";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function concept(id: number, target: string, intent: string) {
  return {
    id,
    identity_schema_version: "fr_l2_concept_identity_v1",
    target,
    pedagogical_intent: intent,
    scope: "",
    identity_features: {},
    signature: `signature-${id}`,
    preferred_unit_id: null,
    state: "active",
    lifecycle_state: "normal",
    support_state: "supported",
    created_at: "2026-08-01T12:00:00Z",
    updated_at: "2026-08-01T12:00:00Z",
  };
}

function unit(id: number, canonical: string) {
  return {
    id,
    extraction_id: 10,
    ordinal: id,
    kind: "grammar",
    canonical,
    statement: `Statement for ${canonical}`,
    example: null,
    confidence: 0.9,
    created_at: "2026-08-01T12:00:00Z",
  };
}

function link(id: number, unitId: number, conceptId: number, relation: string, source = "human") {
  return {
    id,
    unit_id: unitId,
    concept_id: conceptId,
    relation,
    status: "accepted",
    decision_source: source,
    resolver_version: source === "resolver:automatic" ? "concept_resolver_v1" : "",
    score: source === "resolver:automatic" ? 1 : null,
    evidence: "{}",
    supersedes_link_id: null,
    created_at: "2026-08-01T12:00:00Z",
  };
}

const items = [
  {
    unit: unit(1, "conditionnel présent"),
    snapshot: {
      unit_id: 1,
      status: "resolved",
      latest_unit_judgment: null,
      current_same: {
        membership: { concept_id: 20, link_id: 501, updated_at: "2026-08-01T12:00:00Z" },
        decision: link(501, 1, 20, "same", "human"),
      },
      distinctions: [],
      relations: [],
    },
  },
  {
    unit: unit(2, "futur simple"),
    snapshot: {
      unit_id: 2,
      status: "resolved",
      latest_unit_judgment: null,
      current_same: {
        membership: { concept_id: 21, link_id: 502, updated_at: "2026-08-01T12:00:00Z" },
        decision: link(502, 2, 21, "same", "resolver:automatic"),
      },
      distinctions: [],
      relations: [],
    },
  },
  {
    unit: unit(3, "formes comparées"),
    snapshot: {
      unit_id: 3,
      status: "unresolved",
      latest_unit_judgment: null,
      current_same: null,
      distinctions: [{
        id: 601,
        unit_id: 3,
        concept_id: 22,
        decision_source: "human",
        resolver_version: "",
        evidence: "{}",
        created_at: "2026-08-01T12:00:00Z",
      }],
      relations: [
        link(701, 3, 23, "broader"),
        link(702, 3, 24, "narrower"),
        link(703, 3, 999, "related"),
      ],
    },
  },
  {
    unit: unit(4, "fragment invalide"),
    snapshot: {
      unit_id: 4,
      status: "invalid",
      latest_unit_judgment: {
        id: 801,
        unit_id: 4,
        judgment: "invalid",
        decision_source: "human",
        note: "Not a learnable unit",
        evidence: "{}",
        created_at: "2026-08-01T12:00:00Z",
      },
      current_same: null,
      distinctions: [],
      relations: [],
    },
  },
];

function inspectorFetch() {
  const calls: Array<{ method: string; path: string }> = [];
  const impl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const path = new URL(String(url), "http://localhost").pathname;
    calls.push({ method, path });
    const body = path === "/api/effective-annotations"
      ? { effective_annotations: items }
      : path === "/api/concepts"
        ? { concepts: [
          concept(20, "conditionnel présent", "polite request"),
          concept(21, "futur simple", "future event"),
          concept(22, "formation du conditionnel", "form contrast"),
          concept(23, "modes verbaux", "category"),
          concept(24, "conditionnel passé", "past hypothetical"),
        ] }
        : { error: "not found" };
    return new Response(JSON.stringify(body), {
      status: "error" in body ? 404 : 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as unknown as typeof fetch;
  return { impl, calls };
}

describe("AnnotationInspector", () => {
  it("renders effective statuses, provenance, concepts, DISTINCT, and relations using GET only", async () => {
    const { impl, calls } = inspectorFetch();
    globalThis.fetch = impl;

    render(<AnnotationInspector />);

    expect(screen.getByText("Loading effective annotations…")).toBeInTheDocument();
    const humanCard = await screen.findByRole("article", { name: "Unit #1" });
    const automaticCard = screen.getByRole("article", { name: "Unit #2" });
    const unresolvedCard = screen.getByRole("article", { name: "Unit #3" });
    const invalidCard = screen.getByRole("article", { name: "Unit #4" });

    expect(within(humanCard).getByText("resolved")).toBeInTheDocument();
    expect(within(humanCard).getAllByText("conditionnel présent")).toHaveLength(2);
    expect(within(humanCard).getByText(/polite request/)).toBeInTheDocument();
    expect(within(humanCard).getByText("human")).toBeInTheDocument();
    expect(within(humanCard).getByText("event #501")).toBeInTheDocument();

    expect(within(automaticCard).getByText("resolved")).toBeInTheDocument();
    expect(within(automaticCard).getByText("resolver:automatic")).toBeInTheDocument();
    expect(within(unresolvedCard).getByText("unresolved")).toBeInTheDocument();
    expect(within(unresolvedCard).getAllByText(/DISTINCT/)).toHaveLength(2);
    expect(within(unresolvedCard).getByText(/formation du conditionnel/)).toBeInTheDocument();
    expect(within(unresolvedCard).getByText(/BROADER/)).toBeInTheDocument();
    expect(within(unresolvedCard).getByText(/NARROWER/)).toBeInTheDocument();
    expect(within(unresolvedCard).getByText(/RELATED/)).toBeInTheDocument();
    expect(within(unresolvedCard).getByText("Concept #999")).toBeInTheDocument();
    expect(within(invalidCard).getByText("invalid")).toBeInTheDocument();
    expect(within(invalidCard).getByText("Not a learnable unit")).toBeInTheDocument();

    expect(calls.map((call) => call.path).sort()).toEqual([
      "/api/concepts",
      "/api/effective-annotations",
    ]);
    expect(calls.every((call) => call.method === "GET")).toBe(true);
  });

  it("filters locally by status and CURRENT SAME source without additional requests", async () => {
    const { impl, calls } = inspectorFetch();
    globalThis.fetch = impl;
    render(<AnnotationInspector />);
    await screen.findByRole("article", { name: "Unit #1" });

    fireEvent.change(screen.getByLabelText("Annotation status"), { target: { value: "invalid" } });
    expect(screen.getByRole("article", { name: "Unit #4" })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Unit #1" })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Annotation status"), { target: { value: "all" } });
    fireEvent.change(screen.getByLabelText("CURRENT SAME source"), { target: { value: "automatic" } });
    expect(screen.getByRole("article", { name: "Unit #2" })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Unit #1" })).not.toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Unit #3" })).not.toBeInTheDocument();

    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls.every((call) => call.method === "GET")).toBe(true);
  });

  it("surfaces backend projection corruption instead of hiding it", async () => {
    globalThis.fetch = vi.fn(async (url: string | URL | Request) => {
      const path = new URL(String(url), "http://localhost").pathname;
      if (path === "/api/effective-annotations") {
        return new Response(JSON.stringify({ error: "effective annotation is internally inconsistent" }), {
          status: 500,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ concepts: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as unknown as typeof fetch;

    render(<AnnotationInspector />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "effective annotation is internally inconsistent",
    );
  });
});
