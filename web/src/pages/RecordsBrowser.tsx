import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../api/client";
import { ApiError } from "../api/client";
import { CaptureImport } from "../components/CaptureImport";
import { RecordDetail } from "../components/RecordDetail";
import type { UnitTarget } from "../navigation";
import {
  LEARNING_RECORD_STATES,
  type LearningRecord,
  type LearningRecordState,
} from "../types/learning";

// The page size requested from GET /learning-records. The backend clamps limits.
export const RECORDS_PAGE_SIZE = 20;

type StateFilter = "all" | LearningRecordState;

type ListStatus =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready" };

type MoreStatus = { status: "idle" } | { status: "loading" } | { status: "error"; message: string };

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return `(${error.status}) ${error.message}`;
  }
  return error instanceof Error ? error.message : String(error);
}

// RecordsBrowser is a GET-only view of the learning inventory: a filtered,
// cursor-paginated list and a per-record detail. The list's loaded pages, filter,
// and position live here, so opening a record and returning keeps them intact.
// Responses for a superseded filter are discarded.
export function RecordsBrowser({
  returnEpoch = 0,
  onNavigateToUnit,
}: {
  // Changes when the reader returns from another workbench view.
  returnEpoch?: number;
  // Opens an extracted unit in Concept Review or the Inspector.
  onNavigateToUnit?: (target: UnitTarget) => void;
} = {}) {
  const [filter, setFilter] = useState<StateFilter>("all");
  const [records, setRecords] = useState<LearningRecord[]>([]);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [list, setList] = useState<ListStatus>({ status: "loading" });
  const [more, setMore] = useState<MoreStatus>({ status: "idle" });
  const [reloadCount, setReloadCount] = useState(0);
  const [openEntryId, setOpenEntryId] = useState<number | null>(null);
  const [showImport, setShowImport] = useState(false);
  // Rows whose re-read after a write failed: their shown state is unconfirmed.
  const [unconfirmed, setUnconfirmed] = useState<ReadonlySet<number>>(new Set());
  const [returnFocusEntryId, setReturnFocusEntryId] = useState<number | null>(null);

  // generation identifies the current filter/reload. A "load older" response that
  // was requested under an earlier generation must not be appended.
  const generation = useRef(0);

  useEffect(() => {
    const current = ++generation.current;
    setList({ status: "loading" });
    setMore({ status: "idle" });
    setRecords([]);
    setNextCursor(null);
    api.listLearningRecords({ state: filter === "all" ? undefined : filter, limit: RECORDS_PAGE_SIZE })
      .then((page) => {
        if (generation.current !== current) return;
        setRecords(page.records);
        setUnconfirmed(new Set());
        setNextCursor(page.next_before_entry_id);
        setList({ status: "ready" });
      })
      .catch((error: unknown) => {
        if (generation.current !== current) return;
        setList({ status: "error", message: describeError(error) });
      });
  }, [filter, reloadCount]);

  const loadOlder = useCallback(() => {
    if (nextCursor === null || more.status === "loading") return;
    const current = generation.current;
    setMore({ status: "loading" });
    api.listLearningRecords({
      state: filter === "all" ? undefined : filter,
      limit: RECORDS_PAGE_SIZE,
      beforeEntryId: nextCursor,
    })
      .then((page) => {
        if (generation.current !== current) return;
        setRecords((loaded) => [...loaded, ...page.records]);
        setNextCursor(page.next_before_entry_id);
        setMore({ status: "idle" });
      })
      .catch((error: unknown) => {
        if (generation.current !== current) return;
        setMore({ status: "error", message: describeError(error) });
      });
  }, [filter, more.status, nextCursor]);

  // refreshRecord re-reads one changed record's inventory row from the backend after
  // a write in its detail, so the list never derives a state itself. A row read for
  // a superseded filter/reload is discarded. If the read fails the row keeps its
  // loaded values but is marked unconfirmed, never silently presented as current.
  const refreshRecord = useCallback((entryId: number) => {
    const current = generation.current;
    const mark = (stale: boolean) =>
      setUnconfirmed((rows) => {
        const next = new Set(rows);
        if (stale) next.add(entryId);
        else next.delete(entryId);
        return next;
      });
    api.getLearningRecord(entryId)
      .then((fresh) => {
        if (generation.current !== current) return;
        if (fresh === null) {
          mark(true);
          return;
        }
        setRecords((loaded) => loaded.map((r) => (r.entry_id === entryId ? fresh : r)));
        mark(false);
      })
      .catch(() => {
        if (generation.current === current) mark(true);
      });
  }, []);

  const openRecord = useCallback((entryId: number) => {
    setReturnFocusEntryId(entryId);
    setOpenEntryId(entryId);
  }, []);

  // Returning from a detail moves focus back to the record's Open button, which
  // also scrolls the preserved list back to where the reader left it.
  useEffect(() => {
    if (openEntryId !== null || returnFocusEntryId === null) return;
    document.getElementById(`record-open-${returnFocusEntryId}`)?.focus();
  }, [openEntryId, returnFocusEntryId]);

  return (
    <>
      {openEntryId !== null ? (
        // Keyed by entry so every record starts from a fresh detail state.
        <RecordDetail
          key={openEntryId}
          entryId={openEntryId}
          onBack={() => setOpenEntryId(null)}
          onRecordChanged={refreshRecord}
          returnEpoch={returnEpoch}
          onNavigateToUnit={onNavigateToUnit}
        />
      ) : null}

      {/* The list stays mounted while a detail is open, so its pages and filter survive. */}
      <main hidden={openEntryId !== null}>
        <div className="banner info">
          Opening a record does not analyze, review, or extract anything. Analysis and
          extraction run only when you explicitly request them in a record&apos;s detail.
        </div>

        <div className="queue-nav">
          <button
            type="button"
            className="ghost"
            aria-expanded={showImport}
            aria-controls="capture-import"
            onClick={() => setShowImport((v) => !v)}
          >
            {showImport ? "Hide capture import" : "Import a capture"}
          </button>
        </div>
        {/* Kept mounted while hidden so a pending import and its outcome survive. */}
        <div id="capture-import" hidden={!showImport}>
          <CaptureImport onImported={() => setReloadCount((n) => n + 1)} onOpenRecord={openRecord} />
        </div>

        <div className="inspector-filters" aria-label="Record filters">
          <label>
            Record state
            <select value={filter} onChange={(event) => setFilter(event.target.value as StateFilter)}>
              <option value="all">All</option>
              {LEARNING_RECORD_STATES.map((state) => (
                <option key={state} value={state}>
                  {state}
                </option>
              ))}
            </select>
          </label>
        </div>

        {list.status === "loading" ? (
          <div className="empty">Loading learning records…</div>
        ) : list.status === "error" ? (
          <div className="banner error" role="alert">
            Could not load learning records: {list.message}{" "}
            <button type="button" className="ghost" onClick={() => setReloadCount((n) => n + 1)}>
              Retry
            </button>
          </div>
        ) : records.length === 0 ? (
          <div className="empty">
            {filter === "all"
              ? "No learning records exist yet. Import a capture or create an entry to see it here."
              : `No learning records are in the "${filter}" state.`}
          </div>
        ) : (
          <>
            <ul className="records-list" aria-label="Learning records">
              {records.map((record) => (
                <RecordRow
                  key={record.entry_id}
                  record={record}
                  filter={filter}
                  unconfirmed={unconfirmed.has(record.entry_id)}
                  onOpen={() => openRecord(record.entry_id)}
                />
              ))}
            </ul>

            <div className="records-more">
              <span className="hint">
                Showing {records.length} record{records.length === 1 ? "" : "s"}.
              </span>
              {more.status === "error" ? (
                <div className="banner error" role="alert">
                  Could not load older records: {more.message}
                </div>
              ) : null}
              {nextCursor !== null ? (
                <button
                  type="button"
                  className="ghost"
                  disabled={more.status === "loading"}
                  onClick={loadOlder}
                >
                  {more.status === "loading"
                    ? "Loading older records…"
                    : more.status === "error"
                      ? "Retry loading older records"
                      : "Load older records"}
                </button>
              ) : (
                <span className="hint">End of records.</span>
              )}
            </div>
          </>
        )}
      </main>
    </>
  );
}

