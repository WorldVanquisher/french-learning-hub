import { useEffect, useState } from "react";
import * as api from "../api/client";
import { useI18n, type MessageKey } from "../i18n";
import { SourceLine } from "../pages/MistakeNotebook";
import { sourceOpen, type EntrySource, type SourceOpen } from "../types/notebook";

const skillKey: Record<string, MessageKey> = {
  listening: "notebook.skill.listening",
  reading: "notebook.skill.reading",
  writing: "notebook.skill.writing",
  speaking: "notebook.skill.speaking",
};

// RecordSource shows where a record was saved from (Mistake Notebook v1), read
// from its stored source row, or says honestly that it has none: a record
// saved without a source link is never linked by guessing.
export function RecordSource({ entryId, onOpenSource }: { entryId: number; onOpenSource?: (open: SourceOpen) => void }) {
  const { t } = useI18n();
  const [state, setState] = useState<{ status: "loading" } | { status: "error" } | { status: "ready"; data: EntrySource }>({ status: "loading" });
  useEffect(() => {
    let active = true;
    api.getEntrySource(entryId).then(
      (data) => active && setState({ status: "ready", data }),
      () => active && setState({ status: "error" }),
    );
    return () => {
      active = false;
    };
  }, [entryId]);
  if (state.status === "loading") return null;
  if (state.status === "error" || typeof state.data?.linked !== "boolean")
    return (
      <p className="hint" role="status">
        {t("notebook.record.failed")}
      </p>
    );
  const data = state.data;
  if (!data.linked)
    return (
      <section className="panel" aria-label={t("notebook.record.region")}>
        <p className="hint">{t("notebook.record.unlinked")}</p>
      </section>
    );
  const open = sourceOpen(data.item);
  return (
    <section className="panel" aria-label={t("notebook.record.region")}>
      <p>
        {t("notebook.record.linked", { skill: t(skillKey[data.item.skill] ?? "notebook.skill.listening"), title: data.item.title })}{" "}
        {data.item.retry.marked ? <span className="tag">{t("notebook.retry.tag")}</span> : null}
      </p>
      <SourceLine item={data.item} />
      {open && onOpenSource ? (
        <div className="actions">
          <button type="button" className="ghost" onClick={() => onOpenSource(open)}>
            {t("notebook.item.openSource")}
          </button>
        </div>
      ) : null}
    </section>
  );
}
