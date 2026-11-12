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
// response is safe to resend. An imported script whose pack version was
// corrected is tagged "Update available"; the update itself is offered only
// inside the lesson, after a preview (never from this list, never on load).

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
          {(["imported", "available"] as const).map((group) => {
            const rows = load.data.scripts.filter((s) => (group === "imported") === (s.imported_material_id !== null));
            const headingId = `listening-scripts-${group}`;
            return (
              <div key={group}>
                <h3 id={headingId}>
                  {t(group === "imported" ? "listening.scripts.groupImported" : "listening.scripts.groupAvailable", { count: rows.length })}
                </h3>
                {rows.length === 0 ? (
                  <p className="empty">{t(group === "imported" ? "listening.scripts.noneImported" : "listening.scripts.allImported")}</p>
                ) : (
                  <ul className="listening-list" aria-labelledby={headingId}>
                    {rows.map((s) => (
                      <li key={s.id}>
                        <span lang="fr" className="french">
                          {s.title}
                        </span>{" "}
                        <span className="tag">{t("listening.source.scriptOnly")}</span>
                        {s.imported_material_id !== null ? (
                          <>
                            {" "}
                            <span className="tag">{t("listening.scripts.imported")}</span>
                            {s.imported_revision ? (
                              <>
                                {" "}
                                <span className="tag">{t("listening.revision.tag", { n: s.imported_revision })}</span>
                              </>
                            ) : null}
                            {s.pack_status === "update_available" ? (
                              <>
                                {" "}
                                <span className="tag listening-update">{t("listening.scripts.updateAvailable")}</span>
                              </>
                            ) : null}
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
                            {importing.status === "importing" && importing.id === s.id
                              ? t("listening.scripts.importing")
                              : t("listening.scripts.import", { title: s.title })}
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
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

// NextScript is the end-of-lesson step to the next workbook script, in pack
// order: it opens it when already imported, otherwise imports it on this
// explicit click (no model call; a lost response is safe to resend because the
// server replays). Nothing is shown after the last script.
export function NextScript({ packScriptId, onOpen }: { packScriptId: string; onOpen: (materialId: number) => void }) {
  const { t } = useI18n();
  const [scripts, setScripts] = useState<ListeningScripts | null>(null);
  const [state, setState] = useState<ImportState>({ status: "idle" });
  useEffect(() => {
    let active = true;
    api.listListeningScripts().then(
      (data) => active && setScripts(data),
      () => active && setScripts(null), // the lesson works without it; the back button remains
    );
    return () => {
      active = false;
    };
  }, [packScriptId]);
  if (!scripts) return null;
  const at = scripts.scripts.findIndex((s) => packScriptId.endsWith("/" + s.id));
  const next = at >= 0 ? scripts.scripts[at + 1] : undefined;
  if (!next) return at >= 0 ? <p className="hint">{t("listening.nav.lastScript")}</p> : null;
  const go = async () => {
    if (next.imported_material_id !== null) {
      onOpen(next.imported_material_id);
      return;
    }
    setState({ status: "importing", id: next.id });
    try {
      const lesson = await api.importListeningScript(next.id);
      onOpen(lesson.material.id);
    } catch (e) {
      setState(e instanceof NetworkError ? { status: "unknown" } : { status: "error", message: t("listening.scripts.importFailed", { message: describe(e) }) });
    }
  };
  return (
    <>
      {/* Secondary on purpose: before reveal, "Reveal answers and evidence" stays the one primary action. */}
      <button type="button" className="ghost" disabled={state.status === "importing"} onClick={go}>
        {state.status === "importing" ? t("listening.scripts.importing") : t("listening.nav.next", { title: next.title })}
      </button>
      {state.status === "unknown" ? (
        <div className="banner info" role="alert">
          {t("listening.scripts.importUnknown")}
        </div>
      ) : state.status === "error" ? (
        <div className="banner error" role="alert">
          {state.message}
        </div>
      ) : null}
    </>
  );
}
