// Per-visit memory of the public demo's comparison screens (R2): whether the
// evidence under the two examples is shown, and the optional practice question
// (which item, and the visitor's choice or skip for each). It lives in this
// page's memory only: never in the address, browser storage, a cookie or a
// request. So Back from a source opened from a comparison finds the comparison
// as it was left, while a reload or a shared link starts fresh: a link names a
// screen, never progress. Nothing here is a learner record.

// A choice (the index of the chosen form, in side order) or an explicit skip.
export type PracticeAnswer = number | "skip";

export interface CompareVisit {
  // The visitor's own choice; until then the screen's width decides.
  evidence?: boolean;
  practice: boolean;
  item: number;
  answers: ReadonlyArray<PracticeAnswer | undefined>;
}

const NEW_VISIT: CompareVisit = { practice: false, item: 0, answers: [] };
const visits = new Map<string, CompareVisit>();

export const readCompareVisit = (key: string): CompareVisit => visits.get(key) ?? NEW_VISIT;

export function writeCompareVisit(key: string, visit: CompareVisit) {
  visits.set(key, visit);
}

// For tests: a new page load.
export function forgetCompareVisits() {
  visits.clear();
}
