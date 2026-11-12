import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Static guards for the public demo's layout rules. jsdom has no layout, so the
// width itself is measured in a real browser (scripts/validation/demo_ux/
// accept_matrix.mjs, against the device width under phone emulation). These
// fail fast in CI when a rule that keeps evidence inside a phone screen is
// removed, and they keep demo.css from reaching the private workbench.
// Vitest runs from web/.
const styles = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");
const demoCss = readFileSync(resolve(process.cwd(), "src/demo/demo.css"), "utf8");

type Rule = { selectors: string[]; body: string };
function rules(css: string): Rule[] {
  const plain = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const out: Rule[] = [];
  for (const m of plain.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    out.push({ selectors: m[1].split(",").map((s) => s.trim()).filter(Boolean), body: m[2] });
  }
  return out;
}
const declares = (css: string, selector: string, declaration: RegExp) =>
  rules(css).some((r) => r.selectors.includes(selector) && declaration.test(r.body));

// The evidence screen's label/value rows (`.unit-evidence`) hold unbroken
// identifiers such as `fixture:flh073:fr_l2_taxonomy_v1` and nanosecond
// timestamps. Without a shrinkable value column and wrapping values the page
// was 421 px wide on a 390 px phone (the reported bug).
function evidenceRowProblems(css: string): string[] {
  const problems: string[] = [];
  if (!declares(css, ".unit-evidence div", /grid-template-columns:\s*110px\s+minmax\(0,\s*1fr\)/))
    problems.push("the value column of .unit-evidence rows cannot shrink (needs minmax(0, 1fr))");
  if (!declares(css, ".unit-evidence dd", /overflow-wrap:\s*anywhere/)) problems.push(".unit-evidence dd values do not wrap");
  return problems;
}

describe("evidence rows stay inside a phone screen", () => {
  it("keeps a shrinkable value column and wrapping values", () => {
    expect(evidenceRowProblems(styles)).toEqual([]);
  });

  it("fails for the old layout that overflowed (421 px on a 390 px phone)", () => {
    const old = styles
      .replace(/\.unit-evidence div \{ grid-template-columns: 110px minmax\(0, 1fr\); \}/, "")
      .replace(/\.unit-evidence dd, \.library \.hint \{ overflow-wrap: anywhere; \}/, "");
    expect(old).not.toBe(styles);
    expect(evidenceRowProblems(old)).toHaveLength(2);
  });

  it("wraps every kind of demo text, so long learner text and identifiers wrap on 320 px phones", () => {
    for (const selector of [".demo-app .library h2", ".demo-app .library p", ".demo-app .library dd", ".demo-app .library blockquote", ".demo-app .library-unit-head"]) {
      expect(declares(demoCss, selector, /overflow-wrap:\s*anywhere/), selector).toBe(true);
    }
    expect(declares(demoCss, ".demo-app .library button", /white-space:\s*normal/)).toBe(true);
  });
});

describe("demo.css is the public demo's alone", () => {
  it("scopes every selector under the demo's root", () => {
    const all = rules(demoCss).flatMap((r) => r.selectors);
    expect(all.length).toBeGreaterThan(5);
    for (const selector of all) expect(selector, selector).toMatch(/^\.demo-app(\.app$| )/);
  });

  it("adds no fonts, images, animations or transitions, and no at-rule but a narrow-screen media query", () => {
    const plain = demoCss.replace(/\/\*[\s\S]*?\*\//g, "");
    expect(plain).not.toMatch(/url\(|animation|transition|font-family|clip-path/);
    for (const at of plain.match(/@[^{]*/g) ?? []) expect(at.trim()).toMatch(/^@media \(max-width: \d+px\)$/);
  });
});
