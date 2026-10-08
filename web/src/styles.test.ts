import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// A static guard for the button state rules in styles.css. jsdom does not apply
// the cascade or compute contrast, so this cannot prove readability; that is
// verified by measuring rendered styles in a real browser. It only fails if a
// later edit removes or weakens one of these rules.
// Vitest runs from web/; under jsdom import.meta.url is not a file: URL.
const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

function rule(selector: string): string {
  const start = css.indexOf(selector);
  expect(start, `missing selector ${selector}`).toBeGreaterThanOrEqual(0);
  return css.slice(start, css.indexOf("}", start) + 1);
}

describe("button state styles", () => {
  it.each([
    "button.primary:hover:not(:disabled)",
    '.view-tabs button[aria-pressed="true"]:hover:not(:disabled)',
    "button.same:hover:not(:disabled)",
    "button.invalid:hover:not(:disabled)",
  ])("keeps a colored background on hover for %s", (selector) => {
    const body = rule(selector);
    expect(body).toMatch(/background:\s*#[0-9a-f]{6}/i);
    expect(body).not.toMatch(/#f2f4f7/i);
  });

  it("keeps disabled buttons legible and distinct, including colored variants", () => {
    const body = rule("button.invalid:disabled");
    expect(body).not.toMatch(/opacity/);
    expect(body).toMatch(/border:\s*1px dashed/);
    expect(body).toMatch(/cursor:\s*not-allowed/);
    for (const variant of ["button.primary:disabled", "button.same:disabled"]) {
      expect(css).toContain(variant);
    }
  });

  it("shows an explicit keyboard focus ring", () => {
    expect(rule("button:focus-visible")).toMatch(/outline:\s*3px solid/);
  });
});
