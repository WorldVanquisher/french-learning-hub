import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  NetworkError,
  confirmSuggestion,
  createSuggestionRun,
  getSuggestionOverview,
  getSuggestionRun,
  getSuggestionRunByOperation,
  listReviewableUnitsPage,
} from "../api/client";
import { ConceptContent } from "../components/ConceptContent";
import { UnitCard } from "../components/UnitCard";
import { StoredText } from "../components/ExplanationText";
import { msg, useI18n, type MessageKey, type MessageRef } from "../i18n";
import type { ReviewableUnit } from "../types/concept";
import type { SuggestionItem, SuggestionOverview, SuggestionRun, SuggestionStaleReason } from "../types/suggestion";
import { randomOperationId } from "./annotationOperation";
import {
  SuggestionStorageError,
  clearPendingRequest,
  loadPendingRequest,
  savePendingRequest,
  type PendingSuggestionRequest,
} from "./suggestionRequest";

// FLH-097 AI-assisted Concept membership suggestions, inside Concept Review.
//
// Reading, selecting and opening runs send no write. "Generate suggestions" is
// the only action that may contact the provider; "Confirm SAME" is the only
// action that records an annotation, and the backend revalidates the current
// state in the same transaction. "Leave unused" records nothing at all: it is
// not DISTINCT, INVALID or any other judgment. There is no bulk acceptance.

const QUEUE_PAGE = 50;

const staleKey: Record<SuggestionStaleReason, MessageKey> = {
  unit_not_in_current_extraction: "suggest.stale.unit_not_in_current_extraction",
  unit_has_current_same: "suggest.stale.unit_has_current_same",
  unit_invalid: "suggest.stale.unit_invalid",
  target_retired: "suggest.stale.target_retired",
  target_identity_changed: "suggest.stale.target_identity_changed",
  target_distinct_recorded: "suggest.stale.target_distinct_recorded",
};

const outcomeKey: Record<SuggestionItem["outcome"], MessageKey> = {
  suggested: "suggest.outcome.suggested",
  no_suitable_candidate: "suggest.outcome.no_suitable_candidate",
  uncertain: "suggest.outcome.uncertain",
  no_candidates: "suggest.outcome.no_candidates",
};

const stateKey: Record<SuggestionItem["state"], MessageKey> = {
  open: "suggest.state.open",
  confirmed: "suggest.state.confirmed",
  stale: "suggest.state.stale",
  no_suggestion: "suggest.state.no_suggestion",
};

type Notice = { tone: "info" | "error"; text: MessageRef | string } | null;

