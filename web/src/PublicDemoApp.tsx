import { useEffect, useState } from "react";
import * as api from "./api/client";
import { KnowledgeLibrary } from "./pages/KnowledgeLibrary";
import type { PublicDemoInfo } from "./types/library";

// PublicDemoApp is the FLH-073 read-only public demo: a short introduction and
// the Knowledge Library only. There are no records, review, inspector or
// experiment views and no editing, import or review controls; the server
// refuses those routes regardless of what this page shows.
export default function PublicDemoApp() {
  const [info, setInfo] = useState<{ status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: PublicDemoInfo }>({
    status: "loading",
  });
  // The shared index.html names the workbench; the demo names itself.
  useEffect(() => {
    document.title = "Knowledge Library — read-only public demo";
    document.documentElement.lang = "en";
  }, []);
  useEffect(() => {
    let active = true;
    api
      .getPublicDemo()
      .then((data) => active && setInfo({ status: "ready", data }))
      .catch((e: unknown) => active && setInfo({ status: "error", message: e instanceof Error ? e.message : String(e) }));
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>Knowledge Library</h1>
          <p className="subtitle">A read-only public demo of a personal French-learning knowledge service.</p>
        </div>
      </header>
      <section className="panel" aria-label="About this demo">
        <p>
          Each <strong>concept</strong> is one idea a learner has studied, such as a grammar rule. Open one to see the
          short rules (units) filed under it and follow each unit back to the original question it came from.
        </p>
        <p>
          Try a <strong>keyword</strong> search with your own words, then compare <strong>semantic</strong> and{" "}
          <strong>hybrid</strong> results for the example queries. Hybrid merges both rankings and shows where every
          result came from.
        </p>
        <p className="hint">
          All data here is synthetic: invented questions written for this demo, not anyone's real learning records. The
          demo is read-only — nothing you do is saved — and it calls no AI service. Free-text semantic search is
          disabled; semantic and hybrid search use example queries prepared in advance.
        </p>
        {info.status === "ready" && !info.data.artifact.real_model ? (
          <div className="banner info" role="status">
            Development build: the vectors are mechanical test fixtures ({info.data.artifact.vector_generator}), not a
            real language model. Semantic and hybrid rankings show how the ranking works, not how relevant the results
            are.
          </div>
        ) : null}
        {info.status === "ready" ? (
          <p className="hint">
            Artifact {info.data.artifact.version} · vectors: {info.data.artifact.vector_source} ({info.data.artifact.model_id},{" "}
            {info.data.artifact.dimensions} dimensions).
          </p>
        ) : null}
      </section>
      {info.status === "loading" ? (
        <p className="empty" role="status">Loading the demo…</p>
      ) : info.status === "error" ? (
        <div className="banner error" role="alert">
          The demo is unavailable: {info.message}
        </div>
      ) : (
        <KnowledgeLibrary demo={info.data} />
      )}
    </div>
  );
}
