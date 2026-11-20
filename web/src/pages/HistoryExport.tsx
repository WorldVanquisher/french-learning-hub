import { useState } from "react";
import * as api from "../api/client";
import { ApiError } from "../api/client";
import { useI18n, type MessageKey } from "../i18n";
import type { HistoryExportOptions, HistoryExportPreview, HistoryImportPreview } from "../types/history";

// Portable learning history (private workbench): preview an export before
// downloading it, choose whether transcripts and notes are included (both off
// by default), and check an export file against what is stored. Audio and
// credentials are never exported. The check never writes: there is no import.

const describe = (e: unknown) => (e instanceof ApiError ? `(${e.status}) ${e.message}` : e instanceof Error ? e.message : String(e));
const KINDS: [string, MessageKey][] = [
  ["listening_material", "portable.kind.listening_material"],
  ["speaking_take", "portable.kind.speaking_take"],
  ["writing_draft", "portable.kind.writing_draft"],
  ["notebook_record", "portable.kind.notebook_record"],
];
const integrityKey: Record<HistoryImportPreview["integrity"], MessageKey> = {
  complete: "portable.integrity.complete",
  truncated: "portable.integrity.truncated",
  corrupted: "portable.integrity.corrupted",
  unchecked: "portable.integrity.unchecked",
  unreadable: "portable.integrity.unreadable",
};
const resolutionKey: Record<"new" | "same" | "conflict", MessageKey> = {
  new: "portable.resolution.new",
  same: "portable.resolution.same",
  conflict: "portable.resolution.conflict",
};
const statusKey: Record<"new" | "same" | "conflict", MessageKey> = {
  new: "portable.status.new",
  same: "portable.status.same",
  conflict: "portable.status.conflict",
};

// readText reads a chosen file as UTF-8 text (FileReader: every browser).
const readText = (file: File) =>
  new Promise<string>((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result ?? ""));
    r.onerror = () => reject(r.error ?? new Error("the file could not be read"));
    r.readAsText(file, "utf-8");
  });

type Load<T> = { status: "idle" } | { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: T };

