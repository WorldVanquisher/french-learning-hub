import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { AnnotationInspector } from "./pages/AnnotationInspector";
import { ExperimentDashboard } from "./pages/ExperimentDashboard";
import { KnowledgeLibrary } from "./pages/KnowledgeLibrary";
import { Listening } from "./pages/Listening";
import { Reading } from "./pages/Reading";
import { Writing } from "./pages/Writing";
import { Speaking } from "./pages/Speaking";
import { MistakeNotebook, type NotebookMode } from "./pages/MistakeNotebook";
import { HOME_SECTIONS, LearningHome, type HomeSection, type HomeTarget } from "./pages/LearningHome";
import { MockExam } from "./pages/MockExam";
import type { SourceOpen } from "./types/notebook";
import { RecordsBrowser } from "./pages/RecordsBrowser";
import { ReviewQueue, type ReviewResume } from "./pages/ReviewQueue";
import { ConceptSuggestions } from "./pages/ConceptSuggestions";
import { UnitInspection } from "./pages/UnitInspection";
import { recordHeadingId, unitFocusId, type UnitTarget } from "./navigation";
import { LanguageSelect, LocaleProvider, useI18n } from "./i18n";
import { ExplanationLanguageProvider, ExplanationLanguageSelect } from "./explanationLanguage";
import { ThemeSelect } from "./theme";
import { isKeptView, ORIGIN_TRAIL, trailVars, VIEW_COPY, VIEWS, type KeptView, type Origin, type View } from "./workbenchViews";

