import { useCallback, useEffect, useRef, useState } from "react";
import { AnnotationInspector } from "./pages/AnnotationInspector";
import { ExperimentDashboard } from "./pages/ExperimentDashboard";
import { KnowledgeLibrary } from "./pages/KnowledgeLibrary";
import { Listening } from "./pages/Listening";
import { Reading } from "./pages/Reading";
import { RecordsBrowser } from "./pages/RecordsBrowser";
import { ReviewQueue, type ReviewResume } from "./pages/ReviewQueue";
import { ConceptSuggestions } from "./pages/ConceptSuggestions";
import { UnitInspection } from "./pages/UnitInspection";
import { recordHeadingId, unitFocusId, type UnitTarget } from "./navigation";
import { LanguageSelect, LocaleProvider, useI18n, type MessageKey } from "./i18n";
import { ExplanationLanguageProvider, ExplanationLanguageSelect } from "./explanationLanguage";

type View = "records" | "library" | "listening" | "reading" | "review" | "inspector" | "experiments";

// Where a cross-view link came from, for the "Back to …" banner.
type Origin =
  | { kind: "record"; target: UnitTarget }
  | { kind: "suggestions" }
  | { kind: "library" }
  | { kind: "listening" }
  | { kind: "reading" };

const viewCopy: Record<View, { title: MessageKey; subtitle: MessageKey; tab: MessageKey }> = {
  records: { title: "app.records.title", subtitle: "app.records.subtitle", tab: "nav.records" },
  library: { title: "app.library.title", subtitle: "app.library.subtitle", tab: "nav.library" },
  listening: { title: "app.listening.title", subtitle: "app.listening.subtitle", tab: "nav.listening" },
  reading: { title: "app.reading.title", subtitle: "app.reading.subtitle", tab: "nav.reading" },
  review: { title: "app.review.title", subtitle: "app.review.subtitle", tab: "nav.review" },
  inspector: { title: "app.inspector.title", subtitle: "app.inspector.subtitle", tab: "nav.inspector" },
  experiments: { title: "app.experiments.title", subtitle: "app.experiments.subtitle", tab: "nav.experiments" },
};
const VIEWS: View[] = ["records", "library", "listening", "reading", "review", "inspector", "experiments"];

// App keeps the internal workbench views behind a local tab switch. Learning
// Records writes only through explicit capture import, analysis, feedback, and
// extraction requests; the Knowledge Library, Inspector and Experiment Dashboard
// are read-only, except that a unit inspection opened from a record can send
// explicit corrections of an already reviewed current unit;
// Concept Review records annotation decisions. Its "AI suggestions" mode
// (FLH-097) lists stored advisory suggestions; generating them is an explicit
// request and only an explicit per-item confirmation records a human SAME.
//
// The general Concept Review queue is re-read from the backend whenever it is
// shown, but resumes at the unit (and catalog search) where the reviewer left it.
//
// A record's extracted unit can be opened in Concept Review or a focused
// inspection. Learning Records stays mounted (hidden) meanwhile, so returning
// restores the record, its viewed extraction, filters, drafts, and position.
//
// The daily journey also crosses views (Daily workflow v1.0 RC): a decided unit
// opens its Concept in the Knowledge Library; a Concept's source opens its
// record; an AI suggestion opens its unit's record or the Concept the unit is
// filed under. Every such link only opens a read view. The view that was left
// stays mounted, and a "Back to …" banner returns to it.
export default function App() {
  // The provider sits above every view, so switching the language re-renders text in
  // place and never remounts a view or discards its state.
  return (
    <LocaleProvider>
      <ExplanationLanguageProvider>
        <Workbench />
      </ExplanationLanguageProvider>
    </LocaleProvider>
  );
}

