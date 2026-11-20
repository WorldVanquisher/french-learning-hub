// Notebook to practice against a stateful fake of the notebook list and its
// retry save: preview shows source, draft question and action together; edits
// are kept; one mark per record however often approve is clicked or a second
// version is made; unreadable or vanished sources give an actionable message;
// a failed save keeps every draft; keyboard paths; an accent-rich synthetic
// workbook passes through unchanged.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "../i18n";
import type { NotebookItem } from "../types/notebook";
import { NotebookPractice } from "./NotebookPractice";
import { accentItem } from "./practiceDraft.fixture";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

type Fail = { status: number; times: number };
function serve(items: NotebookItem[], fail: Record<number, Fail> = {}) {
  const puts: number[] = [];
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    if (method === "GET" && url.pathname === "/api/mistake-notebook/items") return json(200, { items, unlinked_notice: "n" });
    const m = /^\/api\/mistake-notebook\/items\/(\d+)\/retry$/.exec(url.pathname);
    if (method === "PUT" && m) {
      const id = Number(m[1]);
      puts.push(id);
      const f = fail[id];
      if (f && f.times > 0) {
        f.times--;
        return json(f.status, { error: f.status === 404 ? "notebook record not found" : "could not record the retry decision" });
      }
      const it = items.find((x) => x.entry_id === id)!;
      const changed = !it.retry.marked;
      it.retry = { marked: true, since: "2026-11-19T10:00:00Z" };
      return json(200, { item: it, changed });
    }
    return json(404, { error: "not found" });
  }) as unknown as typeof fetch;
  return puts;
}

const renderPage = () => {
  const props = { onOpenSource: vi.fn(), onOpenRecord: vi.fn(), onOpenToday: vi.fn() };
  render(
    <LocaleProvider>
      <NotebookPractice {...props} />
    </LocaleProvider>,
  );
  return props;
};

const checkbox = (entry: number) => document.querySelector<HTMLInputElement>(`li[data-entry="${entry}"] input[type=checkbox]`)!;
const drafts = () => [...document.querySelectorAll<HTMLElement>("li.practice-draft")];

