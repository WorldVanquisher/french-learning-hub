import { Fragment, useEffect, useRef, useState } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import { useI18n } from "../i18n";
import type {
  ListeningLineBlock,
  ListeningRestorePreview,
  ListeningRevisionComparison,
  ListeningRevisionHistory,
  ListeningRevisionRow,
} from "../types/listening";

// Revision studio (private workbench): the stored revisions of an imported
// script, what belongs to each (lines, questions and answer key, audio, the
// notebook records saved from it), a block comparison of any two, and a
// previewed restore. Reading writes nothing. A restore appends the older
// content as the next revision only after the explicit confirm button; a
// resend replays, and a preview that went stale (another tab or device) is
// replaced by a fresh one with nothing written.

const describe = (e: unknown) => (e instanceof ApiError ? `(${e.status}) ${e.message}` : e instanceof Error ? e.message : String(e));
const day = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString();
};
const short = (fp: string) => fp.replace(/^sha256:/, "").slice(0, 12);

type Load<T> = { status: "idle" } | { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: T };
type Restore =
  | { step: "closed" }
  | { step: "loading"; revision: number }
  | { step: "failed"; message: string }
  | { step: "preview"; preview: ListeningRestorePreview; stale: boolean; sending: boolean; unknown: boolean; error: string | null };

