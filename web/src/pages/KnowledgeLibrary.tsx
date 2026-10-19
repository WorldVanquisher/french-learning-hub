import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import * as api from "../api/client";
import { ApiError } from "../api/client";
import type {
  HybridSearch,
  LibraryConcept,
  LibraryHistoricalUnit,
  LibraryQuery,
  LibrarySearch,
  LibrarySearchMode,
  LibrarySource,
  LibraryStateFilter,
  LibraryUnit,
  PublicDemoInfo,
  SemanticSearch,
} from "../types/library";
import { useI18n, type I18n, type MessageKey } from "../i18n";

// One search outcome per submitted query. Semantic and hybrid modes need a
// query; with an empty one nothing is requested (browsing is keyword search's job).
type SearchOutcome =
  | { kind: "keyword"; data: LibrarySearch }
  | { kind: "semantic"; data: SemanticSearch }
  | { kind: "hybrid"; data: HybridSearch }
  | { kind: "needs-query" };

type Load<T> = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: T };

// The library's own navigation: results → concept → source. The query stays in
// this component's state, so returning shows the same search and results.
type Screen = { kind: "results" } | { kind: "concept"; conceptId: number } | { kind: "source"; conceptId: number; unitId: number };

const resultButtonId = (conceptId: number) => `library-result-${conceptId}`;

function describeError(error: unknown): string {
  if (error instanceof ApiError) return `(${error.status}) ${error.message}`;
  return error instanceof Error ? error.message : String(error);
}

// useLoad runs one GET per key and applies only the latest answer. Data loaded
// for an earlier key is never shown under the current key (no stale results
// labelled with a new query while the new request is in flight).
function useLoad<T>(key: string, load: () => Promise<T>, retry: number): Load<T> {
  const [state, setState] = useState<{ key: string; retry: number; load: Load<T> }>({ key, retry, load: { status: "loading" } });
  useEffect(() => {
    let active = true;
    setState({ key, retry, load: { status: "loading" } });
    load()
      .then((data) => active && setState({ key, retry, load: { status: "ready", data } }))
      .catch((error: unknown) => active && setState({ key, retry, load: { status: "error", message: describeError(error) } }));
    return () => {
      active = false;
    };
    // `load` is recreated each render; `key` and `retry` identify the request.
  }, [key, retry]);
  return state.key === key && state.retry === retry ? state.load : { status: "loading" };
}

// useFocusedHeading moves keyboard focus to a screen's heading when it opens and
// again when its content replaces the loading state.
function useFocusedHeading(status: string) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    ref.current?.focus();
  }, [status]);
  return ref;
}

// Display names of the backend's matched-field identifiers; unknown ones are shown as given.
const fieldLabels: Record<string, MessageKey> = {
  target: "library.field.target",
  pedagogical_intent: "library.field.pedagogical_intent",
  scope: "library.field.scope",
  identity_features: "library.field.identity_features",
  unit_canonical: "library.field.unit_canonical",
  unit_statement: "library.field.unit_statement",
  unit_example: "library.field.unit_example",
};
const fieldList = (i: I18n, fields: string[]) =>
  fields.map((f) => (fieldLabels[f] ? i.t(fieldLabels[f]) : f)).join(i.t("library.fieldSeparator"));

// Machine values such as needs_review or verified_unchanged: English shows them
// with spaces as before; other languages show their status label.
const spaced = (i: I18n, value: string) => (i.locale === "en" ? value.replace("_", " ") : i.status(value));

const resultsLabelKey: Record<LibrarySearchMode, MessageKey> = {
  keyword: "library.resultsLabel.keyword",
  semantic: "library.resultsLabel.semantic",
  hybrid: "library.resultsLabel.hybrid",
};
const modeSearchKey: Record<LibrarySearchMode, MessageKey> = {
  keyword: "library.allConcepts",
  semantic: "library.modeSearch.semantic",
  hybrid: "library.modeSearch.hybrid",
};
const needsQueryKey: Record<LibrarySearchMode, MessageKey> = {
  keyword: "library.needsQuery.semantic",
  semantic: "library.needsQuery.semantic",
  hybrid: "library.needsQuery.hybrid",
};
const searchFailedKey: Record<LibrarySearchMode, MessageKey> = {
  keyword: "library.searchFailed.keyword",
  semantic: "library.searchFailed.semantic",
  hybrid: "library.searchFailed.hybrid",
};