describe("Notebook to practice", () => {
  it("previews source, draft question and action together, keeps edits, and adds each record to Review Today once", async () => {
    const items = [accentItem(1), accentItem(2, { prompt: "Où se trouve l'école ?", title: "Le trajet d'Éloïse" })];
    const puts = serve(items);
    const props = renderPage();
    await screen.findByRole("heading", { name: "Make practice from your notes" });
    fireEvent.click(checkbox(1));
    fireEvent.click(checkbox(2));
    fireEvent.click(screen.getByRole("button", { name: "Preview 2 drafts" }));
    const heading = await screen.findByRole("heading", { name: "2 practice drafts" });
    await waitFor(() => expect(heading).toHaveFocus());
    const [first] = drafts();
    const source = within(first).getByRole("group", { name: "Source" });
    expect(source).toHaveTextContent("Pourquoi Hélène choisit-elle le cours du soir à l'école Saint-Éloi ?");
    expect(source).toHaveTextContent("Parce qu'elle préfère l'été.");
    expect(source).toHaveTextContent("Workbook script, revision 1, question 1");
    const q = within(first).getByLabelText("Practice question (you can edit it)") as HTMLTextAreaElement;
    expect(q.value).toBe("Pourquoi Hélène choisit-elle le cours du soir à l'école Saint-Éloi ?");
    expect((within(first).getByLabelText("What you will do") as HTMLSelectElement).value).toBe("answer_again");
    const typed = "Pourquoi Hélène préfère-t-elle étudier le soir ?\n« Ça dépend… »";
    fireEvent.change(q, { target: { value: typed } });
    // Repeated clicks: one PUT per record.
    const approve = screen.getByRole("button", { name: "Approve and add 2 records to Review Today" });
    await act(async () => {
      fireEvent.click(approve);
      fireEvent.click(approve);
      fireEvent.click(approve);
    });
    await screen.findByRole("heading", { name: "Added to Review Today" });
    expect(puts).toEqual([1, 2]);
    expect(screen.getByRole("status")).toHaveTextContent("2 records are in Review Today.");
    fireEvent.click(screen.getByRole("button", { name: "Open Review Today" }));
    expect(props.onOpenToday).toHaveBeenCalled();
    // The edited wording is what the learner practises, line break included.
    fireEvent.click(screen.getByRole("button", { name: "Practise these drafts now" }));
    const question = document.querySelector(".practice-question")!;
    expect(question.textContent).toBe(typed);
    expect(question).toHaveAttribute("lang", "fr");
  });

  it("makes a deliberate separate version without a second queue item", async () => {
    const items = [accentItem(1)];
    const puts = serve(items);
    renderPage();
    await screen.findByRole("heading", { name: "Make practice from your notes" });
    fireEvent.click(checkbox(1));
    fireEvent.click(screen.getByRole("button", { name: "Preview 1 draft" }));
    await screen.findByRole("heading", { name: "1 practice draft" });
    fireEvent.click(screen.getByRole("button", { name: "Make a separate version" }));
    await waitFor(() => expect(drafts()).toHaveLength(2));
    const second = drafts()[1];
    expect(second).toHaveAttribute("data-key", "1:2");
    expect(second).toHaveTextContent("Version 2");
    const q2 = within(second).getByLabelText("Practice question (you can edit it)");
    await waitFor(() => expect(q2).toHaveFocus());
    fireEvent.change(q2, { target: { value: "Racontez la journée d'Hélène en deux phrases." } });
    fireEvent.change(within(second).getByLabelText("What you will do"), { target: { value: "say_corrected" } });
    fireEvent.click(screen.getByRole("button", { name: "Approve and add 1 record to Review Today" }));
    await screen.findByRole("heading", { name: "Added to Review Today" });
    expect(puts).toEqual([1]);
    expect(screen.getByText(/Review Today lists each record once/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Practise these drafts now" }));
    expect(screen.getByRole("heading", { name: "Item 1 of 2" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reveal reference" }));
    fireEvent.click(screen.getByRole("button", { name: "Next item" }));
    expect(document.querySelector(".practice-question")!.textContent).toBe("Racontez la journée d'Hélène en deux phrases.");
    expect(screen.getByText("Say your sentence again aloud, corrected, then compare with the suggestion.")).toBeInTheDocument();
  });

  it("explains a source that disappeared or moved, and a record removed before approval", async () => {
    const items = [
      accentItem(1, { source_status: "missing", title: "", prompt: "" }),
      accentItem(2, { latest_version: 2 }),
      accentItem(3),
    ];
    serve(items, { 3: { status: 404, times: 1 } });
    const props = renderPage();
    await screen.findByRole("heading", { name: "Make practice from your notes" });
    expect(checkbox(1)).toBeDisabled();
    const missing = document.querySelector<HTMLElement>('li[data-entry="1"]')!;
    expect(missing).toHaveTextContent("This record's source can no longer be read (listening_item #900, item 1), so no draft can be made from it.");
    fireEvent.click(within(missing).getByRole("button", { name: "Open record #1" }));
    expect(props.onOpenRecord).toHaveBeenCalledWith(1);
    const moved = document.querySelector<HTMLElement>('li[data-entry="2"]')!;
    expect(moved).toHaveTextContent("Saved from an older version; the source now has version 2.");
    fireEvent.click(within(moved).getByRole("button", { name: "Open source" }));
    expect(props.onOpenSource).toHaveBeenCalledWith(expect.objectContaining({ skill: "listening", version: 1 }));
    fireEvent.click(checkbox(2));
    fireEvent.click(checkbox(3));
    fireEvent.click(screen.getByRole("button", { name: "Preview 2 drafts" }));
    await screen.findByRole("heading", { name: "2 practice drafts" });
    expect(drafts()[0]).toHaveTextContent("From version 1; the source now has version 2. This draft keeps version 1.");
    fireEvent.click(screen.getByRole("button", { name: "Approve and add 2 records to Review Today" }));
    const gone = await screen.findByText(/Record #3 no longer exists, so it was not added/);
    expect(gone.closest("li")).toHaveAttribute("data-key", "3:1");
    fireEvent.click(within(gone.closest("li")!).getByRole("button", { name: "Open record #3" }));
    expect(props.onOpenRecord).toHaveBeenCalledWith(3);
  });

  it("keeps every draft and edit across a recoverable save error and resends only what failed", async () => {
    const items = [accentItem(1), accentItem(2)];
    const puts = serve(items, { 2: { status: 500, times: 1 } });
    renderPage();
    await screen.findByRole("heading", { name: "Make practice from your notes" });
    fireEvent.click(checkbox(1));
    fireEvent.click(checkbox(2));
    fireEvent.click(screen.getByRole("button", { name: "Preview 2 drafts" }));
    await screen.findByRole("heading", { name: "2 practice drafts" });
    const edited = "Qu'est-ce qu'Hélène fait à l'hôpital ?";
    fireEvent.change(within(drafts()[1]).getByLabelText("Practice question (you can edit it)"), { target: { value: edited } });
    fireEvent.click(screen.getByRole("button", { name: "Approve and add 2 records to Review Today" }));
    expect(await screen.findByText("1 record was not added. Nothing else changed.")).toBeInTheDocument();
    expect(within(drafts()[1]).getByText(/Not saved: \(500\) could not record the retry decision\. Your drafts and edits are kept/)).toBeInTheDocument();
    expect((within(drafts()[1]).getByLabelText("Practice question (you can edit it)") as HTMLTextAreaElement).value).toBe(edited);
    fireEvent.click(screen.getByRole("button", { name: "Approve again" }));
    await screen.findByRole("heading", { name: "Added to Review Today" });
    expect(puts).toEqual([1, 2, 2]);
  });

  it("supports a keyboard path: preview, move between questions, go back, approve", async () => {
    const items = [accentItem(1), accentItem(2)];
    const puts = serve(items);
    renderPage();
    await screen.findByRole("heading", { name: "Make practice from your notes" });
    fireEvent.click(checkbox(1));
    fireEvent.click(checkbox(2));
    const previewButton = screen.getByRole("button", { name: "Preview 2 drafts" });
    fireEvent.click(previewButton);
    const heading = await screen.findByRole("heading", { name: "2 practice drafts" });
    await waitFor(() => expect(heading).toHaveFocus());
    const [q1, q2] = drafts().map((d) => within(d).getByLabelText("Practice question (you can edit it)"));
    q1.focus();
    fireEvent.keyDown(q1, { key: "ArrowDown", altKey: true });
    expect(q2).toHaveFocus();
    fireEvent.keyDown(q2, { key: "ArrowUp", altKey: true });
    expect(q1).toHaveFocus();
    fireEvent.change(q1, { target: { value: "Hélène, où étudie-t-elle ?" } });
    fireEvent.keyDown(q1, { key: "Escape" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Preview 2 drafts" })).toHaveFocus());
    // Back in the preview, the edit is still there.
    fireEvent.click(screen.getByRole("button", { name: "Preview 2 drafts" }));
    await screen.findByRole("heading", { name: "2 practice drafts" });
    const again = within(drafts()[0]).getByLabelText("Practice question (you can edit it)") as HTMLTextAreaElement;
    expect(again.value).toBe("Hélène, où étudie-t-elle ?");
    // A blank question blocks approval with an announced reason; the button
    // stays reachable and takes the learner to the field to fix.
    fireEvent.change(again, { target: { value: "   " } });
    expect(screen.getByRole("alert")).toHaveTextContent("Write a question before approving this draft.");
    expect(again).toHaveAttribute("aria-invalid", "true");
    const approveBlank = screen.getByRole("button", { name: "Approve and add 2 records to Review Today" });
    expect(approveBlank).toBeEnabled();
    screen.getByRole("button", { name: "Back to the selection" }).focus();
    fireEvent.click(approveBlank);
    expect(again).toHaveFocus();
    expect(screen.getByText("1 draft has no question yet. Write one, then approve: focus is on it.")).toBeInTheDocument();
    expect(puts).toEqual([]);
    fireEvent.change(again, { target: { value: "Hélène, où étudie-t-elle ?" } });
    await act(async () => {
      fireEvent.keyDown(again, { key: "Enter", ctrlKey: true });
    });
    const done = await screen.findByRole("heading", { name: "Added to Review Today" });
    await waitFor(() => expect(done).toHaveFocus());
    expect(puts).toEqual([1, 2]);
  });

  it("finishes a practice run and goes back to the approved drafts (regression: the button showed its catalog key)", async () => {
    serve([accentItem(1)]);
    renderPage();
    await screen.findByRole("heading", { name: "Make practice from your notes" });
    fireEvent.click(checkbox(1));
    fireEvent.click(screen.getByRole("button", { name: "Preview 1 draft" }));
    await screen.findByRole("heading", { name: "1 practice draft" });
    fireEvent.click(screen.getByRole("button", { name: "Approve and add 1 record to Review Today" }));
    await screen.findByRole("heading", { name: "Added to Review Today" });
    fireEvent.click(screen.getByRole("button", { name: "Practise these drafts now" }));
    fireEvent.click(screen.getByRole("button", { name: "Reveal reference" }));
    fireEvent.click(screen.getByRole("button", { name: "Finish" }));
    await screen.findByRole("heading", { name: "Practice finished" });
    const back = screen.getByRole("button", { name: "Back to the approved drafts" });
    expect(document.body.textContent).not.toMatch(/notePractice\./);
    fireEvent.click(back);
    expect(await screen.findByRole("heading", { name: "Added to Review Today" })).toBeInTheDocument();
  });

  it("does not resend a record that is already in Review Today", async () => {
    const puts = serve([accentItem(1, { retry: { marked: true, since: "2026-11-18T10:00:00Z" } })]);
    renderPage();
    await screen.findByRole("heading", { name: "Make practice from your notes" });
    fireEvent.click(checkbox(1));
    fireEvent.click(screen.getByRole("button", { name: "Preview 1 draft" }));
    await screen.findByRole("heading", { name: "1 practice draft" });
    fireEvent.click(screen.getByRole("button", { name: "Approve and add 1 record to Review Today" }));
    await screen.findByRole("heading", { name: "Added to Review Today" });
    expect(puts).toEqual([]);
    expect(screen.getByText(/was already in Review Today/)).toBeInTheDocument();
  });
});

