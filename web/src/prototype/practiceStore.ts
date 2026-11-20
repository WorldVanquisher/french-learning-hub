// The practice visit's state for the life of the page (PROTOTYPE). A module
// store, so moving between Review Today, a concept and the rest of the
// workbench keeps it; a reload starts over (the page says so). Nothing is
// written to browser storage, sent or logged.

import { useSyncExternalStore } from "react";
import { loadCatalog, type FixtureCatalog } from "./practiceFixture";
import { checkOp, current, initialVisit, reduce, type VisitAction, type VisitState } from "./practiceSession";

export type PanelStatus = "closed" | "loading" | "ready" | "error";

export interface PracticeVisitSnapshot {
  panel: PanelStatus;
  error: string | null;
  catalog: FixtureCatalog | null;
  visit: VisitState;
  delayMs: number; // a simulated response delay for checks (0 = immediate)
  feedTimeout: boolean; // prototype control: the next feed request times out
  openConcept: string | null; // the source whose concept view is open
  focusItem: string | null; // an exercise to focus when the concept opens
}

let snap: PracticeVisitSnapshot = { panel: "closed", error: null, catalog: null, visit: initialVisit(), delayMs: 0, feedTimeout: false, openConcept: null, focusItem: null };
const listeners = new Set<() => void>();
const set = (next: Partial<PracticeVisitSnapshot>) => {
  snap = { ...snap, ...next };
  listeners.forEach((l) => l());
};
const now = () => new Date().toISOString();
const timers = new Set<ReturnType<typeof setTimeout>>();

export function dispatch(a: VisitAction) {
  if (!snap.catalog) return;
  const next = reduce(snap.catalog, snap.visit, a);
  if (next !== snap.visit) set({ visit: next });
}

export async function openPanel(load: () => Promise<FixtureCatalog> = loadCatalog) {
  if (snap.panel === "ready" || snap.panel === "loading") return;
  set({ panel: "loading", error: null });
  try {
    const catalog = snap.catalog ?? (await load());
    set({ panel: "ready", catalog });
  } catch (e) {
    set({ panel: "error", error: e instanceof Error ? e.message : String(e) });
  }
}
export const closePanel = () => set({ panel: "closed", openConcept: null, focusItem: null });
export const openConcept = (sourceId: string, focusItem: string | null = null) => set({ openConcept: sourceId, focusItem });
export const closeConcept = () => set({ openConcept: null, focusItem: null });
export const consumeFocus = () => snap.focusItem !== null && set({ focusItem: null });
export const setDelay = (ms: number) => set({ delayMs: ms });
// Move focus to an element once React has rendered it (a control that
// replaces itself must not leave focus on the page body).
export const focusSoon = (id: string) =>
  requestAnimationFrame(() => requestAnimationFrame(() => (document.getElementById(id) as HTMLElement | null)?.focus()));

// Ask for a check: the op is the draft's version, so the same unchanged draft
// sent again (a double click, a repeated Ctrl+Enter) is one action. The
// response comes back after the simulated delay, even if the learner has left
// the concept meanwhile.
export function submitAnswer(sourceId: string, practiceId: string, text: string) {
  if (!snap.catalog) return null;
  const op = checkOp(snap.visit, sourceId, practiceId, current(snap.catalog, snap.visit, sourceId).feed.source.revision_sha256);
  dispatch({ type: "submit", op, at: now(), sourceId, practiceId, text });
  // A repeated request was ignored by the reducer: no second response either.
  if (!snap.visit.pending.some((p) => p.op === op)) return op;
  const respond = () => dispatch({ type: "respond", op, at: now() });
  if (snap.delayMs <= 0) respond();
  else {
    const t = setTimeout(() => {
      timers.delete(t);
      respond();
    }, snap.delayMs);
    timers.add(t);
  }
  return op;
}
export const reveal = (sourceId: string, practiceId: string) => dispatch({ type: "reveal", at: now(), sourceId, practiceId });
// Ask the extraction feed for the next revision. With the prototype's timeout
// control on, the request "times out": nothing changes but an event.
export const arrive = (sourceId: string) =>
  dispatch(snap.feedTimeout ? { type: "feedTimeout", at: now(), sourceId } : { type: "arrive", at: now(), sourceId });
export const setFeedTimeout = (on: boolean) => set({ feedTimeout: on });
export const applyWaiting = (sourceId: string) => dispatch({ type: "apply", at: now(), sourceId });

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
export const getSnapshot = () => snap;
export const usePracticeVisit = () => useSyncExternalStore(subscribe, getSnapshot);
export const listenerCount = () => listeners.size;

// Tests only: forget everything (as a reload would).
export function resetPracticeVisit() {
  timers.forEach((t) => clearTimeout(t));
  timers.clear();
  snap = { panel: "closed", error: null, catalog: null, visit: initialVisit(), delayMs: 0, feedTimeout: false, openConcept: null, focusItem: null };
  listeners.forEach((l) => l());
}