function RecordRow({
  record,
  filter,
  unconfirmed,
  onOpen,
}: {
  record: LearningRecord;
  filter: StateFilter;
  unconfirmed: boolean;
  onOpen: () => void;
}) {
  return (
    <li className="record-row">
      <div className="inspector-card-head">
        <h3>Record #{record.entry_id}</h3>
        <span className={`record-state ${record.state}`}>{record.state}</span>
      </div>
      <p className="french record-input">{record.original_input}</p>
      {record.original_context ? <p className="hint">{record.original_context}</p> : null}
      <p className="hint">
        {record.effective
          ? `Effective category: ${record.effective.category}`
          : record.state === "rejected"
            ? "Latest interpretation rejected"
            : "No analysis"}
        {record.analysis_version !== null ? ` · latest analysis v${record.analysis_version}` : ""}
      </p>
      {unconfirmed ? (
        <p className="banner error" role="alert">
          This record changed, but its row could not be re-read from the server. The state shown
          may be out of date; reload the list.
        </p>
      ) : null}
      {filter !== "all" && record.state !== filter ? (
        <p className="hint">
          Changed since this list loaded: now &quot;{record.state}&quot;, which no longer matches the
          &quot;{filter}&quot; filter.
        </p>
      ) : null}
      <button
        type="button"
        className="ghost"
        id={`record-open-${record.entry_id}`}
        aria-label={`Open record #${record.entry_id}`}
        onClick={onOpen}
      >
        Open
      </button>
    </li>
  );
}
