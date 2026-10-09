import { useEffect, useState } from "react";
import { AnnotationInspector } from "./pages/AnnotationInspector";
import { ExperimentDashboard } from "./pages/ExperimentDashboard";
import { KnowledgeLibrary } from "./pages/KnowledgeLibrary";
import { RecordsBrowser } from "./pages/RecordsBrowser";
import { ReviewQueue } from "./pages/ReviewQueue";
import { UnitInspection } from "./pages/UnitInspection";
import { recordHeadingId, unitFocusId, type UnitTarget } from "./navigation";

type View = "records" | "library" | "review" | "inspector" | "experiments";

const viewCopy: Record<View, { title: string; subtitle: string }> = {
  records: {
    title: "Learning Records",
    subtitle: "Import captures, browse learner-authored records, and explicitly request analysis or extraction. Interpretations and eligibility stay backend-owned.",
  },
  library: {
    title: "Knowledge Library",
    subtitle: "Search curated Concepts, see their current support, and follow evidence back to the original record. Read-only.",
  },
  review: {
    title: "Concept Review",
    subtitle: "Experimental human annotation for KnowledgeUnit → KnowledgeConcept resolution. Every explicit decision is recorded as backend data.",
  },
  inspector: {
    title: "Effective Annotation Inspector",
    subtitle: "Read-only inspection of backend-derived annotation state for current-extraction units.",
  },
  experiments: {
    title: "Experiment Dashboard",
    subtitle: "Read-only dataset quality and retrieval baseline comparison from backend-owned reports.",
  },
};

// App keeps the internal workbench views behind a local tab switch. Learning
// Records writes only through explicit capture import, analysis, feedback, and
// extraction requests; the Knowledge Library, Inspector and Experiment Dashboard
// are read-only;
// Concept Review records annotation decisions.
//
// A record's extracted unit can be opened in Concept Review or a focused
// inspection. Learning Records stays mounted (hidden) meanwhile, so returning
// restores the record, its viewed extraction, filters, drafts, and position.
export default function App() {
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
  // A unit opened from a record may be historical, so the inspector's general
  // description ("current-extraction units") would not fit it.
  const copy =
    view === "inspector" && focus
      ? {
          title: "Unit Inspection",
          subtitle: "Read-only inspection of one unit opened from a record, including whether it belongs to the record's current extraction.",
        }
      : viewCopy[view];

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
      </header>
      <nav className="view-tabs" aria-label="Workbench views">
        <button
          type="button"
          aria-pressed={view === "records"}
          onClick={() => show("records")}
        >
          Learning Records
        </button>
        <button
          type="button"
          aria-pressed={view === "library"}
          onClick={() => show("library")}
        >
          Knowledge Library
        </button>
        <button
          type="button"
          aria-pressed={view === "review"}
          onClick={() => show("review")}
        >
          Concept Review
        </button>
        <button
          type="button"
          aria-pressed={view === "inspector"}
          onClick={() => show("inspector")}
        >
          Annotation Inspector
        </button>
        <button
          type="button"
          aria-pressed={view === "experiments"}
          onClick={() => show("experiments")}
        >
          Experiment Dashboard
        </button>
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
          <ReviewQueue />
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
