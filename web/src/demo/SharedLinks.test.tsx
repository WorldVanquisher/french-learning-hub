import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PublicDemoApp from "../PublicDemoApp";
import { demoServer, QUESTION } from "./demoTestServer";

// Shared links that name nothing in this build, and the keyboard return path
// (demo/history.ts): coming back to a screen focuses the control that left it.

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
});

// Each test starts on a new last entry (jsdom keeps one session history per file).
const renderDemo = async (url = "/", options: Parameters<typeof demoServer>[0] = {}, locale?: string) => {
  if (locale) window.localStorage.setItem("flh.ui-locale.v1", locale);
  window.history.pushState(null, "", url);
  const server = demoServer(options);
  render(<StrictMode><PublicDemoApp /></StrictMode>);
  return server;
};
const firstCard = () => screen.findByRole("button", { name: /One question, two pronouns/ });
const exampleHeading = () => screen.findByRole("heading", { level: 2, name: "One question, two pronouns" });
const conceptHeading = (name: RegExp = /the pronouns y and en/) => screen.findByRole("heading", { level: 2, name });
const sourceHeading = () => screen.findByRole("heading", { level: 3, name: "Original learning record #9" });
const click = (name: string | RegExp) => fireEvent.click(screen.getAllByRole("button", { name })[0]);
// A click that also focuses the button, as a keyboard user's Enter does.
const press = (name: string | RegExp) => {
  const button = screen.getAllByRole("button", { name })[0];
  button.focus();
  fireEvent.click(button);
};
const MALFORMED = /That link does not match anything in this demo\. Start with an example below or search the library\./;

describe("a link that matches nothing says so", () => {
  it.each(["/#concept=abc", "/#example=nope", "/#concept=12&unit=", "/#mode=semantic&preset=nope", `/#q=${"a".repeat(201)}`])(
    "opens the start with a notice for %s and writes the start's address",
    async (url) => {
      await renderDemo(url);
      expect(await screen.findByText(MALFORMED)).toHaveAttribute("role", "status");
      expect(await firstCard()).toBeInTheDocument();
      expect(window.location.hash).toBe("");
    },
  );

  it("shows no notice for the start itself or a working link", async () => {
    await renderDemo("/");
    await firstCard();
    expect(screen.queryByText(MALFORMED)).toBeNull();
    cleanup();
    await renderDemo("/#example=y-en");
    await exampleHeading();
    expect(screen.queryByText(MALFORMED)).toBeNull();
  });

  it("drops the notice at the visitor's next move and for a later working fragment", async () => {
    await renderDemo("/#concept=abc");
    await screen.findByText(MALFORMED);
    click(/One question, two pronouns/);
    await exampleHeading();
    click("← Back to examples and search");
    await firstCard();
    expect(screen.queryByText(MALFORMED)).toBeNull();
    // A malformed fragment typed into the address bar during the visit.
    window.history.pushState(null, "", "/#concept=12&unit=x");
    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate", { state: null }));
    });
    expect(await screen.findByText(MALFORMED)).toBeInTheDocument();
    window.history.pushState(null, "", "/#concept=12");
    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate", { state: null }));
    });
    await conceptHeading();
    click("← Back to all concepts");
    await firstCard();
    expect(screen.queryByText(MALFORMED)).toBeNull();
  });

  it("says it in 简体中文 too", async () => {
    await renderDemo("/#example=nope", {}, "zh-CN");
    expect(await screen.findByText(/这个链接与本演示中的任何内容都不对应/)).toBeInTheDocument();
  });
});

