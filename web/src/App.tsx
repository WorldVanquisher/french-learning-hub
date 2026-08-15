import { ReviewQueue } from "./pages/ReviewQueue";

// App is the single experimental dashboard for milestone 10.6. It is an
// annotation / data-collection instrument for future resolver experiments — NOT the
// Review Engine, mastery, scheduling, or an ML resolver. No authentication in this
// milestone.
export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>Concept Review</h1>
          <p className="subtitle">
            Experimental human annotation for KnowledgeUnit → KnowledgeConcept
            resolution. Every decision is recorded as backend data for later resolver
            training. This is not the Review Engine.
          </p>
        </div>
      </header>
      <ReviewQueue />
    </div>
  );
}
