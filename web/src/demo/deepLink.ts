import { DEMO_EXAMPLES } from "./examples";

// Direct links for the public demo. The server serves the demo only at `/`
// (no SPA fallback, and the demo boundary refuses unknown paths), so a link
// must be a URL fragment, which browsers never send to the server:
//
//   #example=y-en                  a guided example
//   #concept=12                    a Concept
//   #concept=12&unit=14            the source of unit 14, reached from Concept 12
//   …&example=y-en                 the same, opened from that example (its back
//                                  actions return to the example)
//
// Anything else, including an unknown example key or a malformed ID, opens the
// starting screen. A link names IDs only; every screen still reads its data
// from the server, so a stale link shows that read's own error.
export type LinkScreen =
  | { kind: "results" }
  | { kind: "example"; example: string }
  | { kind: "concept"; conceptId: number; from?: string }
  | { kind: "source"; conceptId: number; unitId: number; from?: string };

const ID = /^[1-9][0-9]{0,8}$/;

export function screenFromHash(hash: string): LinkScreen {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const exampleKey = params.get("example");
  const example = exampleKey && DEMO_EXAMPLES.some((e) => e.key === exampleKey) ? exampleKey : undefined;
  const concept = params.get("concept");
  const unit = params.get("unit");
  if (exampleKey && !example) return { kind: "results" };
  if (concept === null) return example ? { kind: "example", example } : { kind: "results" };
  if (!ID.test(concept) || (unit !== null && !ID.test(unit))) return { kind: "results" };
  const conceptId = Number(concept);
  if (unit !== null) return { kind: "source", conceptId, unitId: Number(unit), from: example };
  return { kind: "concept", conceptId, from: example };
}

export function hashForScreen(screen: { kind: string; example?: string; conceptId?: number; unitId?: number; from?: string }): string {
  const params = new URLSearchParams();
  if (screen.kind === "example" && screen.example) params.set("example", screen.example);
  if ((screen.kind === "concept" || screen.kind === "source") && screen.conceptId) {
    if (screen.from) params.set("example", screen.from);
    params.set("concept", String(screen.conceptId));
    if (screen.kind === "source" && screen.unitId) params.set("unit", String(screen.unitId));
  }
  const s = params.toString();
  return s ? `#${s}` : "";
}

// The address for a screen: this page, with the screen's fragment (none for the start).
export function urlForScreen(screen: Parameters<typeof hashForScreen>[0]): string {
  return `${window.location.pathname}${window.location.search}${hashForScreen(screen)}`;
}
