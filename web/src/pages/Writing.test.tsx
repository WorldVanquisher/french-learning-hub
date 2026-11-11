// Exam Writing v1 in the private workbench, against a stateful fake server
// built from the authored fixture (test/writingFixture, generated from the
// embedded prompts and the grounded feedback testdata).
import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import PublicDemoApp from "../PublicDemoApp";
import { draftV1, draftV2, feedbackV1, notice, prompts, wordsV1, wordsV2 } from "../test/writingFixture";
import type { WritingDraft, WritingFeedback, WritingRequest, WritingTaskView } from "../types/writing";
import { countWords, diffWords, shownAsGrounded } from "./Writing";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

const GENERATOR = "openai:fake-model:writing_feedback_v1";
type Mode = "ok" | "fail" | "lost" | "lostBefore" | "unknown" | "disabled";
type Call = { method: string; path: string; body: string; key: string | null };
type Server = {
  tasks: WritingTaskView[];
  mode: Mode;
  calls: Call[];
  byKey: Map<string, { request: WritingRequest; feedback: WritingFeedback }>;
};

const newServer = (tasks: WritingTaskView[] = [], mode: Mode = "ok"): Server => ({ tasks, mode, calls: [], byKey: new Map() });

const invitation = prompts[0];
const taskView = (id: number, drafts: string[] = []): WritingTaskView => ({
  task: {
    id,
    title: invitation.title,
    prompt: invitation.prompt,
    requirements: invitation.requirements,
    word_min: invitation.word_min,
    word_max: invitation.word_max,
    origin: "authored",
    prompt_id: invitation.id,
    created_at: "t",
  },
  drafts: drafts.map((text, i): WritingDraft => ({ id: id * 100 + i + 1, version: i + 1, text, word_count: countWords(text), created_at: "t" })),
  feedback: [],
  requests: [],
  generation: { enabled: true, generator: GENERATOR },
  word_convention: "w",
});