export function RevisionStudio({
  materialId,
  currentRevision,
  answered = 0,
  onRestored,
}: {
  materialId: number;
  currentRevision: number;
  answered?: number;
  onRestored: (from: number, to: number, replayed: boolean) => void;
}) {
  const { t, tp } = useI18n();
  const [open, setOpen] = useState(false);
  const [history, setHistory] = useState<Load<ListeningRevisionHistory>>({ status: "idle" });
  const [pair, setPair] = useState<{ from: number; to: number } | null>(null);
  const [comparison, setComparison] = useState<Load<ListeningRevisionComparison>>({ status: "idle" });
  const [restore, setRestore] = useState<Restore>({ step: "closed" });
  const sending = useRef(false);
  const restoreHeading = useRef<HTMLHeadingElement>(null);
  // Closing the restore preview gives focus back to the button that opened it.
  const opener = useRef<number | null>(null);
  const rowButtons = useRef<Record<number, HTMLButtonElement | null>>({});
  const closeRestore = () => {
    setRestore({ step: "closed" });
    const n = opener.current;
    requestAnimationFrame(() => (n !== null ? rowButtons.current[n]?.focus() : undefined));
  };

  useEffect(() => {
    if (!open) return;
    let live = true;
    setHistory({ status: "loading" });
    api.getListeningRevisions(materialId).then(
      (data) => {
        if (!live) return;
        setHistory({ status: "ready", data });
        const n = data.current_revision;
        setPair((p) => p ?? (n > 1 ? { from: n - 1, to: n } : null));
      },
      (e) => live && setHistory({ status: "error", message: describe(e) }),
    );
    return () => {
      live = false;
    };
  }, [open, materialId, currentRevision]);

  useEffect(() => {
    if (!pair) return;
    let live = true;
    setComparison({ status: "loading" });
    api.compareListeningRevisions(materialId, pair.from, pair.to).then(
      (data) => live && setComparison({ status: "ready", data }),
      (e) => live && setComparison({ status: "error", message: describe(e) }),
    );
    return () => {
      live = false;
    };
  }, [materialId, pair?.from, pair?.to]);

  useEffect(() => {
    if (restore.step === "preview" && !restore.sending) restoreHeading.current?.focus();
  }, [restore.step, restore.step === "preview" && restore.stale]);

  const previewRestore = async (revision: number) => {
    opener.current = revision;
    setRestore({ step: "loading", revision });
    try {
      const preview = await api.getListeningRestorePreview(materialId, revision);
      setRestore({ step: "preview", preview, stale: false, sending: false, unknown: false, error: null });
    } catch (e) {
      setRestore({ step: "failed", message: describe(e) });
    }
  };
  const confirmRestore = async (preview: ListeningRestorePreview) => {
    if (sending.current) return;
    sending.current = true;
    setRestore({ step: "preview", preview, stale: false, sending: true, unknown: false, error: null });
    try {
      const res = await api.restoreListeningRevision(materialId, preview.from.revision, preview.target_revision, preview.target_fingerprint);
      setRestore({ step: "closed" });
      onRestored(preview.from.revision, res.revision, res.replayed);
    } catch (e) {
      const body = e instanceof ApiError ? (e.body as { code?: string; preview?: ListeningRestorePreview } | null) : null;
      if (e instanceof ApiError && e.status === 409 && body?.code === "stale_preview" && body.preview) {
        setRestore({ step: "preview", preview: body.preview, stale: true, sending: false, unknown: false, error: null });
      } else if (e instanceof NetworkError) {
        setRestore({ step: "preview", preview, stale: false, sending: false, unknown: true, error: null });
      } else {
        setRestore({ step: "preview", preview, stale: false, sending: false, unknown: false, error: t("studio.restore.failed", { message: describe(e) }) });
      }
    } finally {
      sending.current = false;
    }
  };

  if (!open)
    return (
      <section className="panel revision-studio" aria-label={t("studio.region")}>
        <div className="actions">
          <button type="button" className="ghost" onClick={() => setOpen(true)} aria-expanded={false}>
            {t("studio.open", { n: currentRevision })}
          </button>
        </div>
      </section>
    );

  const rows = history.status === "ready" ? history.data.revisions : [];
  return (
    <section className="panel revision-studio" aria-label={t("studio.region")}>
      <h3>{t("studio.heading")}</h3>
      <div className="actions">
        <button type="button" className="ghost" onClick={() => setOpen(false)} aria-expanded={true}>
          {t("studio.close")}
        </button>
      </div>
      {history.status === "loading" ? <p className="hint" role="status">{t("studio.loading")}</p> : null}
      {history.status === "error" ? (
        <div className="banner error" role="alert">
          {t("studio.failed", { message: history.message })}
        </div>
      ) : null}
      {history.status === "ready" ? (
        <>
          {rows.length === 1 ? <p className="hint" data-studio="one-revision">{t("studio.oneRevision")}</p> : null}
          <ol className="studio-revisions" aria-label={t("studio.list")}>
            {rows.map((r) => (
              <RevisionRow
                key={r.revision}
                row={r}
                onCompare={() => setPair({ from: r.revision, to: history.data.current_revision })}
                onRestore={() => void previewRestore(r.revision)}
                restoreRef={(el) => {
                  rowButtons.current[r.revision] = el;
                }}
                restoring={restore.step === "loading" && restore.revision === r.revision}
              />
            ))}
          </ol>
        </>
      ) : null}

      {restore.step === "failed" ? (
        <div className="banner error" role="alert">
          {t("studio.restore.loadFailed", { message: restore.message })}
        </div>
      ) : null}
      {restore.step === "preview" ? (
        <div className="studio-restore" role="group" aria-label={t("studio.restore.region")}>
          <h4 ref={restoreHeading} tabIndex={-1}>
            {t("studio.restore.heading", { target: restore.preview.target_revision, current: restore.preview.from.revision })}
          </h4>
          {restore.stale ? (
            <div className="banner info" role="alert">
              {t("studio.restore.stale", { current: restore.preview.from.revision })}
            </div>
          ) : null}
          {restore.preview.blocked ? (
            <p role="status">
              {restore.preview.blocked === "is_current"
                ? t("studio.restore.isCurrent", { target: restore.preview.target_revision })
                : t("studio.restore.sameContent", { target: restore.preview.target_revision, current: restore.preview.from.revision })}
            </p>
          ) : (
            <>
              <ul className="listening-steps" aria-label={t("studio.restore.impact")}>
                <li>{t("studio.restore.appends", { next: restore.preview.next_revision ?? 0, target: restore.preview.target_revision })}</li>
                <li>{t("studio.restore.exercise", { exercise: restore.preview.current_exercise_id, current: restore.preview.from.revision })}</li>
                <li>
                  {restore.preview.records_on_current === null
                    ? t("studio.restore.recordsUnknown")
                    : tp("studio.restore.records", restore.preview.records_on_current.length, { current: restore.preview.from.revision })}
                </li>
                <li>{t("studio.restore.history")}</li>
              </ul>
              {answered > 0 ? (
                <div className="banner info" role="note">
                  {tp("listening.revision.unsaved", answered)}
                </div>
              ) : null}
            </>
          )}
          <BlockList comparison={restore.preview} />
          {restore.unknown ? (
            <div className="banner info" role="alert">
              {t("studio.restore.unknown")}
            </div>
          ) : null}
          {restore.error ? (
            <div className="banner error" role="alert">
              {restore.error}
            </div>
          ) : null}
          <div className="actions">
            {!restore.preview.blocked ? (
              <button type="button" className="primary" disabled={restore.sending} onClick={() => void confirmRestore(restore.preview)}>
                {restore.sending
                  ? t("studio.restore.sending")
                  : t("studio.restore.confirm", { target: restore.preview.target_revision, next: restore.preview.next_revision ?? 0 })}
              </button>
            ) : null}
            <button type="button" className="ghost" disabled={restore.sending} onClick={closeRestore}>
              {t("studio.restore.cancel")}
            </button>
          </div>
        </div>
      ) : null}

      {history.status === "ready" && rows.length > 1 ? (
        <div className="studio-compare" role="group" aria-label={t("studio.compare.region")}>
          <h4>{t("studio.compare.heading")}</h4>
          <div className="actions">
            {(["from", "to"] as const).map((side) => (
              <label key={side}>
                {t(side === "from" ? "studio.compare.from" : "studio.compare.to")}{" "}
                <select
                  value={pair?.[side] ?? ""}
                  onChange={(e) => {
                    const n = Number(e.target.value);
                    setPair((p) => ({ from: p?.from ?? 1, to: p?.to ?? history.data.current_revision, [side]: n }));
                  }}
                >
                  {rows.map((r) => (
                    <option key={r.revision} value={r.revision}>
                      {t("listening.revision.tag", { n: r.revision })}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
          {comparison.status === "loading" ? <p className="hint" role="status">{t("studio.loading")}</p> : null}
          {comparison.status === "error" ? (
            <div className="banner error" role="alert">
              {t("studio.failed", { message: comparison.message })}
            </div>
          ) : null}
          {comparison.status === "ready" ? <BlockList comparison={comparison.data} /> : null}
        </div>
      ) : null}
    </section>
  );
}

function RevisionRow({
  row,
  onCompare,
  onRestore,
  restoreRef,
  restoring,
}: {
  row: ListeningRevisionRow;
  onCompare: () => void;
  onRestore: () => void;
  restoreRef: (el: HTMLButtonElement | null) => void;
  restoring: boolean;
}) {
  const { t, tp } = useI18n();
  const today = row.linked_records?.filter((l) => l.in_review_today).length ?? 0;
  return (
    <li className="studio-revision" data-revision={row.revision}>
      <p>
        <strong>{t("listening.revision.tag", { n: row.revision })}</strong>{" "}
        {row.current ? <span className="tag">{t("studio.current")}</span> : null} <span className="hint">{day(row.created_at)}</span>
      </p>
      <dl className="studio-facts">
        <dt>{t("studio.fact.lines")}</dt>
        <dd>{tp("studio.fact.linesValue", row.lines, { transcript: row.transcript_id })}</dd>
        <dt>{t("studio.fact.prompt")}</dt>
        <dd>{tp("studio.fact.promptValue", row.questions, { exercise: row.exercise_id })}</dd>
        <dt>{t("studio.fact.rubric")}</dt>
        <dd>
          {t("studio.fact.rubricValue", { exercise: row.exercise_id })} <code>{row.generator}</code> · <code title={row.fingerprint}>{short(row.fingerprint)}</code>
        </dd>
        <dt>{t("studio.fact.audio")}</dt>
        <dd>{t("studio.fact.audioNone")}</dd>
        <dt>{t("studio.fact.records")}</dt>
        <dd>
          {row.linked_records === null
            ? t("studio.fact.recordsUnknown")
            : row.linked_records.length === 0
              ? t("studio.fact.recordsNone")
              : tp("studio.fact.recordsValue", row.linked_records.length, { today })}
        </dd>
      </dl>
      {!row.current ? (
        <div className="actions">
          <button type="button" className="ghost" onClick={onCompare}>
            {t("studio.compareWithCurrent", { n: row.revision })}
          </button>
          <button type="button" className="ghost" ref={restoreRef} disabled={restoring} onClick={onRestore}>
            {restoring ? t("studio.loading") : t("studio.previewRestore", { n: row.revision })}
          </button>
        </div>
      ) : null}
    </li>
  );
}

// A run of unchanged lines is folded behind one button when "hide unchanged"
// is on; the header always names both revisions.
type Run = { kind: "blocks"; blocks: ListeningLineBlock[] } | { kind: "fold"; blocks: ListeningLineBlock[]; key: string };
const unchanged = (b: ListeningLineBlock) => b.kind === "same" || b.kind === "renumbered";

function BlockList({ comparison }: { comparison: ListeningRevisionComparison }) {
  const { t, tp } = useI18n();
  const [hide, setHide] = useState(true);
  const [shown, setShown] = useState<Record<string, boolean>>({});
  const { from, to, blocks, changes } = comparison;
  const runs: Run[] = [];
  for (const b of blocks) {
    const last = runs[runs.length - 1];
    if (hide && unchanged(b)) {
      if (last?.kind === "fold") last.blocks.push(b);
      else runs.push({ kind: "fold", blocks: [b], key: b.after_line ?? b.before_line ?? String(runs.length) });
    } else if (last?.kind === "blocks") last.blocks.push(b);
    else runs.push({ kind: "blocks", blocks: [b] });
  }
  const edited = blocks.filter((b) => !unchanged(b)).length;
  const firstLine = (bs: ListeningLineBlock[]) => bs[0].after_line ?? bs[0].before_line ?? "";
  const lastLine = (bs: ListeningLineBlock[]) => bs[bs.length - 1].after_line ?? bs[bs.length - 1].before_line ?? "";
  return (
    <div className="studio-blocks">
      <p className="studio-source" data-from={from.revision} data-to={to.revision}>
        {t("studio.compare.between", { from: from.revision, to: to.revision })}{" "}
        <span className="hint">{tp("studio.compare.summary", edited, { questions: changes.questions.length })}</span>
      </p>
      <label className="notebook-filter">
        <input type="checkbox" checked={hide} onChange={(e) => setHide(e.target.checked)} /> {t("studio.compare.hideUnchanged")}
      </label>
      <ol className="studio-lines" aria-label={t("studio.compare.lines", { from: from.revision, to: to.revision })}>
        {runs.map((run, i) =>
          run.kind === "fold" && !shown[run.key] ? (
            <li key={`fold-${run.key}`} className="studio-fold" data-kind="fold">
              <button type="button" className="link-button" onClick={() => setShown((s) => ({ ...s, [run.key]: true }))}>
                {tp("studio.compare.folded", run.blocks.length, { first: firstLine(run.blocks), last: lastLine(run.blocks) })}
              </button>
            </li>
          ) : (
            <Fragment key={`run-${i}`}>
              {run.blocks.map((b, j) => (
                <Block key={`${b.kind}-${b.before_line ?? ""}-${b.after_line ?? ""}-${j}`} block={b} />
              ))}
            </Fragment>
          ),
        )}
      </ol>
    </div>
  );
}

function Block({ block: b }: { block: ListeningLineBlock }) {
  const { t } = useI18n();
  const label =
    b.kind === "added"
      ? t("studio.block.added", { line: b.after_line ?? "" })
      : b.kind === "removed"
        ? t("studio.block.removed", { line: b.before_line ?? "" })
        : b.kind === "changed"
          ? t("studio.block.changed", { before: b.before_line ?? "", after: b.after_line ?? "" })
          : b.kind === "renumbered"
            ? t("studio.block.renumbered", { before: b.before_line ?? "", after: b.after_line ?? "" })
            : t("studio.block.same", { line: b.after_line ?? "" });
  const line = b.after ?? b.before!;
  return (
    <li className={`studio-line studio-${b.kind}`} data-kind={b.kind}>
      <span className="tag">{label}</span>{" "}
      {b.kind === "changed" ? (
        <>
          {b.speaker_changed ? (
            <span className="hint">{t("studio.block.speaker", { before: b.before?.speaker ?? "", after: b.after?.speaker ?? "" })} </span>
          ) : null}
          <strong lang="fr">{line.speaker} :</strong>{" "}
          <span lang="fr" className="french studio-text">
            {b.words.map((w, i) =>
              w.op === "same" ? (
                <span key={i}>{w.text}</span>
              ) : w.op === "inserted" ? (
                <ins key={i} data-op="inserted">
                  <span className="visually-hidden">{t("studio.word.inserted")} </span>
                  {w.text}
                </ins>
              ) : (
                <del key={i} data-op="removed">
                  <span className="visually-hidden">{t("studio.word.removed")} </span>
                  {w.text}
                </del>
              ),
            )}
          </span>
        </>
      ) : (
        <>
          <strong lang="fr">{line.speaker} :</strong>{" "}
          <span lang="fr" className="french studio-text">
            {line.text}
          </span>
        </>
      )}
    </li>
  );
}
