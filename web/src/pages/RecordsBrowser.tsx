import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import * as api from "../api/client";
import { ApiError } from "../api/client";
import { QuestionIntake } from "../components/QuestionIntake";
import { RecordDetail } from "../components/RecordDetail";
import type { UnitTarget } from "../navigation";
import {
  FR_L2_TAXONOMY_V1,
  LEARNING_RECORD_STATES,
  type LearningRecord,
  type LearningRecordState,
} from "../types/learning";
import { useI18n } from "../i18n";

// The page size requested from GET /learning-records. The backend clamps limits.
export const RECORDS_PAGE_SIZE = 20;

type StateFilter = "all" | LearningRecordState;
// An effective fr_l2_taxonomy_v1 category, matched by the backend.
type CategoryFilter = "all" | string;

// parseRecordId accepts a positive decimal record ID ("#" optional), else null.
export function parseRecordId(value: string): number | null {
  const text = value.trim().replace(/^#/, "");
  if (!/^[0-9]{1,15}$/.test(text)) return null;
  const id = Number(text);
  return id >= 1 && Number.isSafeInteger(id) ? id : null;
}

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

// The longest text query the backend accepts (characters).
export const RECORD_SEARCH_MAX = 200;

// RecordsBrowser is a GET-only view of the learning inventory: a filtered,
// cursor-paginated list and a per-record detail. The list's loaded pages, filters,
// jump position and scroll position live here, so opening a record and returning
// keeps them intact. Responses for a superseded filter or jump are discarded.
//
// "Go to record" starts the list at a record ID through the existing exclusive
// before_entry_id cursor (ID + 1), so an old record is one request away instead
// of many "Load older" pages. Newer records are not hidden: the list says where
// it starts and offers to return to the newest records.
//
// "Search text" (FLH-090) is applied explicitly and sent as ?q=; the backend
// matches a literal, case-insensitive substring of the learner's original input
// or context only. Nothing is filtered in the browser over loaded pages.
export function RecordsBrowser({
  returnEpoch = 0,
  onNavigateToUnit,
}: {
  // Changes when the reader returns from another workbench view.
  returnEpoch?: number;
  // Opens an extracted unit in Concept Review or the Inspector.
  onNavigateToUnit?: (target: UnitTarget) => void;
} = {}) {
  const { t, tp, status } = useI18n();
  const [filter, setFilter] = useState<StateFilter>("all");
  const [category, setCategory] = useState<CategoryFilter>("all");
  // The record ID the list starts at (inclusive), or null for the newest records.
  const [anchor, setAnchor] = useState<number | null>(null);
  const [jumpDraft, setJumpDraft] = useState("");
  // The applied text query ("" = none) and the editable draft.
  const [search, setSearch] = useState("");
  const [searchDraft, setSearchDraft] = useState("");
  const searchTooLong = Array.from(searchDraft.trim()).length > RECORD_SEARCH_MAX;
  const [jumpInvalid, setJumpInvalid] = useState(false);
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
    api.listLearningRecords({
      state: filter === "all" ? undefined : filter,
      category: category === "all" ? undefined : category,
      q: search || undefined,
      limit: RECORDS_PAGE_SIZE,
      beforeEntryId: anchor === null ? undefined : anchor + 1,
    })
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
  }, [filter, category, search, anchor, reloadCount]);

  const loadOlder = useCallback(() => {
    if (nextCursor === null || more.status === "loading") return;
    const current = generation.current;
    setMore({ status: "loading" });
    api.listLearningRecords({
      state: filter === "all" ? undefined : filter,
      category: category === "all" ? undefined : category,
      q: search || undefined,
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
  }, [filter, category, search, more.status, nextCursor]);

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    if (searchTooLong) return;
    // Applying (or re-applying) a query restarts from its first page.
    setSearch(searchDraft.trim());
  };
  const clearSearch = () => {
    setSearchDraft("");
    setSearch("");
  };

  const submitJump = (event: FormEvent) => {
    event.preventDefault();
    const id = parseRecordId(jumpDraft);
    setJumpInvalid(id === null);
    if (id !== null) setAnchor(id);
  };
  const filtered = filter !== "all" || category !== "all" || search !== "";

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
        <div className="banner info">{t("records.notice")}</div>

        <div className="queue-nav">
          <button
            type="button"
            className="ghost"
            aria-expanded={showImport}
            aria-controls="capture-import"
            onClick={() => setShowImport((v) => !v)}
          >
            {showImport ? t("records.hideImport") : t("records.showImport")}
          </button>
        </div>
        {/* Kept mounted while hidden so a pending save, its outcome and both drafts
            survive. "Open saved record" opens the detail directly, whether or not the
            record matches the current search, filters or jump. */}
        <div id="capture-import" hidden={!showImport}>
          <QuestionIntake onSaved={() => setReloadCount((n) => n + 1)} onOpenRecord={openRecord} />
        </div>

        <div className="inspector-filters" aria-label={t("records.filters")}>
          <label>
            {t("records.state")}
            <select value={filter} onChange={(event) => setFilter(event.target.value as StateFilter)}>
              <option value="all">{t("common.all")}</option>
              {LEARNING_RECORD_STATES.map((state) => (
                <option key={state} value={state}>
                  {status(state)}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("records.category")}
            <select value={category} onChange={(event) => setCategory(event.target.value)}>
              <option value="all">{t("common.all")}</option>
              {FR_L2_TAXONOMY_V1.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <form className="records-search" onSubmit={submitSearch} role="search">
            <label>
              {t("records.search.label")}
              <input
                type="search"
                value={searchDraft}
                aria-invalid={searchTooLong}
                aria-describedby={searchTooLong ? "records-search-error" : undefined}
                onChange={(event) => setSearchDraft(event.target.value)}
              />
            </label>
            <button type="submit" className="ghost" disabled={searchTooLong}>
              {t("records.search.go")}
            </button>
            {search !== "" ? (
              <button type="button" className="ghost" onClick={clearSearch}>
                {t("records.search.clear")}
              </button>
            ) : null}
          </form>
          <form className="records-jump" onSubmit={submitJump}>
            <label>
              {t("records.jump.label")}
              <input
                type="text"
                inputMode="numeric"
                value={jumpDraft}
                aria-invalid={jumpInvalid}
                aria-describedby={jumpInvalid ? "records-jump-error" : undefined}
                onChange={(event) => {
                  setJumpDraft(event.target.value);
                  setJumpInvalid(false);
                }}
              />
            </label>
            <button type="submit" className="ghost">
              {t("records.jump.go")}
            </button>
          </form>
        </div>
        {searchTooLong ? (
          <p className="hint" id="records-search-error" role="alert">
            {t("records.search.tooLong", { max: RECORD_SEARCH_MAX })}
          </p>
        ) : null}
        {search !== "" ? (
          <p className="hint" role="status">
            {t("records.search.active", { q: search })}
          </p>
        ) : null}
        {jumpInvalid ? (
          <p className="hint" id="records-jump-error" role="alert">
            {t("records.jump.invalid")}
          </p>
        ) : null}
        {anchor !== null ? (
          <div className="banner info" role="status">
            {t("records.jump.showing", { id: anchor })}{" "}
            <button type="button" className="ghost" onClick={() => setAnchor(null)}>
              {t("records.jump.newest")}
            </button>
          </div>
        ) : null}
        {anchor !== null && list.status === "ready" && records[0]?.entry_id !== anchor ? (
          <p className="hint">{t(filtered ? "records.jump.missingFiltered" : "records.jump.missing", { id: anchor })}</p>
        ) : null}

        {list.status === "loading" ? (
          <div className="empty">{t("records.loading")}</div>
        ) : list.status === "error" ? (
          <div className="banner error" role="alert">
            {t("records.loadFailed", { message: list.message })}{" "}
            <button type="button" className="ghost" onClick={() => setReloadCount((n) => n + 1)}>
              {t("common.retry")}
            </button>
          </div>
        ) : records.length === 0 ? (
          <div className="empty">
            {anchor !== null
              ? t("records.jump.none", { id: anchor })
              : search !== ""
                ? t("records.search.none", { q: search })
                : category !== "all"
                ? t("records.emptyFilters")
                : filter === "all"
                  ? t("records.empty")
                  : t("records.emptyFiltered", { state: status(filter) })}
          </div>
        ) : (
          <>
            <ul className="records-list" aria-label={t("records.list")}>
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
              <span className="hint">{tp("records.showing", records.length)}</span>
              {more.status === "error" ? (
                <div className="banner error" role="alert">
                  {t("records.olderFailed", { message: more.message })}
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
                    ? t("records.olderLoading")
                    : more.status === "error"
                      ? t("records.olderRetry")
                      : t("records.older")}
                </button>
              ) : (
                <span className="hint">{t("records.end")}</span>
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
  const { t, status } = useI18n();
  const interpretation = record.effective
    ? t("records.effectiveCategory", { category: record.effective.category })
    : record.state === "rejected"
      ? t("records.rejected")
      : t("records.noAnalysis");
  return (
    <li className="record-row">
      <div className="inspector-card-head">
        <h3>{t("record.heading", { id: record.entry_id })}</h3>
        <span className={`record-state ${record.state}`}>{status(record.state)}</span>
      </div>
      <p className="french record-input">{record.original_input}</p>
      {record.original_context ? <p className="hint">{record.original_context}</p> : null}
      <p className="hint">
        {record.analysis_version !== null
          ? t("records.rowLatest", { interpretation, version: record.analysis_version })
          : interpretation}
      </p>
      {unconfirmed ? (
        <p className="banner error" role="alert">
          {t("records.unconfirmed")}
        </p>
      ) : null}
      {filter !== "all" && record.state !== filter ? (
        <p className="hint">{t("records.changed", { state: status(record.state), filter: status(filter) })}</p>
      ) : null}
      <button
        type="button"
        className="ghost"
        id={`record-open-${record.entry_id}`}
        aria-label={t("records.openLabel", { id: record.entry_id })}
        onClick={onOpen}
      >
        {t("records.open")}
      </button>
    </li>
  );
}
