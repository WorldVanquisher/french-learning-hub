// A duplicate key in a catalog literal silently replaces the earlier message
// (the bundler only warns), so another view's text changes. Read the catalog
// sources and refuse any key written twice.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const keys = (file: string) =>
  readFileSync(new URL(file, import.meta.url), "utf8")
    .split("\n")
    .map((line) => /^\s*"([^"]+)":/.exec(line)?.[1])
    .filter((k): k is string => k !== undefined);

describe("message catalogs", () => {
  for (const file of ["./en.ts", "./zh-CN.ts"])
    it(`${file} writes every key once`, () => {
      const seen = new Set<string>();
      const twice = keys(file).filter((k) => (seen.has(k) ? true : (seen.add(k), false)));
      expect(twice).toEqual([]);
      expect(seen.size).toBeGreaterThan(1000);
    });
});
