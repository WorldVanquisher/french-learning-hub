import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PublicDemoApp from "../PublicDemoApp";
import { hashForScreen, screenFromHash } from "./deepLink";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("demo direct links (URL fragments)", () => {
  it("reads examples, Concepts and evidence, with or without the example they came from", () => {
    expect(screenFromHash("#example=y-en")).toEqual({ kind: "example", example: "y-en" });
    expect(screenFromHash("#concept=12")).toEqual({ kind: "concept", conceptId: 12, from: undefined });
    expect(screenFromHash("#example=y-en&concept=12")).toEqual({ kind: "concept", conceptId: 12, from: "y-en" });
    expect(screenFromHash("#example=y-en&concept=12&unit=14")).toEqual({ kind: "source", conceptId: 12, unitId: 14, from: "y-en" });
    expect(screenFromHash("")).toEqual({ kind: "results" });
  });

  it("opens the start for anything malformed or unknown", () => {
    for (const bad of ["#concept=abc", "#concept=0", "#concept=-3", "#concept=1.5", "#unit=5", "#concept=12&unit=x", "#example=nope", "#example=nope&concept=12", "#concept=1234567890"]) {
      expect(screenFromHash(bad), bad).toEqual({ kind: "results" });
    }
  });

  it("writes the same fragments back, and none for the start", () => {
    for (const hash of ["#example=y-en", "#concept=12", "#example=y-en&concept=12", "#example=y-en&concept=12&unit=14", "#concept=12&unit=14"]) {
      expect(hashForScreen(screenFromHash(hash))).toBe(hash);
    }
    expect(hashForScreen({ kind: "results" })).toBe("");
  });

  it("names a comparison's practice question only when it has that question (R3-056)", () => {
    expect(screenFromHash("#compare=imparfait-passe-compose&practice=2")).toEqual({ kind: "compare", compare: "imparfait-passe-compose", practice: 2 });
    expect(screenFromHash("#compare=present-en-train-de&practice=1")).toEqual({ kind: "compare", compare: "present-en-train-de", practice: 1 });
    // A question the comparison does not have, or none at all, is left out: the pair.
    for (const hash of [
      "#compare=present-en-train-de&practice=2",
      "#compare=imparfait-passe-compose&practice=0",
      "#compare=imparfait-passe-compose&practice=x",
      "#compare=imparfait-passe-compose&practice=",
      "#compare=imparfait-passe-compose&practice=10",
      "#compare=depuis-pendant&practice=1",
    ])
      expect(screenFromHash(hash), hash).toEqual({ kind: "compare", compare: hash.slice(9, hash.indexOf("&")) });
    // Without a comparison it names nothing.
    expect(screenFromHash("#practice=1")).toEqual({ kind: "results" });
    expect(screenFromHash("#example=y-en&practice=1")).toEqual({ kind: "example", example: "y-en" });
    // A Concept or source opened from a question returns to it.
    expect(screenFromHash("#compare=imparfait-passe-compose&practice=2&concept=6&unit=7")).toEqual({
      kind: "source",
      conceptId: 6,
      unitId: 7,
      from: undefined,
      compare: "imparfait-passe-compose",
      comparePractice: 2,
    });
    for (const hash of [
      "#compare=imparfait-passe-compose&practice=1",
      "#compare=imparfait-passe-compose&practice=2&concept=6",
      "#compare=imparfait-passe-compose&practice=2&concept=6&unit=7",
      "#compare=present-en-train-de&practice=1&concept=13&unit=15",
    ])
      expect(hashForScreen(screenFromHash(hash)), hash).toBe(hash);
  });
});

const info = {
  schema_version: "knowledge_library_public_demo_v1", read_only: true, data: "synthetic",
  artifact: { version: "v", manifest_sha256: "m", vector_source: "mechanical-test", real_model: false, vector_generator: "g",
    model_id: "m", dimensions: 64, document_representation: "d", query_representation: "q", release_status: "blocked_mechanical_vectors",
    notice: "n", domain_fingerprint_sha256: "f" },
  query_policy: "p", presets: [], counters: { preset_vector_lookups: 0, refused_vector_lookups: 0 },
};
const concept = { id: 12, identity_schema_version: "fr_l2_concept_identity_v1", target: "the pronouns y and en", pedagogical_intent: "grammar",
  scope: "", identity_features: {}, signature: "{}", preferred_unit_id: null, state: "active", lifecycle_state: "normal",
  support_state: "supported", created_at: "t", updated_at: "t" };

function server() {
  const urls: string[] = [];
  globalThis.fetch = vi.fn(async (input: string | URL | Request) => {
    const url = new URL(String(input), "http://localhost");
    urls.push(`${url.pathname}${url.search}${url.hash}`);
    const path = url.pathname.replace(/^\/api/, "");
    const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    if (path === "/knowledge-library/demo") return reply(200, info);
    if (path === "/knowledge-library/concepts")
      return reply(200, { schema_version: "knowledge_library_search_v1", query: "", tokens: [], state: "all", limit: 20, total_matches: 0, truncated: false, results: [] });
    if (path === "/knowledge-library/concepts/12")
      return reply(200, { schema_version: "knowledge_library_concept_v1", concept, preferred_unit: null, supporting_units: [], non_supporting_members: [],
        current_relations: [], historical_units: [], history_event_count: 0 });
    return reply(404, { error: "not found" });
  }) as unknown as typeof fetch;
  return urls;
}

describe("Public demo direct links", () => {
  it("opens a linked Concept, writes the start's address on the way back, and sends no fragment", async () => {
    const urls = server();
    window.history.replaceState(null, "", "/#concept=12");
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    expect(await screen.findByRole("heading", { level: 2, name: /the pronouns y and en/ })).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("navigation", { name: "Return" })).getByRole("button"));
    expect(await screen.findByRole("button", { name: /One question, two pronouns/ })).toBeInTheDocument();
    expect(window.location.hash).toBe("");
    fireEvent.click(screen.getByRole("button", { name: /One question, two pronouns/ }));
    expect(window.location.hash).toBe("#example=y-en");
    expect(urls.every((u) => !u.includes("#") && !/[?&](concept|unit|example)=/.test(u))).toBe(true);
  });

  it("says a linked Concept is not in this demo, keeps the return bar and offers no retry", async () => {
    server();
    window.history.replaceState(null, "", "/#concept=404");
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    expect(await screen.findByText(/This link names Concept #404, which this demo build does not have/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
    expect(within(screen.getByRole("navigation", { name: "Return" })).getByRole("button")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open the example “One question, two Concepts”" })).toBeInTheDocument();
  });
});
