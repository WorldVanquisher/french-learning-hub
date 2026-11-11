// The workbench's views and its cross-view "Back to …" trail, as data.
//
// App switches views locally (there is no router). Adding a view, or a view a
// cross-view link can start from, means adding entries here; TypeScript then
// refuses any table that misses the new view or origin, instead of a branch
// chain silently falling back to another view.
import type { MessageKey } from "./i18n";
import type { UnitTarget } from "./navigation";

export type View = "home" | "records" | "library" | "listening" | "reading" | "writing" | "speaking" | "notebook" | "exam" | "review" | "inspector" | "experiments";

// Tab order.
export const VIEWS: readonly View[] = ["home", "records", "library", "listening", "reading", "writing", "speaking", "notebook", "exam", "review", "inspector", "experiments"];

export const VIEW_COPY: Record<View, { title: MessageKey; subtitle: MessageKey; tab: MessageKey }> = {
  home: { title: "app.home.title", subtitle: "app.home.subtitle", tab: "nav.home" },
  records: { title: "app.records.title", subtitle: "app.records.subtitle", tab: "nav.records" },
  library: { title: "app.library.title", subtitle: "app.library.subtitle", tab: "nav.library" },
  listening: { title: "app.listening.title", subtitle: "app.listening.subtitle", tab: "nav.listening" },
  reading: { title: "app.reading.title", subtitle: "app.reading.subtitle", tab: "nav.reading" },
  writing: { title: "app.writing.title", subtitle: "app.writing.subtitle", tab: "nav.writing" },
  speaking: { title: "app.speaking.title", subtitle: "app.speaking.subtitle", tab: "nav.speaking" },
  notebook: { title: "app.notebook.title", subtitle: "app.notebook.subtitle", tab: "nav.notebook" },
  exam: { title: "app.exam.title", subtitle: "app.exam.subtitle", tab: "nav.exam" },
  review: { title: "app.review.title", subtitle: "app.review.subtitle", tab: "nav.review" },
  inspector: { title: "app.inspector.title", subtitle: "app.inspector.subtitle", tab: "nav.inspector" },
  experiments: { title: "app.experiments.title", subtitle: "app.experiments.subtitle", tab: "nav.experiments" },
};

// Views kept mounted (hidden) once opened, so their filters, drafts, typed
// answers and open items survive a visit to another view. The others mount
// only while shown and re-read their state.
export const KEPT_VIEWS = ["records", "library", "listening", "reading", "writing", "speaking", "notebook", "exam"] as const satisfies readonly View[];
export type KeptView = (typeof KEPT_VIEWS)[number];
export const isKeptView = (v: View): v is KeptView => (KEPT_VIEWS as readonly View[]).includes(v);

// Where a cross-view link came from, for the "Back to …" banner.
export type Origin =
  | { kind: "record"; target: UnitTarget }
  | { kind: "suggestions" }
  | { kind: "library" }
  | { kind: "listening" }
  | { kind: "reading" }
  | { kind: "writing" }
  | { kind: "speaking" }
  | { kind: "notebook" }
  | { kind: "exam" }
  | { kind: "records" };

// For each origin: the view "Back" returns to and the banner's two messages.
// The record messages take the record id ({id}); the others take no variable.
export const ORIGIN_TRAIL: Record<Origin["kind"], { view: View; from: MessageKey; back: MessageKey }> = {
  record: { view: "records", from: "trail.fromRecord", back: "trail.backToRecord" },
  suggestions: { view: "review", from: "trail.fromSuggestions", back: "trail.backToSuggestions" },
  library: { view: "library", from: "trail.fromLibrary", back: "trail.backToLibrary" },
  listening: { view: "listening", from: "trail.fromListening", back: "trail.backToListening" },
  reading: { view: "reading", from: "trail.fromReading", back: "trail.backToReading" },
  writing: { view: "writing", from: "trail.fromWriting", back: "trail.backToWriting" },
  speaking: { view: "speaking", from: "trail.fromSpeaking", back: "trail.backToSpeaking" },
  notebook: { view: "notebook", from: "trail.fromNotebook", back: "trail.backToNotebook" },
  exam: { view: "exam", from: "trail.fromExam", back: "trail.backToExam" },
  records: { view: "records", from: "trail.fromRecordSource", back: "trail.backToRecords" },
};

export const trailVars = (origin: Origin) => (origin.kind === "record" ? { id: origin.target.entryId } : undefined);
