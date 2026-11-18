import { lazy } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LazySection } from "./LazySection";
import { LocaleProvider } from "./i18n";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("LazySection", () => {
  it("shows a loading line, then the section", async () => {
    let done: (m: { default: () => JSX.Element }) => void = () => {};
    const Section = lazy(() => new Promise<{ default: () => JSX.Element }>((r) => (done = r)));
    render(
      <LocaleProvider>
        <LazySection>
          <Section />
        </LazySection>
      </LocaleProvider>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Loading this section…");
    done({ default: () => <p>Section body</p> });
    expect(await screen.findByText("Section body")).toBeInTheDocument();
  });

  it("says what to do when the section's file cannot be loaded", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const Section = lazy(() => Promise.reject(new TypeError("Failed to fetch dynamically imported module")));
    render(
      <LocaleProvider>
        <LazySection>
          <Section />
        </LazySection>
      </LocaleProvider>,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("This section could not be loaded. If the workbench was just upgraded, reload the page");
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
  });
});
