// The Endfield preview theme is opt-in: the standard look stays the default,
// the choice is a per-device convenience, and the public demo never changes.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import PublicDemoApp from "./PublicDemoApp";
import { LocaleProvider } from "./i18n";
import { THEME_STORAGE_KEY } from "./theme";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
});

function serve() {
  globalThis.fetch = vi.fn(async () => new Response(JSON.stringify({ reviewable_units: [], records: [], concepts: [] }), { status: 200, headers: { "Content-Type": "application/json" } })) as unknown as typeof fetch;
}

describe("Endfield preview theme", () => {
  it("is off by default and switches the whole workbench when chosen, remembered on this device", () => {
    serve();
    const { unmount } = render(<App />);
    expect(document.documentElement.dataset.theme).toBeUndefined();
    const select = screen.getByRole("combobox", { name: "Theme" }) as HTMLSelectElement;
    expect(select.value).toBe("standard");
    fireEvent.change(select, { target: { value: "endfield" } });
    expect(document.documentElement.dataset.theme).toBe("endfield");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("endfield");
    unmount();
    expect(document.documentElement.dataset.theme).toBeUndefined();
    render(<App />);
    expect(document.documentElement.dataset.theme).toBe("endfield");
    fireEvent.change(screen.getByRole("combobox", { name: "Theme" }), { target: { value: "standard" } });
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });

  it("treats an unknown stored value as the standard theme and says when the choice cannot be saved", () => {
    serve();
    window.localStorage.setItem(THEME_STORAGE_KEY, "neon");
    render(<App />);
    expect(document.documentElement.dataset.theme).toBeUndefined();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Theme" }), { target: { value: "endfield" } });
    expect(document.documentElement.dataset.theme).toBe("endfield");
    expect(screen.getByRole("status").textContent).toContain("could not be saved on this device");
  });

  it("is offered in Simplified Chinese", () => {
    serve();
    window.localStorage.setItem("flh.ui-locale.v1", "zh-CN");
    render(
      <LocaleProvider>
        <App />
      </LocaleProvider>,
    );
    expect(screen.getByRole("option", { name: "Endfield 预览" })).toBeTruthy();
  });

  it("never applies to the public demo", () => {
    serve();
    window.localStorage.setItem(THEME_STORAGE_KEY, "endfield");
    render(<PublicDemoApp />);
    expect(screen.queryByRole("combobox", { name: "Theme" })).toBeNull();
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });

  it("scopes every rule to the opt-in attribute, keeps focus rings unclipped and turns motion off when asked", () => {
    const css = readFileSync(resolve(process.cwd(), "src/theme-endfield.css"), "utf8");
    const code = css.replace(/\/\*[\s\S]*?\*\//g, "");
    const rules = code.split("}").map((r) => r.trim()).filter(Boolean);
    for (const r of rules) {
      const selector = r.slice(0, r.indexOf("{")).trim().replace(/^@media[^{]*\{\s*/, "");
      if (!selector || selector.startsWith("@media")) continue;
      for (const part of selector.split(","))
        if (part.trim()) expect(part.trim(), `unscoped selector ${part.trim()}`).toMatch(/^:root\[data-theme="endfield"\]/);
    }
    expect(code).not.toMatch(/clip-path/);
    expect(code).not.toMatch(/@font-face|url\(/);
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*transition: none !important/);
    expect(css).toMatch(/button:focus-visible[\s\S]*outline: 3px solid/);
  });
});
