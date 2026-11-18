import type { ReactNode } from "react";

// Shows why a keyword result matched: the words of a matched field that the
// search's own tokens reach, marked. The tokens are the server's
// (knowledge_library_search_v1 `tokens`, already normalized by
// concept_lexical_normalization_v1); a word is marked when its normalized form
// starts with one of them, as the server's prefix matching does. Display only:
// it never changes what matched, the order or any stored text.

const WORD = /[\p{L}\p{M}\p{N}]+/gu;

export function normalizeWord(word: string): string {
  return word.toLowerCase().normalize("NFD").replace(/\p{M}/gu, "");
}

export function markMatches(text: string, tokens: readonly string[]): ReactNode {
  const usable = tokens.filter((t) => t.length >= 2);
  if (usable.length === 0 || !text) return text;
  const out: ReactNode[] = [];
  let last = 0;
  let marked = 0;
  for (const m of text.matchAll(WORD)) {
    const word = m[0];
    const start = m.index ?? 0;
    const norm = normalizeWord(word);
    if (!usable.some((t) => norm.startsWith(t))) continue;
    if (start > last) out.push(text.slice(last, start));
    out.push(<mark key={`${start}`}>{word}</mark>);
    last = start + word.length;
    marked++;
  }
  if (marked === 0) return text;
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// matchedFeatures lists the identity details (key: value, in key order) whose
// text the search's tokens reach, each with its matching words marked, at most
// `max` of them. Values that are not text are shown as JSON.
export function matchedFeatures(features: Record<string, unknown> | null | undefined, tokens: readonly string[], max = 3): ReactNode[] {
  if (!features) return [];
  const out: ReactNode[] = [];
  for (const key of Object.keys(features).sort()) {
    const v = features[key];
    const text = `${key}: ${typeof v === "string" ? v : JSON.stringify(v)}`;
    const marked = markMatches(text, tokens);
    if (typeof marked !== "string") out.push(<span key={key}>{marked}</span>);
    if (out.length === max) break;
  }
  return out;
}
