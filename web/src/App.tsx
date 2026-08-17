import { useState } from "react";
import { AnnotationInspector } from "./pages/AnnotationInspector";
import { ReviewQueue } from "./pages/ReviewQueue";

type View = "review" | "inspector";

// App keeps the two internal annotation views behind a local tab switch. The
// inspector is intentionally separate from the write-capable review workflow.
export default function App() {
  const [view, setView] = useState<View>("review");

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>{view === "review" ? "Concept Review" : "Effective Annotation Inspector"}</h1>
          <p className="subtitle">
            {view === "review"
              ? "Experimental human annotation for KnowledgeUnit → KnowledgeConcept resolution. Every explicit decision is recorded as backend data."
              : "Read-only inspection of backend-derived annotation state for current-extraction units."}
          </p>
        </div>
      </header>
      <nav className="view-tabs" aria-label="Annotation views">
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
      </nav>
      {view === "review" ? <ReviewQueue /> : <AnnotationInspector />}
    </div>
  );
}
