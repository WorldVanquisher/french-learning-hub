import { useEffect, useState } from "react";
import * as api from "./api/client";
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
  // The shared index.html names the workbench; the demo names itself. The
  // provider sets the document language.
  useEffect(() => {
    document.title = t("demo.documentTitle");
  }, [t]);
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
  const strong = (text: string) => <strong>{text}</strong>;

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>{t("demo.title")}</h1>
          <p className="subtitle">{t("demo.subtitle")}</p>
        </div>
        <LanguageSelect />
      </header>
      <section className="panel" aria-label={t("demo.about")}>
        <p>{tn("demo.about.concepts", { concept: strong(t("demo.term.concept")) })}</p>
        <p>
          {tn("demo.about.modes", {
            keyword: strong(t("demo.term.keyword")),
            semantic: strong(t("demo.term.semantic")),
            hybrid: strong(t("demo.term.hybrid")),
          })}
        </p>
        <p className="hint">{t("demo.about.synthetic")}</p>
        {info.status === "ready" && !info.data.artifact.real_model ? (
          <div className="banner info" role="status">
            {t("demo.mechanical", { generator: info.data.artifact.vector_generator })}
          </div>
        ) : null}
        {info.status === "ready" ? (
          <p className="hint">
            {t("demo.artifact", {
              version: info.data.artifact.version,
              source: info.data.artifact.vector_source,
              model: info.data.artifact.model_id,
              dimensions: info.data.artifact.dimensions,
            })}
          </p>
        ) : null}
      </section>
      {info.status === "loading" ? (
        <p className="empty" role="status">{t("demo.loading")}</p>
      ) : info.status === "error" ? (
        <div className="banner error" role="alert">
          {t("demo.unavailable", { message: info.message })}
        </div>
      ) : (
        <KnowledgeLibrary demo={info.data} />
      )}
    </div>
  );
}
