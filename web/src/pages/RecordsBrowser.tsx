import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../api/client";
import { ApiError } from "../api/client";
import { RecordDetail } from "../components/RecordDetail";
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
export function RecordsBrowser() {
  const [filter, setFilter] = useState<StateFilter>("all");
  const [records, setRecords] = useState<LearningRecord[]>([]);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [list, setList] = useState<ListStatus>({ status: "loading" });
  const [more, setMore] = useState<MoreStatus>({ status: "idle" });
  const [reloadCount, setReloadCount] = useState(0);
  const [openEntryId, setOpenEntryId] = useState<number | null>(null);
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
        <RecordDetail key={openEntryId} entryId={openEntryId} onBack={() => setOpenEntryId(null)} />
      ) : null}

      {/* The list stays mounted while a detail is open, so its pages and filter survive. */}
      <main hidden={openEntryId !== null}>
        <div className="banner info">
          Read-only view of the learning inventory. Opening a record does not analyze,
          review, or extract anything.
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
                  onOpen={() => {
                    setReturnFocusEntryId(record.entry_id);
                    setOpenEntryId(record.entry_id);
                  }}
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

function RecordRow({ record, onOpen }: { record: LearningRecord; onOpen: () => void }) {
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
