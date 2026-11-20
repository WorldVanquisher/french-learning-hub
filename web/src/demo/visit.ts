// Per-visit memory of the public demo's comparison screens (R2, R3): whether the
// evidence under the two examples and the source context panel are shown, and
// the visitor's choice or skip for each practice question. Which question is
// shown is part of the comparison's link (`practice=`, R3-056); everything here
// lives in this page's memory only: never in the address, browser storage, a
// cookie or a request. So Back and Forward, and Back from a source opened from
// a comparison, find it as it was left, while a reload or a shared link starts
// fresh: a link names a screen or a question, never progress. Nothing here is a
// learner record.

// A choice (the index of the chosen form, in side order) or an explicit skip.
export type PracticeAnswer = number | "skip";

export interface CompareVisit {
  // The visitor's own choice; until then the screen's width decides.
  evidence?: boolean;
  // The source context panel (R3-046), closed until opened.
  source?: boolean;
  // Per question (0-based).
  answers: ReadonlyArray<PracticeAnswer | undefined>;
}

const NEW_VISIT: CompareVisit = { answers: [] };
const visits = new Map<string, CompareVisit>();

export const readCompareVisit = (key: string): CompareVisit => visits.get(key) ?? NEW_VISIT;

export function writeCompareVisit(key: string, visit: CompareVisit) {
  visits.set(key, visit);
}

// For tests: a new page load.
export function forgetCompareVisits() {
  visits.clear();
}