// KnowledgeLibrary is a GET-only view of curated Concepts. Searching, opening a
// Concept, or following a source records nothing and calls no provider; every
// status shown is a backend fact.
//
// With `demo` (FLH-073 public demo) keyword search stays free text, while
// semantic and hybrid search run only the demo's preset queries.
export function KnowledgeLibrary({ demo }: { demo?: PublicDemoInfo } = {}) {
  const i18n = useI18n();
  const { t, tn } = i18n;
  const [draft, setDraft] = useState<LibraryQuery>({ q: "", state: "all" });
  const [draftPreset, setDraftPreset] = useState<string>(demo?.presets[0]?.id ?? "");
  const [query, setQuery] = useState<LibraryQuery>({ q: "", state: "all" });
  const [draftMode, setDraftMode] = useState<LibrarySearchMode>("keyword");
  const [mode, setMode] = useState<LibrarySearchMode>("keyword");
  const [screen, setScreen] = useState<Screen>({ kind: "results" });
  const [retry, setRetry] = useState(0);
  const returnTo = useRef<number | null>(null);

  const search = useLoad<SearchOutcome>(
    `${mode}\u0000${query.state}\u0000${query.q}\u0000${query.preset ?? ""}`,
    async (): Promise<SearchOutcome> => {
      if (mode === "keyword") return { kind: "keyword", data: await api.searchLibrary(query) };
      if (!query.q) return { kind: "needs-query" };
      if (demo) {
        if (mode === "hybrid") return { kind: "hybrid", data: await api.demoHybridSearch(query) };
        return { kind: "semantic", data: await api.demoSemanticSearch(query) };
      }
      if (mode === "hybrid") return { kind: "hybrid", data: await api.hybridSearchLibrary(query) };
      return { kind: "semantic", data: await api.semanticSearchLibrary(query) };
    },
    retry,
  );

  // On return, focus the result the reader opened. Detail screens focus their own heading.
  useEffect(() => {
    if (screen.kind === "results" && returnTo.current !== null && search.status === "ready") {
      document.getElementById(resultButtonId(returnTo.current))?.focus();
      returnTo.current = null;
    }
  }, [screen, search.status]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const preset = demo && draftMode !== "keyword" ? demo.presets.find((p) => p.id === draftPreset) : undefined;
    setQuery(preset ? { q: preset.text, state: draft.state, preset: preset.id } : { q: draft.q.trim(), state: draft.state });
    setMode(draftMode);
  };
  const backToResults = (conceptId: number) => {
    returnTo.current = conceptId;
    setScreen({ kind: "results" });
  };
  const openConcept = (conceptId: number) => setScreen({ kind: "concept", conceptId });
  const resultsLabel = query.q ? t(resultsLabelKey[mode], { q: query.q }) : t(modeSearchKey[mode]);
  const strong = (key: MessageKey) => <strong>{t(key)}</strong>;

  return (
    <main className="library">
      <div hidden={screen.kind !== "results"}>
        <form className="panel library-search" role="search" onSubmit={submit}>
          {demo && draftMode !== "keyword" ? (
            <label htmlFor="library-preset">{t("library.exampleQuery")}</label>
          ) : (
            <label htmlFor="library-query">{t("library.searchLabel")}</label>
          )}
          <div className="discovery-search-row">
            {demo && draftMode !== "keyword" ? (
              <select id="library-preset" value={draftPreset} onChange={(e) => setDraftPreset(e.target.value)}>
                {demo.presets.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}: “{p.text}”
                  </option>
                ))}
              </select>
            ) : (
              <input
                id="library-query"
                type="search"
                value={draft.q}
                placeholder={t("library.placeholder")}
                onChange={(e) => setDraft({ ...draft, q: e.target.value })}
              />
            )}
            <select
              aria-label={t("library.stateFilter")}
              value={draft.state}
              onChange={(e) => setDraft({ ...draft, state: e.target.value as LibraryStateFilter })}
            >
              <option value="all">{t("library.state.all")}</option>
              <option value="active">{t("library.state.active")}</option>
              <option value="orphaned">{t("library.state.orphaned")}</option>
              <option value="retired">{t("library.state.retired")}</option>
            </select>
            <button type="submit" className="primary">{t("library.search")}</button>
            <button
              type="button"
              className="ghost"
              onClick={() => {
                setDraft({ q: "", state: "all" });
                setQuery({ q: "", state: "all" });
                setDraftMode("keyword");
                setMode("keyword");
              }}
            >
              {t("common.clear")}
            </button>
          </div>
          <fieldset className="library-mode">
            <legend>{t("library.mode")}</legend>
            <label>
              <input
                type="radio"
                name="library-mode"
                value="keyword"
                checked={draftMode === "keyword"}
                onChange={() => setDraftMode("keyword")}
              />{" "}
              {t("library.mode.keyword")}
            </label>{" "}
            <label>
              <input
                type="radio"
                name="library-mode"
                value="semantic"
                checked={draftMode === "semantic"}
                onChange={() => setDraftMode("semantic")}
              />{" "}
              {t("library.mode.semantic")}
            </label>{" "}
            <label>
              <input
                type="radio"
                name="library-mode"
                value="hybrid"
                checked={draftMode === "hybrid"}
                onChange={() => setDraftMode("hybrid")}
              />{" "}
              {t("library.mode.hybrid")}
            </label>
          </fieldset>
          {demo ? (
            <p className="hint" role="note">
              {tn("library.demo.note", { label: strong("library.demo.label") })}
            </p>
          ) : null}
          <p className="hint">
            {tn("library.terms", { concept: strong("library.term.concept"), unit: strong("library.term.unit") })}
          </p>
          <p className="hint">{t("library.searchScope")}</p>
          {demo ? (
            <p className="hint">{tn("library.semantic.demo", { semantic: strong("library.mode.semantic") })}</p>
          ) : (
            <p className="hint">{tn("library.semantic.full", { semantic: strong("library.mode.semantic") })}</p>
          )}
          <p className="hint">{tn("library.hybrid.explain", { hybrid: strong("library.mode.hybrid") })}</p>
        </form>
        {search.status === "ready" && search.data.kind === "keyword" ? (
          <Results
            search={{ status: "ready", data: search.data.data }}
            query={query}
            onOpen={openConcept}
            onRetry={() => setRetry((n) => n + 1)}
          />
        ) : search.status === "ready" && search.data.kind === "semantic" ? (
          <SemanticResults data={search.data.data} query={query} onOpen={openConcept} />
        ) : search.status === "ready" && search.data.kind === "hybrid" ? (
          <HybridResults data={search.data.data} query={query} onOpen={openConcept} />
        ) : search.status === "ready" ? (
          <p className="empty" role="status">{t(needsQueryKey[mode])}</p>
        ) : search.status === "loading" ? (
          <p className="empty" role="status">{t("library.searching")}</p>
        ) : (
          <div className="banner error" role="alert">
            {t(searchFailedKey[mode], { message: search.message })}{" "}
            <button type="button" className="ghost" onClick={() => setRetry((n) => n + 1)}>
              {t("common.tryAgain")}
            </button>
          </div>
        )}
      </div>
      {screen.kind === "concept" ? (
        <ConceptScreen
          key={`concept-${screen.conceptId}`}
          conceptId={screen.conceptId}
          backLabel={t("library.backTo", { label: resultsLabel })}
          onBack={() => backToResults(screen.conceptId)}
          onOpenConcept={openConcept}
          onOpenSource={(unitId) => setScreen({ kind: "source", conceptId: screen.conceptId, unitId })}
        />
      ) : null}
      {screen.kind === "source" ? (
        <SourceScreen
          key={`source-${screen.unitId}`}
          unitId={screen.unitId}
          conceptId={screen.conceptId}
          resultsLabel={resultsLabel}
          onBackToConcept={() => openConcept(screen.conceptId)}
          onBackToResults={() => backToResults(screen.conceptId)}
          onOpenConcept={openConcept}
        />
      ) : null}
    </main>
  );
}

