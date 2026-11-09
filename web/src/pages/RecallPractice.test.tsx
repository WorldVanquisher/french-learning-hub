// Recall practice v1 (Knowledge Library, private workbench): start from a Concept,
// choose questions from current support only, answer before the stored evidence
// is revealed, retry a missed item, trace it to its original source, and send
// nothing but GETs. Data is the authored French fixture in test/recallPracticeFixture.
import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import PublicDemoApp from "../PublicDemoApp";
import { LocaleProvider } from "../i18n";
import { KnowledgeLibrary } from "./KnowledgeLibrary";
import {
  conceptEn,
  conceptEnDetail,
  fixtureResponses,
  questions,
  source,
  unitPartitive,
  unitQuantity,
} from "../test/recallPracticeFixture";
import type { LibraryUnit } from "../types/library";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

type Call = { method: string; path: string; search: string; body: string };
type Reply = { status?: number; body: unknown };

// serve answers from the fixture; an override (by /api path) wins. Every request
// is recorded with its method and body.
function serve(overrides: Record<string, () => Reply> = {}) {
  const calls: Call[] = [];
  const responses = fixtureResponses();
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    calls.push({ method: (init?.method ?? "GET").toUpperCase(), path: url.pathname, search: url.search, body: String(init?.body ?? "") });
    let reply: Reply;
    if (overrides[url.pathname]) reply = overrides[url.pathname]();
    else if (url.pathname in responses) reply = { body: responses[url.pathname] };
    else if (url.pathname === "/api/reviewable-units") reply = { body: { reviewable_units: [] } };
    else reply = { body: { concepts: [] } };
    return new Response(JSON.stringify(reply.body), { status: reply.status ?? 200, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
  return calls;
}

const sourcePaths = (calls: Call[]) => calls.filter((c) => c.path.includes("/source")).map((c) => c.path);
const region = () => screen.getByRole("region", { name: "Recall practice" });

// From the workbench: Knowledge Library → Concept #21 → Start recall practice.
async function openPracticeInApp() {
  render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Knowledge Library" }));
  fireEvent.click(await screen.findByRole("button", { name: conceptEn.target }));
  fireEvent.click(await screen.findByRole("button", { name: "Start recall practice…" }));
  await screen.findByRole("heading", { name: "Recall practice · Concept #21" });
}

async function openPracticeAlone(conceptId = 21) {
  render(
    <StrictMode>
      <LocaleProvider>
        <KnowledgeLibrary openRequest={{ conceptId, nonce: 1 }} />
      </LocaleProvider>
    </StrictMode>,
  );
}

describe("recall practice", () => {
  it("starts from Concept detail and offers only the current supporting questions, none preselected", async () => {
    const calls = serve();
    await openPracticeInApp();
    const boxes = await within(region()).findAllByRole("checkbox");
    expect(boxes).toHaveLength(2);
    expect(within(region()).getByRole("checkbox", { name: /Record #31:.*J'en ai deux/ })).not.toBeChecked();
    expect(within(region()).getByRole("checkbox", { name: /Record #32:.*j'en veux/ })).not.toBeChecked();
    expect(within(region()).getByRole("button", { name: "Choose at least one question" })).toBeDisabled();
    // The older-extraction member, the reassigned unit and the relation are not
    // offered, and their sources are never even read.
    expect(new Set(sourcePaths(calls))).toEqual(new Set(["/api/knowledge-library/units/201/source", "/api/knowledge-library/units/202/source"]));
    for (const id of [204, 205, 206]) expect(sourcePaths(calls)).not.toContain(`/api/knowledge-library/units/${id}/source`);
    for (const q of [questions[34].input, questions[35].input]) expect(screen.queryByText(q, { exact: false })).toBeNull();
    // The answers are not shown while choosing either.
    expect(screen.queryByText(unitQuantity.statement)).toBeNull();
    expect(screen.queryByText(questions[31].context)).toBeNull();
  });

  it("hides the answer, reveals the stored evidence, retries a missed item, opens the right source, and sends only GETs", async () => {
    const calls = serve();
    const stored = vi.spyOn(Storage.prototype, "setItem");
    const logs = (["log", "info", "warn", "error", "debug"] as const).map((m) => vi.spyOn(console, m));
    const SECRET = "mon-essai-secret: en remplace « de pommes »";
    await openPracticeInApp();
    fireEvent.click(await within(region()).findByRole("checkbox", { name: /Record #31/ }));
    fireEvent.click(within(region()).getByRole("checkbox", { name: /Record #32/ }));
    fireEvent.click(within(region()).getByRole("button", { name: "Start practice with 2 questions" }));

    // Question 1: the learner's question only. No title, statement, example or context.
    expect(await screen.findByRole("heading", { name: "Question 1 of 2" })).toHaveFocus();
    expect(within(region()).getByText(questions[31].input)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: new RegExp(conceptEn.target.slice(0, 12)) })).toBeNull();
    expect(screen.queryByRole("button", { name: conceptEn.target })).toBeNull(); // the results list is hidden
    for (const text of [unitQuantity.statements!.en!, unitQuantity.statements!.zh!, unitQuantity.example!, questions[31].context, unitPartitive.statement])
      expect(screen.queryByText(text, { exact: false })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Stored reference explanation" })).toBeNull();

    fireEvent.change(within(region()).getByLabelText("Your attempt (optional)"), { target: { value: SECRET } });
    fireEvent.click(within(region()).getByRole("button", { name: "Reveal stored explanation" }));
    const reveal = within(region()).getByRole("region", { name: "Stored reference explanation" });
    expect(within(reveal).getByRole("heading", { name: "Stored reference explanation" })).toHaveFocus();
    expect(within(reveal).getByText(unitQuantity.statements!.en!)).toBeInTheDocument();
    expect(within(reveal).getByText(unitQuantity.statements!.zh!)).toBeInTheDocument(); // default: both stored languages
    expect(within(reveal).getByText(unitQuantity.example!)).toBeInTheDocument();
    expect(within(reveal).getByText(/a reference, not a grading rubric/)).toBeInTheDocument();
    fireEvent.click(within(region()).getByRole("button", { name: "Recalled" }));

    // Question 2: the attempt was cleared; the learner marks it Try again.
    expect(await screen.findByRole("heading", { name: "Question 2 of 2" })).toBeInTheDocument();
    expect(within(region()).getByLabelText("Your attempt (optional)")).toHaveValue("");
    expect(within(region()).getByText(questions[32].input)).toBeInTheDocument();
    fireEvent.click(within(region()).getByRole("button", { name: "Reveal stored explanation" }));
    fireEvent.click(within(region()).getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("heading", { name: "First pass finished" })).toBeInTheDocument();
    expect(within(region()).getByText("Recalled: 1 · Try again: 1 · Skipped: 0")).toBeInTheDocument();
    fireEvent.click(within(region()).getByRole("button", { name: "Second pass over the 1 question marked Try again" }));

    // The second pass holds only the missed item.
    expect(await screen.findByRole("heading", { name: "Second pass: question 1 of 1" })).toBeInTheDocument();
    expect(within(region()).getByText(questions[32].input)).toBeInTheDocument();
    fireEvent.click(within(region()).getByRole("button", { name: "Reveal stored explanation" }));
    fireEvent.click(within(region()).getByRole("button", { name: "Open the original source (record #32)" }));

    // The right original source: unit #202 from record #32, with its context.
    expect(await screen.findByRole("heading", { name: "Where unit #202 came from: learning record #32" })).toBeInTheDocument();
    const record = screen.getByRole("region", { name: "Original learning record #32" });
    expect(within(record).getByText(questions[32].input)).toBeInTheDocument();
    expect(within(record).getByText(questions[32].context)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Recall practice" })).toBeNull(); // kept, but hidden
    fireEvent.click(screen.getByRole("button", { name: "← Back to practice" }));

    // Back in the same session, at the same revealed card.
    expect(await screen.findByRole("heading", { name: "Second pass: question 1 of 1" })).toBeInTheDocument();
    expect(within(region()).getByRole("region", { name: "Stored reference explanation" })).toBeInTheDocument();
    fireEvent.click(within(region()).getByRole("button", { name: "Recalled" }));
    expect(await screen.findByRole("heading", { name: "Second pass finished" })).toBeInTheDocument();
    expect(within(region()).getByText("Recalled: 1 · Try again: 0 · Skipped: 0")).toBeInTheDocument();
    expect(within(region()).queryByRole("button", { name: /Second pass over/ })).toBeNull();
    // A new selection re-reads current support and starts with nothing chosen.
    const before = calls.length;
    fireEvent.click(within(region()).getByRole("button", { name: "Choose questions again" }));
    expect(await within(region()).findByRole("checkbox", { name: /Record #31/ })).not.toBeChecked();
    expect(calls.slice(before).map((c) => c.path)).toEqual(
      expect.arrayContaining(["/api/knowledge-library/concepts/21", "/api/knowledge-library/units/201/source"]),
    );

    // The whole session read only, and never read evidence outside current support.
    expect(calls.length).toBeGreaterThan(0);
    expect(calls.filter((c) => c.method !== "GET")).toEqual([]);
    expect(new Set(sourcePaths(calls))).toEqual(new Set(["/api/knowledge-library/units/201/source", "/api/knowledge-library/units/202/source"]));
    // The attempt text never left the page: not in a request, browser storage or a log.
    const leaked = (v: unknown) => JSON.stringify(v ?? "").includes("mon-essai-secret");
    expect(calls.some((c) => leaked(c.path + c.search + c.body))).toBe(false);
    expect(stored.mock.calls.some((args) => leaked(args))).toBe(false);
    for (const spy of logs) expect(spy.mock.calls.some((args) => leaked(args))).toBe(false);
  });

  it("follows the Explanation-language preference when revealing", async () => {
    serve();
    await openPracticeInApp();
    fireEvent.click(await within(region()).findByRole("checkbox", { name: /Record #31/ }));
    fireEvent.click(within(region()).getByRole("button", { name: "Start practice with 1 question" }));
    fireEvent.click(await within(region()).findByRole("button", { name: "Reveal stored explanation" }));
    const select = screen.getByLabelText("Explanation language");
    fireEvent.change(select, { target: { value: "zh" } });
    expect(within(region()).getByText(unitQuantity.statements!.zh!)).toBeInTheDocument();
    expect(within(region()).queryByText(unitQuantity.statements!.en!)).toBeNull();
    fireEvent.change(select, { target: { value: "en" } });
    expect(within(region()).getByText(unitQuantity.statements!.en!)).toBeInTheDocument();
    expect(within(region()).queryByText(unitQuantity.statements!.zh!)).toBeNull();
  });

  it("states a failed read, a missing source, missing question text and units that no longer support, and offers none of them", async () => {
    const extra = (id: number, entry: number): LibraryUnit => ({ ...unitQuantity, unit_id: id, entry_id: entry, extraction_id: id * 10 });
    const moved = extra(207, 31);
    const blank = extra(208, 38); // record #38 has no question text in the fixture
    const missing = extra(209, 39);
    let firstRead = true;
    const calls = serve({
      "/api/knowledge-library/concepts/21": () => ({ body: { ...conceptEnDetail, supporting_units: [unitQuantity, unitPartitive, moved, blank, missing] } }),
      "/api/knowledge-library/units/201/source": () => {
        if (firstRead) {
          firstRead = false;
          return { status: 500, body: { error: "database is locked" } };
        }
        return { body: source(unitQuantity, 21) };
      },
      "/api/knowledge-library/units/202/source": () => ({ body: source(unitPartitive, 21, "invalid") }),
      "/api/knowledge-library/units/207/source": () => ({ body: source(moved, 22) }),
      "/api/knowledge-library/units/208/source": () => ({ body: source(blank, 21) }),
      "/api/knowledge-library/units/209/source": () => ({ status: 404, body: { error: "unit not found" } }),
    });
    await openPracticeAlone();
    fireEvent.click(await screen.findByRole("button", { name: "Start recall practice…" }));
    const failed = await within(await screen.findByRole("region", { name: "Recall practice" })).findByRole("alert");
    expect(failed).toHaveTextContent("Could not load the question for unit #201, so it is not offered: (500) database is locked");
    expect(within(region()).getByText("Unit #202 was judged INVALID, so it is not offered.")).toBeInTheDocument();
    expect(within(region()).getByText("Unit #207 is no longer filed under this Concept, so it is not offered.")).toBeInTheDocument();
    expect(within(region()).getByText("Record #38 has no question text, so unit #208 is not offered.")).toBeInTheDocument();
    expect(within(region()).getByText("The source of unit #209 was not found, so it is not offered.")).toBeInTheDocument();
    // A failed read never looks like a usable card.
    expect(within(region()).queryAllByRole("checkbox")).toHaveLength(0);
    expect(within(region()).getByText(/can be offered as a question right now/)).toBeInTheDocument();
    expect(within(region()).getByRole("button", { name: "Choose at least one question" })).toBeDisabled();

    fireEvent.click(within(failed).getByRole("button", { name: "Retry" }));
    expect(await within(region()).findByRole("checkbox", { name: /Record #31/ })).not.toBeChecked();
    expect(within(region()).queryAllByRole("checkbox")).toHaveLength(1);
    expect(within(region()).queryByText(/can be offered as a question right now/)).toBeNull();
    expect(calls.filter((c) => c.method !== "GET")).toEqual([]);
  });

  it("explains when there is no usable support, including support that disappeared before practice started", async () => {
    let gone = false;
    serve({
      "/api/knowledge-library/concepts/23": () => ({ body: { ...conceptEnDetail, concept: { ...conceptEn, id: 23 }, supporting_units: [] } }),
      "/api/knowledge-library/concepts/24": () => ({ body: { ...conceptEnDetail, concept: { ...conceptEn, id: 24, state: "retired", lifecycle_state: "retired" } } }),
      "/api/knowledge-library/concepts/21": () => ({ body: gone ? { ...conceptEnDetail, supporting_units: [] } : conceptEnDetail }),
    });
    await openPracticeAlone(23);
    expect(await screen.findByText(/needs at least one unit that currently supports this Concept/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start recall practice…" })).toBeNull();
    cleanup();

    await openPracticeAlone(24);
    expect(await screen.findByText("This Concept is retired, so recall practice is not offered.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start recall practice…" })).toBeNull();
    cleanup();

    // Support disappears after the Concept was shown: practice's own read says so.
    await openPracticeAlone(21);
    const start = await screen.findByRole("button", { name: "Start recall practice…" });
    gone = true;
    fireEvent.click(start);
    await waitFor(() => expect(within(region()).getByText(/needs at least one unit that currently supports/)).toBeInTheDocument());
    expect(within(region()).queryAllByRole("checkbox")).toHaveLength(0);
  });

  it("is offered in Simplified Chinese", async () => {
    window.localStorage.setItem("flh.ui-locale.v1", "zh-CN");
    serve();
    await openPracticeAlone();
    fireEvent.click(await screen.findByRole("button", { name: "开始回忆练习…" }));
    expect(await screen.findByRole("heading", { name: "回忆练习 · 概念 #21" })).toBeInTheDocument();
    expect(await screen.findByRole("checkbox", { name: /记录 #31：/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "请至少选择一道题" })).toBeDisabled();
  });

  it("is not available in the public demo", async () => {
    const info = {
      schema_version: "knowledge_library_public_demo_v1", read_only: true, data: "synthetic",
      artifact: { version: "v", manifest_sha256: "m", vector_source: "mechanical-test", real_model: false, vector_generator: "g", model_id: "x",
        dimensions: 4, document_representation: "d", query_representation: "q", release_status: "blocked", notice: "n", domain_fingerprint_sha256: "f" },
      query_policy: "presets only", presets: [], counters: { preset_vector_lookups: 0, refused_vector_lookups: 0 },
    };
    const calls = serve({ "/api/knowledge-library/demo": () => ({ body: info }) });
    render(
      <StrictMode>
        <PublicDemoApp />
      </StrictMode>,
    );
    fireEvent.click(await screen.findByRole("button", { name: conceptEn.target }));
    expect(await screen.findByRole("heading", { name: new RegExp("pronom « en »") })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Recall practice" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Start recall practice…" })).toBeNull();
    expect(sourcePaths(calls)).toEqual([]);
  });
});