function serve(server: Server) {
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const body = String(init?.body ?? "");
    const key = (init?.headers as Record<string, string> | undefined)?.["Idempotency-Key"] ?? null;
    server.calls.push({ method, path: url.pathname, body, key });
    const p = url.pathname;
    const generation = server.mode === "disabled" ? { enabled: false, generator: null } : { enabled: true, generator: GENERATOR };
    const view = (v: WritingTaskView) => ({ ...v, generation });
    const find = (id: number) => server.tasks.find((v) => v.task.id === id);
    let m: RegExpExecArray | null;
    if (method === "GET" && p === "/api/writing/prompts")
      return json(200, {
        set: "flh_writing_prompts_v1",
        notice,
        prompts: prompts.map((x) => ({ ...x, started_task_id: server.tasks.find((v) => v.task.prompt_id === x.id)?.task.id ?? null })),
      });
    if ((m = /^\/api\/writing\/prompts\/(.+)$/.exec(p)) && method === "POST") {
      const existing = server.tasks.find((v) => v.task.prompt_id === m![1]);
      if (existing) return json(200, view(existing));
      const v = taskView(server.tasks.length + 1);
      server.tasks.push(v);
      return json(201, view(v));
    }
    if (method === "GET" && p === "/api/writing/tasks")
      return json(200, { generation, tasks: server.tasks.map((v) => ({ task: v.task, versions: v.drafts.length, feedback: v.feedback.length })) });
    if (method === "POST" && p === "/api/writing/tasks") {
      const req = JSON.parse(body) as { title: string; prompt: string; requirements: string[] };
      const v = taskView(server.tasks.length + 1);
      v.task = { ...v.task, title: req.title, prompt: req.prompt, requirements: req.requirements, word_min: 60, word_max: 120, origin: "learner", prompt_id: null };
      server.tasks.push(v);
      return json(201, view(v));
    }
    if ((m = /^\/api\/writing\/tasks\/(\d+)$/.exec(p)) && method === "GET") {
      const v = find(Number(m[1]));
      return v ? json(200, view(v)) : json(404, { error: "not found" });
    }
    if ((m = /^\/api\/writing\/tasks\/(\d+)\/drafts$/.exec(p)) && method === "POST") {
      const v = find(Number(m[1]))!;
      const text = (JSON.parse(body) as { text: string }).text;
      if (v.drafts.at(-1)?.text === text) return json(409, { code: "unchanged", error: "unchanged" });
      v.drafts.push({ id: v.task.id * 100 + v.drafts.length + 1, version: v.drafts.length + 1, text, word_count: countWords(text), created_at: "t" });
      return json(201, view(v));
    }
    if ((m = /^\/api\/writing\/drafts\/(\d+)\/feedback$/.exec(p)) && method === "POST") {
      const draftId = Number(m[1]);
      const v = server.tasks.find((x) => x.drafts.some((d) => d.id === draftId))!;
      if (server.mode === "disabled") return json(503, { error: "writing feedback is not enabled (WRITING_PROVIDER)" });
      if (key && server.byKey.has(key)) return json(200, server.byKey.get(key));
      if (server.mode === "lostBefore") throw new TypeError("network down");
      const confirm = body.includes('"confirm_unknown_retry":true');
      const last = v.requests.find((r) => r.draft_id === draftId);
      if (last?.state === "unknown" && !confirm) return json(409, { code: "outcome_unknown", error: "unknown", request: last });
      const id = 500 + v.feedback.length;
      const failed = server.mode === "fail" || server.mode === "unknown";
      const fb: WritingFeedback = {
        id,
        draft_id: draftId,
        status: failed ? "failed" : "completed",
        failure_code: server.mode === "fail" ? "invalid_output" : server.mode === "unknown" ? "provider_unavailable" : null,
        generator: GENERATOR,
        created_at: "t",
        content: failed ? null : feedbackV1,
      };
      const state = server.mode === "fail" ? "failed" : server.mode === "unknown" ? "unknown" : "completed";
      const req: WritingRequest = { id: 70 + v.requests.length, operation_id: key ?? "k", draft_id: draftId, after_unknown: confirm, started_at: "t", deadline_at: "t", finished_at: "t", state, feedback_id: id };
      v.feedback.unshift(fb);
      v.requests.unshift(req);
      server.byKey.set(key ?? "k", { request: req, feedback: fb });
      if (server.mode === "lost") throw new TypeError("network down");
      if (failed) return json(server.mode === "fail" ? 502 : 504, { error: "provider failed", request: req, feedback: fb });
      return json(201, { request: req, feedback: fb });
    }
    if ((m = /^\/api\/writing\/feedback-requests\/(.+)$/.exec(p)) && method === "GET") {
      const r = server.byKey.get(decodeURIComponent(m[1]));
      return r ? json(200, r) : json(404, { error: "no feedback request is recorded under this key" });
    }
    if (p === "/api/captures" && method === "POST") {
      const doc = JSON.parse(body) as { capture_id: string };
      return json(201, { capture_id: doc.capture_id, entry_id: 88, analysis_id: null, created: true });
    }
    if (p === "/api/knowledge-library/demo")
      return json(200, {
        schema_version: "knowledge_library_public_demo_v1", read_only: true, data: "synthetic",
        artifact: { version: "v", manifest_sha256: "m", vector_source: "mechanical-test", real_model: false, vector_generator: "g", model_id: "x",
          dimensions: 4, document_representation: "d", query_representation: "q", release_status: "blocked", notice: "n", domain_fingerprint_sha256: "f" },
        query_policy: "presets only", presets: [], counters: { preset_vector_lookups: 0, refused_vector_lookups: 0 },
      });
    if (p === "/api/knowledge-library/concepts")
      return json(200, { schema_version: "knowledge_library_search_v1", query: "", tokens: [], state: "all", limit: 20, total_matches: 0, truncated: false, results: [] });
    if (p === "/api/reviewable-units") return json(200, { reviewable_units: [] });
    if (p === "/api/learning-records") return json(200, { records: [], next_before_entry_id: null });
    return json(200, { concepts: [] });
  }) as unknown as typeof fetch;
}

const writes = (s: Server) => s.calls.filter((c) => c.method !== "GET");
const feedbackPosts = (s: Server) => s.calls.filter((c) => c.method === "POST" && c.path.endsWith("/feedback"));

async function openWriting() {
  render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Writing" }));
  return await screen.findByRole("region", { name: "Saved writing tasks" });
}