function Workbench() {
  const { t } = useI18n();
  const [view, setView] = useState<View>("review");
  const [recordsMounted, setRecordsMounted] = useState(false);
  // The library stays mounted once opened, so its query, results and open
  // Concept survive switching to another view and back.
  const [libraryMounted, setLibraryMounted] = useState(false);
  // Listening stays mounted once opened, so a lesson's typed answers and reveal
  // survive opening a saved record and coming back (they are never stored).
  const [listeningMounted, setListeningMounted] = useState(false);
  // Reading stays mounted once opened, for the same reason.
  const [readingMounted, setReadingMounted] = useState(false);
  // The unit opened from a record, or null for the ordinary tab views.
  const [focus, setFocus] = useState<UnitTarget | null>(null);
  // Bumped on return so the record re-reads what may have changed elsewhere.
  const [returnEpoch, setReturnEpoch] = useState(0);
  const [returnFocus, setReturnFocus] = useState<UnitTarget | null>(null);
  // Where the general Concept Review queue was left (unit, position, search text).
  // The queue unmounts when another view is shown; this restores its place.
  const [reviewResume, setReviewResume] = useState<ReviewResume | null>(null);
  const keepReviewResume = useCallback((next: ReviewResume) => setReviewResume(next), []);
  // The general Concept Review shows either the unit queue or AI suggestions.
  const [reviewMode, setReviewMode] = useState<"queue" | "suggestions">("queue");
  // AI suggestions stay mounted once opened, so an open run survives a visit to
  // a record or a Concept; returning re-reads it (refreshEpoch).
  const [suggestionsMounted, setSuggestionsMounted] = useState(false);
  const [suggestionsEpoch, setSuggestionsEpoch] = useState(0);
  // Cross-view open requests; the nonce makes a repeated request open again.
  const nonce = useRef(0);
  const [libraryOpen, setLibraryOpen] = useState<{ conceptId: number; nonce: number } | null>(null);
  const [recordOpen, setRecordOpen] = useState<{ entryId: number; nonce: number } | null>(null);
  // The view a cross-view link left, shown as a "Back to …" banner on view `on`.
  const [origin, setOrigin] = useState<{ from: Origin; on: View } | null>(null);
  // A unit opened from a record may be historical, so the inspector's general
  // description ("current-extraction units") would not fit it.
  const copy =
    view === "inspector" && focus
      ? { title: t("app.unitInspection.title"), subtitle: t("app.unitInspection.subtitle") }
      : { title: t(viewCopy[view].title), subtitle: t(viewCopy[view].subtitle) };

  useEffect(() => {
    document.title = t("app.documentTitle");
  }, [t]);

  const show = (next: View) => {
    setFocus(null);
    setOrigin(null);
    setView(next);
    if (next === "records") setRecordsMounted(true);
    if (next === "library") setLibraryMounted(true);
    if (next === "listening") setListeningMounted(true);
    if (next === "reading") setReadingMounted(true);
  };

  const suggestionsVisible = view === "review" && !focus && reviewMode === "suggestions";
  useEffect(() => {
    if (suggestionsVisible) setSuggestionsMounted(true);
  }, [suggestionsVisible]);
  // Each time the suggestions become visible again, they re-read current state.
  const wasVisible = useRef(false);
  useEffect(() => {
    if (suggestionsVisible && !wasVisible.current && suggestionsMounted) setSuggestionsEpoch((n) => n + 1);
    wasVisible.current = suggestionsVisible;
  }, [suggestionsVisible, suggestionsMounted]);

  // openConcept shows one Concept in the Knowledge Library.
  const openConcept = (conceptId: number, from: Origin) => {
    setFocus(null);
    setLibraryMounted(true);
    setLibraryOpen({ conceptId, nonce: ++nonce.current });
    setOrigin({ from, on: "library" });
    setView("library");
  };
  // openRecord shows one record in Learning Records; its list keeps its filters.
  const openRecord = (entryId: number, from: Origin) => {
    setFocus(null);
    setRecordsMounted(true);
    setRecordOpen({ entryId, nonce: ++nonce.current });
    setOrigin({ from, on: "records" });
    setView("records");
    setReturnEpoch((n) => n + 1);
  };
  const goBack = (from: Origin) => {
    setOrigin(null);
    if (from.kind === "record") {
      setReturnFocus(from.target);
      setFocus(null);
      setView("records");
      setReturnEpoch((n) => n + 1);
    } else if (from.kind === "suggestions") {
      setFocus(null);
      setReviewMode("suggestions");
      setView("review");
    } else if (from.kind === "listening") {
      setFocus(null);
      setView("listening");
    } else if (from.kind === "reading") {
      setFocus(null);
      setView("reading");
    } else {
      setFocus(null);
      setView("library");
    }
  };
  const openUnit = (target: UnitTarget) => {
    setFocus(target);
    setView(target.kind === "review" ? "review" : "inspector");
  };
  const backToRecord = () => {
    setOrigin(null);
    setReturnFocus(focus);
    setFocus(null);
    setView("records");
    setReturnEpoch((n) => n + 1);
  };

  // Put keyboard focus back on the unit the reader left from, or the record.
  useEffect(() => {
    if (view !== "records" || !returnFocus) return;
    const target =
      document.getElementById(unitFocusId(returnFocus.unitId)) ??
      document.getElementById(recordHeadingId(returnFocus.entryId));
    target?.focus();
    setReturnFocus(null);
  }, [view, returnFocus]);

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>{copy.title}</h1>
          <p className="subtitle">{copy.subtitle}</p>
        </div>
        <LanguageSelect />
        <ExplanationLanguageSelect />
      </header>
      <nav className="view-tabs" aria-label={t("nav.label")}>
        {VIEWS.map((v) => (
          <button key={v} type="button" aria-pressed={view === v} onClick={() => show(v)}>
            {t(viewCopy[v].tab)}
          </button>
        ))}
      </nav>
      {origin && origin.on === view && !focus ? <BackBanner origin={origin.from} onBack={() => goBack(origin.from)} /> : null}
      {recordsMounted ? (
        <div hidden={view !== "records"}>
          <RecordsBrowser
            returnEpoch={returnEpoch}
            onNavigateToUnit={openUnit}
            onOpenConcept={(conceptId, from) => openConcept(conceptId, { kind: "record", target: from })}
            openRequest={recordOpen}
          />
        </div>
      ) : null}
      {libraryMounted ? (
        <div hidden={view !== "library"}>
          <KnowledgeLibrary openRequest={libraryOpen} onOpenRecord={(entryId) => openRecord(entryId, { kind: "library" })} />
        </div>
      ) : null}
      {listeningMounted ? (
        <div hidden={view !== "listening"}>
          <Listening onOpenRecord={(entryId) => openRecord(entryId, { kind: "listening" })} />
        </div>
      ) : null}
      {readingMounted ? (
        <div hidden={view !== "reading"}>
          <Reading onOpenRecord={(entryId) => openRecord(entryId, { kind: "reading" })} />
        </div>
      ) : null}
      {view === "review" ? (
        focus ? (
          <ReviewQueue
            key={`review-${focus.entryId}-${focus.unitId}`}
            focus={focus}
            onBack={backToRecord}
            onInspect={(unitId) => openUnit({ ...focus, kind: "inspect", unitId })}
          />
        ) : (
          <>
            <div className="view-tabs review-modes" role="group" aria-label={t("review.mode.label")}>
              <button type="button" aria-pressed={reviewMode === "queue"} onClick={() => setReviewMode("queue")}>
                {t("review.mode.queue")}
              </button>
              <button type="button" aria-pressed={reviewMode === "suggestions"} onClick={() => setReviewMode("suggestions")}>
                {t("review.mode.suggestions")}
              </button>
            </div>
            {reviewMode === "queue" ? <ReviewQueue resume={reviewResume} onResumeChange={keepReviewResume} /> : null}
          </>
        )
      ) : null}
      {/* After the review-mode tabs; kept mounted once opened (see suggestionsMounted). */}
      {suggestionsMounted ? (
        <div hidden={!suggestionsVisible}>
          <ConceptSuggestions
            refreshEpoch={suggestionsEpoch}
            onOpenRecord={(entryId) => openRecord(entryId, { kind: "suggestions" })}
            onOpenConcept={(conceptId) => openConcept(conceptId, { kind: "suggestions" })}
          />
        </div>
      ) : null}
      {view === "inspector" ? (
        focus ? (
          <UnitInspection
            key={`inspect-${focus.entryId}-${focus.unitId}`}
            focus={focus}
            onBack={backToRecord}
            onReview={() => openUnit({ ...focus, kind: "review" })}
            onOpenConcept={(conceptId) => openConcept(conceptId, { kind: "record", target: focus })}
          />
        ) : (
          <AnnotationInspector />
        )
      ) : view === "experiments" ? (
        <ExperimentDashboard />
      ) : null}
    </div>
  );
}

// BackBanner returns to the view a cross-view link was followed from. That view
// stayed mounted, so it shows its state as it was left.
function BackBanner({ origin, onBack }: { origin: Origin; onBack: () => void }) {
  const { t } = useI18n();
  const label =
    origin.kind === "record"
      ? t("trail.backToRecord", { id: origin.target.entryId })
      : origin.kind === "suggestions"
        ? t("trail.backToSuggestions")
        : origin.kind === "listening"
          ? t("trail.backToListening")
          : origin.kind === "reading"
            ? t("trail.backToReading")
            : t("trail.backToLibrary");
  const from =
    origin.kind === "record"
      ? t("trail.fromRecord", { id: origin.target.entryId })
      : origin.kind === "suggestions"
        ? t("trail.fromSuggestions")
        : origin.kind === "listening"
          ? t("trail.fromListening")
          : origin.kind === "reading"
            ? t("trail.fromReading")
            : t("trail.fromLibrary");
  return (
    <div className="banner info trail" role="navigation" aria-label={t("trail.label")}>
      {from}{" "}
      <button type="button" className="ghost" onClick={onBack}>
        {label}
      </button>
    </div>
  );
}
