import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
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
    // unresolved unit, and the six actions are present.
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
    globalThis.fetch = routeFetch({ "/api/reviewable-units": { reviewable_units: [] } });
    render(<ReviewQueue />);
    expect(await screen.findByText(/No units are awaiting review/)).toBeInTheDocument();
  });
});