async function openTask(title = invitation.title) {
  const list = await openWriting();
  fireEvent.click(await within(list).findByRole("button", { name: title }));
  return await screen.findByRole("region", { name: "Saved versions" });
}

describe("Writing helpers", () => {
  it("counts words with the backend convention", () => {
    expect(countWords("l'invitation, peut-être 20 heures !")).toBe(4);
    expect(countWords("  ")).toBe(0);
    expect(wordsV1).toBe(countWords(draftV1));
  });

  it("diffs word by word and keeps whitespace", () => {
    expect(diffWords("Je suis arrivé vers 20 heures", "J'arriverai vers 20 heures")).toEqual([
      { op: "del", text: "Je suis arrivé" },
      { op: "add", text: "J'arriverai" },
      { op: "same", text: " vers 20 heures" },
    ]);
  });

  it("never shows a quote as grounded unless it occurs in the version as the server says", () => {
    const [located, , ambiguous, missing] = feedbackV1.corrections;
    expect(shownAsGrounded(draftV1, located)).toBe(true);
    expect(shownAsGrounded(draftV1, ambiguous)).toBe(true);
    expect(shownAsGrounded(draftV1, missing)).toBe(false);
    // A v1 report read against v2: its fixed quote is no longer there.
    expect(shownAsGrounded(draftV2, located)).toBe(false);
    // A "located" claim for a repeated phrase is not displayed as located.
    expect(shownAsGrounded(draftV1, { ...ambiguous, grounding: "located" })).toBe(false);
  });
});

