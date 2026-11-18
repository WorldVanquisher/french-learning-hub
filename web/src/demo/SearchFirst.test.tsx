import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PublicDemoApp from "../PublicDemoApp";
import { demoServer } from "./demoTestServer";

// A first visitor who searches instead of opening an example: the results
// follow the search form directly, and a submitted search brings what it found
// into view (FLH-153 follow-up, items 21–23).

let scrolled: Element[] = [];
beforeEach(() => {
  scrolled = [];
  // jsdom has no layout; record what the page asks to bring into view.
  Element.prototype.scrollIntoView = vi.fn(function (this: Element) {
    scrolled.push(this);
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
  delete (Element.prototype as Partial<Element>).scrollIntoView;
});

const renderDemo = async (url = "/") => {
  window.history.pushState(null, "", url);
  demoServer();
  render(<StrictMode><PublicDemoApp /></StrictMode>);
  await screen.findByRole("button", { name: /One question, two pronouns/ });
};
const search = (q: string) => {
  const field = screen.getByLabelText("Search learned material");
  field.focus();
  fireEvent.change(field, { target: { value: q } });
  fireEvent.submit(field.closest("form")!);
};
const follows = (a: Node, b: Node) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

describe("the demo's search results follow the form", () => {
  it("shows how search works after the results, outside the form", async () => {
    await renderDemo();
    search("il faut");
    const result = await screen.findByRole("button", { name: "subjunctive after « il faut que »" });
    const help = screen.getByText(/is one idea you have learned, such as a grammar rule/);
    const form = screen.getByRole("search");
    expect(form).not.toContainElement(help);
    expect(follows(result, help)).toBe(true);
    // The public demo's own note stays in the form, next to the modes it explains.
    expect(form).toContainElement(screen.getByRole("note"));
  });
});

describe("a submitted search brings what it found into view", () => {
  it("scrolls to the first result, and leaves focus in the form", async () => {
    await renderDemo();
    search("il faut");
    const result = await screen.findByRole("button", { name: "subjunctive after « il faut que »" });
    await waitFor(() => expect(scrolled).toContain(result.closest("li")));
    expect(screen.getByLabelText("Search learned material")).toHaveFocus();
  });

  it("scrolls to the help when nothing matched", async () => {
    await renderDemo();
    search("zzz");
    await screen.findByText("Nothing found? Try one of these");
    await waitFor(() => expect(scrolled.some((e) => e.classList.contains("demo-no-match"))).toBe(true));
  });

  it("does not scroll for a search opened by a link or by Back", async () => {
    await renderDemo("/#q=il+faut");
    await screen.findByRole("button", { name: "subjunctive after « il faut que »" });
    expect(scrolled).toEqual([]);
    search("pronouns");
    await screen.findByRole("button", { name: "the pronouns y and en" });
    await waitFor(() => expect(scrolled.length).toBe(1));
    act(() => window.history.back());
    await screen.findByRole("button", { name: "subjunctive after « il faut que »" });
    await new Promise((r) => setTimeout(r, 50));
    expect(scrolled.filter((e) => e.classList.contains("library-result")).length).toBe(1);
  });
});
