import { useState } from "react";
import { AnnotationInspector } from "./pages/AnnotationInspector";
import { ExperimentDashboard } from "./pages/ExperimentDashboard";
import { ReviewQueue } from "./pages/ReviewQueue";

type View = "review" | "inspector" | "experiments";

const viewCopy: Record<View, { title: string; subtitle: string }> = {
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

// App keeps the three internal workbench views behind a local tab switch. The
// Inspector and Experiment Dashboard remain separate from the write-capable
// Concept Review workflow.
export default function App() {
  const [view, setView] = useState<View>("review");
  const copy = viewCopy[view];

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
          aria-pressed={view === "review"}
          onClick={() => setView("review")}
        >
          Concept Review
        </button>
        <button
          type="button"
          aria-pressed={view === "inspector"}
          onClick={() => setView("inspector")}
        >
          Annotation Inspector
        </button>
        <button
          type="button"
          aria-pressed={view === "experiments"}
          onClick={() => setView("experiments")}
        >
          Experiment Dashboard
        </button>
      </nav>
      {view === "review" ? (
        <ReviewQueue />
      ) : view === "inspector" ? (
        <AnnotationInspector />
      ) : (
        <ExperimentDashboard />
      )}
    </div>
  );
}
