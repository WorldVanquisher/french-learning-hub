import { useCallback, useEffect, useState } from "react";
import { AnnotationInspector } from "./pages/AnnotationInspector";
import { ExperimentDashboard } from "./pages/ExperimentDashboard";
import { KnowledgeLibrary } from "./pages/KnowledgeLibrary";
import { RecordsBrowser } from "./pages/RecordsBrowser";
import { ReviewQueue, type ReviewResume } from "./pages/ReviewQueue";
import { ConceptSuggestions } from "./pages/ConceptSuggestions";
import { UnitInspection } from "./pages/UnitInspection";
import { recordHeadingId, unitFocusId, type UnitTarget } from "./navigation";
import { LanguageSelect, LocaleProvider, useI18n, type MessageKey } from "./i18n";
import { ExplanationLanguageProvider, ExplanationLanguageSelect } from "./explanationLanguage";

type View = "records" | "library" | "review" | "inspector" | "experiments";

const viewCopy: Record<View, { title: MessageKey; subtitle: MessageKey; tab: MessageKey }> = {
  records: { title: "app.records.title", subtitle: "app.records.subtitle", tab: "nav.records" },
  library: { title: "app.library.title", subtitle: "app.library.subtitle", tab: "nav.library" },
  review: { title: "app.review.title", subtitle: "app.review.subtitle", tab: "nav.review" },
  inspector: { title: "app.inspector.title", subtitle: "app.inspector.subtitle", tab: "nav.inspector" },
  experiments: { title: "app.experiments.title", subtitle: "app.experiments.subtitle", tab: "nav.experiments" },
};
const VIEWS: View[] = ["records", "library", "review", "inspector", "experiments"];

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
    setView(next);
    if (next === "records") setRecordsMounted(true);
    if (next === "library") setLibraryMounted(true);
  };
  const openUnit = (target: UnitTarget) => {
    setFocus(target);
    setView(target.kind === "review" ? "review" : "inspector");
  };
  const backToRecord = () => {
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
      {recordsMounted ? (
        <div hidden={view !== "records"}>
          <RecordsBrowser returnEpoch={returnEpoch} onNavigateToUnit={openUnit} />
        </div>
      ) : null}
      {libraryMounted ? (
        <div hidden={view !== "library"}>
          <KnowledgeLibrary />
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
            {reviewMode === "queue" ? (
              <ReviewQueue resume={reviewResume} onResumeChange={keepReviewResume} />
            ) : (
              <ConceptSuggestions />
            )}
          </>
        )
      ) : view === "inspector" ? (
        focus ? (
          <UnitInspection
            key={`inspect-${focus.entryId}-${focus.unitId}`}
            focus={focus}
            onBack={backToRecord}
            onReview={() => openUnit({ ...focus, kind: "review" })}
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
