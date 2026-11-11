import { useCallback, useEffect, useRef, useState } from "react";
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
import { LanguageSelect, LocaleProvider, useI18n, type MessageKey } from "./i18n";
import { ExplanationLanguageProvider, ExplanationLanguageSelect } from "./explanationLanguage";

type View = "home" | "records" | "library" | "listening" | "reading" | "writing" | "speaking" | "notebook" | "exam" | "review" | "inspector" | "experiments";

// The learning home lists the seven sections, then the Mock Exam.
const HOME_WITH_EXAM: { target: HomeTarget | "exam"; title: HomeSection["title"]; body: HomeSection["body"]; action: HomeSection["action"] }[] = [
  ...HOME_SECTIONS,
  { target: "exam", title: "home.exam.title", body: "home.exam.body", action: "home.exam.action" },
];

// Where a cross-view link came from, for the "Back to …" banner.
type Origin =
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

const viewCopy: Record<View, { title: MessageKey; subtitle: MessageKey; tab: MessageKey }> = {
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
const VIEWS: View[] = ["home", "records", "library", "listening", "reading", "writing", "speaking", "notebook", "exam", "review", "inspector", "experiments"];

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
  // Writing stays mounted once opened, so an unsaved revision and an open
  // mistake form survive opening a saved record and coming back.
  const [writingMounted, setWritingMounted] = useState(false);
  // Speaking stays mounted once opened: takes' audio exists only in its memory
  // (never stored), so leaving it mounted keeps a take playable after opening a
  // saved record and coming back.
  const [speakingMounted, setSpeakingMounted] = useState(false);
  // The Mistake Notebook stays mounted once opened, so its filter, an open
  // retry session and its self-checks survive opening a source and coming back.
  const [notebookMounted, setNotebookMounted] = useState(false);
  // Mock Exam stays mounted once opened, so a running exam (its unsaved
  // choices and countdown) survives a visit to another view.
  const [examMounted, setExamMounted] = useState(false);
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
    if (next === "writing") setWritingMounted(true);
    if (next === "speaking") setSpeakingMounted(true);
    if (next === "notebook") setNotebookMounted(true);
    if (next === "exam") setExamMounted(true);
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
  // openSource shows the exact item a notebook record was saved from.
  const openSource = (open: SourceOpen, from: Origin) => {
    setFocus(null);
    const n = ++nonce.current;
    if (open.skill === "listening") {
      setListeningMounted(true);
      setListeningOpen({ materialId: open.materialId, nonce: n, target: { exerciseId: open.exerciseId, item: open.item, version: open.version } });
    } else if (open.skill === "reading") {
      setReadingMounted(true);
      setReadingOpen({ lessonId: open.lessonId, nonce: n, target: { exerciseId: open.exerciseId, item: open.item, version: open.version } });
    } else if (open.skill === "writing") {
      setWritingMounted(true);
      setWritingOpen({ taskId: open.taskId, draftVersion: open.draftVersion, nonce: n });
    } else {
      setSpeakingMounted(true);
      setSpeakingOpen({ exerciseId: open.exerciseId, takeId: open.takeId, transcriptVersion: open.transcriptVersion, nonce: n });
    }
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
    } else if (from.kind === "writing") {
      setFocus(null);
      setView("writing");
    } else if (from.kind === "speaking") {
      setFocus(null);
      setView("speaking");
    } else if (from.kind === "notebook") {
      setFocus(null);
      setView("notebook");
    } else if (from.kind === "exam") {
      setFocus(null);
      setView("exam");
    } else if (from.kind === "records") {
      setFocus(null);
      setView("records");
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
            onOpenSource={(open) => openSource(open, { kind: "records" })}
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
          <Listening onOpenRecord={(entryId) => openRecord(entryId, { kind: "listening" })} openRequest={listeningOpen} />
        </div>
      ) : null}
      {readingMounted ? (
        <div hidden={view !== "reading"}>
          <Reading onOpenRecord={(entryId) => openRecord(entryId, { kind: "reading" })} openRequest={readingOpen} />
        </div>
      ) : null}
      {writingMounted ? (
        <div hidden={view !== "writing"}>
          <Writing onOpenRecord={(entryId) => openRecord(entryId, { kind: "writing" })} openRequest={writingOpen} />
        </div>
      ) : null}
      {speakingMounted ? (
        <div hidden={view !== "speaking"}>
          <Speaking onOpenRecord={(entryId) => openRecord(entryId, { kind: "speaking" })} openRequest={speakingOpen} />
        </div>
      ) : null}
      {view === "home" ? <LearningHome<HomeTarget | "exam"> sections={HOME_WITH_EXAM} onOpen={openHome} /> : null}
      {examMounted ? (
        <div hidden={view !== "exam"}>
          <MockExam onOpenRecord={(entryId) => openRecord(entryId, { kind: "exam" })} />
        </div>
      ) : null}
      {notebookMounted ? (
        <div hidden={view !== "notebook"}>
          <MistakeNotebook
            onOpenSource={(open) => openSource(open, { kind: "notebook" })}
            onOpenRecord={(entryId) => openRecord(entryId, { kind: "notebook" })}
            onOpenConcept={(conceptId) => openConcept(conceptId, { kind: "notebook" })}
            modeRequest={notebookMode}
          />
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
            : origin.kind === "writing"
              ? t("trail.backToWriting")
              : origin.kind === "speaking"
                ? t("trail.backToSpeaking")
                : origin.kind === "notebook"
                  ? t("trail.backToNotebook")
                  : origin.kind === "exam"
                    ? t("trail.backToExam")
                  : origin.kind === "records"
                    ? t("trail.backToRecords")
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
            : origin.kind === "writing"
              ? t("trail.fromWriting")
              : origin.kind === "speaking"
                ? t("trail.fromSpeaking")
                : origin.kind === "notebook"
                  ? t("trail.fromNotebook")
                  : origin.kind === "exam"
                    ? t("trail.fromExam")
                  : origin.kind === "records"
                    ? t("trail.fromRecordSource")
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
