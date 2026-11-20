// The practice prototype in jsdom, from Review Today, on the SEALED Extraction
// 2.1 fixtures: today's practice, an approved concept (recall before reveal,
// the source, new sentences, choices), a source revision during the visit
// (withdrawn, kept drafts, a refused late check, restored IDs), resuming after
// inspecting evidence, the study packet preview and copy, the two tutor
// sessions, this visit's log and export, and a reload that forgets everything.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "../i18n";
import { ReviewToday } from "../pages/ReviewToday";
import { FIXTURE_DOCUMENTS } from "./extractionPracticeFixture";
import { FixtureError } from "./practiceFixture";
import { getSnapshot, listenerCount, openPanel, resetPracticeVisit } from "./practiceStore";

afterEach(() => {
  cleanup();
  resetPracticeVisit();
  vi.restoreAllMocks();
  vi.useRealTimers();
  window.localStorage.clear();
});

const STUDY_MD = FIXTURE_DOCUMENTS.find((d) => d.name === "study-y-en-r1.md")!.text;
const FORBIDDEN = (JSON.parse(FIXTURE_DOCUMENTS.find((d) => d.name === "cases.json")!.text) as { cases: Record<string, { expect: { forbidden_strings: string[] } }> }).cases[
  "study-packet-without-answers"
].expect.forbidden_strings;

function serve() {
  globalThis.fetch = vi.fn(async (input: string | URL | Request) => {
    const url = new URL(String(input), "http://localhost");
    const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    if (url.pathname === "/api/review-today")
      return json(200, { schema_version: "review_today_v1", generated_at: "t", zone: "UTC", today: "2026-11-19", items: [], history: { notebook_items: 0, speaking_exercises: 0, speaking_takes: 0 }, sources: { speaking: true, notebook: true } });
    return json(404, { error: "not found" });
  }) as unknown as typeof fetch;
}

const renderToday = () =>
  render(
    <LocaleProvider>
      <ReviewToday onOpenSpeaking={vi.fn()} onOpenSource={vi.fn()} onShow={vi.fn()} />
    </LocaleProvider>,
  );

const conceptRow = (sourceId: string) => document.querySelector(`[data-source="practice"][data-source-id="${sourceId}"]`) as HTMLElement;

async function openPanelUI() {
  serve();
  renderToday();
  fireEvent.click(await screen.findByRole("button", { name: "Show the practice prototype (synthetic data)…" }));
  await screen.findByRole("list", { name: "Approved concepts to practise" });
}

async function openConcept(sourceId = "y-en-demo", heading = "Practise: y vs en") {
  await openPanelUI();
  fireEvent.click(within(conceptRow(sourceId)).getByRole("button", { name: "Open the concept" }));
  const h = await screen.findByRole("heading", { name: heading });
  await waitFor(() => expect(h).toHaveFocus());
}

const card = (id: string) => screen.getByRole("group", { name: `Exercise ${id}` });
const stateOf = (id: string) => card(id).querySelector(".feed-state") as HTMLElement;
const type = (id: string, text: string) => fireEvent.change(within(card(id)).getByRole("textbox"), { target: { value: text } });
const summary = () => document.querySelector('[data-practice="summary"]') as HTMLElement;
const back = async () => {
  fireEvent.click(screen.getByRole("button", { name: "← Back to Review Today" }));
  await screen.findByRole("list", { name: "Approved concepts to practise" });
};

