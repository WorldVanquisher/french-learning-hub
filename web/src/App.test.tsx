import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("App annotation views", () => {
  it("opens the read-only inspector through the local view switch", async () => {
    const calls: Array<{ method: string; path: string }> = [];
    globalThis.fetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      const method = (init?.method ?? "GET").toUpperCase();
      const path = new URL(String(url), "http://localhost").pathname;
      calls.push({ method, path });
      const body = path === "/api/reviewable-units"
        ? { reviewable_units: [] }
        : path === "/api/effective-annotations"
          ? { effective_annotations: [] }
          : { concepts: [] };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as unknown as typeof fetch;

    render(<App />);
    expect(screen.getByRole("heading", { name: "Concept Review" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Annotation Inspector" }));

    expect(
      await screen.findByRole("heading", { name: "Effective Annotation Inspector" }),
    ).toBeInTheDocument();
    expect(await screen.findByText(/No KnowledgeUnits exist in the current extraction/)).toBeInTheDocument();
    expect(calls.some((call) => call.path === "/api/effective-annotations")).toBe(true);
    expect(calls.every((call) => call.method === "GET")).toBe(true);
  });
});