// ResultMeta is the stored Concept type and scope (data) followed by the counts.
function ResultMeta({ concept, members, supporting }: { concept: LibraryConcept["concept"]; members: number; supporting: number }) {
  const { tp } = useI18n();
  return (
    <div className="hint">
      {concept.pedagogical_intent}
      {concept.scope ? ` · ${concept.scope}` : ""} · {tp("library.resultMeta", members, { supporting, id: concept.id })}
    </div>
  );
}

function Results({
  search,
  query,
  onOpen,
  onRetry,
}: {
  search: Load<LibrarySearch>;
  query: LibraryQuery;
  onOpen: (conceptId: number) => void;
  onRetry: () => void;
}) {
  const i18n = useI18n();
  const { t, tp, status } = i18n;
  if (search.status === "loading") return <p className="empty" role="status">{t("library.searching")}</p>;
  if (search.status === "error")
    return (
      <div className="banner error" role="alert">
        {t("library.searchFailed.keyword", { message: search.message })}{" "}
        <button type="button" className="ghost" onClick={onRetry}>
          {t("common.tryAgain")}
        </button>
      </div>
    );
  const data = search.data;
  if (data.results.length === 0)
    return (
      <div className="empty" role="status">
        {query.q
          ? query.state === "all"
            ? t("library.noMatch", { q: query.q })
            : t("library.noMatchState", { q: query.q, state: status(query.state) })
          : query.state === "all"
            ? t("library.empty")
            : t("library.emptyState", { state: status(query.state) })}
      </div>
    );
  return (
    <section aria-label={t("library.results")}>
      <p className="hint" role="status">
        {data.truncated
          ? t("library.truncated", { shown: data.results.length, total: data.total_matches })
          : query.q
            ? tp("library.countMatching", data.total_matches, { q: query.q })
            : tp("library.count", data.total_matches)}
      </p>
      <ol className="library-results">
        {data.results.map((r) => (
          <li key={r.concept.id} className="panel library-result">
            <button type="button" className="link-button" id={resultButtonId(r.concept.id)} onClick={() => onOpen(r.concept.id)}>
              {r.concept.target}
            </button>{" "}
            <StateTag state={r.concept.state} />
            <ResultMeta concept={r.concept} members={r.current_member_count} supporting={r.supporting_unit_count} />
            {r.match_tier !== "browse" ? (
              <div className="hint">
                {t(r.match_tier === "unit_evidence" ? "library.foundInUnits" : "library.foundIn", {
                  fields: fieldList(i18n, r.matched_fields),
                })}
              </div>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}

function SemanticResults({
  data,
  query,
  onOpen,
}: {
  data: SemanticSearch;
  query: LibraryQuery;
  onOpen: (conceptId: number) => void;
}) {
  const i18n = useI18n();
  const { t, tp, tn, status } = i18n;
  const dropped = data.skipped.stale + data.skipped.missing + data.skipped.incompatible;
  const idx = data.index;
  const lastRunOk = idx.last_run_outcome === "published" || idx.last_run_outcome === "verified_unchanged";
  const outcome = idx.last_run_outcome ? spaced(i18n, idx.last_run_outcome) : "";
  return (
    <section aria-label={t("library.semanticResults")}>
      {!lastRunOk && idx.last_run_outcome ? (
        <div className="banner info" role="status">
          {tn(idx.last_error ? "library.lastRun.failedError" : "library.lastRun.failed", {
            outcome,
            error: idx.last_error,
            status: <code>semantic-index status</code>,
            sync: <code>semantic-index sync</code>,
          })}
        </div>
      ) : null}
      <p className="hint" role="status">
        {query.state === "all"
          ? tp("library.semantic.count", data.results.length, { q: data.query, model: idx.model_id })
          : tp("library.semantic.countState", data.results.length, {
              q: data.query,
              state: status(query.state),
              model: idx.model_id,
            })}
      </p>
      <p className="hint">
        {t("library.semantic.index", {
          published: idx.published_at ?? t("library.semantic.unknownTime"),
          operation: idx.last_run_operation || t("library.semantic.noRun"),
          outcome,
        })}
      </p>
      {dropped > 0 || data.filtered_by_state > 0 ? (
        <p className="hint">
          {data.filtered_by_state > 0
            ? tp("library.semantic.droppedFiltered", dropped, { filtered: data.filtered_by_state })
            : tp("library.semantic.dropped", dropped)}
        </p>
      ) : null}
      {data.results.length === 0 ? (
        <p className="empty">{t("library.semantic.none", { q: data.query })}</p>
      ) : (
        <ol className="library-results">
          {data.results.map((r) => (
            <li key={r.concept.id} className="panel library-result">
              <button type="button" className="link-button" id={resultButtonId(r.concept.id)} onClick={() => onOpen(r.concept.id)}>
                {r.concept.target}
              </button>{" "}
              <StateTag state={r.concept.state} />
              <ResultMeta concept={r.concept} members={r.current_member_count} supporting={r.supporting_unit_count} />
              <div className="hint">{t("library.similarity", { value: r.similarity.toFixed(2) })}</div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function HybridResults({
  data,
  query,
  onOpen,
}: {
  data: HybridSearch;
  query: LibraryQuery;
  onOpen: (conceptId: number) => void;
}) {
  const i18n = useI18n();
  const { t, tp, status } = i18n;
  const kw = data.components.keyword;
  const sem = data.components.semantic;
  const semDropped = sem.skipped.stale + sem.skipped.missing + sem.skipped.incompatible;
  const fusedDropped =
    data.dropped_after_fusion.missing + data.dropped_after_fusion.filtered_by_state + data.dropped_after_fusion.changed_during_search;
  const stateFiltered = query.state !== "all";
  return (
    <section aria-label={t("library.hybridResults")}>
      <p className="hint" role="status">
        {data.truncated
          ? t(stateFiltered ? "library.hybrid.truncatedState" : "library.hybrid.truncated", {
              shown: data.results.length,
              total: data.total_candidates,
              q: data.query,
              state: status(query.state),
            })
          : tp(stateFiltered ? "library.hybrid.countState" : "library.hybrid.count", data.results.length, {
              q: data.query,
              state: status(query.state),
            })}
      </p>
      <p className="hint">
        {t(kw.truncated_at_depth ? "library.hybrid.policyCut" : "library.hybrid.policy", {
          depth: data.depth,
          found: kw.total_matches,
          used: kw.returned,
          returned: sem.returned,
          collection: sem.index.collection,
          model: sem.index.model_id,
          policy: data.policy.version,
          k: data.policy.rrf_k,
        })}
      </p>
      {semDropped > 0 || sem.filtered_by_state > 0 || fusedDropped > 0 ? (
        <p className="hint">
          {sem.filtered_by_state > 0
            ? tp("library.hybrid.semDroppedFiltered", semDropped, { filtered: sem.filtered_by_state })
            : tp("library.hybrid.semDropped", semDropped)}{" "}
          {tp("library.hybrid.fusedDropped", fusedDropped)}
        </p>
      ) : null}
      {data.results.length === 0 ? (
        <p className="empty">{t("library.hybrid.none", { q: data.query })}</p>
      ) : (
        <ol className="library-results">
          {data.results.map((r) => (
            <li key={r.concept.id} className="panel library-result">
              <button type="button" className="link-button" id={resultButtonId(r.concept.id)} onClick={() => onOpen(r.concept.id)}>
                {r.concept.target}
              </button>{" "}
              <StateTag state={r.concept.state} />
              <ResultMeta concept={r.concept} members={r.current_member_count} supporting={r.supporting_unit_count} />
              <div className="hint">
                {r.keyword
                  ? t("library.hybrid.keyword", { rank: r.keyword.rank, fields: fieldList(i18n, r.keyword.matched_fields) })
                  : t("library.hybrid.noKeyword")}
                {" · "}
                {r.semantic
                  ? t("library.hybrid.semantic", { rank: r.semantic.rank, value: r.semantic.similarity.toFixed(2) })
                  : t("library.hybrid.noSemantic")}
                {" · "}
                {t("library.hybrid.score", { score: r.fused_score.toFixed(4) })}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function StateTag({ state }: { state: "active" | "orphaned" | "retired" }) {
  const { status } = useI18n();
  return <span className={`tag ${state}`}>{status(state)}</span>;
}

const supportText: Record<string, MessageKey> = {
  active: "library.support.active",
  orphaned: "library.support.orphaned",
  retired: "library.support.retired",
};

function ConceptScreen({
  conceptId,
  backLabel,
  onBack,
  onOpenConcept,
  onOpenSource,
}: {
  conceptId: number;
  backLabel: string;
  onBack: () => void;
  onOpenConcept: (conceptId: number) => void;
  onOpenSource: (unitId: number) => void;
}) {
  const i18n = useI18n();
  const { t, tp, tn, status } = i18n;
  const [retry, setRetry] = useState(0);
  const load = useLoad<LibraryConcept>(String(conceptId), () => api.getLibraryConcept(conceptId), retry);
  const headingRef = useFocusedHeading(load.status);
  const back = (
    <button type="button" className="ghost" onClick={onBack}>
      {backLabel}
    </button>
  );
  if (load.status !== "ready")
    return (
      <section className="panel" aria-label={t("library.concept.region")}>
        <h2 ref={headingRef} tabIndex={-1}>
          {t("library.concept.heading", { id: conceptId })}
        </h2>
        {back}
        {load.status === "loading" ? (
          <p className="hint" role="status">{t("library.concept.loading", { id: conceptId })}</p>
        ) : (
          <div className="banner error" role="alert">
            {t("library.concept.failed", { id: conceptId, message: load.message })}{" "}
            <button type="button" className="ghost" onClick={() => setRetry((n) => n + 1)}>
              {t("common.tryAgain")}
            </button>
          </div>
        )}
      </section>
    );
  const d = load.data;
  const c = d.concept;
  const features = Object.entries(c.identity_features);
  // Within a section a unit appears once, except relations: one unit may hold
  // several distinct relations to this concept, so those rows key by link ID.
  const unit = (u: LibraryUnit, note?: ReactNode, key: string | number = u.unit_id) => (
    <UnitCard key={key} unit={u} note={note} onOpenSource={() => onOpenSource(u.unit_id)} />
  );
  return (
    <div>
      <section className="panel library-concept" aria-label={t("library.concept.region")}>
        <h2 ref={headingRef} tabIndex={-1} className="library-title">
          {c.target} <StateTag state={c.state} />
        </h2>
        {back}
        <dl className="unit-evidence">
          <Row label={t("library.row.status")}>{supportText[c.state] ? t(supportText[c.state]) : c.state}</Row>
          <Row label={t("library.row.type")}>{c.pedagogical_intent}</Row>
          <Row label={t("library.row.scope")}>{c.scope || <em>{t("library.notSet")}</em>}</Row>
          <Row label={t("library.row.identity")}>
            {features.length ? features.map(([k, v]) => `${k}: ${v}`).join(" · ") : <em>{t("library.noneLower")}</em>}
          </Row>
        </dl>
        <p className="hint">{t("library.filedVersusSupporting")}</p>
        <p className="hint">
          {t("library.concept.meta", { id: c.id, lifecycle: status(c.lifecycle_state), support: status(c.support_state) })}
        </p>
      </section>

      <section className="panel library-section current" aria-labelledby="lib-preferred">
        <h3 id="lib-preferred">{t("library.preferred")}</h3>
        {d.preferred_unit ? (
          unit(d.preferred_unit, preferredNote(i18n, d.preferred_unit, d))
        ) : (
          <p className="hint">{t("library.preferred.none")}</p>
        )}
      </section>

      <section className="panel library-section current" aria-labelledby="lib-support">
        <h3 id="lib-support">{t("library.supporting", { count: d.supporting_units.length })}</h3>
        {d.supporting_units.length ? (
          d.supporting_units.map((u) => unit(u))
        ) : (
          <p className="hint">{t("library.supporting.none")}</p>
        )}
      </section>

      {d.non_supporting_members.length ? (
        <section className="panel library-section" aria-labelledby="lib-members">
          <h3 id="lib-members">{t("library.members", { count: d.non_supporting_members.length })}</h3>
          <p className="hint">{t("library.members.hint")}</p>
          {d.non_supporting_members.map((u) => unit(u, <span>{notSupportingReasons(i18n, u).join(" ")}</span>))}
        </section>
      ) : null}

      <section className="panel library-section" aria-labelledby="lib-relations">
        <h3 id="lib-relations">{t("library.relations", { count: d.current_relations.length })}</h3>
        <p className="hint">{t("library.relations.hint")}</p>
        {d.current_relations.length ? (
          d.current_relations.map((r) =>
            unit(
              r.unit,
              <span>
                {tn("library.relations.note", {
                  relation: <strong>{r.relation.toUpperCase()}</strong>,
                  unit: r.unit.unit_id,
                  link: r.link_id,
                  source: r.decision_source,
                })}
              </span>,
              `relation-${r.link_id}`,
            ),
          )
        ) : (
          <p className="hint">{t("library.relations.none")}</p>
        )}
      </section>

      <section className="panel library-section history" aria-labelledby="lib-history">
        <h3 id="lib-history">{t("library.history", { count: d.historical_units.length })}</h3>
        <p className="hint">{tp("library.history.hint", d.history_event_count)}</p>
        {d.historical_units.length
          ? d.historical_units.map((h) => unit(h.unit, <HistoricalNote h={h} onOpenConcept={onOpenConcept} />))
          : <p className="hint">{t("library.history.none")}</p>}
      </section>
    </div>
  );
}

function preferredNote(i: I18n, u: LibraryUnit, d: LibraryConcept): string {
  const supporting = d.supporting_units.some((s) => s.unit_id === u.unit_id);
  return supporting
    ? i.t("library.preferred.supporting")
    : i.t("library.preferred.notSupporting", { reasons: notSupportingReasons(i, u).join(" ") });
}

function notSupportingReasons(i: I18n, u: LibraryUnit): string[] {
  const reasons: string[] = [];
  if (!u.in_current_extraction)
    reasons.push(i.t("library.reason.oldExtraction", { version: u.extraction_version, record: u.entry_id }));
  if (u.admission === "suppressed") reasons.push(i.t("library.reason.suppressed"));
  else if (u.admission !== "active") reasons.push(i.t("library.reason.waiting", { admission: spaced(i, u.admission) }));
  return reasons;
}

function HistoricalNote({ h, onOpenConcept }: { h: LibraryHistoricalUnit; onOpenConcept: (id: number) => void }) {
  const { t, tn, status } = useI18n();
  const e = h.latest_event;
  return (
    <span>
      {h.effective_status === "invalid"
        ? t("library.historical.invalid")
        : h.current_concept_id !== null
          ? tn("library.historical.moved", {
              concept: (
                <button type="button" className="link-button" onClick={() => onOpenConcept(h.current_concept_id!)}>
                  {t("library.conceptLink", { id: h.current_concept_id })}
                </button>
              ),
            })
          : t("library.historical.unfiled")}
      {!h.unit.in_current_extraction ? <>{" "}{t("library.historical.oldExtraction", { version: h.unit.extraction_version })}</> : ""}{" "}
      {t("library.historical.lastDecision", {
        relation: e.relation.toUpperCase(),
        status: status(e.status),
        source: e.decision_source,
        id: e.id,
      })}
    </span>
  );
}

function UnitCard({ unit, note, onOpenSource }: { unit: LibraryUnit; note?: ReactNode; onOpenSource: () => void }) {
  const i18n = useI18n();
  const { t } = i18n;
  return (
    <article className="library-unit" aria-label={t("inspector.unit", { id: unit.unit_id })}>
      <div className="library-unit-head">
        <strong>{unit.canonical}</strong>{" "}
        <span className={`tag ${unit.in_current_extraction ? "active" : "retired"}`}>
          {unit.in_current_extraction ? t("library.unit.current") : t("library.unit.older", { version: unit.extraction_version })}
        </span>
      </div>
      <p>{unit.statement}</p>
      {unit.example ? <FrenchExample text={unit.example} /> : null}
      {note ? <p className="hint">{note}</p> : null}
      <div className="hint">
        {t("library.unit.meta", {
          id: unit.unit_id,
          kind: unit.kind,
          record: unit.entry_id,
          version: unit.extraction_version,
          admission: spaced(i18n, unit.admission),
        })}{" "}
        <button type="button" className="link-button" onClick={onOpenSource}>
          {t("library.unit.viewSource", { id: unit.entry_id })}
        </button>
      </div>
    </article>
  );
}

// The French example is learner-facing study material: always shown as written, marked lang="fr".
function FrenchExample({ text }: { text: string }) {
  const { t } = useI18n();
  return (
    <p className="hint">
      {t("library.frenchExample")}{" "}
      <span lang="fr" className="french">
        {text}
      </span>
    </p>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

const resolutionText: Record<string, MessageKey> = {
  unreviewed: "library.resolution.unreviewed",
  accepted: "library.resolution.accepted",
  corrected: "library.resolution.corrected",
  rejected: "library.resolution.rejected",
};

function SourceScreen({
  unitId,
  conceptId,
  resultsLabel,
  onBackToConcept,
  onBackToResults,
  onOpenConcept,
}: {
  unitId: number;
  conceptId: number;
  resultsLabel: string;
  onBackToConcept: () => void;
  onBackToResults: () => void;
  onOpenConcept: (conceptId: number) => void;
}) {
  const i18n = useI18n();
  const { t, tn, status } = i18n;
  const [retry, setRetry] = useState(0);
  const load = useLoad<LibrarySource>(String(unitId), () => api.getLibraryUnitSource(unitId), retry);
  const headingRef = useFocusedHeading(load.status);
  const nav = (
    <div className="actions">
      <button type="button" className="ghost" onClick={onBackToConcept}>
        {t("library.source.backToConcept", { id: conceptId })}
      </button>
      <button type="button" className="ghost" onClick={onBackToResults}>
        {t("library.backTo", { label: resultsLabel })}
      </button>
    </div>
  );
  if (load.status !== "ready")
    return (
      <section className="panel" aria-label={t("library.source.region")}>
        <h2 ref={headingRef} tabIndex={-1}>
          {t("library.source.heading", { id: unitId })}
        </h2>
        {nav}
        {load.status === "loading" ? (
          <p className="hint" role="status">{t("library.source.loading", { id: unitId })}</p>
        ) : (
          <div className="banner error" role="alert">
            {t("library.source.failed", { id: unitId, message: load.message })}{" "}
            <button type="button" className="ghost" onClick={() => setRetry((n) => n + 1)}>
              {t("common.tryAgain")}
            </button>
          </div>
        )}
      </section>
    );
  const s = load.data;
  const interp = s.source_interpretation;
  const isCurrent = s.unit.in_current_extraction;
  const newer = s.latest_analysis && s.latest_analysis.id !== interp.analysis.id ? s.latest_analysis : null;
  const resolution = resolutionText[interp.effective.resolution]
    ? t(resolutionText[interp.effective.resolution])
    : interp.effective.resolution;
  return (
    <div>
      <section className="panel" aria-label={t("library.source.region")}>
        <h2 ref={headingRef} tabIndex={-1} className="library-title">
          {t("library.source.title", { unit: s.unit.unit_id, record: s.entry.id })}
        </h2>
        {nav}
        <p className="hint">{t("library.source.hint")}</p>
      </section>

      <section className="panel library-section" aria-labelledby="src-unit">
        <h3 id="src-unit">{t("library.source.unit", { id: s.unit.unit_id })}</h3>
        <p>
          <strong>{s.unit.canonical}</strong>: {s.unit.statement}
        </p>
        {s.unit.example ? <FrenchExample text={s.unit.example} /> : null}
        <p className="hint">
          {s.annotation.status === "invalid"
            ? t("library.source.now.invalid")
            : s.annotation.current_concept_id !== null
              ? tn("library.source.now.filed", {
                  concept: (
                    <button type="button" className="link-button" onClick={() => onOpenConcept(s.annotation.current_concept_id!)}>
                      {t("library.conceptLink", { id: s.annotation.current_concept_id })}
                    </button>
                  ),
                })
              : t("library.source.now.none")}{" "}
          {t("library.source.nowMeta", { kind: s.unit.kind, admission: spaced(i18n, s.unit.admission) })}
        </p>
      </section>

      <section className="panel library-section current" aria-labelledby="src-entry">
        <h3 id="src-entry">{t("library.source.entry", { id: s.entry.id })}</h3>
        <dl className="unit-evidence">
          <Row label={t("library.source.wrote")}>
            <span className="french">{s.entry.original_input}</span>
          </Row>
          <Row label={t("library.source.context")}>{s.entry.original_context || <em>{t("library.noneLower")}</em>}</Row>
          <Row label={t("library.source.recorded")}>{s.entry.created_at}</Row>
        </dl>
      </section>

      <section className={`panel library-section ${isCurrent ? "current" : "history"}`} aria-labelledby="src-extraction">
        <h3 id="src-extraction">{t("library.source.extraction", { version: s.extraction.version })}</h3>
        <p className="hint">{t("library.source.extraction.hint")}</p>
        <p>
          {isCurrent
            ? t("library.source.extraction.current")
            : s.current_extraction.extraction_id === null
              ? t("library.source.extraction.historical")
              : t(
                  s.current_extraction.selection_mode === "pinned"
                    ? "library.source.extraction.historicalPinned"
                    : "library.source.extraction.historicalAutomatic",
                  { id: s.current_extraction.extraction_id },
                )}
        </p>
        <p className="hint">
          {t("library.source.extraction.meta", {
            id: s.extraction.id,
            extractor: s.extraction.extractor,
            created: s.extraction.created_at,
          })}
        </p>
      </section>

      <section className="panel library-section" aria-labelledby="src-interp">
        <h3 id="src-interp">{t("library.source.interpretation", { version: interp.analysis.version })}</h3>
        <p className="hint">{t("library.source.interpretation.hint")}</p>
        <dl className="unit-evidence">
          <Row label={t("library.source.review")}>
            {interp.feedback
              ? t("library.source.review.feedback", { resolution, id: interp.feedback.id, status: status(interp.feedback.status) })
              : t("library.source.review.none", { resolution })}
          </Row>
          {interp.effective.effective ? (
            <>
              <Row label={t("effective.category")}>{interp.effective.effective.category}</Row>
              <Row label={t("library.source.explanationUsed")}>{interp.effective.effective.explanation}</Row>
            </>
          ) : (
            <Row label={t("library.source.explanationUsed")}>{t("library.source.rejected")}</Row>
          )}
          {interp.effective.resolution === "corrected" ? (
            <Row label={t("library.source.beforeCorrection")}>
              {interp.effective.original.category}: {interp.effective.original.explanation}
            </Row>
          ) : null}
          <Row label={t("library.source.producedBy")}>{interp.analysis.analyzer}</Row>
        </dl>
        <p className="hint">
          {newer
            ? t("library.source.newer", { newer: newer.version, version: interp.analysis.version })
            : t("library.source.latest", { version: interp.analysis.version })}
        </p>
      </section>
    </div>
  );
}