describe("a link to an ID this build lacks leads on to a working example", () => {
  it("opens the example from a missing Concept without reloading, and Back returns to the link", async () => {
    await renderDemo("/#concept=999");
    expect(await screen.findByText(/This link names Concept #999, which this demo build does not have/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
    const before = window.history.length;
    const marker = (window as unknown as { __sameDocument?: number });
    marker.__sameDocument = 1;
    click("Open the example “One question, two pronouns”");
    expect(await screen.findByText(QUESTION)).toBeInTheDocument();
    expect(window.location.hash).toBe("#example=y-en");
    expect(window.history.length).toBe(before + 1);
    expect(marker.__sameDocument).toBe(1);
    window.history.back();
    expect(await screen.findByText(/This link names Concept #999/)).toBeInTheDocument();
  });

  it("opens the example a missing unit's link came from, in 简体中文", async () => {
    await renderDemo("/#example=y-en&concept=12&unit=999", {}, "zh-CN");
    expect(await screen.findByText(/这个链接指向单元 #999，但此演示构建中没有它/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "再试一次" })).toBeNull();
    click("打开示例“一个问题，两个代词”");
    expect(await screen.findByText(QUESTION)).toBeInTheDocument();
    expect(window.location.hash).toBe("#example=y-en");
  });

  it("keeps the retry for a failure that may pass", async () => {
    await renderDemo("/#concept=12", { fail: { "/knowledge-library/concepts/12": 503 } });
    expect(await screen.findByRole("alert")).toHaveTextContent("(503)");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.queryByText(/which this demo build does not have/)).toBeNull();
  });
});

describe("coming back focuses the control that left the screen", () => {
  it("returns from the evidence to the source button used, by the in-page back and by the browser's Back", async () => {
    await renderDemo();
    await firstCard();
    press(/One question, two pronouns/);
    await exampleHeading();
    press("Open the Concept and its evidence");
    await conceptHeading();
    press("View source record #9 for unit #13");
    await sourceHeading();
    press("← Back to concept #12");
    await conceptHeading();
    await waitFor(() => expect(screen.getByRole("button", { name: "View source record #9 for unit #13" })).toHaveFocus());

    window.history.forward();
    const heading = await sourceHeading();
    await waitFor(() => expect(screen.getByRole("heading", { level: 2, name: /Where unit #13 came from/ })).toHaveFocus());
    expect(heading).toBeInTheDocument();
    window.history.back();
    await conceptHeading();
    await waitFor(() => expect(screen.getByRole("button", { name: "View source record #9 for unit #13" })).toHaveFocus());

    // …and from the Concept to the example's step 3 button.
    window.history.back();
    await exampleHeading();
    await waitFor(() => expect(screen.getByRole("button", { name: "Open the Concept and its evidence" })).toHaveFocus());
    // …and from the example to its card.
    window.history.back();
    await waitFor(() => expect(screen.getByRole("button", { name: /One question, two pronouns/ })).toHaveFocus());
  });

  it("returns to the example's step 4 button from the evidence it opened", async () => {
    await renderDemo("/#example=y-en");
    await exampleHeading();
    press("See the evidence for “y remplace à + lieu”");
    await sourceHeading();
    press("← Back to the example “One question, two pronouns”");
    await exampleHeading();
    await waitFor(() => expect(screen.getByRole("button", { name: "See the evidence for “y remplace à + lieu”" })).toHaveFocus());
  });

  it("returns to the search field when Back undoes a search", async () => {
    await renderDemo();
    await firstCard();
    const field = screen.getByLabelText("Search learned material");
    field.focus();
    fireEvent.change(field, { target: { value: "il faut" } });
    fireEvent.submit(field.closest("form")!);
    const result = await screen.findByRole("button", { name: "subjunctive after « il faut que »" });
    result.focus();
    fireEvent.click(result);
    await conceptHeading(/subjunctive after « il faut que »/);
    window.history.back();
    await waitFor(() => expect(screen.getByRole("button", { name: "subjunctive after « il faut que »" })).toHaveFocus());
    window.history.back();
    await waitFor(() => expect(screen.getByLabelText("Search learned material")).toHaveValue(""));
    await waitFor(() => expect(screen.getByLabelText("Search learned material")).toHaveFocus());
  });

  it("focuses the heading when nothing was focused on the way out (a pointer click in some browsers)", async () => {
    await renderDemo();
    await firstCard();
    click(/One question, two pronouns/);
    await exampleHeading();
    click("Open the Concept and its evidence");
    await conceptHeading();
    (document.activeElement as HTMLElement | null)?.blur();
    click("View source record #9 for unit #12");
    await sourceHeading();
    window.history.back();
    const heading = await conceptHeading();
    await waitFor(() => expect(heading).toHaveFocus());
  });
});
