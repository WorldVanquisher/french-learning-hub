import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PublicDemoApp from "../PublicDemoApp";
import { KnowledgeLibrary } from "../pages/KnowledgeLibrary";
import { LocaleProvider } from "../i18n";
import { hashForScreen, linkFromHash, NO_SEARCH } from "./deepLink";
import { stepsBack } from "./history";
import { demoServer, QUESTION } from "./demoTestServer";

// The public demo's navigation contract (demo/history.ts): every screen is one
// history entry, an in-page back is the browser's Back when its screen is
// earlier in the visit (otherwise it replaces the entry), a submitted search
// is an entry, and the address names the screen and search, so a reload or a
// shared link reopens both.

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

// Each test starts on a new last entry: jsdom keeps one session history per
// file, and a push would otherwise drop forward entries an earlier test left.
const renderDemo = async (url = "/") => {
  window.history.pushState(null, "", url);
  const server = demoServer();
  render(<StrictMode><PublicDemoApp /></StrictMode>);
  return server;
};
const startScreen = () => screen.findByRole("button", { name: /One question, two pronouns/ });
const exampleHeading = () => screen.findByRole("heading", { level: 2, name: "One question, two pronouns" });
const conceptHeading = (name: RegExp = /the pronouns y and en/) => screen.findByRole("heading", { level: 2, name });
const sourceHeading = () => screen.findByRole("heading", { level: 3, name: "Original learning record #9" });
const click = (name: string | RegExp) => fireEvent.click(screen.getAllByRole("button", { name })[0]);
const search = (q: string) => {
  fireEvent.change(screen.getByLabelText("Search learned material"), { target: { value: q } });
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
};

describe("demo links name the screen and the search", () => {
  it("reads and writes keyword, filtered and preset searches before any screen", () => {
    expect(linkFromHash("#q=il+faut")).toEqual({
      screen: { kind: "results" },
      search: { mode: "keyword", q: "il faut", state: "all" },
      malformed: false,
    });
    expect(linkFromHash("#q=il+faut&concept=1")).toEqual({
      screen: { kind: "concept", conceptId: 1, from: undefined },
      search: { mode: "keyword", q: "il faut", state: "all" },
      malformed: false,
    });
    expect(linkFromHash("").malformed).toBe(false);
    expect(linkFromHash("#").malformed).toBe(false);
    expect(linkFromHash("#state=active").search).toEqual({ mode: "keyword", q: "", state: "active" });
    expect(linkFromHash("#mode=semantic&preset=right-now", ["right-now"]).search).toEqual({ mode: "semantic", q: "", state: "all", preset: "right-now" });
    for (const hash of [
      "#q=il+faut",
      "#q=il+faut&concept=1",
      "#q=pronouns&example=y-en",
      "#q=il+faut&state=active&concept=1&unit=14",
      "#state=orphaned",
      "#mode=hybrid&preset=right-now&example=y-en&concept=12",
    ]) {
      const link = linkFromHash(hash, ["right-now"]);
      expect(hashForScreen(link.screen, link.search), hash).toBe(hash);
    }
  });

  it("opens the start for a malformed or unknown search, whatever screen it names", () => {
    for (const bad of [
      "#mode=semantic",
      "#mode=semantic&preset=nope",
      "#mode=quantum&preset=right-now",
      "#preset=right-now",
      "#q=x&mode=semantic&preset=right-now",
      "#state=bogus&concept=12",
      `#q=${"a".repeat(201)}`,
      "#mode=semantic&preset=Right%20Now",
    ]) {
      expect(linkFromHash(bad, ["right-now"]), bad).toEqual({ screen: { kind: "results" }, search: NO_SEARCH, malformed: true });
    }
  });

  it("counts an in-page back by the most recent matching entry, never the current one", () => {
    const trail = ["#", "#example=y-en", "#example=y-en&concept=12", "#example=y-en&concept=12&unit=12"];
    expect(stepsBack(trail, "#example=y-en&concept=12")).toBe(1);
    expect(stepsBack(trail, "#example=y-en")).toBe(2);
    expect(stepsBack(trail, "#")).toBe(3);
    expect(stepsBack(["#concept=12&unit=12"], "#concept=12")).toBe(0);
    expect(stepsBack(["#example=y-en"], "#example=y-en")).toBe(0);
  });
});

