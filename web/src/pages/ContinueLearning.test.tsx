import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "../i18n";
import { ContinueLearning, loadContinue, type ContinueItem } from "./ContinueLearning";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const item = (skill: ContinueItem["skill"], id: number, createdAt: string, title = `${skill} ${id}`): ContinueItem => ({ skill, id, title, createdAt, detail: null });
const ok = (items: ContinueItem[]) => () => Promise.resolve(items);
const fail = () => Promise.reject(new Error("unavailable"));

describe("loadContinue", () => {
  it("keeps the newest item per section, newest section first, and names sections that failed", async () => {
    const r = await loadContinue({
      listening: fail,
      reading: ok([item("reading", 1, "2026-11-01T10:00:00Z"), item("reading", 4, "2026-11-03T10:00:00Z")]),
      writing: ok([]),
      speaking: ok([item("speaking", 2, "2026-11-05T09:00:00Z"), item("speaking", 3, "2026-11-05T09:00:00Z")]),
    });
    expect(r.items.map((i) => `${i.skill}#${i.id}`)).toEqual(["speaking#3", "reading#4"]);
    expect(r.failed).toEqual(["listening"]);
  });
});

describe("ContinueLearning", () => {
  it("lists what was started and opens the chosen item", async () => {
    const onContinue = vi.fn();
    const fetchers = {
      listening: ok([]),
      reading: ok([]),
      writing: ok([{ ...item("writing", 7, "2026-11-02T08:00:00Z", "Une lettre à Camille"), detail: { key: "home.continue.writingVersions" as const, count: 3 } }]),
      speaking: ok([item("speaking", 5, "2026-11-04T08:00:00Z", "Répondre à une invitation")]),
    };
    render(
      <LocaleProvider>
        <ContinueLearning onContinue={onContinue} fetchers={fetchers} />
      </LocaleProvider>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Looking for what you started");
    const first = await screen.findByRole("button", { name: "Continue Speaking: Répondre à une invitation" });
    expect(screen.getByText("Une lettre à Camille")).toHaveAttribute("lang", "fr");
    expect(screen.getByText(/3 saved versions/)).toBeInTheDocument();
    const buttons = screen.getAllByRole("button", { name: /^Continue / });
    expect(buttons.map((b) => b.getAttribute("aria-label"))).toEqual(["Continue Speaking: Répondre à une invitation", "Continue Writing: Une lettre à Camille"]);
    fireEvent.click(first);
    expect(onContinue).toHaveBeenCalledWith(expect.objectContaining({ skill: "speaking", id: 5 }));
  });

  it("says when nothing was started, and names a section it could not read", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const { unmount } = render(
      <LocaleProvider>
        <ContinueLearning onContinue={() => {}} fetchers={{ listening: ok([]), reading: ok([]), writing: ok([]), speaking: ok([]) }} />
      </LocaleProvider>,
    );
    expect(await screen.findByText("Nothing started yet. Choose a section below to begin.")).toBeInTheDocument();
    unmount();
    render(
      <LocaleProvider>
        <ContinueLearning onContinue={() => {}} fetchers={{ listening: ok([]), reading: fail, writing: ok([]), speaking: ok([item("speaking", 1, "2026-11-04T08:00:00Z")]) }} />
      </LocaleProvider>,
    );
    expect(await screen.findByText("Could not read Reading. The other sections are shown.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Continue Speaking/ })).toBeInTheDocument();
    expect(setItem).not.toHaveBeenCalled();
  });
});
