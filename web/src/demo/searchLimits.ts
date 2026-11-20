// The keyword search's limits (internal/application/knowledge_library_service.go
// ParseLibrarySearchQuery and Search): at most 200 bytes of UTF-8 after
// trimming, at least one searchable word, at most 8 different words. A word is
// what concept_lexical_normalization_v1 makes of the text: lower case, accents
// removed, split at anything that is not a letter or a digit, one-letter words
// dropped. The server is the authority; this only explains its refusal.
export const MAX_QUERY_BYTES = 200;
export const MAX_QUERY_WORDS = 8;

export function queryWords(q: string): string[] {
  const words = q
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .split(/[^\p{L}\p{Nd}]+/u)
    .filter((w) => [...w].length > 1);
  return [...new Set(words)];
}

export const queryBytes = (q: string) => new TextEncoder().encode(q.trim()).length;

export type QueryProblem = { kind: "bytes"; count: number } | { kind: "no-word" } | { kind: "words"; count: number };

// queryProblem names the limit a query breaks, in the server's order, or null.
export function queryProblem(q: string): QueryProblem | null {
  const text = q.trim();
  const bytes = queryBytes(text);
  if (bytes > MAX_QUERY_BYTES) return { kind: "bytes", count: bytes };
  if (text === "") return null;
  const words = queryWords(text);
  if (words.length === 0) return { kind: "no-word" };
  if (words.length > MAX_QUERY_WORDS) return { kind: "words", count: words.length };
  return null;
}