export function HistoryExport() {
  const { t, tp } = useI18n();
  const [open, setOpen] = useState(false);
  const [opts, setOpts] = useState<HistoryExportOptions>({ transcripts: false, notes: false });
  const [preview, setPreview] = useState<Load<HistoryExportPreview>>({ status: "idle" });
  const [check, setCheck] = useState<Load<HistoryImportPreview & { name: string }>>({ status: "idle" });
  const load = async (o: HistoryExportOptions) => {
    setPreview({ status: "loading" });
    try {
      setPreview({ status: "ready", data: await api.getHistoryExportPreview(o) });
    } catch (e) {
      setPreview({ status: "error", message: describe(e) });
    }
  };
  const toggle = (k: keyof HistoryExportOptions) => {
    const next = { ...opts, [k]: !opts[k] };
    setOpts(next);
    if (preview.status !== "idle") void load(next);
  };
  const choose = async (file: File | undefined) => {
    if (!file) return;
    setCheck({ status: "loading" });
    try {
      const data = await api.previewHistoryImport(await readText(file));
      setCheck({ status: "ready", data: { ...data, name: file.name } });
    } catch (e) {
      setCheck({ status: "error", message: describe(e) });
    }
  };
  if (!open)
    return (
      <section className="today-history-export" aria-label={t("portable.region")}>
        <button type="button" className="ghost" aria-expanded={false} onClick={() => setOpen(true)}>
          {t("portable.open")}
        </button>
      </section>
    );
  const p = preview.status === "ready" ? preview.data : null;
  const textState = (selected: boolean, omitted: number) =>
    selected ? t("portable.text.included") : omitted > 0 ? tp("portable.text.omitted", omitted) : t("portable.text.absent");
  return (
    <section className="today-history-export" aria-label={t("portable.region")}>
      <h3>{t("portable.heading")}</h3>
      <button type="button" className="ghost" aria-expanded={true} onClick={() => setOpen(false)}>
        {t("portable.close")}
      </button>
      <p className="hint">{t("portable.hint")}</p>
      <fieldset className="history-options">
        <legend>{t("portable.options")}</legend>
        <label>
          <input type="checkbox" checked={opts.transcripts} onChange={() => toggle("transcripts")} /> {t("portable.option.transcripts")}
        </label>
        <label>
          <input type="checkbox" checked={opts.notes} onChange={() => toggle("notes")} /> {t("portable.option.notes")}
        </label>
        <p className="hint">{t("portable.never")}</p>
      </fieldset>
      <div className="actions">
        <button type="button" className="primary" onClick={() => void load(opts)}>
          {t("portable.preview")}
        </button>
      </div>
      {preview.status === "loading" ? <p className="hint" role="status">{t("portable.loading")}</p> : null}
      {preview.status === "error" ? (
        <div className="banner error" role="alert">
          {t("portable.failed", { message: preview.message })}
        </div>
      ) : null}
      {p ? (
        <div className="history-preview" role="group" aria-label={t("portable.previewRegion")}>
          <p role="status">{t("portable.summary", { records: p.footer.records, format: p.header.format })}</p>
          <ul className="listening-steps">
            {KINDS.map(([k, key]) => (
              <li key={k} data-kind={k}>
                {t(key)}: {p.header.counts[k] ?? 0}
              </li>
            ))}
          </ul>
          <dl className="studio-facts">
            <dt>{t("portable.option.transcripts")}</dt>
            <dd data-text="transcripts">{textState(p.header.included.transcripts, p.header.omitted_texts.transcripts ?? 0)}</dd>
            <dt>{t("portable.option.notes")}</dt>
            <dd data-text="notes">
              {textState(
                p.header.included.notes,
                (p.header.omitted_texts.text ?? 0) + (p.header.omitted_texts.original_input ?? 0) + (p.header.omitted_texts.original_context ?? 0) + (p.header.omitted_texts.attempt ?? 0),
              )}
            </dd>
            <dt>{t("portable.audio")}</dt>
            <dd>{t("portable.audioNever")}</dd>
          </dl>
          <h4>{t("portable.files")}</h4>
          <ul className="listening-steps" aria-label={t("portable.files")}>
            {p.files.map((f) => (
              <li key={f.format} data-format={f.format}>
                <a href={api.historyExportUrl(opts, f.format === "text" ? "text" : undefined)} download>
                  {t(f.format === "text" ? "portable.download.text" : "portable.download.ndjson")}
                </a>{" "}
                {t(f.app_import === "preview_only" ? "portable.file.ndjson" : "portable.file.text")}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <h4>{t("portable.check.heading")}</h4>
      <label htmlFor="history-check-file">{t("portable.check.label")}</label>{" "}
      <input id="history-check-file" type="file" accept=".ndjson,.jsonl,.json,application/x-ndjson,text/plain" onChange={(e) => void choose(e.target.files?.[0])} />
      <p className="hint">{t("portable.check.hint")}</p>
      {check.status === "loading" ? <p className="hint" role="status">{t("portable.loading")}</p> : null}
      {check.status === "error" ? (
        <div className="banner error" role="alert">
          {t("portable.check.failed", { message: check.message })}
        </div>
      ) : null}
      {check.status === "ready" ? (
        <div className="history-check" role="group" aria-label={t("portable.check.region")} data-integrity={check.data.integrity}>
          <p role="status">
            {t(integrityKey[check.data.integrity], { name: check.data.name, format: check.data.format ?? "?" })}
          </p>
          {check.data.problems.length > 0 ? (
            <ul className="banner error">
              {check.data.problems.map((pr, i) => (
                <li key={i}>{pr}</li>
              ))}
            </ul>
          ) : null}
          {check.data.missing_fields.length > 0 ? <p className="hint">{t("portable.check.missing", { fields: check.data.missing_fields.join(", ") })}</p> : null}
          <p>{t("portable.check.counts", { newCount: check.data.new, same: check.data.same, conflicts: check.data.conflicts })}</p>
          <ol className="listening-steps" aria-label={t("portable.check.rows")}>
            {check.data.rows.slice(0, 50).map((r) => (
              <li key={`${r.line}-${r.key}`} data-status={r.status}>
                <span className="tag">{t(statusKey[r.status])}</span> <code>{r.key}</code>
                {r.fields.length > 0 ? ` (${r.fields.join(", ")})` : ""} — {t(resolutionKey[r.status])}
              </li>
            ))}
          </ol>
          <p className="hint">{t("portable.check.nothingWritten")}</p>
        </div>
      ) : null}
    </section>
  );
}
