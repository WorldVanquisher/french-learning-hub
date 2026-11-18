import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { DEFAULT_VIEW, sectionHash, viewFromHash } from "./sectionAddress";
import { VIEWS } from "./workbenchViews";

// Workbench section addresses: `#/<view>` keeps the section across a reload,
// Back and Forward, without any request or browser storage.

function mockApi(calls: string[]) {
  globalThis.fetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const path = new URL(String(url), "http://localhost").pathname;
    calls.push(`${(init?.method ?? "GET").toUpperCase()} ${path}`);
    const body =
      path === "/api/reviewable-units"
        ? { reviewable_units: [] }
        : path === "/api/learning-records"
          ? { records: [], next_before_entry_id: null }
          : { concepts: [] };
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  window.history.replaceState(null, "", "/");
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("section address parsing", () => {
  it("accepts every section's canonical fragment and nothing else", () => {
    for (const v of VIEWS) expect(viewFromHash(sectionHash(v))).toBe(v);
    expect(viewFromHash("")).toBe(DEFAULT_VIEW);
    expect(viewFromHash("#")).toBe(DEFAULT_VIEW);
    for (const bad of ["#/", "#/Speaking", "#speaking", "#/speaking/", "#/speaking?x=1", "#/nope", "#concept=12", "#/__proto__", "#/constructor"]) {
      expect(viewFromHash(bad)).toBe("unknown");
    }
  });
});

describe("workbench section addresses", () => {
  it("opens the section named by the address, as after a reload", async () => {
    const calls: string[] = [];
    mockApi(calls);
    window.history.replaceState(null, "", "/#/home");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Learning home" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Home" })).toHaveAttribute("aria-pressed", "true");
    expect(document.title).toBe("Home — French Learning Hub");
    expect(window.location.hash).toBe("#/home");
    expect(calls.every((c) => c.startsWith("GET "))).toBe(true);
  });

  it("keeps an empty address on the default section and adds an entry per section chosen", async () => {
    mockApi([]);
    const before = window.history.length;
    render(<App />);
    expect(window.location.hash).toBe("");
    expect(screen.getByRole("button", { name: "Concept Review" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Learning Records" }));
    expect(window.location.hash).toBe("#/records");
    fireEvent.click(screen.getByRole("button", { name: "Home" }));
    expect(window.location.hash).toBe("#/home");
    expect(window.history.length).toBe(before + 2);
    expect(document.title).toBe("Home — French Learning Hub");
  });

  it("moves between sections with Back and Forward", async () => {
    mockApi([]);
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Learning Records" }));
    fireEvent.click(screen.getByRole("button", { name: "Home" }));
    await act(async () => {
      window.history.back();
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "Learning Records" })).toHaveAttribute("aria-pressed", "true"));
    expect(window.location.hash).toBe("#/records");
    // Focus moves to the section's title after Back.
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1 }));
    await act(async () => {
      window.history.back();
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "Concept Review" })).toHaveAttribute("aria-pressed", "true"));
    expect(window.location.hash).toBe("");
    await act(async () => {
      window.history.forward();
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "Learning Records" })).toHaveAttribute("aria-pressed", "true"));
    // Back and Forward add no entries of their own.
    expect(window.location.hash).toBe("#/records");
  });

  it("opens the default section for an unknown address and corrects it in place", async () => {
    mockApi([]);
    window.history.replaceState(null, "", "/#/nope");
    const before = window.history.length;
    render(<App />);
    expect(screen.getByRole("button", { name: "Concept Review" })).toHaveAttribute("aria-pressed", "true");
    expect(window.location.hash).toBe("#/review");
    expect(window.history.length).toBe(before);
  });

  it("writes nothing to browser storage", async () => {
    mockApi([]);
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Knowledge Library" }));
    fireEvent.click(screen.getByRole("button", { name: "Speaking" }));
    expect(window.location.hash).toBe("#/speaking");
    expect(setItem).not.toHaveBeenCalled();
  });
});
