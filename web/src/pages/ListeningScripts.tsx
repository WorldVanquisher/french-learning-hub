import { useEffect, useState } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import { useI18n } from "../i18n";
import type { ListeningScripts } from "../types/listening";

// Workbook listening scripts (private workbench; never in the public demo).
//
// The server embeds the authored, synthetic and unreviewed scripts of the FLH
// reading/listening workbook with their questions. This panel lists them by
// title only and imports one on an explicit click: the server stores it as a
// script-only listening lesson (no link, video, audio or timestamp) and makes
// no model call. Importing again replays and opens the same lesson, so a lost
// response is safe to resend.

const describe = (e: unknown) =>
  e instanceof ApiError ? `(${e.status}) ${e.message}` : e instanceof Error ? e.message : String(e);

type ImportState = { status: "idle" } | { status: "importing"; id: string } | { status: "unknown" } | { status: "error"; message: string };

export function ScriptsPanel({ epoch, onOpen }: { epoch: number; onOpen: (materialId: number) => void }) {
  const { t } = useI18n();
  const [retry, setRetry] = useState(0);
  const [load, setLoad] = useState<{ status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: ListeningScripts }>({
    status: "loading",
  });
  const [importing, setImporting] = useState<ImportState>({ status: "idle" });
  useEffect(() => {
    let active = true;
    setLoad({ status: "loading" });
    api.listListeningScripts().then(
      (data) => active && setLoad({ status: "ready", data }),
      (e: unknown) => active && setLoad({ status: "error", message: describe(e) }),
    );
    return () => {
      active = false;
    };
  }, [epoch, retry]);

  const importScript = async (id: string) => {
    setImporting({ status: "importing", id });
    try {
      const lesson = await api.importListeningScript(id);
      setImporting({ status: "idle" });
      onOpen(lesson.material.id);
    } catch (e) {
      setImporting(
        e instanceof NetworkError ? { status: "unknown" } : { status: "error", message: t("listening.scripts.importFailed", { message: describe(e) }) },
      );
    }
  };

  return (
    <section className="panel" aria-label={t("listening.scripts.region")}>
      <h2>{t("listening.scripts.heading")}</h2>
      <p className="hint">{t("listening.scripts.hint")}</p>
      {load.status === "loading" ? (
        <p className="hint" role="status">
          {t("listening.scripts.loading")}
        </p>
      ) : load.status === "error" ? (
        <div className="banner error" role="alert">
          {t("listening.scripts.failed", { message: load.message })}{" "}
          <button type="button" className="ghost" onClick={() => setRetry((n) => n + 1)}>
            {t("common.retry")}
          </button>
        </div>
      ) : load.data.scripts.length === 0 ? (
        <p className="empty">{t("listening.scripts.empty")}</p>
      ) : (
        <>
        <p className="hint">
          {t("listening.scripts.importedCount", {
            imported: load.data.scripts.filter((s) => s.imported_material_id !== null).length,
            total: load.data.scripts.length,
          })}
        </p>
        <ul className="listening-list">
          {load.data.scripts.map((s) => (
            <li key={s.id}>
              <span lang="fr" className="french">
                {s.title}
              </span>{" "}
              <span className="tag">{t("listening.source.scriptOnly")}</span>
              {s.imported_material_id !== null ? (
                <>
                  {" "}
                  <span className="tag">{t("listening.scripts.imported")}</span>
                </>
              ) : null}
              <div className="hint">
                {t("listening.scripts.meta", { genre: s.genre, level: s.style_level, lines: s.lines, questions: s.questions })}
              </div>
              {s.imported_material_id !== null ? (
                <button type="button" className="ghost" onClick={() => onOpen(s.imported_material_id!)}>
                  {t("listening.scripts.open", { title: s.title })}
                </button>
              ) : (
                <button type="button" className="ghost" disabled={importing.status === "importing"} onClick={() => importScript(s.id)}>
                  {importing.status === "importing" && importing.id === s.id ? t("listening.scripts.importing") : t("listening.scripts.import", { title: s.title })}
                </button>
              )}
            </li>
          ))}
        </ul>
        </>
      )}
      {importing.status === "unknown" ? (
        <div className="banner info" role="alert">
          {t("listening.scripts.importUnknown")}
        </div>
      ) : importing.status === "error" ? (
        <div className="banner error" role="alert">
          {importing.message}
        </div>
      ) : null}
    </section>
  );
}
