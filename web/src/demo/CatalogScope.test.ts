import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { en } from "../i18n/en";
import { zhCN } from "../i18n/zh-CN";
import { DEMO_MESSAGE_NAMESPACES, pruneCatalog } from "./catalogScope";

// A public demo build ships only DEMO_MESSAGE_NAMESPACES (vite.config.ts). These
// tests keep that list exact: every namespace the demo's code can reference is
// in it (a dropped key would show as its raw name), and it names nothing the
// demo no longer uses. Vitest runs from web/.
const src = resolve(process.cwd(), "src");
const catalogFiles = new Set([resolve(src, "i18n/en.ts"), resolve(src, "i18n/zh-CN.ts")]);
const namespaces = new Set(Object.keys(en).map((k) => k.slice(0, k.indexOf("."))));

// The demo build renders PublicDemoApp from main.tsx; main.tsx's import of the
// workbench (./App) is dead code there, because VITE_FLH_PUBLIC_DEMO is a
// build-time constant. Every other relative import, static or dynamic, is
// followed; the catalogs themselves are not scanned.
function demoGraph(): Map<string, string> {
  const files = new Map<string, string>();
  const queue = [resolve(src, "main.tsx")];
  while (queue.length) {
    const file = queue.pop()!;
    if (files.has(file)) continue;
    const text = readFileSync(file, "utf8");
    files.set(file, text);
    const specs = [
      ...text.matchAll(/(?:import|export)\s[^;]*?from\s+["'](\.[^"']+)["']/g),
      ...text.matchAll(/import\s+["'](\.[^"']+)["']/g),
      ...text.matchAll(/import\(\s*["'](\.[^"']+)["']\s*\)/g),
    ].map((m) => m[1]);
    for (const spec of specs) {
      // Styles and data (discovery.json) name no message keys.
      if (/\.(css|json)$/.test(spec)) continue;
      if (file === resolve(src, "main.tsx") && spec === "./App") continue;
      const target = ["", ".ts", ".tsx", "/index.ts", "/index.tsx"].map((ext) => resolve(dirname(file), spec + ext)).find((p) => existsSync(p) && /\.tsx?$/.test(p));
      if (!target) throw new Error(`cannot resolve ${spec} from ${file}`);
      if (!catalogFiles.has(target) && !/\.test\.tsx?$/.test(target)) queue.push(target);
    }
  }
  return files;
}

// Namespaces named in string or template literals ("demo.x", `status.${v}`),
// limited to the catalogs' namespaces (storage keys such as "flh.…" are not).
function referencedNamespaces(files: Map<string, string>): Map<string, string[]> {
  const found = new Map<string, string[]>();
  for (const [file, text] of files) {
    for (const m of text.matchAll(/["'`]([a-z][A-Za-z0-9]*)\.(?:[A-Za-z0-9_-]|\$\{)/g)) {
      if (!namespaces.has(m[1])) continue;
      found.set(m[1], [...new Set([...(found.get(m[1]) ?? []), file.slice(src.length + 1)])]);
    }
  }
  return found;
}

describe("the public demo's message scope", () => {
  const files = demoGraph();
  const used = referencedNamespaces(files);

  it("relies on the import vite.config.ts replaces in demo builds", () => {
    // vite.config.ts resolves exactly this import from main.tsx to an empty
    // component in demo builds; renaming it would silently bundle the workbench.
    expect(readFileSync(resolve(src, "main.tsx"), "utf8")).toMatch(/^import App from "\.\/App";$/m);
  });

  it("walks the demo's code and not the workbench's", () => {
    const names = [...files.keys()].map((f) => f.slice(src.length + 1));
    expect(names).toContain("PublicDemoApp.tsx");
    expect(names).toContain("pages/KnowledgeLibrary.tsx");
    expect(names).toContain("demo/ExampleScreen.tsx");
    expect(names).not.toContain("App.tsx");
    expect(names).not.toContain("pages/Speaking.tsx");
  });

  it("keeps every namespace the demo's code references, and only those", () => {
    expect([...used.keys()].sort()).toEqual([...DEMO_MESSAGE_NAMESPACES].sort());
  });

  it("prunes both catalogs to the same keys, with their text unchanged", () => {
    for (const [file, catalog] of [
      ["i18n/en.ts", en],
      ["i18n/zh-CN.ts", zhCN],
    ] as const) {
      const pruned = pruneCatalog(readFileSync(resolve(src, file), "utf8"), DEMO_MESSAGE_NAMESPACES);
      const expected = Object.keys(catalog).filter((k) => DEMO_MESSAGE_NAMESPACES.includes(k.slice(0, k.indexOf("."))));
      expect(pruned.kept.map((e) => e.key), file).toEqual(expected);
      for (const e of pruned.kept) expect(e.value, e.key).toBe((catalog as Record<string, string>)[e.key]);
      expect(pruned.dropped, file).toBe(Object.keys(catalog).length - expected.length);
      expect(pruned.dropped, file).toBeGreaterThan(expected.length);
      expect(pruned.code).toMatch(/^\s+"demo\.title": /m);
      expect(pruned.code).not.toMatch(/"speaking\./);
    }
  });

  it("refuses a catalog it does not understand instead of guessing", () => {
    expect(() => pruneCatalog('export const en = {\n  "demo.a": `x`,\n};', ["demo"])).toThrow(/not understood/);
    expect(() => pruneCatalog('export const en = {\n  "demo.a": "x" + "y",\n};', ["demo"])).toThrow(/not understood/);
    expect(() => pruneCatalog('export const en = {\n  "demo.a": "x",\n  "demo.a": "y",\n};', ["demo"])).toThrow(/duplicate/);
    expect(pruneCatalog('export const en = {\n  // c\n  "demo.a": "x",\n  "home.b": "y"\n} satisfies X;', ["demo"]).code).toBe(
      'export const en = {\n  "demo.a": "x",\n} satisfies X;',
    );
  });
});