// The learning home lists the seven sections, then the Mock Exam.
const HOME_WITH_EXAM: { target: HomeTarget | "exam"; title: HomeSection["title"]; body: HomeSection["body"]; action: HomeSection["action"] }[] = [
  ...HOME_SECTIONS,
  { target: "exam", title: "home.exam.title", body: "home.exam.body", action: "home.exam.action" },
];

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
  // Views kept mounted once opened (KEPT_VIEWS): Learning Records keeps its
  // record, filters and drafts; the library its query and open Concept;
  // Listening and Reading a lesson's typed answers and reveal (never stored);
  // Writing an unsaved revision and an open mistake form; Speaking its takes'
  // audio (memory only); the Mistake Notebook its filter and retry session;
  // Mock Exam a running exam's choices and countdown.
  const [mounted, setMounted] = useState<ReadonlySet<KeptView>>(() => new Set());
  const keep = (v: View) => {
    if (isKeptView(v)) setMounted((prev) => (prev.has(v) ? prev : new Set(prev).add(v)));
  };
  // Requests to open the exact source item of a notebook record in its skill view.
  const [listeningOpen, setListeningOpen] = useState<{ materialId: number; nonce: number; target?: { exerciseId: number; item: number; version: number } } | null>(null);
  const [readingOpen, setReadingOpen] = useState<{ lessonId: number; nonce: number; target?: { exerciseId: number; item: number; version: number } } | null>(null);
  // The learning home opens the notebook directly at Grammar or Vocabulary.
  const [notebookMode, setNotebookMode] = useState<{ mode: NotebookMode; nonce: number } | null>(null);
  const [writingOpen, setWritingOpen] = useState<{ taskId: number; draftVersion: number; nonce: number } | null>(null);
  const [speakingOpen, setSpeakingOpen] = useState<{ exerciseId: number; takeId: number; transcriptVersion: number; nonce: number } | null>(null);
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
      : { title: t(VIEW_COPY[view].title), subtitle: t(VIEW_COPY[view].subtitle) };

  useEffect(() => {
    document.title = t("app.documentTitle");
  }, [t]);

  const show = (next: View) => {
    setFocus(null);
    setOrigin(null);
    setView(next);
    keep(next);
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
    keep("library");
    setLibraryOpen({ conceptId, nonce: ++nonce.current });
    setOrigin({ from, on: "library" });
    setView("library");
  };
  // openRecord shows one record in Learning Records; its list keeps its filters.
  const openRecord = (entryId: number, from: Origin) => {
    setFocus(null);
    keep("records");
    setRecordOpen({ entryId, nonce: ++nonce.current });
    setOrigin({ from, on: "records" });
    setView("records");
    setReturnEpoch((n) => n + 1);
  };
  // openSource shows the exact item a notebook record was saved from.
  const openSource = (open: SourceOpen, from: Origin) => {
    setFocus(null);
    const n = ++nonce.current;
    if (open.skill === "listening") {
      setListeningOpen({ materialId: open.materialId, nonce: n, target: { exerciseId: open.exerciseId, item: open.item, version: open.version } });
    } else if (open.skill === "reading") {
      setReadingOpen({ lessonId: open.lessonId, nonce: n, target: { exerciseId: open.exerciseId, item: open.item, version: open.version } });
    } else if (open.skill === "writing") {
      setWritingOpen({ taskId: open.taskId, draftVersion: open.draftVersion, nonce: n });
    } else {
      setSpeakingOpen({ exerciseId: open.exerciseId, takeId: open.takeId, transcriptVersion: open.transcriptVersion, nonce: n });
    }
    keep(open.skill);
    setOrigin({ from, on: open.skill });
    setView(open.skill);
  };
  const openHome = (target: HomeTarget | "exam") => {
    if (target === "grammar" || target === "vocabulary") {
      setNotebookMode({ mode: target, nonce: ++nonce.current });
      show("notebook");
    } else {
      show(target);
    }
  };
  // goBack returns to the view a cross-view link left (ORIGIN_TRAIL), which
  // stayed mounted; a record also re-reads and gets keyboard focus back.
  const goBack = (from: Origin) => {
    setOrigin(null);
    setFocus(null);
    if (from.kind === "record") {
      setReturnFocus(from.target);
      setReturnEpoch((n) => n + 1);
    }
    if (from.kind === "suggestions") setReviewMode("suggestions");
    setView(ORIGIN_TRAIL[from.kind].view);
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
        <ThemeSelect />
      </header>
      <nav className="view-tabs" aria-label={t("nav.label")}>
        {VIEWS.map((v) => (
          <button key={v} type="button" aria-pressed={view === v} onClick={() => show(v)}>
            {t(VIEW_COPY[v].tab)}
          </button>
        ))}
      </nav>
      {origin && origin.on === view && !focus ? <BackBanner origin={origin.from} onBack={() => goBack(origin.from)} /> : null}
      <Kept view="records" shown={view} mounted={mounted}>
        <RecordsBrowser
          returnEpoch={returnEpoch}
          onNavigateToUnit={openUnit}
          onOpenConcept={(conceptId, from) => openConcept(conceptId, { kind: "record", target: from })}
          onOpenSource={(open) => openSource(open, { kind: "records" })}
          openRequest={recordOpen}
        />
      </Kept>
      <Kept view="library" shown={view} mounted={mounted}>
        <KnowledgeLibrary openRequest={libraryOpen} onOpenRecord={(entryId) => openRecord(entryId, { kind: "library" })} />
      </Kept>
      <Kept view="listening" shown={view} mounted={mounted}>
        <Listening onOpenRecord={(entryId) => openRecord(entryId, { kind: "listening" })} openRequest={listeningOpen} />
      </Kept>
      <Kept view="reading" shown={view} mounted={mounted}>
        <Reading onOpenRecord={(entryId) => openRecord(entryId, { kind: "reading" })} openRequest={readingOpen} />
      </Kept>
      <Kept view="writing" shown={view} mounted={mounted}>
        <Writing onOpenRecord={(entryId) => openRecord(entryId, { kind: "writing" })} openRequest={writingOpen} />
      </Kept>
      <Kept view="speaking" shown={view} mounted={mounted}>
        <Speaking onOpenRecord={(entryId) => openRecord(entryId, { kind: "speaking" })} openRequest={speakingOpen} />
      </Kept>
      {view === "home" ? <LearningHome<HomeTarget | "exam"> sections={HOME_WITH_EXAM} onOpen={openHome} /> : null}
      <Kept view="exam" shown={view} mounted={mounted}>
        <MockExam onOpenRecord={(entryId) => openRecord(entryId, { kind: "exam" })} />
      </Kept>
      <Kept view="notebook" shown={view} mounted={mounted}>
        <MistakeNotebook
          onOpenSource={(open) => openSource(open, { kind: "notebook" })}
          onOpenRecord={(entryId) => openRecord(entryId, { kind: "notebook" })}
          onOpenConcept={(conceptId) => openConcept(conceptId, { kind: "notebook" })}
          modeRequest={notebookMode}
        />
      </Kept>
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


// stayed mounted, so it shows its state as it was left.
// Kept renders a KEPT_VIEWS view once it has been opened and hides it while
// another view is shown, so its state survives the visit.
function Kept({ view, shown, mounted, children }: { view: KeptView; shown: View; mounted: ReadonlySet<KeptView>; children: ReactNode }) {
  return mounted.has(view) ? <div hidden={shown !== view}>{children}</div> : null;
}

// BackBanner returns to the view a cross-view link was followed from. That view
// stayed mounted, so it shows its state as it was left.
function BackBanner({ origin, onBack }: { origin: Origin; onBack: () => void }) {
  const { t } = useI18n();
  const trail = ORIGIN_TRAIL[origin.kind];
  const vars = trailVars(origin);
  return (
    <div className="banner info trail" role="navigation" aria-label={t("trail.label")}>
      {t(trail.from, vars)}{" "}
      <button type="button" className="ghost" onClick={onBack}>
        {t(trail.back, vars)}
      </button>
    </div>
  );
}