describe("Practice prototype on the sealed Extraction 2.1 fixtures", () => {
  it("opens with verified fixtures, a small set for today and both approved concepts, labelled synthetic and page-only", async () => {
    await openPanelUI();
    // the open button is replaced by the panel: focus lands on its heading, never on the body
    await waitFor(() => expect(screen.getByRole("heading", { name: "Practice from approved concepts (prototype)" })).toHaveFocus());
    const prov = document.querySelector('[data-fixture="verified"]')!;
    expect(prov).toHaveTextContent("Sealed fixtures: 22 documents from the Extraction 2.1 handoff (SHA256SUMS bad6f86e9911…), each re-checked in this page.");
    expect(prov.querySelectorAll("[data-doc]")).toHaveLength(22);
    expect(prov.querySelector('[data-doc="tutor-y-en-r1.json"]')).toHaveAttribute("data-origin", "generated");
    const today = screen.getByRole("list", { name: "Today's practice: 3 items to start with" });
    expect([...today.querySelectorAll("[data-practice]")].map((li) => `${li.getAttribute("data-practice")}:${li.getAttribute("data-pick-reason")}`)).toEqual([
      "p-664f7533a19d:missed_last_time",
      "p-e61b319d2129:missed_last_time",
      "p-baa71166205b:not_an_option_last_time",
    ]);
    const rows = within(screen.getByRole("list", { name: "Approved concepts to practise" })).getAllByRole("listitem");
    expect(rows.map((r) => [r.getAttribute("data-source"), r.getAttribute("data-reason"), r.getAttribute("data-source-id")])).toEqual([
      ["practice", "practice_outcome", "y-en-demo"],
      ["practice", "practice_outcome", "savoir-connaitre-demo"],
    ]);
    expect(rows[0]).toHaveTextContent("5 practice items from an approved concept. Recorded in the feed: 1 missed, 1 revealed, 1 self-checked, 2 correct.");
    expect(rows[0]).toHaveTextContent("Based on: source y-en-demo revision 1 (fd55a3600f1c), feed flh_practice_review_feed_v1, keys from tutor packet pk-d3fe3ae8566c");
    expect(screen.getByText(/A fixed synthetic example from the extraction prototype, not your data\. Disappears on reload/)).toBeInTheDocument();
    expect(document.querySelector('[data-week="empty"]')).toHaveTextContent("No practice yet this week.");
  });

  it("refuses to open when a fixture checksum does not match", async () => {
    serve();
    await act(async () => openPanel(async () => Promise.reject(new FixtureError("fixture checksum mismatch for feed-y-en-demo-r2.json: recorded 095dc9da0116…, computed 1234…"))));
    renderToday();
    expect(await screen.findByRole("alert")).toHaveTextContent("The practice feed could not be read: fixture checksum mismatch for feed-y-en-demo-r2.json");
    expect(document.querySelector('[data-fixture="refused"]')).not.toBeNull();
    expect(screen.queryByRole("list", { name: "Approved concepts to practise" })).toBeNull();
  });

  it("recalls before anything is revealed, then opens the source", async () => {
    await openConcept();
    expect(screen.getByText(/Disappears on reload: your answers, reveals and self-checks stay in this page only/)).toBeInTheDocument();
    expect(document.querySelector('[data-source="locked"]')).not.toBeNull();
    // closed: no focusable content inside the source part but its own button
    const sourcePart = document.querySelector('[data-section="source"]')!;
    expect([...sourcePart.querySelectorAll("button, a[href], input, textarea, [tabindex]:not([tabindex='-1'])")].map((e) => e.textContent)).toEqual(["Open the source now (counts as a reveal)"]);
    const recall = card("p-2ea892e5eaa0");
    fireEvent.click(within(recall).getByRole("button", { name: "Check my recall" }));
    const field = within(recall).getByLabelText("What you remember (stays in this page)");
    expect(within(recall).getByRole("alert")).toHaveTextContent("Write your answer first, or reveal without answering.");
    expect(field).toHaveFocus();
    fireEvent.change(field, { target: { value: "« y » après à (j'y vais), « en » après de (j'en viens)." } });
    fireEvent.keyDown(field, { key: "Enter", ctrlKey: true });
    expect(stateOf("p-2ea892e5eaa0")).toHaveTextContent("Done: Check it yourself.");
    expect(stateOf("p-2ea892e5eaa0")).toHaveAttribute("data-announce", "done");
    expect(within(recall).getByRole("group", { name: "Reference" })).toHaveTextContent("Ask which preposition introduces the place");
    fireEvent.click(within(recall).getByRole("button", { name: "I had it" }));
    expect(within(recall).getByRole("button", { name: "I had it" })).toHaveAttribute("aria-pressed", "true");
    const evidence = screen.getByRole("list", { name: "Your own words, as quoted" });
    expect(within(evidence).getAllByRole("listitem")).toHaveLength(4);
    const knowledge = screen.getByRole("list", { name: "Approved knowledge" });
    const contrast = knowledge.querySelector('[data-knowledge="k-0d3281b28da6"]')!;
    expect(contrast).toHaveTextContent("Your correction, accepted from codex's proposal c1 (packet pk-e2920fe276cb).");
    const example = knowledge.querySelector('[data-knowledge="k-cb9627cc7213"]')!;
    expect(example.querySelector('[data-withheld="key"]')).not.toBeNull();
    expect(example).not.toHaveTextContent("Oui, j'en reviens.");
    expect(summary()).toHaveAttribute("data-independent", "1");
    expect(summary()).toHaveTextContent("1 self-checked as known");
  });

  it("shows what the feed does not offer from the learner's question, with each quote's grounding, never as an exercise (R3-055)", async () => {
    await openConcept();
    fireEvent.click(screen.getByRole("button", { name: "Open the source now (counts as a reveal)" }));
    const list = await screen.findByRole("list", { name: "Not offered from your question" });
    const claim = list.querySelector('[data-not-offered="k-5ca79503ae78"]')!;
    expect(claim).toHaveAttribute("data-support", "unsupported");
    expect(claim).toHaveAttribute("data-state", "rejected");
    expect(claim).toHaveTextContent("you rejected it");
    expect(claim).toHaveTextContent("« en » goes with every verb of movement, so « j'en vais » is also correct.");
    const g = claim.querySelector('[data-grounding="not_found"]')!;
    expect(g).toHaveTextContent("Quote « en goes with every verb of movement »: not_found.");
    expect(g).toHaveTextContent("these words are not in the learner's question or context");
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    expect(getSnapshot().catalog!.timelines.flatMap((tl) => tl.states.flatMap((s) => s.feed.items.flatMap((i) => i.knowledge_ids)))).not.toContain("k-5ca79503ae78");
  });

  it("keeps the revision, the draft and the visit when the extraction feed times out, says so, and retries only on request (R3-056)", async () => {
    await openConcept();
    type("p-664f7533a19d", "Oui, j'en");
    await back();
    fireEvent.click(screen.getByRole("checkbox", { name: "Simulate an extraction timeout" }));
    fireEvent.click(within(conceptRow("y-en-demo")).getByRole("button", { name: "Simulate the next feed: revision 2 (synthetic)" }));
    const row = conceptRow("y-en-demo");
    expect(row).toHaveAttribute("data-revision", "1");
    const banner = row.querySelector('[data-reason-code="feed_timeout"]') as HTMLElement;
    expect(banner).toHaveTextContent("The extraction feed did not answer in time. Nothing changed: you are still on revision 1, and your answers and drafts are kept.");
    await waitFor(() => expect(banner).toHaveFocus());
    expect(document.querySelectorAll(`[id="${banner.id}"]`)).toHaveLength(1);
    const v = getSnapshot().visit;
    expect(v.events.at(-1)).toMatchObject({ code: "feed_timeout", sourceId: "y-en-demo", revision: 1 });
    expect(Object.values(v.drafts)).toContain("Oui, j'en");
    fireEvent.click(screen.getByRole("checkbox", { name: "Simulate an extraction timeout" }));
    fireEvent.click(within(banner).getByRole("button", { name: "Try the feed again" }));
    // the answer in progress makes the revision wait; nothing is lost
    expect(conceptRow("y-en-demo").querySelector('[data-reason-code="feed_timeout"]')).toBeNull();
    expect(conceptRow("y-en-demo").querySelector('[data-reason-code="revision_waiting"]')).not.toBeNull();
    fireEvent.click(within(conceptRow("y-en-demo")).getByRole("button", { name: "Open the concept" }));
    await screen.findByRole("heading", { name: "Practise: y vs en" });
    expect(within(card("p-664f7533a19d")).getByRole("textbox")).toHaveValue("Oui, j'en");
  });

  it("offers one way on when today's practice from a concept is done: the other concept's first item (R3-085)", async () => {
    await openConcept("savoir-connaitre-demo", "Practise: connaître vs savoir");
    const data = getSnapshot().catalog!.timelines.find((tl) => tl.sourceId === "savoir-connaitre-demo")!.states[0].data!;
    expect(document.querySelector("[data-done-today]")).toBeNull();
    for (const it of data.items) {
      const c = card(it.practice_id);
      if (it.kind === "choose") fireEvent.click(within(c).getByRole("button", { name: data.rubric(it.practice_id).answer! }));
      else {
        fireEvent.change(within(c).getByRole("textbox"), { target: { value: data.rubric(it.practice_id).answer ?? data.rubric(it.practice_id).reference[0] ?? "x" } });
        fireEvent.click(within(c).getByRole("button", { name: it.kind === "explain" ? "Check my recall" : "Check" }));
        const had = within(c).queryByRole("button", { name: "I had it" });
        if (had) fireEvent.click(had);
      }
    }
    const done = document.querySelector("[data-done-today]") as HTMLElement;
    expect(done).toHaveTextContent("Today's practice from this concept is done");
    expect(done).toHaveAttribute("data-next-action", "other_concept");
    fireEvent.click(within(done).getByRole("button", { name: "Practise next: y vs en" }));
    await screen.findByRole("heading", { name: "Practise: y vs en" });
  });

  it("starts today's first item straight on its field, suggests the next useful exercise, and resumes after inspecting evidence", async () => {
    await openPanelUI();
    fireEvent.click(within(document.querySelector('[data-practice="p-664f7533a19d"]') as HTMLElement).getByRole("button", { name: "Start" }));
    await screen.findByRole("heading", { name: "Practise: y vs en" });
    await waitFor(() => expect(within(card("p-664f7533a19d")).getByRole("textbox")).toHaveFocus());
    const next = document.querySelector("[data-next]")!;
    expect(next).toHaveAttribute("data-next", "p-2ea892e5eaa0");
    expect(next).toHaveTextContent("After the miss on p-664f7533a19d: recall the rule itself.");
    // leave the exercise to inspect its evidence, then come back: the draft is kept
    type("p-664f7533a19d", "Oui, j'en");
    fireEvent.click(within(card("p-664f7533a19d")).getByRole("button", { name: "Inspect the evidence for this exercise" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "2. Your source" })).toHaveFocus());
    fireEvent.click(screen.getByRole("button", { name: "Back to exercise p-664f7533a19d" }));
    const field = within(card("p-664f7533a19d")).getByRole("textbox");
    expect(field).toHaveFocus();
    expect(field).toHaveValue("Oui, j'en");
    fireEvent.click(within(next as HTMLElement).getByRole("button", { name: "Start it" }));
    expect(within(card("p-2ea892e5eaa0")).getByRole("textbox")).toHaveFocus();
  });

  it("grades like the extraction lane, keeps answers after a reveal apart, and applies a repeated check once", async () => {
    await openConcept();
    type("p-8d5cabf2ab59", "Oui, nous en allons.");
    fireEvent.click(within(card("p-8d5cabf2ab59")).getByRole("button", { name: "Check" }));
    expect(card("p-8d5cabf2ab59").querySelector("[data-outcome]")).toHaveAttribute("data-outcome", "incorrect");
    // the same unchanged answer sent again (double click, repeated Ctrl+Enter): one attempt
    fireEvent.click(within(card("p-8d5cabf2ab59")).getByRole("button", { name: "Check" }));
    fireEvent.keyDown(within(card("p-8d5cabf2ab59")).getByRole("textbox"), { key: "Enter", ctrlKey: true });
    expect(getSnapshot().visit.attempts).toHaveLength(1);
    expect(getSnapshot().visit.duplicatesIgnored).toBe(2);
    type("p-8d5cabf2ab59", "Oui, on y va !");
    fireEvent.keyDown(within(card("p-8d5cabf2ab59")).getByRole("textbox"), { key: "Enter", ctrlKey: true });
    expect(card("p-8d5cabf2ab59").querySelector("[data-outcome]")).toHaveTextContent("Correct It matches « Oui, on y va. ».");
    // reveal, then answer: counted after a reveal, not as independent
    fireEvent.click(within(card("p-0e74504cf958")).getByRole("button", { name: "Reveal without answering" }));
    expect(stateOf("p-0e74504cf958")).toHaveTextContent("Revealed: the reference is shown below. This is not an attempt.");
    fireEvent.click(within(card("p-0e74504cf958")).getByRole("button", { name: "en" }));
    expect(card("p-0e74504cf958")).toHaveTextContent("After a reveal: not independent");
    expect([summary().dataset.independent, summary().dataset.afterReveal, summary().dataset.revealed]).toEqual(["2", "1", "1"]);
    // a mistake that matched a known confusion becomes its own practice item
  });

  it("turns a quote-linked mistake into a practice item that leads today's set", async () => {
    await openConcept();
    type("p-664f7533a19d", "Oui, j'y reviens.");
    fireEvent.click(within(card("p-664f7533a19d")).getByRole("button", { name: "Check" }));
    fireEvent.click(within(card("p-664f7533a19d")).getByRole("button", { name: "Practise this mistake again later" }));
    expect(card("p-664f7533a19d")).toHaveTextContent("Saved for this visit as practice item personal-1");
    await back();
    const first = screen.getByRole("list", { name: /Today's practice/ }).querySelector("[data-practice]")!;
    expect([first.getAttribute("data-practice"), first.getAttribute("data-pick-reason")]).toEqual(["p-664f7533a19d", "personal_correction"]);
    expect(document.querySelector('[data-personal="personal-1"]')).toHaveTextContent("quoting ev-17c9dfcc08, ev-fd704f2740");
  });

  it("withdraws a revised source's exercises, keeps their history, then restores the same IDs on the newer revision", async () => {
    await openConcept();
    fireEvent.click(within(card("p-22a947cd7f5c")).getByRole("button", { name: "y" }));
    await back();
    fireEvent.click(within(conceptRow("y-en-demo")).getByRole("button", { name: "Simulate the next feed: revision 2 (synthetic)" }));
    const row = conceptRow("y-en-demo");
    expect(row).toHaveAttribute("data-revision", "2");
    expect(row.querySelector('[data-reason-code="withdrawn_source_revised"]')).toHaveTextContent("5 exercises withdrawn in revision 2, waiting for your review in the extraction tool.");
    expect([...document.querySelectorAll("[data-pick-reason]")].map((e) => e.getAttribute("data-practice"))).not.toContain("p-664f7533a19d");
    // history kept, marked withdrawn
    const entry = document.querySelector('[data-entry]')!;
    expect(entry).toHaveAttribute("data-availability", "withdrawn");
    expect(entry).toHaveTextContent("Withdrawn since revision 2");
    fireEvent.click(within(row).getByRole("button", { name: "Open the concept" }));
    await screen.findByRole("heading", { name: "Practise: y vs en" });
    expect(document.querySelector("[data-nothing-offered]")).toHaveTextContent("Revision 2 offers no exercise from this concept yet.");
    const w = document.querySelector('[data-withdrawn="p-22a947cd7f5c"]')!;
    expect(w).toHaveTextContent("The extraction feed says: not offered from revision 2: its knowledge needs the learner's review or was rejected");
    expect(w).toHaveTextContent("Your 1 answer on it stays in this visit's history.");
    // R4-WB-027: the evidence it was built on stays visible, from revision 1
    const prev = w.querySelector('[data-previous-evidence="1"]')!;
    expect(prev.querySelector("summary")).toHaveTextContent("What it was built on, in revision 1 (no longer in the latest source)");
    expect(prev.querySelectorAll("[data-evidence]").length).toBeGreaterThan(0);
    expect([...prev.querySelectorAll("q")].every((q) => (q.textContent ?? "").length > 3)).toBe(true);
    expect(screen.queryByRole("group", { name: "Exercise p-22a947cd7f5c" })).toBeNull();
    await back();
    fireEvent.click(within(conceptRow("y-en-demo")).getByRole("button", { name: "Simulate the next feed: revision 2 (synthetic)" }));
    expect(conceptRow("y-en-demo").querySelector('[data-reason-code="restored_same_id"]')).toHaveTextContent("5 exercises restored with their previous IDs on revision 2.");
    fireEvent.click(within(conceptRow("y-en-demo")).getByRole("button", { name: "Open the concept" }));
    await screen.findByRole("heading", { name: "Practise: y vs en" });
    expect(document.querySelector('[data-reason-code="restored_same_id"]')).toHaveTextContent("5 exercises are back with the same IDs on revision 2");
    fireEvent.click(within(card("p-22a947cd7f5c")).getByRole("button", { name: "y" }));
    expect(getSnapshot().visit.attempts.map((a) => `${a.practiceId}@${a.revision}:${a.outcome}`)).toEqual(["p-22a947cd7f5c@1:correct", "p-22a947cd7f5c@2:correct"]);
  });

  it("lets a revision wait while an answer is in progress, keeps the draft, and refuses a late check for a withdrawn exercise", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await openConcept();
    fireEvent.click(screen.getByRole("button", { name: "← Back to Review Today" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Simulate a slow check (2 seconds)" }));
    fireEvent.click(within(conceptRow("y-en-demo")).getByRole("button", { name: "Open the concept" }));
    await screen.findByRole("heading", { name: "Practise: y vs en" });
    type("p-8d5cabf2ab59", "Oui, on y va !");
    fireEvent.click(within(card("p-8d5cabf2ab59")).getByRole("button", { name: "Check" }));
    expect(stateOf("p-8d5cabf2ab59")).toHaveTextContent("Checking your answer…");
    expect(stateOf("p-8d5cabf2ab59")).toHaveAttribute("data-announce", "pending");
    // not disabled (focus would be lost): marked aria-disabled, and a second press does nothing
    const checkBtn = within(card("p-8d5cabf2ab59")).getByRole("button", { name: "Check" });
    expect(checkBtn).toHaveAttribute("aria-disabled", "true");
    checkBtn.focus();
    fireEvent.click(checkBtn);
    expect(checkBtn).toHaveFocus();
    expect(getSnapshot().visit.pending).toHaveLength(1);
    type("p-664f7533a19d", "Oui, j'en reviens");
    fireEvent.click(screen.getByRole("button", { name: "← Back to Review Today" }));
    await screen.findByRole("list", { name: "Approved concepts to practise" });
    fireEvent.click(within(conceptRow("y-en-demo")).getByRole("button", { name: "Simulate the next feed: revision 2 (synthetic)" }));
    expect(conceptRow("y-en-demo").querySelector('[data-reason-code="revision_waiting"]')).toHaveTextContent("Revision 2 of this source has arrived. You have an answer in progress, so it waits");
    expect(conceptRow("y-en-demo")).toHaveAttribute("data-revision", "1");
    fireEvent.click(within(conceptRow("y-en-demo")).getByRole("button", { name: "Apply revision 2" }));
    await act(async () => {
      vi.advanceTimersByTime(2100);
    });
    const v = getSnapshot().visit;
    expect(v.attempts).toHaveLength(0);
    expect(v.events.map((e) => e.code)).toEqual(expect.arrayContaining(["revision_waiting", "revision_applied", "draft_kept_withdrawn", "late_response_withdrawn"]));
    fireEvent.click(within(conceptRow("y-en-demo")).getByRole("button", { name: "Open the concept" }));
    await screen.findByRole("heading", { name: "Practise: y vs en" });
    const kept = document.querySelector('[data-reason-code="draft_kept_withdrawn"]')!;
    expect(kept.querySelector('[data-kept="p-8d5cabf2ab59"]')).toHaveTextContent("Oui, on y va !");
    expect(kept.querySelector('[data-kept="p-664f7533a19d"]')).toHaveTextContent("Oui, j'en reviens");
  });

  it("copies and shows the study packet with the network gone: no request is made after the page loaded (R3-057)", async () => {
    await openConcept();
    // from here on every request fails, as when the connection drops
    const offline = vi.fn(async () => Promise.reject(new TypeError("Failed to fetch")));
    globalThis.fetch = offline as unknown as typeof fetch;
    const share = document.querySelector('[data-packet="pk-afdb387f3af6"]') as HTMLElement;
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    fireEvent.click(within(share).getByRole("button", { name: "Copy the study packet" }));
    await waitFor(() => expect(share.querySelector('[data-copy="copied"]')).toHaveTextContent("Copied packet pk-afdb387f3af6"));
    expect((writeText.mock.calls[0] as unknown as [string])[0]).toBe(STUDY_MD);
    fireEvent.click(within(share).getByRole("button", { name: "Show the packet text" }));
    expect((within(share).getByLabelText("Packet pk-afdb387f3af6 (Markdown)") as HTMLTextAreaElement).value).toBe(STUDY_MD);
    expect(offline).not.toHaveBeenCalled();
  });

  it("previews the study packet beside the copy action; nothing of this visit is in it; dismissing the text keeps the draft; the clipboard can fail", async () => {
    await openConcept();
    type("p-664f7533a19d", "UNIQUE-DRAFT-7f3a");
    fireEvent.click(within(card("p-664f7533a19d")).getByRole("button", { name: "Check" }));
    type("p-8d5cabf2ab59", "Oui, ce soir nous y allons, DRAFT-9b2c");
    const share = document.querySelector('[data-packet="pk-afdb387f3af6"]')!;
    expect(share.querySelector('[data-share="scope"]')).toHaveTextContent("About: y vs en, source y-en-demo revision 1 (fd55a3600f1c), flh_practice_packet_v2.");
    expect(share.querySelector('[data-share="contents"]')).toHaveTextContent(`In it: 6 approved knowledge items, 4 quoted excerpts and 5 exercise prompts (${STUDY_MD.length} characters).`);
    expect(share.querySelector('[data-share="left-off"]')).toHaveTextContent("Where we left off: last confusion y / en; next exercise p-8d5cabf2ab59.");
    expect(share.querySelector('[data-share="continuity"]')).toHaveTextContent("It continues packet pk-e2920fe276cb and names 1 change since then.");
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    fireEvent.click(within(share as HTMLElement).getByRole("button", { name: "Copy the study packet" }));
    await waitFor(() => expect(share.querySelector('[data-copy="copied"]')).toHaveTextContent("Copied packet pk-afdb387f3af6"));
    const copied = (writeText.mock.calls[0] as unknown as [string])[0];
    expect(copied).toBe(STUDY_MD);
    for (const f of [...FORBIDDEN, "UNIQUE-DRAFT-7f3a", "DRAFT-9b2c"]) expect(copied).not.toContain(f);
    // show the text, dismiss it with Escape: focus back on the toggle, the draft untouched
    fireEvent.click(within(share as HTMLElement).getByRole("button", { name: "Show the packet text" }));
    const area = within(share as HTMLElement).getByLabelText("Packet pk-afdb387f3af6 (Markdown)");
    fireEvent.keyDown(area, { key: "Escape" });
    await waitFor(() => expect(within(share as HTMLElement).getByRole("button", { name: "Show the packet text" })).toHaveFocus());
    expect(within(card("p-8d5cabf2ab59")).getByRole("textbox")).toHaveValue("Oui, ce soir nous y allons, DRAFT-9b2c");
    // the browser refuses: the text is shown and selected
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: vi.fn(async () => Promise.reject(new Error("denied"))) } });
    await act(async () => {
      fireEvent.click(within(share as HTMLElement).getByRole("button", { name: "Copy the study packet" }));
    });
    const shown = (await within(share as HTMLElement).findByLabelText("Packet pk-afdb387f3af6 (Markdown)")) as HTMLTextAreaElement;
    expect(shown.value).toBe(STUDY_MD);
    await waitFor(() => expect(shown).toHaveFocus());
    expect(share.querySelector('[data-copy="selected"]')).toHaveTextContent("The browser did not allow copying.");
    // back: focus on the control that opened the concept
    fireEvent.click(screen.getByRole("button", { name: "← Back to Review Today" }));
    await waitFor(() => expect(within(conceptRow("y-en-demo")).getByRole("button", { name: "Open the concept" })).toHaveFocus());
  });

  it("walks from one tutor to another: every proposal reviewed before anything is accepted", async () => {
    await openPanelUI();
    fireEvent.click(screen.getByRole("button", { name: "Show the two tutor sessions…" }));
    const s1 = screen.getByRole("region", { name: "Session 1: codex" });
    const s2 = screen.getByRole("region", { name: "Session 2: claude-code" });
    expect([...s1.querySelectorAll("[data-proposal]")].map((e) => `${e.getAttribute("data-proposal")}:${e.getAttribute("data-class")}`)).toEqual(["c1:accepted_candidate", "c2:duplicate", "c3:accepted_candidate"]);
    expect([...s2.querySelectorAll("[data-proposal]")].map((e) => `${e.getAttribute("data-proposal")}:${e.getAttribute("data-class")}`)).toEqual([
      "q1:conflict",
      "q2:accepted_candidate",
      "q3:duplicate",
      "q4:unknown_reference",
    ]);
    // the class is a text label, not a colour
    expect(s2.querySelector('[data-proposal="q1"] [data-class-tag]')).toHaveTextContent("Conflict");
    expect(s1.querySelector('[data-proposal="c1"]')).toHaveTextContent("You accepted c1 in the extraction tool: packet pk-afdb387f3af6 carries it.");
    expect(s2.querySelector('[data-left-off="pk-afdb387f3af6"]')).toHaveTextContent("Continues packet pk-e2920fe276cb.");
    expect(s2.querySelector("[data-last-confusion]")).toHaveTextContent("Last confusion: y / en on p-664f7533a19d (no answer text is shared).");
    expect(s1.querySelector('[data-proposal="c3"]')).toHaveTextContent("Not accepted here: exercise proposals stay in the preview.");
    expect(s1.querySelector('[data-proposal="c3"] [data-proposed-answer]')).toBeNull();
    fireEvent.click(within(s1.querySelector('[data-proposal="c3"]') as HTMLElement).getByRole("button", { name: "Show the proposed answer" }));
    expect(s1.querySelector('[data-proposal="c3"] [data-proposed-answer]')).toHaveTextContent("Oui, j'y vais ce soir.");
    const q2 = s2.querySelector('[data-proposal="q2"]') as HTMLElement;
    expect(q2.querySelector("[data-current]")).toHaveTextContent("« en » replaces a place introduced by « de »: « Je viens de la boulangerie, j'en viens. »");
    expect(q2.querySelector("[data-proposed]")).toHaveTextContent("« en » replaces a place introduced by « de », « du », « de la » or « des »");
    fireEvent.click(within(q2).getByRole("button", { name: "Accept q2 for this visit…" }));
    const confirm = within(q2).getByRole("group", { name: "Confirm proposal q2" });
    expect(confirm).toHaveTextContent("practice accept --work W --packet packet.json --proposals proposals.json --proposal q2");
    expect(getSnapshot().visit.accepted).toHaveLength(0);
    fireEvent.click(within(confirm).getByRole("button", { name: "Accept for this visit" }));
    expect(q2.querySelector('[data-accepted-visit="q2"]')).toHaveTextContent("q2 accepted for this visit only (page memory).");
    expect(s2.querySelector('[data-proposal="q1"]')).toHaveTextContent("Nothing to accept: only a candidate correction can be accepted.");
    // the concept view shows the visit-only acceptance beside the knowledge it changes
    fireEvent.click(within(conceptRow("y-en-demo")).getByRole("button", { name: "Open the concept" }));
    await screen.findByRole("heading", { name: "Practise: y vs en" });
    fireEvent.click(screen.getByRole("button", { name: "Open the source now (counts as a reveal)" }));
    expect(document.querySelector('[data-knowledge="k-40cbe73ae3f5"] [data-accepted-visit="claude-code:q2"]')).toHaveTextContent("Accepted for this visit only, from claude-code's proposal q2:");
  });

  it("never sends or stores a typed answer; only the learner's opt-in puts it in an export, and a reload removes it (R4-WB-032, R4-WB-033)", async () => {
    const SECRET = "ZZ-PRIVATE-7731 je le connais";
    await openConcept("savoir-connaitre-demo", "Practise: connaître vs savoir");
    const calls: string[] = [];
    const real = globalThis.fetch;
    globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      calls.push(`${String(input)} ${String(init?.body ?? "")}`);
      return real(input, init);
    }) as unknown as typeof fetch;
    type("p-3ac3b47e483a", SECRET);
    fireEvent.click(within(card("p-3ac3b47e483a")).getByRole("button", { name: "Check" }));
    fireEvent.click(within(card("p-3ac3b47e483a")).getByRole("button", { name: "Not yet" }));
    type("p-e61b319d2129", SECRET);
    await back();
    const storage = () => [...Object.keys(window.localStorage).map((k) => window.localStorage.getItem(k)), ...Object.keys(window.sessionStorage).map((k) => window.sessionStorage.getItem(k))].join(" ");
    expect(calls.join(" ")).not.toContain("ZZ-PRIVATE-7731");
    expect(storage()).not.toContain("ZZ-PRIVATE-7731");
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    fireEvent.click(screen.getByRole("button", { name: "Copy this visit as JSON" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect((writeText.mock.calls[0] as unknown as [string])[0]).not.toContain("ZZ-PRIVATE-7731");
    fireEvent.click(screen.getByRole("checkbox", { name: "Include my answer texts (off by default)" }));
    fireEvent.click(screen.getByRole("button", { name: "Copy this visit as JSON" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(2));
    expect((writeText.mock.calls[1] as unknown as [string])[0]).toContain("ZZ-PRIVATE-7731");
    // removal: a reload forgets the visit (attempts, drafts, the opt-in)
    resetPracticeVisit();
    const after = getSnapshot();
    expect([after.visit.attempts.length, Object.keys(after.visit.drafts).length, JSON.stringify(after).includes("ZZ-PRIVATE")]).toEqual([0, 0, false]);
    expect(calls.join(" ")).not.toContain("ZZ-PRIVATE-7731");
  });

  it("traces each attempt to its source, revision and evidence, and lists a check in flight apart (R4-WB-026, R4-WB-028)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await openConcept();
    fireEvent.click(within(card("p-22a947cd7f5c")).getByRole("button", { name: "y" }));
    await back();
    fireEvent.click(screen.getByRole("checkbox", { name: "Simulate a slow check (2 seconds)" }));
    fireEvent.click(within(conceptRow("y-en-demo")).getByRole("button", { name: "Open the concept" }));
    await screen.findByRole("heading", { name: "Practise: y vs en" });
    type("p-8d5cabf2ab59", "Oui, on y va !");
    fireEvent.click(within(card("p-8d5cabf2ab59")).getByRole("button", { name: "Check" }));
    await back();
    const log = document.querySelector('[data-log="visit"]')!;
    const pending = log.querySelector('[data-log="pending"]')!;
    expect(pending.querySelectorAll("[data-pending]")).toHaveLength(1);
    expect(pending).toHaveTextContent("Waiting for a check (not an attempt yet)");
    expect(pending).toHaveTextContent("p-8d5cabf2ab59");
    const done = [...log.querySelectorAll("[data-entry]")];
    expect(done.map((e) => e.querySelector("code")?.textContent)).not.toContain("p-8d5cabf2ab59");
    const trace = done[0].querySelector("[data-trace]")!;
    expect(trace).toHaveAttribute("data-trace", "y-en-demo@1");
    expect(trace.textContent).toMatch(/^\(source y-en-demo, revision 1; evidence ev-[0-9a-f]+/);
    await act(async () => {
      vi.advanceTimersByTime(2100);
    });
    expect(document.querySelector('[data-log="pending"]')).toBeNull();
  });

  it("logs the visit by skill and day with each outcome's origin, and exports it without answer texts unless asked", async () => {
    await openConcept("savoir-connaitre-demo", "Practise: connaître vs savoir");
    fireEvent.click(within(card("p-3ca128617083")).getByRole("button", { name: "connais" }));
    type("p-3ac3b47e483a", "Oui, je le connais bien.");
    fireEvent.click(within(card("p-3ac3b47e483a")).getByRole("button", { name: "Check" }));
    fireEvent.click(within(card("p-3ac3b47e483a")).getByRole("button", { name: "Not yet" }));
    await back();
    const log = document.querySelector('[data-log="visit"]')!;
    expect(log.querySelector('[data-skill="recognition"]')).toHaveTextContent("1: 1 correct, 0 not yet, 0 self-checked, 0 not an option");
    expect(log.querySelector('[data-skill="production"]')).toHaveTextContent("1: 0 correct, 0 not yet, 1 self-checked, 0 not an option");
    expect(log.querySelector('[data-week="active"]')).not.toBeNull();
    expect([...log.querySelectorAll("[data-entry]")].map((e) => e.getAttribute("data-origin"))).toEqual(["exact_match", "learner_judgment"]);
    expect(log.querySelector('[data-recorded="feed"]')).toHaveTextContent("Recorded by the extraction tool");
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    fireEvent.click(screen.getByRole("button", { name: "Copy this visit as JSON" }));
    await waitFor(() => expect(log.querySelector('[data-export="copied"]')).toHaveTextContent("Copied, without your answer texts."));
    const plain = JSON.parse((writeText.mock.calls[0] as unknown as [string])[0]);
    expect(plain.schema).toBe("flh_wb_practice_visit_export_v0");
    expect(JSON.stringify(plain)).not.toContain("je le connais bien");
    expect(plain.attempts.map((a: { feed: string; origin: string }) => `${a.feed}:${a.origin}`)).toEqual([
      "feed-savoir-connaitre-demo-r1.json:exact_match",
      "feed-savoir-connaitre-demo-r1.json:learner_judgment",
    ]);
    fireEvent.click(screen.getByRole("checkbox", { name: "Include my answer texts (off by default)" }));
    fireEvent.click(screen.getByRole("button", { name: "Copy this visit as JSON" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(2));
    expect((writeText.mock.calls[1] as unknown as [string])[0]).toContain("Oui, je le connais bien.");
  });

  it("keeps every expected answer hidden until an answer or a deliberate reveal (R2-023)", async () => {
    await openPanelUI();
    const keys = [...FORBIDDEN, "Oui, je connais ton frère.", "Oui, je sais nager.", "Non, je ne sais pas nager."];
    expect(keys.filter((k) => document.body.textContent!.includes(k))).toEqual([]);
    fireEvent.click(within(conceptRow("y-en-demo")).getByRole("button", { name: "Open the concept" }));
    await screen.findByRole("heading", { name: "Practise: y vs en" });
    expect(keys.filter((k) => document.body.textContent!.includes(k))).toEqual([]);
    // the recall opens the source, but a worked example's key stays withheld until its exercises are done
    type("p-2ea892e5eaa0", "y après à, en après de");
    fireEvent.click(within(card("p-2ea892e5eaa0")).getByRole("button", { name: "Check my recall" }));
    expect(document.querySelector('[data-source="open"]')).not.toBeNull();
    expect(keys.filter((k) => document.body.textContent!.includes(k))).toEqual([]);
    // one answer shows that exercise's key only
    fireEvent.click(within(card("p-664f7533a19d")).getByRole("button", { name: "Reveal without answering" }));
    expect(card("p-664f7533a19d")).toHaveTextContent("Reference answer: Oui, j'en reviens.");
    expect(document.body.textContent).not.toContain("Oui, nous y allons.");
  });

  it("cues a transfer to a new sentence after the same confusion twice (R2-025)", async () => {
    await openConcept("savoir-connaitre-demo", "Practise: connaître vs savoir");
    expect(document.querySelector("[data-next]")).toHaveAttribute("data-transfer", "false");
    type("p-e61b319d2129", "Oui, je connais nager.");
    fireEvent.click(within(card("p-e61b319d2129")).getByRole("button", { name: "Check" }));
    const next = document.querySelector("[data-next]")!;
    expect(next).toHaveAttribute("data-next", "p-3ac3b47e483a");
    expect(next).toHaveAttribute("data-transfer", "true");
    expect(next.querySelector('[data-reason-code="transfer_after_repeated_confusion"]')).toHaveTextContent("You have mixed these forms up 2 times.");
    fireEvent.click(within(next as HTMLElement).getByRole("button", { name: "Start it" }));
    expect(within(card("p-3ac3b47e483a")).getByRole("textbox")).toHaveFocus();
    expect(card("p-3ac3b47e483a")).toHaveTextContent("New sentence: not in your source");
  });

  it("explains a revision in Chinese while the producer's reason stays as written (R2-019)", async () => {
    window.localStorage.setItem("flh.ui-locale.v1", "zh-CN");
    serve();
    renderToday();
    fireEvent.click(await screen.findByRole("button", { name: "显示练习原型（合成数据）…" }));
    await screen.findByRole("list", { name: "今日练习：从 3 项开始" });
    fireEvent.click(within(conceptRow("y-en-demo")).getByRole("button", { name: "模拟下一份反馈：修订版本 2（合成数据）" }));
    expect(conceptRow("y-en-demo").querySelector('[data-reason-code="withdrawn_source_revised"]')).toHaveTextContent("修订版本 2 撤回了 5 道练习，正在等待你在提取工具中审核。");
    fireEvent.click(within(conceptRow("y-en-demo")).getByRole("button", { name: "打开这个概念" }));
    await screen.findByRole("heading", { name: "练习：y vs en" });
    const w = document.querySelector('[data-withdrawn="p-2ea892e5eaa0"]')!;
    expect(w).toHaveTextContent("提取反馈的说明：");
    expect(w.querySelector("q")).toHaveTextContent("not offered from revision 2: its knowledge needs the learner's review or was rejected");
    expect(w).toHaveTextContent("本次访问中你没有答过这道练习。");
    expect(document.querySelector("[data-nothing-offered]")).toHaveTextContent("修订版本 2 暂时没有提供这个概念的练习。");
    fireEvent.click(screen.getByRole("button", { name: "← 返回今日复习" }));
    await screen.findByRole("list", { name: "可练习的已批准概念" });
    fireEvent.click(within(conceptRow("y-en-demo")).getByRole("button", { name: "模拟下一份反馈：修订版本 2（合成数据）" }));
    expect(conceptRow("y-en-demo").querySelector('[data-reason-code="restored_same_id"]')).toHaveTextContent("5 道练习以原来的编号在修订版本 2 中恢复。");
    expect(document.body.textContent).not.toMatch(/\{[a-zA-Z]+\}/);
  });

  it("labels every history entry with its source: exact match, your judgment, revealed, agent suggestion, extraction record (R2-061/062)", async () => {
    await openConcept();
    fireEvent.click(within(card("p-22a947cd7f5c")).getByRole("button", { name: "y" }));
    type("p-8d5cabf2ab59", "Oui, ce soir nous y allons avec Paul.");
    fireEvent.click(within(card("p-8d5cabf2ab59")).getByRole("button", { name: "Check" }));
    fireEvent.click(within(card("p-8d5cabf2ab59")).getByRole("button", { name: "I had it" }));
    fireEvent.click(within(card("p-0e74504cf958")).getByRole("button", { name: "Reveal without answering" }));
    await back();
    fireEvent.click(screen.getByRole("button", { name: "Show the two tutor sessions…" }));
    const q2 = document.querySelector('[data-session="2"] [data-proposal="q2"]') as HTMLElement;
    fireEvent.click(within(q2).getByRole("button", { name: "Accept q2 for this visit…" }));
    fireEvent.click(within(q2).getByRole("button", { name: "Accept for this visit" }));
    const log = document.querySelector('[data-log="visit"]')!;
    expect([...log.querySelectorAll("[data-history-day] [data-entry]")].map((e) => `${e.getAttribute("data-origin")}:${e.textContent!.includes("Exact answer match") || e.textContent!.includes("Your judgment") || e.textContent!.includes("Revealed") || e.textContent!.includes("Agent suggestion")}`)).toEqual([
      "exact_match:true",
      "learner_judgment:true",
      "revealed:true",
      "agent_suggestion:true",
    ]);
    expect(log.querySelector('[data-entry="accepted:2:q2"]')).toHaveTextContent("claude-code's proposal q2 for k-40cbe73ae3f5, accepted for this visit only.");
    expect(log.querySelector('[data-accepted-in-tool="codex:c1"]')).toHaveTextContent("codex's proposal c1 for k-0d3281b28da6, accepted by you in the extraction tool.");
  });

  it("revisits one confusion straight from the log, without going through today's set (R2-064)", async () => {
    await openConcept("savoir-connaitre-demo", "Practise: connaître vs savoir");
    fireEvent.click(within(card("p-3ca128617083")).getByRole("button", { name: "sais" }));
    await back();
    const conf = document.querySelector('[data-confusion="p-3ca128617083"]') as HTMLElement;
    fireEvent.click(within(conf).getByRole("button", { name: "Practise p-3ca128617083 again" }));
    await screen.findByRole("heading", { name: "Practise: connaître vs savoir" });
    await waitFor(() => expect(document.getElementById("feed-p-3ca128617083")).toHaveFocus());
  });

  it("keeps withdrawn material in the week and the history, marked, after a revision (R2-067)", async () => {
    await openConcept();
    fireEvent.click(within(card("p-22a947cd7f5c")).getByRole("button", { name: "y" }));
    fireEvent.click(within(card("p-0e74504cf958")).getByRole("button", { name: "Reveal without answering" }));
    await back();
    const before = [...document.querySelectorAll("[data-week='active'] [data-day]")].map((e) => e.getAttribute("data-count"));
    fireEvent.click(within(conceptRow("y-en-demo")).getByRole("button", { name: "Simulate the next feed: revision 2 (synthetic)" }));
    const after = [...document.querySelectorAll("[data-week='active'] [data-day]")].map((e) => e.getAttribute("data-count"));
    expect(after).toEqual(before);
    expect(after.reduce((n, x) => n + Number(x), 0)).toBe(2);
    const entries = [...document.querySelectorAll("[data-history-day] [data-entry]")];
    expect(entries.map((e) => e.getAttribute("data-availability"))).toEqual(["withdrawn", "withdrawn"]);
    expect(entries[0]).toHaveTextContent("Withdrawn since revision 2");
    expect(document.querySelector('[data-skill="recognition"]')).toHaveTextContent("1: 1 correct");
    // its "practise again" is not offered while withdrawn
    expect(document.querySelector('[data-confusion]')).toBeNull();
  });

  it("renders a mixed French and Chinese excerpt with each run in its language (R2-074)", async () => {
    const { Excerpt } = await import("./ConceptPractice");
    const { container } = render(<Excerpt text="我问老师：« [Oui, j'en vais.] » 对吗？" />);
    const outer = container.querySelector(".feed-excerpt")!;
    expect(outer).toHaveAttribute("lang", "fr");
    expect([...outer.querySelectorAll('[lang="zh-CN"]')].map((e) => e.textContent)).toEqual(["我问老师：« ", "对吗？"].map((x) => x.replace("« ", "")));
    expect(outer.querySelector("mark")).toHaveTextContent("Oui, j'en vais.");
    expect(outer.querySelector("mark [lang]")).toBeNull();
  });

  it("releases every store subscription when Review Today unmounts, however often it is visited (R2-083)", async () => {
    expect(listenerCount()).toBe(0);
    for (let i = 0; i < 5; i++) {
      serve();
      const v = renderToday();
      if (i === 0) fireEvent.click(await screen.findByRole("button", { name: "Show the practice prototype (synthetic data)…" }));
      await screen.findByRole("list", { name: "Approved concepts to practise" });
      fireEvent.click(within(conceptRow("y-en-demo")).getByRole("button", { name: "Open the concept" }));
      await screen.findByRole("heading", { name: "Practise: y vs en" });
      expect(listenerCount()).toBeGreaterThan(0);
      v.unmount();
      expect(listenerCount()).toBe(0);
      // the concept stays open in the store (page memory) across visits; close it for the next round
      const { closeConcept } = await import("./practiceStore");
      closeConcept();
    }
  });

  it("forgets everything on reload, as the page says", async () => {
    await openConcept();
    fireEvent.click(within(card("p-0e74504cf958")).getByRole("button", { name: "en" }));
    cleanup();
    resetPracticeVisit(); // a reload starts the module over
    serve();
    renderToday();
    expect(await screen.findByRole("button", { name: "Show the practice prototype (synthetic data)…" })).toHaveAttribute("aria-expanded", "false");
    expect(getSnapshot().visit.attempts).toHaveLength(0);
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("renders in Chinese with every placeholder filled; French and producer text stay as they are", async () => {
    window.localStorage.setItem("flh.ui-locale.v1", "zh-CN");
    serve();
    const view = renderToday();
    fireEvent.click(await screen.findByRole("button", { name: "显示练习原型（合成数据）…" }));
    await screen.findByRole("list", { name: "今日练习：从 3 项开始" });
    fireEvent.click(screen.getByRole("button", { name: "显示两次辅导会话……" }));
    expect(view.container.textContent).not.toMatch(/\{[a-zA-Z]+\}/);
    fireEvent.click(within(conceptRow("y-en-demo")).getByRole("button", { name: "打开这个概念" }));
    await screen.findByRole("heading", { name: "练习：y vs en" });
    expect(view.container.textContent).not.toMatch(/\{[a-zA-Z]+\}/);
    expect(view.container.textContent).toContain("Tu reviens du marché ? Answer with « y » or « en ».");
    expect(document.querySelector('[data-share="scope"]')).toHaveTextContent("关于：y vs en，来源 y-en-demo 修订版本 1（fd55a3600f1c），flh_practice_packet_v2。");
  });
});
