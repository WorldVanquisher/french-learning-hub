import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PublicDemoApp from "../PublicDemoApp";

// Failure cases for the public demo's reads: each test holds chosen responses
// back and releases them in a chosen order, so the regression is reproducible.

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const info = {
  schema_version: "knowledge_library_public_demo_v1", read_only: true, data: "synthetic",
  artifact: { version: "v", manifest_sha256: "m", vector_source: "mechanical-test", real_model: false, vector_generator: "flh073_mechanical_hash_v1",
    model_id: "flh073-mechanical-hash@1", dimensions: 64, document_representation: "d", query_representation: "q", release_status: "blocked_mechanical_vectors",
    notice: "n", domain_fingerprint_sha256: "f" },
  query_policy: "p", presets: [], counters: { preset_vector_lookups: 0, refused_vector_lookups: 0 },
};
const concept = (id: number, target: string) => ({
  id, identity_schema_version: "fr_l2_concept_identity_v1", target, pedagogical_intent: "grammar", scope: "",
  identity_features: {}, signature: "{}", preferred_unit_id: null, state: "active", lifecycle_state: "normal",
  support_state: "supported", created_at: "t", updated_at: "t",
});
const search = (q: string, hits: Array<[number, string]>) => ({
  schema_version: "knowledge_library_search_v1", query: q, tokens: [], state: "all", limit: 20, total_matches: hits.length, truncated: false,
  results: hits.map(([id, target]) => ({ concept: concept(id, target), match_tier: "identity", matched_fields: ["target"], current_member_count: 1, supporting_unit_count: 1 })),
});
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

// A fetch whose answers wait until the test releases them by key.
function heldServer(answer: (path: string, q: string | null) => Response) {
  const held = new Map<string, Array<() => void>>();
  const hold = new Set<string>();
  globalThis.fetch = vi.fn(async (input: string | URL | Request) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname.replace(/^\/api/, "");
    const key = `${path}?${url.searchParams.get("q") ?? ""}`;
    if (hold.has(key)) await new Promise<void>((resolve) => held.set(key, [...(held.get(key) ?? []), resolve]));
    return answer(path, url.searchParams.get("q"));
  }) as unknown as typeof fetch;
  return {
    hold: (key: string) => hold.add(key),
    release: async (key: string) => {
      hold.delete(key);
      await act(async () => {
        for (const r of held.get(key) ?? []) r();
        held.delete(key);
      });
    },
  };
}

describe("Public demo resilience", () => {
  it("states a failed demo description with its status and recovers on Try again without a reload", async () => {
    let fail = true;
    heldServer((path, q) => {
      if (path === "/knowledge-library/demo") return fail ? json(503, { error: "unavailable" }) : json(200, info);
      if (path === "/knowledge-library/concepts") return json(200, search(q ?? "", []));
      return json(404, { error: "not available" });
    });
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The demo is unavailable: (503) unavailable");
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("button", { name: /One question, two pronouns/ })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("never lets an older, slower search answer replace a newer one", async () => {
    const server = heldServer((path, q) => {
      if (path === "/knowledge-library/demo") return json(200, info);
      if (path === "/knowledge-library/concepts")
        return json(200, q === "pronouns" ? search(q, [[12, "the pronouns y and en"]]) : q === "train" ? search(q, [[14, "« être en train de »"]]) : search(q ?? "", []));
      return json(404, { error: "not available" });
    });
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    const input = await screen.findByLabelText("Search learned material");
    server.hold("/knowledge-library/concepts?pronouns");
    fireEvent.change(input, { target: { value: "pronouns" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    fireEvent.change(input, { target: { value: "train" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByRole("button", { name: "« être en train de »" })).toBeInTheDocument();
    await server.release("/knowledge-library/concepts?pronouns");
    expect(screen.queryByRole("button", { name: "the pronouns y and en" })).toBeNull();
    expect(screen.getByText(/1 concept matching “train”/)).toBeInTheDocument();
  });

  it("shows the example chosen last when an earlier one answers late", async () => {
    const server = heldServer((path, q) => {
      if (path === "/knowledge-library/demo") return json(200, info);
      if (path === "/knowledge-library/concepts") return json(200, search(q ?? "", []));
      return json(404, { error: "not available" });
    });
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    server.hold("/knowledge-library/concepts?pronouns");
    fireEvent.click(await screen.findByRole("button", { name: /One question, two pronouns/ }));
    fireEvent.click(await screen.findByRole("button", { name: "One question, two Concepts" }));
    // The later example has no data in this server, so it says so.
    expect(await screen.findByText("This example is not part of this demo build.")).toBeInTheDocument();
    await server.release("/knowledge-library/concepts?pronouns");
    await waitFor(() => expect(screen.getByRole("heading", { level: 2, name: "One question, two Concepts" })).toBeInTheDocument());
    expect(screen.queryByRole("heading", { level: 2, name: "One question, two pronouns" })).toBeNull();
  });
});