describe("Writing (private workbench)", () => {
  it("save v1 → request feedback → see hints → revise to v2 → compare → capture one mistake", async () => {
    const server = newServer();
    serve(server);
    await openWriting();
    const promptsRegion = screen.getByRole("region", { name: "Authored writing tasks" });
    fireEvent.click(within(await within(promptsRegion).findByText(invitation.title).then((n) => n.closest("li")!)).getByRole("button", { name: "Start this task" }));
    await screen.findByRole("heading", { name: invitation.title });
    expect(writes(server).map((c) => c.path)).toEqual(["/api/writing/prompts/wr-invitation-anniversaire"]);
    expect(screen.getByText(/there is no score, mark or level/)).toBeInTheDocument();

    // Version 1 from the example draft (deliberate mistakes). Drafting calls no provider.
    const editor = screen.getByRole("form", { name: "Draft editor" });
    fireEvent.click(await within(editor).findByRole("button", { name: "Use the example draft (it contains mistakes on purpose)" }));
    expect(within(editor).getByText(`${wordsV1} words`)).toBeInTheDocument();
    fireEvent.click(within(editor).getByRole("button", { name: "Save as version 1" }));
    expect(await screen.findByText(`Showing version 1: ${wordsV1} words (target 60–90).`)).toBeInTheDocument();
    expect(screen.getByLabelText("Text of version 1").textContent).toBe(draftV1);
    expect(feedbackPosts(server)).toEqual([]);

    // One explicit request, for version 1, under a key.
    fireEvent.click(screen.getByRole("button", { name: "Request feedback on version 1" }));
    const report = await screen.findByRole("group", { name: "Feedback report on version 1" });
    const posts = feedbackPosts(server);
    expect(posts).toHaveLength(1);
    expect(posts[0].path).toBe("/api/writing/drafts/101/feedback");
    expect(posts[0].key).toMatch(/^[0-9a-f-]{36}$/);
    expect(within(report).getByText(/This report is about version/)).toHaveTextContent(`This report is about version 1 only (${GENERATOR}).`);
    expect(within(report).getByText("Content points partly covered")).toBeInTheDocument();

    // Hints first; the suggested wording stays hidden.
    const c1 = within(report).getByRole("group", { name: "Correction 1" });
    expect(within(c1).getByText(feedbackV1.corrections[0].hint_en)).toBeInTheDocument();
    expect(screen.queryByText(feedbackV1.corrections[0].suggestion)).toBeNull();
    expect(screen.queryByText(feedbackV1.corrections[0].reason_en)).toBeNull();
    // The located quote can be shown in version 1's text.
    fireEvent.click(within(c1).getByRole("button", { name: "Show in version 1" }));
    expect(screen.getByLabelText("Text of version 1").querySelector("mark")?.textContent).toBe(feedbackV1.corrections[0].quote);
    // A repeated phrase gets no invented location.
    const c3 = within(report).getByRole("group", { name: "Correction 3" });
    expect(within(c3).getByText(/appears more than once in this version, so no position is attached/)).toBeInTheDocument();
    expect(within(c3).queryByRole("button", { name: "Show in version 1" })).toBeNull();
    expect(c3.getAttribute("value")).toBe("3"); // the list marker is the report's number
    // A quote that is not in the text is never presented as a grounded correction.
    expect(within(report).queryByRole("group", { name: "Correction 4" })).toBeNull();
    const missing = within(report).getByRole("region", { name: "Quotes not found in this version" });
    expect(within(missing).getByText(`« ${feedbackV1.corrections[3].quote} »`)).toBeInTheDocument();
    expect(screen.queryByText(feedbackV1.corrections[3].hint_en)).toBeNull();

    // Revise from the hints into version 2 (the suggestion was never revealed).
    const reviser = screen.getByRole("form", { name: "Draft editor" });
    expect(within(reviser).getByRole("heading", { name: "Revise into version 2" })).toBeInTheDocument();
    expect(within(reviser).getByLabelText("Text of version 2")).toHaveValue(draftV1);
    fireEvent.change(within(reviser).getByLabelText("Text of version 2"), { target: { value: draftV2 } });
    fireEvent.click(within(reviser).getByRole("button", { name: "Save as version 2" }));
    expect(await screen.findByText(`Showing version 2: ${wordsV2} words (target 60–90).`)).toBeInTheDocument();
    // The v1 report is not carried over to v2.
    expect(screen.getByRole("heading", { name: "Feedback on version 2" })).toBeInTheDocument();
    expect(screen.getByText("Other versions have their own feedback (v1). It is never carried over to this version.")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /Feedback report/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Request feedback on version 2" })).toBeInTheDocument();

    // Compare v1 → v2.
    const compare = screen.getByRole("region", { name: "Compare versions" });
    expect(within(compare).getByRole("heading", { name: "Changes from version 1 to version 2" })).toBeInTheDocument();
    const removed = [...compare.querySelectorAll("del")].map((n) => n.textContent).join("|");
    const added = [...compare.querySelectorAll("ins")].map((n) => n.textContent).join("|");
    expect(removed).toContain("Je suis arrivé");
    expect(added).toContain("J'arriverai");
    expect(added).toContain("ne");

    // Back on v1: its text and its report are exactly as they were.
    fireEvent.click(screen.getByRole("button", { name: `Version 1 · ${wordsV1} words` }));
    expect(screen.getByLabelText("Text of version 1").textContent).toBe(draftV1);
    const again = screen.getByRole("group", { name: "Feedback report on version 1" });
    const first = within(again).getByRole("group", { name: "Correction 1" });
    fireEvent.click(within(first).getByRole("button", { name: "Show suggested wording" }));
    expect(within(first).getByText(feedbackV1.corrections[0].suggestion)).toBeInTheDocument();
    expect(within(first).getByText(feedbackV1.corrections[0].reason_en)).toBeInTheDocument();

    // Capture one mistake as an ordinary learning record, only on explicit save.
    fireEvent.click(within(first).getByRole("button", { name: "Save this mistake…" }));
    const form = screen.getByRole("form", { name: "Save the mistake from correction 1" });
    const before = writes(server).length;
    fireEvent.change(within(form).getByLabelText("Your revised wording"), { target: { value: "J'arriverai vers 20 heures" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save learning record" }));
    expect(await screen.findByText("Saved as learning record #88.")).toBeInTheDocument();
    const captures = writes(server).slice(before);
    expect(captures.map((c) => c.path)).toEqual(["/api/captures"]);
    const doc = JSON.parse(captures[0].body) as Record<string, string>;
    expect(Object.keys(doc).sort()).toEqual(["capture_id", "original_context", "original_input", "schema_version", "source", "source_ref"]);
    // Mistake Notebook v1: the exact stored item, never the typed answer unless the learner includes it.
    expect((doc as unknown as { source_ref: unknown }).source_ref).toEqual({ type: "writing_correction", record_id: 500, item: 1 });
    expect(doc.source).toBe("manual");
    expect(doc.capture_id).toMatch(/^writing-1-101-500-1-[0-9a-f-]{36}$/);
    expect(doc.original_input).toBe(
      `« Je suis arrivé vers 20 heures » → « J'arriverai vers 20 heures »\n${feedbackV1.corrections[0].reason_en}\n${feedbackV1.corrections[0].reason_zh}`,
    );
    expect(doc.original_context).toContain("Writing task #1: Répondre à une invitation (authored prompt wr-invitation-anniversaire)");
    expect(doc.original_context).toContain(`Draft version 1, feedback #500 (${GENERATOR})`);

    // Exactly: start, v1, one feedback request, v2, one capture. No Concept or other write.
    expect(writes(server).map((c) => c.path)).toEqual([
      "/api/writing/prompts/wr-invitation-anniversaire",
      "/api/writing/tasks/1/drafts",
      "/api/writing/drafts/101/feedback",
      "/api/writing/tasks/1/drafts",
      "/api/captures",
    ]);

    // A way to the record and back to the same task.
    fireEvent.click(screen.getByRole("button", { name: "Open record #88 in Learning Records" }));
    expect(await screen.findByText("Opened from a writing task.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "← Back to Writing" }));
    expect(screen.getByLabelText("Text of version 1").textContent).toBe(draftV1);
  });

  it("a failed request never loses either version, and an unsaved revision survives it", async () => {
    const server = newServer([taskView(1, [draftV1, draftV2])], "fail");
    serve(server);
    await openTask();
    fireEvent.change(screen.getByLabelText("Text of version 3"), { target: { value: `${draftV2}\nUnsaved line.` } });
    fireEvent.click(screen.getByRole("button", { name: "Request feedback on version 2" }));
    expect(await screen.findByText("The last request for this version failed (the provider's answer did not pass validation). Your versions are safe; you can request again.")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /Feedback report/ })).toBeNull();
    expect(screen.getByLabelText("Text of version 2").textContent).toBe(draftV2);
    expect(screen.getByLabelText("Text of version 3")).toHaveValue(`${draftV2}\nUnsaved line.`);
    fireEvent.click(screen.getByRole("button", { name: `Version 1 · ${wordsV1} words` }));
    expect(screen.getByLabelText("Text of version 1").textContent).toBe(draftV1);
    expect(screen.queryByText(/The last request for this version failed/)).toBeNull(); // the failure belongs to v2
    expect(writes(server).map((c) => c.path)).toEqual(["/api/writing/drafts/102/feedback"]);
  });

  it("after a lost response it looks the key up first and resends only the same key", async () => {
    const server = newServer([taskView(1, [draftV1])], "lostBefore");
    serve(server);
    await openTask();
    fireEvent.click(screen.getByRole("button", { name: "Request feedback on version 1" }));
    expect(await screen.findByText("No answer arrived, and nothing is recorded under this request yet.")).toBeInTheDocument();
    const [first] = feedbackPosts(server);
    expect(server.calls.filter((c) => c.path === `/api/writing/feedback-requests/${first.key}`)).toHaveLength(1);
    expect(screen.getByLabelText("Text of version 1").textContent).toBe(draftV1);
    server.mode = "ok";
    fireEvent.click(screen.getByRole("button", { name: "Send the same request again" }));
    expect(await screen.findByRole("group", { name: "Feedback report on version 1" })).toBeInTheDocument();
    const posts = feedbackPosts(server);
    expect(posts).toHaveLength(2);
    expect(posts[1].key).toBe(first.key);
  });

  it("a lost response that was recorded is found by its key without a second request", async () => {
    const server = newServer([taskView(1, [draftV1])], "lost");
    serve(server);
    await openTask();
    fireEvent.click(screen.getByRole("button", { name: "Request feedback on version 1" }));
    expect(await screen.findByRole("group", { name: "Feedback report on version 1" })).toBeInTheDocument();
    expect(feedbackPosts(server)).toHaveLength(1);
  });

  it("an unknown outcome needs an acknowledged retry", async () => {
    const server = newServer([taskView(1, [draftV1])], "unknown");
    serve(server);
    await openTask();
    fireEvent.click(screen.getByRole("button", { name: "Request feedback on version 1" }));
    expect(await screen.findByText(/no result came back: the provider may have been charged/)).toBeInTheDocument();
    expect(screen.queryByText(/The last request for this version failed/)).toBeNull();
    expect(screen.getByLabelText("Text of version 1").textContent).toBe(draftV1);
    server.mode = "ok";
    fireEvent.click(screen.getByRole("button", { name: "Request again anyway (it may be charged twice)" }));
    expect(await screen.findByRole("group", { name: "Feedback report on version 1" })).toBeInTheDocument();
    const posts = feedbackPosts(server);
    expect(posts).toHaveLength(2);
    expect(posts[0].body).toBe("");
    expect(JSON.parse(posts[1].body)).toEqual({ confirm_unknown_retry: true });
    expect(posts[1].key).not.toBe(posts[0].key);
  });

  it("drafting and revising work without a provider, and an unchanged text is not a new version", async () => {
    const server = newServer([], "disabled");
    serve(server);
    await openWriting();
    const own = screen.getByRole("form", { name: "Your own writing task" });
    fireEvent.change(within(own).getByLabelText("Title"), { target: { value: "Mon week-end" } });
    fireEvent.change(within(own).getByLabelText("Prompt (in French)"), { target: { value: "Racontez votre week-end à un ami." } });
    fireEvent.change(within(own).getByLabelText("Content points, one per line (optional)"), { target: { value: "Où ?\n\nAvec qui ?" } });
    fireEvent.click(within(own).getByRole("button", { name: "Save task" }));
    await screen.findByRole("heading", { name: "Mon week-end" });
    expect(JSON.parse(writes(server)[0].body)).toEqual({ title: "Mon week-end", prompt: "Racontez votre week-end à un ami.", requirements: ["Où ?", "Avec qui ?"] });
    expect(screen.queryByRole("button", { name: /Use the example draft/ })).toBeNull();
    fireEvent.change(screen.getByLabelText("Text of version 1"), { target: { value: "Samedi, je suis allé au marché avec ma sœur." } });
    fireEvent.click(screen.getByRole("button", { name: "Save as version 1" }));
    expect(await screen.findByText(/Feedback is not configured on this server \(WRITING_PROVIDER=disabled\)/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Request feedback/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Save as version 2" }));
    expect(await screen.findByText("This text is identical to the latest version, so no new version was saved.")).toBeInTheDocument();
    expect(feedbackPosts(server)).toEqual([]);
  });

  it("follows the explanation-language preference", async () => {
    window.localStorage.setItem("flh.explanation-language.v1", "zh");
    const server = newServer([taskView(1, [draftV1])]);
    serve(server);
    await openTask();
    fireEvent.click(screen.getByRole("button", { name: "Request feedback on version 1" }));
    const c1 = within(await screen.findByRole("group", { name: "Feedback report on version 1" })).getByRole("group", { name: "Correction 1" });
    expect(within(c1).getByText(feedbackV1.corrections[0].hint_zh)).toBeInTheDocument();
    expect(within(c1).queryByText(feedbackV1.corrections[0].hint_en)).toBeNull();
  });

  it("is offered in Simplified Chinese, with the French kept as written", async () => {
    window.localStorage.setItem("flh.ui-locale.v1", "zh-CN");
    serve(newServer([taskView(1, [draftV1])]));
    render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
    fireEvent.click(screen.getByRole("button", { name: "写作" }));
    fireEvent.click(await screen.findByRole("button", { name: invitation.title }));
    expect(await screen.findByRole("button", { name: "请求版本 1 的反馈" })).toBeInTheDocument();
    expect(screen.getByText(invitation.prompt)).toBeInTheDocument();
    expect(screen.getByLabelText("版本 1 的文本").textContent).toBe(draftV1);
  });

  it("is not part of the public demo", async () => {
    const server = newServer([taskView(1, [draftV1])]);
    serve(server);
    render(
      <StrictMode>
        <PublicDemoApp />
      </StrictMode>,
    );
    expect(await screen.findByRole("search")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Writing" })).toBeNull();
    await waitFor(() => expect(server.calls.length).toBeGreaterThan(0));
    expect(server.calls.filter((c) => c.path.startsWith("/api/writing"))).toEqual([]);
  });
});