function serverDetail(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function ConceptSuggestions() {
  const { t } = useI18n();
  const [overview, setOverview] = useState<SuggestionOverview | null>(null);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [queue, setQueue] = useState<ReviewableUnit[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [queueLoading, setQueueLoading] = useState(true);
  const [selected, setSelected] = useState<number[]>([]);
  const [pending, setPending] = useState<PendingSuggestionRequest | null>(null);
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [run, setRun] = useState<SuggestionRun | null>(null);

  const refreshOverview = useCallback(async () => {
    try {
      setOverview(await getSuggestionOverview());
      setOverviewError(null);
    } catch (e) {
      setOverviewError(serverDetail(e));
    }
  }, []);

  useEffect(() => {
    void refreshOverview();
    void (async () => {
      try {
        const page = await listReviewableUnitsPage({ limit: QUEUE_PAGE });
        setQueue(page.reviewable_units);
        setCursor(page.next_cursor);
      } catch (e) {
        setNotice({ tone: "error", text: serverDetail(e) });
      } finally {
        setQueueLoading(false);
      }
    })();
    try {
      setPending(loadPendingRequest());
    } catch {
      setNotice({ tone: "error", text: msg("suggest.storage.unreadable") });
    }
  }, [refreshOverview]);

  const loadMore = async () => {
    if (!cursor) return;
    setQueueLoading(true);
    try {
      const page = await listReviewableUnitsPage({ limit: QUEUE_PAGE, after: cursor });
      setQueue((q) => [...q, ...page.reviewable_units]);
      setCursor(page.next_cursor);
    } catch (e) {
      setNotice({ tone: "error", text: serverDetail(e) });
    } finally {
      setQueueLoading(false);
    }
  };

  const maxUnits = overview?.limits.max_units ?? 0;
  const toggle = (unitId: number) =>
    setSelected((s) => (s.includes(unitId) ? s.filter((id) => id !== unitId) : s.length < maxUnits ? [...s, unitId] : s));

  const forget = (operationId: string) => {
    try {
      clearPendingRequest(operationId);
    } catch {
      setNotice({ tone: "error", text: msg("suggest.storage.cleanupFailed") });
    }
    setPending(null);
  };

  // send performs the one provider-contacting request under an explicit key.
  const send = async (request: PendingSuggestionRequest) => {
    setSending(true);
    setNotice(null);
    try {
      const created = await createSuggestionRun(request.unitIds, request.operationId);
      forget(request.operationId);
      setRun(created);
      if (created.status === "failed") {
        // A same-key replay of an earlier failed run: known outcome, nothing new
        // was called. Retrying is a separate, explicit new request.
        setNotice({ tone: "error", text: msg("suggest.notice.failedStored") });
      } else {
        setSelected([]);
        setNotice({ tone: "info", text: msg("suggest.notice.stored", { id: created.id }) });
      }
    } catch (e) {
      if (e instanceof ApiError && e.body && typeof e.body === "object" && "run" in e.body) {
        // Provider or output failure: the failed run is stored; the outcome is known.
        forget(request.operationId);
        setRun((e.body as { run: SuggestionRun }).run);
        setNotice({ tone: "error", text: msg("suggest.notice.failedStored") });
      } else if (e instanceof NetworkError || (e instanceof ApiError && (e.status >= 500 || e.status === 409 && /in progress/.test(e.message)))) {
        setNotice({ tone: "error", text: msg("suggest.notice.unknown") });
      } else {
        // Refused before generation (validation, disabled, key conflict): nothing stored.
        forget(request.operationId);
        setNotice({ tone: "error", text: serverDetail(e) });
      }
    } finally {
      setSending(false);
      void refreshOverview();
    }
  };

  // startNew sends a NEW request (fresh key) for the given units. It is used by
  // Generate and by the explicit retry of a failed run; nothing calls it
  // automatically.
  const startNew = async (unitIds: number[]) => {
    if (unitIds.length === 0 || pending || sending) return;
    const request = { operationId: randomOperationId(), unitIds: [...unitIds] };
    try {
      savePendingRequest(request);
    } catch (e) {
      if (e instanceof SuggestionStorageError) {
        setNotice({ tone: "error", text: msg("suggest.storage.notSent") });
        return;
      }
      throw e;
    }
    setPending(request);
    await send(request);
  };
  const generate = () => startNew(selected);

  const checkPending = async () => {
    if (!pending) return;
    try {
      const stored = await getSuggestionRunByOperation(pending.operationId);
      forget(pending.operationId);
      setRun(stored);
      setNotice(
        stored.status === "failed"
          ? { tone: "error", text: msg("suggest.notice.foundFailed", { id: stored.id }) }
          : { tone: "info", text: msg("suggest.notice.found", { id: stored.id }) },
      );
    } catch (e) {
      if (e instanceof ApiError && e.isNotFound) setNotice({ tone: "info", text: msg("suggest.notice.notCommitted") });
      else setNotice({ tone: "error", text: serverDetail(e) });
    }
  };

  const openRun = async (id: number) => {
    try {
      setRun(await getSuggestionRun(id));
    } catch (e) {
      setNotice({ tone: "error", text: serverDetail(e) });
    }
  };

  const enabled = overview?.enabled ?? false;
  return (
    <div className="suggestions">
      <section className="panel" aria-labelledby="suggest-select-heading">
        <h2 id="suggest-select-heading">{t("suggest.select.title")}</h2>
        <p className="hint">{t("suggest.select.intro")}</p>
        {overviewError ? <p className="error">{overviewError}</p> : null}
        {overview && !enabled ? <p className="notice">{t("suggest.disabled")}</p> : null}
        {overview ? (
          <p className="hint">
            {t("suggest.limits", {
              units: overview.limits.max_units,
              candidates: overview.limits.candidates_per_unit,
              unitChars: overview.limits.max_unit_text_chars,
              conceptChars: overview.limits.max_concept_text_chars,
            })}
          </p>
        ) : null}
        {queueLoading && queue.length === 0 ? <p>{t("suggest.queue.loading")}</p> : null}
        {!queueLoading && queue.length === 0 ? <p>{t("suggest.queue.empty")}</p> : null}
        <ul className="suggest-queue">
          {queue.map((u) => {
            const checked = selected.includes(u.unit_id);
            const full = !checked && selected.length >= maxUnits;
            return (
              <li key={u.unit_id}>
                <label>
                  <input type="checkbox" checked={checked} disabled={full || !!pending} onChange={() => toggle(u.unit_id)} />{" "}
                  <span className="french">{u.canonical}</span>{" "}
                  <span className="muted">{t("suggest.queue.unitMeta", { id: u.unit_id, entry: u.entry_id ?? "—" })}</span>
                </label>
                <div className="french statement">
                  <StoredText primary={u.statement} variants={u.statements} kind="statement" />
                </div>
              </li>
            );
          })}
        </ul>
        {cursor ? (
          <button type="button" onClick={() => void loadMore()} disabled={queueLoading}>
            {t("suggest.queue.more")}
          </button>
        ) : null}
        <p role="status">{t("suggest.selectedCount", { count: selected.length, max: maxUnits })}</p>
        <button
          type="button"
          className="primary"
          disabled={!enabled || selected.length === 0 || sending || !!pending}
          onClick={() => void generate()}
        >
          {sending ? t("suggest.generating") : t("suggest.generate")}
        </button>
        <p className="hint">{t("suggest.generate.note")}</p>
      </section>

      {notice ? (
        <p className={notice.tone === "error" ? "error" : "notice"} role="status">
          {typeof notice.text === "string" ? notice.text : t(notice.text.msgKey, notice.text.vars)}
        </p>
      ) : null}

      {pending && !sending ? (
        <section className="panel" aria-labelledby="suggest-pending-heading">
          <h2 id="suggest-pending-heading">{t("suggest.pending.title")}</h2>
          <p>{t("suggest.pending.body", { units: pending.unitIds.join(", ") })}</p>
          <div className="actions">
            <button type="button" onClick={() => void checkPending()}>{t("suggest.pending.check")}</button>
            <button type="button" onClick={() => void send(pending)}>{t("suggest.pending.resend")}</button>
            <button type="button" onClick={() => forget(pending.operationId)}>{t("suggest.pending.forget")}</button>
          </div>
          <p className="hint">{t("suggest.pending.note")}</p>
        </section>
      ) : null}

      {run ? (
        <RunView
          run={run}
          onRunChange={setRun}
          canRetry={enabled && !pending && !sending}
          onRetry={() => void startNew(run.unit_ids)}
        />
      ) : null}

      <section className="panel" aria-labelledby="suggest-runs-heading">
        <h2 id="suggest-runs-heading">{t("suggest.runs.title")}</h2>
        {overview && overview.runs.length === 0 ? <p>{t("suggest.runs.empty")}</p> : null}
        <ul className="suggest-runs">
          {overview?.runs.map((r) => (
            <li key={r.id}>
              <button type="button" onClick={() => void openRun(r.id)} aria-pressed={run?.id === r.id}>
                {t("suggest.runs.item", { id: r.id, units: r.unit_ids.length, suggested: r.suggested_count, created: r.created_at })}
              </button>{" "}
              <span className={r.status === "failed" ? "error" : "muted"}>
                {r.status === "failed" ? t("suggest.run.failed", { code: r.failure_code ?? "" }) : t("suggest.run.completed")}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function RunView({
  run,
  onRunChange,
  canRetry,
  onRetry,
}: {
  run: SuggestionRun;
  onRunChange: (r: SuggestionRun) => void;
  canRetry: boolean;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  const [left, setLeft] = useState<number[]>([]);
  const replaceItem = (item: SuggestionItem) =>
    onRunChange({ ...run, items: (run.items ?? []).map((i) => (i.id === item.id ? item : i)) });
  const reread = async () => onRunChange(await getSuggestionRun(run.id));
  return (
    <section className="panel" aria-labelledby="suggest-run-heading">
      <h2 id="suggest-run-heading">{t("suggest.run.title", { id: run.id })}</h2>
      <p className="muted">
        {t("suggest.run.meta", { generator: run.generator, policy: run.candidate_policy, created: run.created_at })}
      </p>
      {run.status === "failed" ? (
        <>
          <p className="error">{t("suggest.run.failedBody", { code: run.failure_code ?? "" })}</p>
          <button type="button" disabled={!canRetry} onClick={onRetry}>
            {t("suggest.run.retryNew")}
          </button>
          <p className="hint">{t("suggest.run.retryNote")}</p>
        </>
      ) : (
        <p className="hint">{t("suggest.run.limitNote", { candidates: run.candidate_limit })}</p>
      )}
      {(run.items ?? []).map((item) => (
        <ItemView
          key={item.id}
          item={item}
          left={left.includes(item.id)}
          onLeave={() => setLeft((l) => [...l, item.id])}
          onShow={() => setLeft((l) => l.filter((id) => id !== item.id))}
          onItem={replaceItem}
          onReread={reread}
        />
      ))}
    </section>
  );
}

function ItemView({
  item,
  left,
  onLeave,
  onShow,
  onItem,
  onReread,
}: {
  item: SuggestionItem;
  left: boolean;
  onLeave: () => void;
  onShow: () => void;
  onItem: (item: SuggestionItem) => void;
  onReread: () => Promise<void>;
}) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<Notice>(null);
  const target = item.suggested_concept_id;

  const confirm = async () => {
    if (target === null) return;
    setBusy(true);
    setNote(null);
    try {
      const result = await confirmSuggestion(item.id, target);
      onItem(result.item);
      setNote({ tone: "info", text: msg(result.replayed ? "suggest.confirm.replayed" : "suggest.confirm.done", { link: result.link.id }) });
    } catch (e) {
      if (e instanceof NetworkError) {
        setNote({ tone: "error", text: msg("suggest.confirm.unknown") });
      } else if (e instanceof ApiError && e.isConflict) {
        setNote({ tone: "error", text: msg("suggest.confirm.stale") });
        try {
          await onReread();
        } catch {
          // The refused confirmation already says what happened.
        }
      } else {
        setNote({ tone: "error", text: serverDetail(e) });
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className={`suggest-item suggest-${item.state}`} aria-label={t("suggest.item.label", { id: item.unit_id })}>
      {item.unit ? <UnitCard unit={item.unit} /> : null}
      <div className="field-row">
        <span className="label">{t("suggest.item.outcome")}</span>
        <span className="value">{t(outcomeKey[item.outcome])}</span>
      </div>
      <div className="field-row">
        <span className="label">{t("suggest.item.state")}</span>
        <span className="value">{t(stateKey[item.state])}</span>
      </div>
      {item.reason ? (
        <div className="field-row">
          <span className="label">{t("suggest.item.reason")}</span>
          <span className="value" lang="en">{item.reason}</span>
        </div>
      ) : null}
      {item.outcome === "no_suitable_candidate" || item.outcome === "no_candidates" ? (
        <p className="hint">{t("suggest.item.notProven")}</p>
      ) : null}
      <details>
        <summary>{t("suggest.item.candidates", { count: item.candidates.length })}</summary>
        <ol>
          {item.candidates.map((c) => (
            <li key={c.concept_id}>
              <span className="french">{c.target}</span>{" "}
              <span className="muted">{t("suggest.item.candidateMeta", { id: c.concept_id, source: c.source })}</span>
            </li>
          ))}
        </ol>
      </details>
      {item.state !== "confirmed" && item.stale_reasons.length > 0 ? (
        <ul className="stale-reasons">
          {item.stale_reasons.map((r) => (
            <li key={r}>{t(staleKey[r])}</li>
          ))}
        </ul>
      ) : null}
      {target !== null ? (
        <div className="suggest-target">
          <h3>{t("suggest.item.proposed", { id: target })}</h3>
          <ConceptContent conceptId={target} />
        </div>
      ) : null}
      {item.state === "confirmed" && item.confirmation ? (
        <p className="notice">
          {t(item.confirmation.still_current ? "suggest.item.confirmed" : "suggest.item.confirmedSuperseded", {
            link: item.confirmation.link_id,
          })}
        </p>
      ) : null}
      {item.state === "open" && target !== null ? (
        left ? (
          <p className="muted">
            {t("suggest.item.left")}{" "}
            <button type="button" onClick={onShow}>{t("suggest.item.showAgain")}</button>
          </p>
        ) : (
          <div className="actions">
            <button type="button" className="primary" disabled={busy} onClick={() => void confirm()}>
              {t("suggest.item.confirm", { id: target })}
            </button>
            <button type="button" disabled={busy} onClick={onLeave}>{t("suggest.item.leave")}</button>
          </div>
        )
      ) : null}
      {note ? (
        <p className={note.tone === "error" ? "error" : "notice"} role="status">
          {typeof note.text === "string" ? note.text : t(note.text.msgKey, note.text.vars)}
        </p>
      ) : null}
      {note && note.tone === "error" && typeof note.text !== "string" && note.text.msgKey === "suggest.confirm.unknown" ? (
        <button type="button" onClick={() => void onReread()}>{t("suggest.confirm.reread")}</button>
      ) : null}
    </article>
  );
}
