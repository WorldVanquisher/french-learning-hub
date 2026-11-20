import { StrictMode } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PublicDemoApp from "../PublicDemoApp";
import { demoServer } from "./demoTestServer";

// R4-DEM-026/027: evidence controls name their destination, and a quoted
// question's language is marked only when the demo knows it.

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
});

describe("evidence names and quotations", () => {
  it("says when a rule's words are not in the question, so it cannot be read off it (R4-DEM-032)", async () => {
    demoServer();
    window.history.pushState(null, "", "/#example=en-train-de&step=2");
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    const note = "None of this rule's words are in the question: it comes from the stored interpretation of the question (see the source evidence).";
    const units = await screen.findAllByRole("listitem", {}, { timeout: 3000 }).then(() => [...document.querySelectorAll(".demo-unit")]);
    const withNote = units.filter((u) => u.querySelector("[data-unit-origin]")).map((u) => u.querySelector(".demo-unit-canonical")!.textContent);
    // « présent pour une action en cours » shares « pour » with the question; « être en train de » shares none.
    expect(withNote).toEqual(["être en train de + infinitif"]);
    expect(screen.getByText(note)).toBeInTheDocument();
  });

  it("names each Concept button by its Concept when a question has two (R4-DEM-027)", async () => {
    demoServer();
    window.history.pushState(null, "", "/#example=en-train-de&step=3");
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    // A direct link to step 3 resolves the example's search, Concepts and source first.
    expect(await screen.findByRole("button", { name: "Open the Concept “the present tense for an action happening now” and its evidence" }, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open the Concept “« être en train de » + infinitive: in the middle of doing” and its evidence" })).toBeInTheDocument();
    window.history.replaceState(null, "", "/");
  });

  it("marks a quoted question's language on the source screen only when the demo knows it (R4-DEM-026)", async () => {
    demoServer();
    window.history.pushState(null, "", "/#concept=12&unit=12");
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    // An authored French example's question.
    expect(await screen.findByText("Dans « j'y vais » et « j'en veux », qu'est-ce que « y » et « en » remplacent ?", { selector: "blockquote" }, { timeout: 3000 })).toHaveAttribute("lang", "fr");
    cleanup();
    window.history.pushState(null, "", "/#concept=1&unit=1");
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    // Any other question: no language is claimed.
    expect(await screen.findByText("When do I use the subjunctive after il faut que?", { selector: "blockquote" }, { timeout: 3000 })).not.toHaveAttribute("lang");
    window.history.replaceState(null, "", "/");
  });

});
