import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("App annotation views", () => {
  it("opens the Learning Records view with GET requests only", async () => {
    const calls: Array<{ method: string; path: string }> = [];
    globalThis.fetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      const method = (init?.method ?? "GET").toUpperCase();
      const path = new URL(String(url), "http://localhost").pathname;
      calls.push({ method, path });
      const body = path === "/api/reviewable-units"
        ? { reviewable_units: [] }
        : path === "/api/learning-records"
          ? { records: [], next_before_entry_id: null }
          : { concepts: [] };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as unknown as typeof fetch;

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Learning Records" }));

    expect(await screen.findByRole("heading", { name: "Learning Records" })).toBeInTheDocument();
    expect(await screen.findByText(/No learning records exist yet/)).toBeInTheDocument();
    expect(calls.some((call) => call.path === "/api/learning-records")).toBe(true);
    expect(calls.every((call) => call.method === "GET")).toBe(true);
  });

  it("opens the read-only inspector through the local view switch", async () => {
    const calls: Array<{ method: string; path: string }> = [];
    globalThis.fetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      const method = (init?.method ?? "GET").toUpperCase();
      const path = new URL(String(url), "http://localhost").pathname;
      calls.push({ method, path });
      const body = path === "/api/reviewable-units"
        ? { reviewable_units: [] }
        : path === "/api/effective-annotations"
          ? { effective_annotations: [] }
          : { concepts: [] };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as unknown as typeof fetch;

    render(<App />);
    expect(screen.getByRole("heading", { name: "Concept Review" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Annotation Inspector" }));

    expect(
      await screen.findByRole("heading", { name: "Effective Annotation Inspector" }),
    ).toBeInTheDocument();
    expect(await screen.findByText(/No KnowledgeUnits exist in the current extraction/)).toBeInTheDocument();
    expect(calls.some((call) => call.path === "/api/effective-annotations")).toBe(true);
    expect(calls.every((call) => call.method === "GET")).toBe(true);
  });

  it("opens the read-only Experiment Dashboard through the third tab", async () => {
    const calls: Array<{ method: string; path: string }> = [];
    globalThis.fetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      const method = (init?.method ?? "GET").toUpperCase();
      const path = new URL(String(url), "http://localhost").pathname;
      calls.push({ method, path });

      let body: unknown;
      if (path === "/api/reviewable-units") {
        body = { reviewable_units: [] };
      } else if (path === "/api/concepts") {
        body = { concepts: [] };
      } else if (path === "/api/annotation-dataset/v1/quality") {
        body = {
          schema_version: "concept_annotation_quality_report_v1",
          dataset_schema_version: "concept_annotation_dataset_v1",
          valid: true,
          error_count: 0,
          warning_count: 0,
          summary: {
            total_records: 0,
            total_entries: 0,
            total_extractions: 0,
            total_referenced_concepts: 0,
            effective_status: { resolved: 0, unresolved: 0, invalid: 0 },
            admission_effective: { active: 0, suppressed: 0, needs_review: 0 },
            authority: { resolved_human_same: 0, resolved_automatic_same: 0 },
          },
          label_inventory: {
            records_with_any_human_label: 0,
            records_without_human_label: 0,
            human_same_records: 0,
            human_distinct_pairs: 0,
            human_relations: { broader: 0, narrower: 0, related: 0 },
            human_invalid_records: 0,
            unlabeled_unresolved_records: 0,
            automatic_same_only_records: 0,
          },
          provenance: {
            extractors: [],
            concept_identity_schema_versions: [],
            human_label_resolver_versions: [],
          },
          leakage_risk: {
            entries_with_multiple_records: 0,
            max_records_per_entry: 0,
            human_same_concepts: 0,
            human_same_concepts_with_multiple_units: 0,
            human_same_concepts_spanning_multiple_entries: 0,
            max_units_per_human_same_concept: 0,
          },
          issues: [],
        };
      } else {
        body = {
          schema_version: "concept_retrieval_comparison_v1",
          state: "evaluated",
          dataset_valid: true,
          candidate_universe: { concepts: 0 },
          evaluation_samples: { eligible_samples: 0 },
          retrievers: [],
        };
      }
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as unknown as typeof fetch;

    render(<App />);
    expect(screen.getByRole("button", { name: "Concept Review" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Annotation Inspector" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Experiment Dashboard" }));

    expect(
      await screen.findByRole("heading", { name: "Experiment Dashboard" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("No structural dataset errors were reported.")).toBeInTheDocument();
    expect(calls.some((call) => call.path === "/api/annotation-dataset/v1/quality")).toBe(true);
    expect(calls.some((call) => call.path === "/api/retrieval-comparison/v1")).toBe(true);
    expect(calls.every((call) => call.method === "GET")).toBe(true);
  });
});

// FLH-089/FLH-090: the general Concept Review queue resumes where the reviewer
// left it, through bounded pages and the backend's from_unit_id locator.
describe("App Concept Review position across views", () => {
  const unit = (id: number) => ({
    unit_id: id, kind: "grammar", canonical: `canonical ${id}`, statement: `statement ${id}`, example: null,
    confidence: 0.9, signature: "{}", entry_id: 1,
    candidate_identity: { target: `target ${id}`, pedagogical_intent: "grammar", scope: "", identity_features: {} },
  });
  // A paging-aware fake of GET /reviewable-units over ascending unit IDs (one entry,
  // ordinal = position): honours limit, after (opaque "1.<ordinal>.<id>") and
  // from_unit_id (inclusive position, even for a unit no longer listed).
  type QueueState = { units: number[]; failQueue?: boolean; hold?: Promise<void> | null };
  function serve(state: QueueState) {
    const calls: string[] = [];
    globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const path = url.pathname;
      calls.push(`${(init?.method ?? "GET").toUpperCase()} ${path}${url.search}`);
      const membership = path.match(/^\/api\/knowledge-units\/(\d+)\/concept-membership$/);
      const resolution = path.match(/^\/api\/knowledge-units\/(\d+)\/concept-resolution$/);
      let status = 200;
      let body: unknown = { concepts: [] };
      if (path === "/api/reviewable-units") {
        if (state.hold && url.searchParams.has("after")) await state.hold;
        if (state.failQueue) {
          status = 500;
          body = { error: "queue unavailable" };
        } else {
          const limit = Number(url.searchParams.get("limit") ?? "50");
          const after = url.searchParams.get("after");
          const from = url.searchParams.get("from_unit_id");
          const list = [...state.units].sort((a, b) => a - b);
          const startAt = after !== null
            ? list.findIndex((id) => id > Number(after.split(".")[2]))
            : from !== null
              ? list.findIndex((id) => id >= Number(from))
              : 0;
          const rest = startAt < 0 ? [] : list.slice(startAt);
          const pageIds = rest.slice(0, limit);
          const last = pageIds[pageIds.length - 1];
          body = {
            reviewable_units: pageIds.map(unit),
            next_cursor: rest.length > limit ? `1.${last}.${last}` : null,
            limit,
          };
        }
      } else if (membership) body = { unit_id: Number(membership[1]), current_membership: null };
      else if (resolution) body = { unit_id: Number(resolution[1]), candidate_identity: unit(1).candidate_identity, signature: "{}", decision: "no_match", matches: [] };
      else if (/\/concept-distinctions$/.test(path)) body = { distinctions: [] };
      else if (path.startsWith("/api/annotation-dataset") || path.startsWith("/api/retrieval")) {
        status = 404;
        body = { error: "not in this test" };
      }
      return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    }) as unknown as typeof fetch;
    return calls;
  }
  const queueReads = (calls: string[]) => calls.filter((c) => c.startsWith("GET /api/reviewable-units"));
  const leaveAndReturn = async () => {
    fireEvent.click(screen.getByRole("button", { name: "Experiment Dashboard" }));
    fireEvent.click(screen.getByRole("button", { name: "Concept Review" }));
  };
  const skip = () => fireEvent.click(screen.getByRole("button", { name: "skip →" }));

  it("restores the unit and the catalog search after switching views, re-reading one page from that unit", async () => {
    const calls = serve({ units: [11, 12, 13, 14, 15] });
    render(<App />);
    expect(await screen.findByText("unit 1 of 5")).toBeInTheDocument();
    skip();
    skip();
    expect(screen.getByText("unit 3 of 5")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "subjonctif" } });

    await leaveAndReturn();
    expect(await screen.findByText("canonical 13")).toBeInTheDocument();
    // The window now starts at unit 13; earlier units are not loaded, and the text says so.
    expect(screen.getByText("unit 1 of 3 loaded from where you left off; earlier units are not loaded")).toBeInTheDocument();
    expect(screen.getByRole("searchbox")).toHaveValue("subjonctif");
    // The queue is backend authority: re-read with the bounded locator, never scanned.
    expect(queueReads(calls)).toEqual(["GET /api/reviewable-units?limit=50", "GET /api/reviewable-units?limit=50&from_unit_id=13"]);
    expect(screen.queryByText(/no longer awaiting review/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Start from the beginning of the queue" }));
    expect(await screen.findByText("unit 1 of 5")).toBeInTheDocument();
    expect(screen.getByText("canonical 11")).toBeInTheDocument();
  });

  it("continues with the next unit in queue order, and says so, when the unit left the queue meanwhile", async () => {
    const state = { units: [11, 12, 13, 14, 15] };
    serve(state);
    render(<App />);
    await screen.findByText("unit 1 of 5");
    skip();
    skip();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "typed for 13" } });

    state.units = [11, 12, 14, 15]; // unit 13 was decided elsewhere
    await leaveAndReturn();
    expect(await screen.findByText("canonical 14")).toBeInTheDocument();
    // Search text typed for unit 13 never leaks into unit 14, which gets its own seed.
    expect(screen.getByRole("searchbox")).toHaveValue("target 14");
    expect(
      screen.getByText("Unit #13, where you left the queue, is no longer awaiting review; continuing with the next unit in queue order."),
    ).toBeInTheDocument();
    skip();
    expect(screen.queryByText(/no longer awaiting review/)).not.toBeInTheDocument();
  });

  it("keeps the unit on an explicit queue reload", async () => {
    const calls = serve({ units: [21, 22, 23] });
    render(<App />);
    await screen.findByText("unit 1 of 3");
    skip();
    fireEvent.click(screen.getByRole("button", { name: "reload queue" }));
    expect(await screen.findByText("canonical 22")).toBeInTheDocument();
    expect(queueReads(calls)).toEqual(["GET /api/reviewable-units?limit=50", "GET /api/reviewable-units?limit=50&from_unit_id=22"]);
  });

  it("keeps the saved position when a queue re-read fails, and restores it on the next success", async () => {
    const state: QueueState = { units: [31, 32, 33, 34] };
    serve(state);
    render(<App />);
    await screen.findByText("unit 1 of 4");
    skip();
    skip();

    state.failQueue = true;
    await leaveAndReturn();
    expect(await screen.findByRole("alert")).toHaveTextContent("queue unavailable");

    state.failQueue = false;
    await leaveAndReturn();
    expect(await screen.findByText("canonical 33")).toBeInTheDocument();
  });

  it("loads one bounded page, never the whole queue, and the next page only past the loaded end", async () => {
    const units = Array.from({ length: 120 }, (_, i) => 1001 + i);
    const calls = serve({ units });
    render(<App />);
    expect(await screen.findByText("unit 1 of 50 loaded; more units follow in the queue")).toBeInTheDocument();
    expect(queueReads(calls)).toEqual(["GET /api/reviewable-units?limit=50"]);

    for (let i = 0; i < 49; i++) skip();
    expect(screen.getByText("unit 50 of 50 loaded; more units follow in the queue")).toBeInTheDocument();
    expect(queueReads(calls)).toHaveLength(1);

    skip(); // past the loaded end: exactly one more page
    expect(await screen.findByText("canonical 1051")).toBeInTheDocument();
    expect(screen.getByText("unit 51 of 100 loaded; more units follow in the queue")).toBeInTheDocument();
    expect(queueReads(calls)).toEqual(["GET /api/reviewable-units?limit=50", "GET /api/reviewable-units?limit=50&after=1.1050.1050"]);
    expect(calls.every((c) => c.startsWith("GET "))).toBe(true);
  });

  it("drops a slow next page that finishes after the queue was reloaded", async () => {
    let release!: () => void;
    // 52 units: the first page ends at unit 50, and the next page is held.
    const state: QueueState = { units: Array.from({ length: 52 }, (_, i) => i + 1), hold: new Promise<void>((r) => (release = r)) };
    serve(state);
    render(<App />);
    await screen.findByText("unit 1 of 50 loaded; more units follow in the queue");
    for (let i = 0; i < 49; i++) skip();
    skip(); // requests the next page, which is held
    expect(await screen.findByRole("button", { name: "loading…" })).toBeDisabled();

    state.hold = null;
    fireEvent.click(screen.getByRole("button", { name: "reload queue" }));
    expect(await screen.findByText("canonical 50")).toBeInTheDocument();
    await act(async () => release());
    // The superseded page was not appended to the reloaded window.
    expect(screen.getByText("unit 1 of 3 loaded from where you left off; earlier units are not loaded")).toBeInTheDocument();
  });
});
