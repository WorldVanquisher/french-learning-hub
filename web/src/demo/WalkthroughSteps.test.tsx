import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PublicDemoApp from "../PublicDemoApp";
import { hashForScreen, linkFromHash, NO_SEARCH } from "./deepLink";
import { markSharedWords, sharedWords } from "./ExampleScreen";
import { demoServer, QUESTION } from "./demoTestServer";

// The guided example's optional step-by-step walkthrough: each step is a link
// (#example=…&step=N) and a history entry, Back and Forward retrace the steps,
// and from step 2 the question marks the words that reappear in its rules.
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
});

const renderDemo = async (url: string, locale?: string) => {
  if (locale) window.localStorage.setItem("flh.ui-locale.v1", locale);
  window.history.pushState(null, "", url);
  const server = demoServer();
  render(<StrictMode><PublicDemoApp /></StrictMode>);
  return server;
};
const popTo = (url: string, state: unknown) =>
  act(() => {
    window.history.replaceState(state, "", url);
    window.dispatchEvent(new PopStateEvent("popstate", { state }));
  });

describe("walkthrough links", () => {
  it("reads and writes a step on an example only", () => {
    expect(linkFromHash("#example=y-en&step=3").screen).toEqual({ kind: "example", example: "y-en", step: 3 });
    expect(hashForScreen({ kind: "example", example: "y-en", step: 2 })).toBe("#example=y-en&step=2");
    expect(hashForScreen({ kind: "example", example: "y-en" })).toBe("#example=y-en");
    // R2-085: a step is optional, so one that is invalid, blank or on another
    // screen is left out and the rest of the link opens.
    for (const odd of ["#example=y-en&step=0", "#example=y-en&step=5", "#example=y-en&step=x", "#example=y-en&step="])
      expect(linkFromHash(odd), odd).toEqual({ screen: { kind: "example", example: "y-en" }, search: NO_SEARCH, malformed: false });
    expect(linkFromHash("#step=2")).toEqual({ screen: { kind: "results" }, search: NO_SEARCH, malformed: false });
    expect(linkFromHash("#example=y-en&concept=12&step=2").screen).toEqual({ kind: "concept", conceptId: 12, from: "y-en" });
  });

  it("marks whole question words that reappear in the rules, and longer forms of long words only", () => {
    const { container } = render(<p>{markSharedWords("Il faut que tu viennes demain ; ils remplacent", ["il faut que + subjonctif de venir", "remplace"])}</p>);
    expect([...container.querySelectorAll("mark")].map((m) => m.textContent)).toEqual(["Il", "faut", "que", "remplacent"]);
    expect(sharedWords("Il faut que tu viennes ; il faut", ["il faut que"])).toEqual(["Il", "faut", "que", "il"]);
    expect(sharedWords("Pourquoi ?", ["subjonctif"])).toEqual([]);
  });
});

describe("walking an example step by step", () => {
  it("starts on request, puts each step in the address and history, and focuses each step's heading", async () => {
    await renderDemo("/#example=y-en");
    await screen.findByText(QUESTION, { selector: "blockquote" });
    expect(screen.queryByRole("navigation", { name: "Walkthrough" })).toBeNull();
    const before = window.history.length;
    fireEvent.click(screen.getByRole("button", { name: "Walk through it step by step" }));
    expect(window.location.hash).toBe("#example=y-en&step=1");
    expect(screen.getByText("Step 1 of 4: the learner's question")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("heading", { level: 3, name: /The learner asked/ })).toHaveFocus());
    expect(screen.getByRole("button", { name: "← Previous step" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Next step →" }));
    expect(window.location.hash).toBe("#example=y-en&step=2");
    await waitFor(() => expect(screen.getByRole("heading", { level: 3, name: /What was extracted/ })).toHaveFocus());
    expect(document.querySelector("[aria-current=step]")?.getAttribute("aria-labelledby")).toBe("demo-step-extracted");
    // What changed: the question's words that reappear in the rules are marked.
    const marks = [...document.querySelectorAll("blockquote.demo-question mark")].map((m) => m.textContent);
    expect(marks).toEqual(["en", "en", "remplacent"]);
    // …and listed, marked, beside the rules, with the way on in the current step.
    const changed = document.querySelector(".demo-walk-changed")!;
    expect(changed).toHaveTextContent("Words of the question that reappear in these rules: en, remplacent.");
    expect([...changed.querySelectorAll("mark")].map((m) => m.textContent)).toEqual(["en", "remplacent"]);
    expect(document.querySelector("[aria-current=step] .demo-walk")).not.toBeNull();
    expect(document.querySelectorAll(".demo-walk")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Next step →" }));
    fireEvent.click(screen.getByRole("button", { name: "Next step →" }));
    expect(window.location.hash).toBe("#example=y-en&step=4");
    expect(screen.getByRole("button", { name: "Next step →" })).toBeDisabled();
    expect(window.history.length).toBe(before + 4);
  });

  it("restores the step on Back and Forward, and a shared step link opens at that step", async () => {
    await renderDemo("/#example=y-en");
    await screen.findByText(QUESTION, { selector: "blockquote" });
    fireEvent.click(screen.getByRole("button", { name: "Walk through it step by step" }));
    const step1 = window.history.state;
    fireEvent.click(screen.getByRole("button", { name: "Next step →" }));
    const step2 = window.history.state;
    popTo("/#example=y-en&step=1", step1);
    expect(screen.getByText("Step 1 of 4: the learner's question")).toBeInTheDocument();
    popTo("/#example=y-en&step=2", step2);
    expect(screen.getByText("Step 2 of 4: the rules taken from it")).toBeInTheDocument();
    cleanup();

    await renderDemo("/#example=y-en&step=3");
    expect(await screen.findByText("Step 3 of 4: the Concept they are filed under")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("heading", { level: 3, name: /Filed under 1 Concept/ })).toHaveFocus());
  });

  it("returns from the Concept to the step it was opened from", async () => {
    await renderDemo("/#example=y-en&step=3");
    await screen.findByText("Step 3 of 4: the Concept they are filed under");
    fireEvent.click(screen.getAllByRole("button", { name: /^Open the Concept “.+” and its evidence$/ })[0]);
    await screen.findByRole("heading", { level: 2, name: /the pronouns y and en/ });
    expect(window.location.hash).toBe("#example=y-en&concept=12");
    fireEvent.click(screen.getByRole("button", { name: "← Back to the example “One question, two pronouns”" }));
    await waitFor(() => expect(window.location.hash).toBe("#example=y-en&step=3"));
  });

  it("reads the same in 简体中文", async () => {
    await renderDemo("/#example=y-en&step=2", "zh-CN");
    expect(await screen.findByText("第 2 步，共 4 步：从中提取的规则")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下一步 →" })).toBeInTheDocument();
    expect(screen.getByText(/提问中在这些规则里再次出现的词/)).toBeInTheDocument();
  });
});
