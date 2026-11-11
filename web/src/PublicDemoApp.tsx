import { useEffect, useState } from "react";
import * as api from "./api/client";
import { ApiError } from "./api/client";
import { KnowledgeLibrary } from "./pages/KnowledgeLibrary";
import type { PublicDemoInfo } from "./types/library";
import { LanguageSelect, LocaleProvider, useI18n } from "./i18n";

// PublicDemoApp is the FLH-073 read-only public demo: a short introduction and
// the Knowledge Library only. There are no records, review, inspector or
// experiment views and no editing, import or review controls; the server
// refuses those routes regardless of what this page shows. The language choice
// (English by default) only changes application text; it is stored in this
// browser and never sent to the server.
export default function PublicDemoApp() {
  return (
    <LocaleProvider>
      <PublicDemo />
    </LocaleProvider>
  );
}

function PublicDemo() {
  const { t, tn } = useI18n();
  const [info, setInfo] = useState<{ status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: PublicDemoInfo }>({
    status: "loading",
  });
  // A failed read of the demo description is retried in place: a visitor who
  // arrives during a restart should not have to know to reload the page.
  const [attempt, setAttempt] = useState(0);
  // The shared index.html names the workbench; the demo names itself. The
  // provider sets the document language.
  useEffect(() => {
    document.title = t("demo.documentTitle");
  }, [t]);
  useEffect(() => {
    let active = true;
    setInfo({ status: "loading" });
    api
      .getPublicDemo()
      .then((data) => active && setInfo({ status: "ready", data }))
      .catch(
        (e: unknown) =>
          active &&
          setInfo({
            status: "error",
            message: e instanceof ApiError ? `(${e.status}) ${e.message}` : e instanceof Error ? e.message : String(e),
          }),
      );
    return () => {
      active = false;
    };
  }, [attempt]);
  const strong = (text: string) => <strong>{text}</strong>;
  const mechanical = info.status === "ready" && !info.data.artifact.real_model;

  // The starting screen: one sentence on what to do and the warning a
  // mechanical build needs, then the examples, then the synthetic-data notice
  // and artifact identity (always in view) with the longer explanation folded
  // away. On a phone the first example is then on the first screen. The labels
  // in the header stay visible on every screen.
  const intro =
    info.status === "ready" ? (
      <section className="panel demo-intro" aria-label={t("demo.start")}>
        <p className="demo-lead">{t("demo.lead")}</p>
        {mechanical ? (
          <div className="banner info" role="status">
            {tn("demo.mechanical.short", { strong: strong(t("demo.mechanical.strong")) })}
          </div>
        ) : null}
      </section>
    ) : null;
  const about =
    info.status === "ready" ? (
      <section className="panel demo-about" aria-label={t("demo.about")}>
        <details className="demo-details">
          <summary>{t("demo.details")}</summary>
          <p>{tn("demo.about.concepts", { concept: strong(t("demo.term.concept")) })}</p>
          <p>
            {tn("demo.about.modes", {
              keyword: strong(t("demo.term.keyword")),
              semantic: strong(t("demo.term.semantic")),
              hybrid: strong(t("demo.term.hybrid")),
            })}
          </p>
          {mechanical ? <p className="hint">{t("demo.mechanical", { generator: info.data.artifact.vector_generator })}</p> : null}
        </details>
        <p className="hint">{t("demo.about.synthetic")}</p>
        <p className="hint">
          {t("demo.artifact", {
            version: info.data.artifact.version,
            source: info.data.artifact.vector_source,
            model: info.data.artifact.model_id,
            dimensions: info.data.artifact.dimensions,
          })}
        </p>
      </section>
    ) : null;

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>{t("demo.title")}</h1>
          <p className="subtitle">{t("demo.subtitle")}</p>
          <p className="demo-labels">
            <span className="tag demo-label">{t("demo.label.readOnly")}</span>{" "}
            <span className="tag demo-label">{t("demo.label.synthetic")}</span>
            {mechanical ? (
              <>
                {" "}
                <span className="tag demo-label warn">{t("demo.label.mechanical")}</span>
              </>
            ) : null}
          </p>
        </div>
        <LanguageSelect />
      </header>
      {info.status === "loading" ? (
        <p className="empty" role="status">{t("demo.loading")}</p>
      ) : info.status === "error" ? (
        <div className="banner error" role="alert">
          {t("demo.unavailable", { message: info.message })}{" "}
          <button type="button" className="ghost" onClick={() => setAttempt((n) => n + 1)}>
            {t("common.tryAgain")}
          </button>
        </div>
      ) : (
        <KnowledgeLibrary demo={info.data} intro={intro} about={about} guided />
      )}
    </div>
  );
}
