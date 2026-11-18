// The public demo's message scope. A demo build (VITE_FLH_PUBLIC_DEMO=1) ships
// only the message namespaces the demo's own code can reference; the private
// workbench's text (listening, speaking, writing, records, review, …), about
// four fifths of each catalog, is left out of the demo bundle. vite.config.ts
// applies pruneCatalog to src/i18n/en.ts and src/i18n/zh-CN.ts in demo builds
// only; the workbench build, the type of MessageKey and every test keep the
// full catalogs.
//
// CatalogScope.test.ts walks the demo's import graph (main.tsx without the
// workbench's App) and fails when the graph references a namespace missing
// here, or when this list names one the graph no longer uses. A key the demo
// renders is therefore never dropped: a missing key would show as its raw name.
//
// Imported by vite.config.ts (Node) and by the test, so it uses no DOM or app
// imports.
export const DEMO_MESSAGE_NAMESPACES: readonly string[] = [
  "app",
  "common",
  "demo",
  "effective",
  "explanationLanguage",
  "explanationText",
  "inspector",
  "language",
  "library",
  "practice",
  "status",
];

export interface CatalogEntry {
  key: string;
  value: string;
}

export interface PrunedCatalog {
  code: string;
  kept: CatalogEntry[];
  dropped: number;
}

const namespaceOf = (key: string) => key.slice(0, key.indexOf("."));

// pruneCatalog rewrites one catalog module, keeping the entries whose
// namespace (the key up to its first dot) is in `keep`, in their order, with
// their exact source text. It understands exactly the catalogs' format: one
// `export const … = {` object of `"key": "value",` entries (double-quoted,
// JSON-compatible strings) and `//` comments, which are dropped. Anything else
// throws, so a format change stops the build instead of shipping a wrong
// catalog.
export function pruneCatalog(source: string, keep: readonly string[]): PrunedCatalog {
  const start = source.indexOf("export const ");
  const open = start < 0 ? -1 : source.indexOf("= {", start);
  if (open < 0) throw new Error("catalog not understood: no `export const … = {` object");
  const wanted = new Set(keep);
  let pos = open + 3;
  const fail = (what: string): never => {
    throw new Error(`catalog not understood at offset ${pos}: ${what} near ${JSON.stringify(source.slice(pos, pos + 40))}`);
  };
  const skip = () => {
    for (;;) {
      while (pos < source.length && /\s/.test(source[pos])) pos++;
      if (source.startsWith("//", pos)) {
        const end = source.indexOf("\n", pos);
        pos = end < 0 ? source.length : end + 1;
      } else return;
    }
  };
  const string = (): string => {
    if (source[pos] !== '"') fail("expected a double-quoted string");
    const from = pos++;
    while (pos < source.length && source[pos] !== '"') {
      if (source[pos] === "\n") fail("line break inside a string");
      pos += source[pos] === "\\" ? 2 : 1;
    }
    if (pos >= source.length) fail("unterminated string");
    pos++;
    return source.slice(from, pos);
  };
  const kept: Array<CatalogEntry & { raw: string }> = [];
  const seen = new Set<string>();
  let dropped = 0;
  for (;;) {
    skip();
    if (source[pos] === "}") break;
    const rawKey = string();
    skip();
    if (source[pos] !== ":") fail("expected ':'");
    pos++;
    skip();
    const rawValue = string();
    skip();
    if (source[pos] === ",") pos++;
    else if (source[pos] !== "}") fail("expected ',' or '}'");
    let key: string;
    let value: string;
    try {
      key = JSON.parse(rawKey) as string;
      value = JSON.parse(rawValue) as string;
    } catch {
      return fail("a string that is not JSON-compatible");
    }
    if (!key.includes(".")) fail(`key ${JSON.stringify(key)} has no namespace`);
    if (seen.has(key)) fail(`duplicate key ${JSON.stringify(key)}`);
    seen.add(key);
    if (wanted.has(namespaceOf(key))) kept.push({ key, value, raw: `${rawKey}: ${rawValue}` });
    else dropped++;
  }
  const code = `${source.slice(0, open + 3)}\n${kept.map((e) => `  ${e.raw},`).join("\n")}\n${source.slice(pos)}`;
  return { code, kept: kept.map(({ key, value }) => ({ key, value })), dropped };
}
