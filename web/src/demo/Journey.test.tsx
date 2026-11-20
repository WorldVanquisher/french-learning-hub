import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PublicDemoApp from "../PublicDemoApp";
import { hashForScreen, screenFromHash } from "./deepLink";
import { demoServer } from "./demoTestServer";
import { DEMO_EXAMPLES } from "./examples";
import { GALLERY } from "./FeatureGallery";
import { CORRECTION_REPLAY } from "./journeyFixtures";

// R5: the guided journey's fixture replay, the analysis route and the feature
// gallery. (The journey itself is walked in Compare.test.tsx.)

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
});

const catalog = JSON.parse(readFileSync(resolve(process.cwd(), "../scripts/demo/flh073/fixtures/catalog.json"), "utf8")) as {
  data_classification: string;
  entries: Array<{ key: string; original_input: string; analysis: { explanation: string }; units: Array<{ canonical: string; example?: string }> }>;
};

describe("the correction replay is a verified synthetic fixture", () => {
  it("corrects the analysis the public artifact stores for its example, verbatim", () => {
    expect(catalog.data_classification).toBe("synthetic");
    const ex = DEMO_EXAMPLES.find((e) => e.key === CORRECTION_REPLAY.example)!;
    const entry = catalog.entries.find((e) => e.original_input === ex.question)!;
    expect(CORRECTION_REPLAY.corrects).toBe(entry.analysis.explanation);
  });

  it("states only forms the example's own units use, in both explanation languages, and names nothing private", () => {
    const ex = DEMO_EXAMPLES.find((e) => e.key === CORRECTION_REPLAY.example)!;
    const entry = catalog.entries.find((e) => e.original_input === ex.question)!;
    const unitText = entry.units.map((u) => `${u.canonical} ${u.example ?? ""}`).join(" ").toLowerCase();
    for (const text of [CORRECTION_REPLAY.corrected.en, CORRECTION_REPLAY.corrected.zh]) {
      for (const form of text.match(/« ([^»]+) »/g) ?? []) {
        const f = form.slice(2, -2).toLowerCase();
        if (f === "je suis cuisinant") continue; // the learner's own wording, from the question
        expect(unitText, f).toContain(f.replace(/ \+ .*$/, ""));
      }
      expect(text).not.toMatch(/https?:|\/home\/|@|#\d/);
    }
  });
});

describe("the analysis route", () => {
  it("reads #analysis=<example> alone, and nothing else beside it", () => {
    expect(screenFromHash("#analysis=en-train-de")).toEqual({ kind: "analysis", example: "en-train-de" });
    expect(hashForScreen({ kind: "analysis", example: "en-train-de" })).toBe("#analysis=en-train-de");
    for (const bad of ["#analysis=", "#analysis=nope", "#analysis=en-train-de&concept=13", "#analysis=en-train-de&example=y-en", "#analysis=en-train-de&compare=present-en-train-de"])
      expect(screenFromHash(bad), bad).toEqual({ kind: "results" });
  });

  it("opens from a fresh link: the stored analysis read from the server, the replay labelled, and reads only", async () => {
    const s = demoServer();
    window.history.pushState(null, "", "/#analysis=en-train-de");
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    const stored = await screen.findByRole("region", { name: "The stored analysis (version 1)" }, { timeout: 3000 });
    // The analysis as the server stores it (the test server's explanation), not the fixture's.
    expect(within(stored).getByText("unreviewed")).toBeInTheDocument();
    expect(within(stored).queryByText(/is not French/)).toBeNull();
    const replay = screen.getByRole("region", { name: "How a correction is recorded" });
    expect(within(replay).getByText("Fixture replay")).toBeInTheDocument();
    expect(within(replay).getByText(/Not from this server and not stored\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Next: the rule taken from it and its source (unit #16)" })).toHaveAttribute("href", "#example=en-train-de&concept=14&unit=16");
    expect(s.calls.every((c) => c.method === "GET" && c.url.startsWith("/api/knowledge-library/"))).toBe(true);
  });
});

describe("the feature gallery (R5)", () => {
  it("lists the private-only features compactly, says why, and links to what the demo shows", async () => {
    const s = demoServer();
    window.history.pushState(null, "", "/");
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    const gallery = await screen.findByRole("region", { name: "More of FLH: the private workbench" });
    const cards = within(gallery).getAllByRole("listitem");
    expect(cards).toHaveLength(GALLERY.length);
    expect(within(gallery).getAllByText("Private only")).toHaveLength(GALLERY.filter((c) => c.privateOnly).length);
    expect(within(gallery).getAllByText("In this demo")).toHaveLength(1);
    const before = s.calls.length;
    // A retry, replayed: the journey's question.
    fireEvent.click(within(gallery).getByRole("button", { name: "Try a retry, replayed (tour step 5)" }));
    expect(window.location.hash).toBe("#compare=present-en-train-de&practice=1");
    await screen.findByRole("heading", { level: 3, name: "Which form completes the example?" });
    window.history.pushState(null, "", "/");
    cleanup();
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    const g2 = await screen.findByRole("region", { name: "More of FLH: the private workbench" });
    // A preset semantic search, from the build's presets.
    fireEvent.click(within(g2).getByRole("button", { name: "Try a preset semantic search" }));
    await waitFor(() => expect(window.location.hash).toBe("#mode=semantic&preset=right-now"));
    expect(s.calls.slice(before).every((c) => c.method === "GET" && c.url.startsWith("/api/knowledge-library/"))).toBe(true);
  });

  it("makes no request of its own", async () => {
    const s = demoServer();
    window.history.pushState(null, "", "/");
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    await screen.findByRole("region", { name: "More of FLH: the private workbench" });
    // Only the start's own reads: the demo description and the browse list.
    expect(new Set(s.calls.map((c) => c.url.replace(/\?.*$/, "")))).toEqual(new Set(["/api/knowledge-library/demo", "/api/knowledge-library/concepts"]));
  });
});