describe("in-page back and the browser's Back are the same move", () => {
  it("never sends the browser's Back forward to the screen just left, and keeps Forward", async () => {
    await renderDemo();
    await startScreen();
    const before = window.history.length;
    click(/One question, two pronouns/);
    await exampleHeading();
    click("Open the Concept and its evidence");
    await conceptHeading();
    click("View source record #9 for unit #12");
    await sourceHeading();
    expect(window.history.length).toBe(before + 3);
    expect(window.location.hash).toBe("#example=y-en&concept=12&unit=12");

    click("← Back to concept #12");
    const concept = await conceptHeading();
    await waitFor(() => expect(concept).toHaveFocus());
    expect(window.location.hash).toBe("#example=y-en&concept=12");
    expect(window.history.length).toBe(before + 3);

    window.history.back();
    expect(await screen.findByText(QUESTION)).toBeInTheDocument();
    expect(window.location.hash).toBe("#example=y-en");
    window.history.forward();
    await conceptHeading();
    window.history.forward();
    expect(await sourceHeading()).toBeInTheDocument();
  });

  it("goes from evidence straight back to its example, with the Concept still ahead", async () => {
    await renderDemo();
    await startScreen();
    click(/One question, two pronouns/);
    await exampleHeading();
    click("Open the Concept and its evidence");
    await conceptHeading();
    click("View source record #9 for unit #12");
    await sourceHeading();
    click("← Back to the example “One question, two pronouns”");
    const heading = await exampleHeading();
    await waitFor(() => expect(heading).toHaveFocus());
    expect(window.location.hash).toBe("#example=y-en");
    window.history.forward();
    expect(await conceptHeading()).toBeInTheDocument();
  });

  it("replaces the entry when the screen named is not in this visit (a direct link), so no loop is left behind", async () => {
    await renderDemo("/#example=y-en&concept=12&unit=12");
    await sourceHeading();
    const before = window.history.length;
    click("← Back to concept #12");
    await conceptHeading();
    expect(window.location.hash).toBe("#example=y-en&concept=12");
    click("← Back to the example “One question, two pronouns”");
    await exampleHeading();
    click("← Back to examples and search");
    await waitFor(() => expect(screen.getByRole("button", { name: /One question, two pronouns/ })).toHaveFocus());
    expect(window.location.hash).toBe("");
    expect(window.history.length).toBe(before);
  });

  it("joins a fragment typed into the address bar to the visit", async () => {
    await renderDemo();
    await startScreen();
    window.history.pushState(null, "", "/#concept=12");
    window.dispatchEvent(new PopStateEvent("popstate", { state: null }));
    await conceptHeading();
    expect((window.history.state as { flhTrail: string[] }).flhTrail).toEqual(["#", "#concept=12"]);
    const before = window.history.length;
    click("← Back to all concepts");
    expect(await startScreen()).toBeInTheDocument();
    await waitFor(() => expect(window.location.hash).toBe(""));
    expect(window.history.length).toBe(before);
  });
});

describe("searches are entries and links keep them", () => {
  it("walks submitted searches with Back and Forward and restores the form", async () => {
    await renderDemo();
    await startScreen();
    const before = window.history.length;
    search("pronouns");
    await screen.findByRole("button", { name: "the pronouns y and en" });
    expect(window.location.hash).toBe("#q=pronouns");
    search("pronouns"); // the same search again adds nothing
    search("il faut");
    const result = await screen.findByRole("button", { name: "subjunctive after « il faut que »" });
    expect(window.location.hash).toBe("#q=il+faut");
    expect(window.history.length).toBe(before + 2);

    fireEvent.click(result);
    await conceptHeading(/subjunctive after « il faut que »/);
    expect(window.location.hash).toBe("#q=il+faut&concept=1");
    click("← Back to results for “il faut”");
    await waitFor(() => expect(screen.getByRole("button", { name: "subjunctive after « il faut que »" })).toHaveFocus());

    window.history.back();
    await waitFor(() => expect(screen.getByLabelText("Search learned material")).toHaveValue("pronouns"));
    expect(await screen.findByRole("button", { name: "the pronouns y and en" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "subjunctive after « il faut que »" })).toBeNull();
    window.history.back();
    await waitFor(() => expect(screen.getByLabelText("Search learned material")).toHaveValue(""));
    expect(await screen.findByRole("button", { name: "subjunctive after « il faut que »" })).toBeInTheDocument();
    window.history.forward();
    await waitFor(() => expect(screen.getByLabelText("Search learned material")).toHaveValue("pronouns"));
  });

  it("reopens a Concept with the way back to the search it was opened from (reload or shared link)", async () => {
    await renderDemo("/#q=pronouns&concept=12");
    await conceptHeading();
    click("← Back to results for “pronouns”");
    await waitFor(() => expect(screen.getByLabelText("Search learned material")).toHaveValue("pronouns"));
    expect(window.location.hash).toBe("#q=pronouns");
    await waitFor(() => expect(screen.getByRole("button", { name: "the pronouns y and en" })).toHaveFocus());
  });

  it("keeps the visit's trail across a reload, so back actions still move back", async () => {
    await renderDemo();
    await startScreen();
    click(/One question, two pronouns/);
    await exampleHeading();
    click("Open the Concept and its evidence");
    await conceptHeading();
    cleanup(); // the page goes away; the address and the history entry stay
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    await conceptHeading();
    const before = window.history.length;
    click("← Back to the example “One question, two pronouns”");
    await exampleHeading();
    expect(window.history.length).toBe(before);
    window.history.back();
    expect(await startScreen()).toBeInTheDocument();
  });

  it("reopens a semantic preset search from its link", async () => {
    await renderDemo("/#mode=semantic&preset=right-now");
    expect(await screen.findByRole("region", { name: "Semantic results" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Semantic" })).toBeChecked();
    expect(screen.getByLabelText("Example query")).toHaveValue("right-now");
  });

  it("rewrites a malformed link to the start's own address", async () => {
    await renderDemo("/#concept=abc");
    await startScreen();
    expect(window.location.hash).toBe("");
  });
});

describe("the private workbench's library keeps no history", () => {
  it("opens and leaves a Concept without touching the address or the history", async () => {
    window.history.replaceState(null, "", "/");
    demoServer();
    const before = window.history.length;
    render(<StrictMode><LocaleProvider><KnowledgeLibrary /></LocaleProvider></StrictMode>);
    fireEvent.click(await screen.findByRole("button", { name: "the pronouns y and en" }));
    await conceptHeading();
    expect(screen.queryByRole("navigation", { name: "Return" })).toBeNull();
    click("← Back to all concepts");
    await screen.findByRole("button", { name: "the pronouns y and en" });
    expect(window.history.length).toBe(before);
    expect(window.location.hash).toBe("");
  });
});
