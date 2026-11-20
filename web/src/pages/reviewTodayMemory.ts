// Review Today's page memory (R4): what the learner was doing in the queue
// while they open an item's lesson or take and come back. The workbench
// unmounts Review Today when another section shows, so this lives in a module,
// for the page's lifetime only: never in browser storage, never sent, gone on
// reload (as "Hide for this visit" says).
//   - hidden: the Speaking steps hidden for this visit;
//   - returnTo: the queue item that was opened, so focus comes back to it.
// A persisted defer, or a recorded outcome, needs storage the owner has not
// approved (docs/plans/PRACTICE-STORAGE-RELEASE-RECORD.md): until then this is
// the simulated persistence for those actions (R4-WB-015).

let hidden: string[] = [];
let returnTo: string | null = null;

export const hiddenKeys = (): string[] => hidden;
export const setHiddenKeys = (keys: string[]): void => {
  hidden = [...keys];
};
export const rememberReturn = (key: string): void => {
  returnTo = key;
};
// The item to give focus back to, once: reading it clears it.
export const takeReturn = (): string | null => {
  const k = returnTo;
  returnTo = null;
  return k;
};
// Tests and a reload start from nothing.
export const resetReviewTodayMemory = (): void => {
  hidden = [];
  returnTo = null;
};
