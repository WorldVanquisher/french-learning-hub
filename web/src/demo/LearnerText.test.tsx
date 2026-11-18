import { StrictMode } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PublicDemoApp from "../PublicDemoApp";
import { demoServer, QUESTION } from "./demoTestServer";

// The learner's own question and context keep their own direction in the
// public demo, so a record written in a right-to-left script (or starting with
// one) reads in its own order. French and Chinese text is unchanged: "auto"
// resolves to left-to-right for them (FLH-153 follow-up, item 35).

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
});

const renderDemo = (url: string) => {
  window.history.pushState(null, "", url);
  demoServer();
  render(<StrictMode><PublicDemoApp /></StrictMode>);
};

describe("learner text keeps its own direction", () => {
  it("on the example: the question and its context", async () => {
    renderDemo("/#example=y-en");
    const question = await screen.findByText(QUESTION);
    expect(question.closest("blockquote")).toHaveAttribute("dir", "auto");
    const context = question.closest("section")!.querySelector("p.hint");
    expect(context).toHaveAttribute("dir", "auto");
  });

  it("on the source evidence: the question, and the context isolated", async () => {
    renderDemo("/#concept=12&unit=12");
    await screen.findByRole("heading", { level: 3, name: "Original learning record #9" });
    const question = screen.getAllByText(QUESTION).find((e) => e.tagName === "BLOCKQUOTE");
    expect(question).toHaveAttribute("dir", "auto");
    const context = screen.getByText("Context").closest("div")!.querySelector("dd");
    expect(context?.firstElementChild?.tagName).toBe("BDI");
  });
});
