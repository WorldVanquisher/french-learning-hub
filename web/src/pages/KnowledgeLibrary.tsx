import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import * as api from "../api/client";
import { ApiError } from "../api/client";
import type {
  LibraryConcept,
  LibraryHistoricalUnit,
  LibraryQuery,
  LibrarySearch,
  LibrarySource,
  LibraryStateFilter,
  LibraryUnit,
} from "../types/library";

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

const fieldLabels: Record<string, string> = {
  target: "title",
  pedagogical_intent: "type",
  scope: "scope",
  identity_features: "identity details",
  unit_canonical: "the name of a unit filed here",
  unit_statement: "the explanation of a unit filed here",
  unit_example: "the example of a unit filed here",
};

// KnowledgeLibrary is a GET-only view of curated Concepts. Searching, opening a
// Concept, or following a source records nothing and calls no provider; every
// status shown is a backend fact.
export function KnowledgeLibrary() {
  const [draft, setDraft] = useState<LibraryQuery>({ q: "", state: "all" });
  const [query, setQuery] = useState<LibraryQuery>({ q: "", state: "all" });
  const [screen, setScreen] = useState<Screen>({ kind: "results" });
  const [retry, setRetry] = useState(0);
  const returnTo = useRef<number | null>(null);

  const search = useLoad<LibrarySearch>(`${query.state}\u0000${query.q}`, () => api.searchLibrary(query), retry);

  // On return, focus the result the reader opened. Detail screens focus their own heading.
  useEffect(() => {
    if (screen.kind === "results" && returnTo.current !== null && search.status === "ready") {
      document.getElementById(resultButtonId(returnTo.current))?.focus();
      returnTo.current = null;
    }
  }, [screen, search.status]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setQuery({ q: draft.q.trim(), state: draft.state });
  };
  const backToResults = (conceptId: number) => {
    returnTo.current = conceptId;
    setScreen({ kind: "results" });
  };
  const openConcept = (conceptId: number) => setScreen({ kind: "concept", conceptId });
  const resultsLabel = query.q ? `results for “${query.q}”` : "all concepts";

  return (
    <main className="library">
      <div hidden={screen.kind !== "results"}>
        <form className="panel library-search" role="search" onSubmit={submit}>
          <label htmlFor="library-query">Search learned material</label>
          <div className="discovery-search-row">
            <input
              id="library-query"
              type="search"
              value={draft.q}
              placeholder="e.g. subjonctif, il faut que, passé composé"
              onChange={(e) => setDraft({ ...draft, q: e.target.value })}
            />
            <select
              aria-label="Concept status"
              value={draft.state}
              onChange={(e) => setDraft({ ...draft, state: e.target.value as LibraryStateFilter })}
            >
              <option value="all">all statuses</option>
              <option value="active">active (supported)</option>
              <option value="orphaned">orphaned (unsupported)</option>
              <option value="retired">retired</option>
            </select>
            <button type="submit" className="primary">Search</button>
            <button
              type="button"
              className="ghost"
              onClick={() => {
                setDraft({ q: "", state: "all" });
                setQuery({ q: "", state: "all" });
              }}
            >
              clear
            </button>
          </div>
          <p className="hint">
            A <strong>concept</strong> is one idea you have learned, such as a grammar rule. A <strong>unit</strong> is a
            short rule taken from one of your learning records; units are filed under concepts and always link back to
            the record they came from.
          </p>
          <p className="hint">
            Search looks at concept titles and identity details, and at the name, explanation and French example of every
            unit filed under a concept (its CURRENT SAME members), even units that no longer support it. Units that were
            moved away are not searched. Accents and case are ignored, and each word matches the start of a word.
            Read-only: searching records nothing.
          </p>
        </form>
        <Results
          search={search}
          query={query}
          onOpen={openConcept}
          onRetry={() => setRetry((n) => n + 1)}
        />
      </div>
      {screen.kind === "concept" ? (
        <ConceptScreen
          key={`concept-${screen.conceptId}`}
          conceptId={screen.conceptId}
          backLabel={`← Back to ${resultsLabel}`}
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
  if (search.status === "loading") return <p className="empty" role="status">Searching the knowledge library…</p>;
  if (search.status === "error")
    return (
      <div className="banner error" role="alert">
        Could not search the knowledge library: {search.message}{" "}
        <button type="button" className="ghost" onClick={onRetry}>
          Try again
        </button>
      </div>
    );
  const data = search.data;
  if (data.results.length === 0)
    return (
      <div className="empty" role="status">
        {query.q
          ? `No concepts match “${query.q}”${query.state === "all" ? "" : ` with status ${query.state}`}.`
          : query.state === "all"
            ? "The library is empty. Concepts appear here after they are created in Concept Review."
            : `No ${query.state} concepts.`}
      </div>
    );
  return (
    <section aria-label="Library results">
      <p className="hint" role="status">
        {data.truncated
          ? `Showing the first ${data.results.length} of ${data.total_matches} matching concepts. Refine the search to see others.`
          : `${data.total_matches} concept${data.total_matches === 1 ? "" : "s"}${query.q ? ` matching “${query.q}”` : ""}.`}
      </p>
      <ol className="library-results">
        {data.results.map((r) => (
          <li key={r.concept.id} className="panel library-result">
            <button type="button" className="link-button" id={resultButtonId(r.concept.id)} onClick={() => onOpen(r.concept.id)}>
              {r.concept.target}
            </button>{" "}
            <StateTag state={r.concept.state} />
            <div className="hint">
              {r.concept.pedagogical_intent}
              {r.concept.scope ? ` · ${r.concept.scope}` : ""} · {r.current_member_count} unit
              {r.current_member_count === 1 ? "" : "s"} filed here, {r.supporting_unit_count} currently supporting ·
              concept #{r.concept.id}
            </div>
            {r.match_tier !== "browse" ? (
              <div className="hint">
                Found in {r.matched_fields.map((f) => fieldLabels[f] ?? f).join(", ")}
                {r.match_tier === "unit_evidence"
                  ? ", not in the concept's title. Being filed here does not mean the unit supports the concept; open it to see."
                  : ""}
              </div>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}

function StateTag({ state }: { state: "active" | "orphaned" | "retired" }) {
  return <span className={`tag ${state}`}>{state}</span>;
}

const supportText: Record<string, string> = {
  active:
    "Active: at least one unit currently supports this concept. It is filed here, comes from its record's current extraction, and has not been hidden by the learner.",
  orphaned:
    "Orphaned: no unit currently supports this concept. It keeps its identity and history, can still be inspected, and becomes active again if a supporting unit returns.",
  retired: "Retired by a person. Its history can still be inspected.",
};

// Membership versus support, in the words used on the concept page.
const filedVersusSupporting =
  "A unit is filed under a concept when it was judged to be the same idea (its CURRENT SAME membership). It supports the concept only while it also comes from its record's current extraction and the learner has not hidden it (admission active).";

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
      <section className="panel" aria-label="Concept">
        <h2 ref={headingRef} tabIndex={-1}>
          Concept #{conceptId}
        </h2>
        {back}
        {load.status === "loading" ? (
          <p className="hint" role="status">Loading concept #{conceptId}…</p>
        ) : (
          <div className="banner error" role="alert">
            Could not load concept #{conceptId}: {load.message}{" "}
            <button type="button" className="ghost" onClick={() => setRetry((n) => n + 1)}>
              Try again
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
      <section className="panel library-concept" aria-label="Concept">
        <h2 ref={headingRef} tabIndex={-1} className="library-title">
          {c.target} <StateTag state={c.state} />
        </h2>
        {back}
        <dl className="unit-evidence">
          <Row label="Status">{supportText[c.state]}</Row>
          <Row label="Type">{c.pedagogical_intent}</Row>
          <Row label="Scope">{c.scope || <em>not set</em>}</Row>
          <Row label="Identity details">
            {features.length ? features.map(([k, v]) => `${k}: ${v}`).join(" · ") : <em>none</em>}
          </Row>
        </dl>
        <p className="hint">{filedVersusSupporting}</p>
        <p className="hint">
          Concept #{c.id} · lifecycle {c.lifecycle_state} · support {c.support_state}
        </p>
      </section>

      <section className="panel library-section current" aria-labelledby="lib-preferred">
        <h3 id="lib-preferred">Best explanation (preferred unit)</h3>
        {d.preferred_unit ? (
          unit(d.preferred_unit, preferredNote(d.preferred_unit, d))
        ) : (
          <p className="hint">No unit has been chosen as the best explanation.</p>
        )}
      </section>

      <section className="panel library-section current" aria-labelledby="lib-support">
        <h3 id="lib-support">Currently supporting this concept ({d.supporting_units.length})</h3>
        {d.supporting_units.length ? (
          d.supporting_units.map((u) => unit(u))
        ) : (
          <p className="hint">No unit currently supports this concept.</p>
        )}
      </section>

      {d.non_supporting_members.length ? (
        <section className="panel library-section" aria-labelledby="lib-members">
          <h3 id="lib-members">Filed here but not supporting ({d.non_supporting_members.length})</h3>
          <p className="hint">These units are still filed under this concept, but they do not count as support, for the reason shown.</p>
          {d.non_supporting_members.map((u) => unit(u, <span>{notSupportingReasons(u).join(" ")}</span>))}
        </section>
      ) : null}

      <section className="panel library-section" aria-labelledby="lib-relations">
        <h3 id="lib-relations">Linked units ({d.current_relations.length})</h3>
        <p className="hint">
          A link records that a unit is BROADER, NARROWER or RELATED to this concept. A link is not filing and gives no
          support.
        </p>
        {d.current_relations.length ? (
          d.current_relations.map((r) =>
            unit(
              r.unit,
              <span>
                <strong>{r.relation.toUpperCase()}</strong> link from unit #{r.unit.unit_id} to this concept
                {` (link #${r.link_id}, decided by ${r.decision_source}).`}
              </span>,
              `relation-${r.link_id}`,
            ),
          )
        ) : (
          <p className="hint">No units are linked to this concept.</p>
        )}
      </section>

      <section className="panel library-section history" aria-labelledby="lib-history">
        <h3 id="lib-history">History: no longer current ({d.historical_units.length})</h3>
        <p className="hint">
          Units that were once filed or linked here but are not any more. They are shown so you can trace past decisions,
          and never count as support. {d.history_event_count} decision{d.history_event_count === 1 ? "" : "s"} recorded for
          this concept in total (append-only).
        </p>
        {d.historical_units.length
          ? d.historical_units.map((h) => unit(h.unit, <HistoricalNote h={h} onOpenConcept={onOpenConcept} />))
          : <p className="hint">No earlier units.</p>}
      </section>
    </div>
  );
}

function preferredNote(u: LibraryUnit, d: LibraryConcept): string {
  const supporting = d.supporting_units.some((s) => s.unit_id === u.unit_id);
  return supporting
    ? "Chosen as the best explanation; it also currently supports the concept."
    : `Chosen as the best explanation and still filed here, but it does not support the concept: ${notSupportingReasons(u).join(" ")}`;
}

function notSupportingReasons(u: LibraryUnit): string[] {
  const reasons: string[] = [];
  if (!u.in_current_extraction)
    reasons.push(
      `It comes from extraction v${u.extraction_version} of record #${u.entry_id}, which is no longer that record's current extraction.`,
    );
  if (u.admission === "suppressed") reasons.push("The learner hid it (admission suppressed).");
  else if (u.admission !== "active") reasons.push(`It is waiting for review (admission ${u.admission.replace("_", " ")}).`);
  return reasons;
}

function HistoricalNote({ h, onOpenConcept }: { h: LibraryHistoricalUnit; onOpenConcept: (id: number) => void }) {
  const e = h.latest_event;
  return (
    <span>
      {h.effective_status === "invalid" ? (
        "This unit was later marked INVALID: judged not to be a usable unit."
      ) : h.current_concept_id !== null ? (
        <>
          This unit was moved: it is now filed under{" "}
          <button type="button" className="link-button" onClick={() => onOpenConcept(h.current_concept_id!)}>
            concept #{h.current_concept_id}
          </button>
          .
        </>
      ) : (
        "This unit is no longer filed under any concept."
      )}
      {!h.unit.in_current_extraction ? ` Its extraction v${h.unit.extraction_version} is not the record's current one.` : ""}{" "}
      Last decision here: {e.relation.toUpperCase()} {e.status} ({e.decision_source}, event #{e.id}).
    </span>
  );
}

function UnitCard({ unit, note, onOpenSource }: { unit: LibraryUnit; note?: ReactNode; onOpenSource: () => void }) {
  return (
    <article className="library-unit" aria-label={`Unit #${unit.unit_id}`}>
      <div className="library-unit-head">
        <strong>{unit.canonical}</strong>{" "}
        <span className={`tag ${unit.in_current_extraction ? "active" : "retired"}`}>
          {unit.in_current_extraction ? "current extraction" : `older extraction v${unit.extraction_version}`}
        </span>
      </div>
      <p>{unit.statement}</p>
      {unit.example ? <FrenchExample text={unit.example} /> : null}
      {note ? <p className="hint">{note}</p> : null}
      <div className="hint">
        Unit #{unit.unit_id} · {unit.kind} · record #{unit.entry_id}, extraction v{unit.extraction_version} · admission{" "}
        {unit.admission.replace("_", " ")}{" "}
        <button type="button" className="link-button" onClick={onOpenSource}>
          View source record #{unit.entry_id}
        </button>
      </div>
    </article>
  );
}

function FrenchExample({ text }: { text: string }) {
  return (
    <p className="hint">
      French example:{" "}
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

const resolutionText: Record<string, string> = {
  unreviewed: "not reviewed by a person",
  accepted: "accepted by a person",
  corrected: "corrected by a person",
  rejected: "rejected by a person",
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
  const [retry, setRetry] = useState(0);
  const load = useLoad<LibrarySource>(String(unitId), () => api.getLibraryUnitSource(unitId), retry);
  const headingRef = useFocusedHeading(load.status);
  const nav = (
    <div className="actions">
      <button type="button" className="ghost" onClick={onBackToConcept}>
        ← Back to concept #{conceptId}
      </button>
      <button type="button" className="ghost" onClick={onBackToResults}>
        ← Back to {resultsLabel}
      </button>
    </div>
  );
  if (load.status !== "ready")
    return (
      <section className="panel" aria-label="Source">
        <h2 ref={headingRef} tabIndex={-1}>
          Where unit #{unitId} came from
        </h2>
        {nav}
        {load.status === "loading" ? (
          <p className="hint" role="status">Loading the source of unit #{unitId}…</p>
        ) : (
          <div className="banner error" role="alert">
            Could not load the source of unit #{unitId}: {load.message}{" "}
            <button type="button" className="ghost" onClick={() => setRetry((n) => n + 1)}>
              Try again
            </button>
          </div>
        )}
      </section>
    );
  const s = load.data;
  const interp = s.source_interpretation;
  const isCurrent = s.unit.in_current_extraction;
  const newer = s.latest_analysis && s.latest_analysis.id !== interp.analysis.id ? s.latest_analysis : null;
  return (
    <div>
      <section className="panel" aria-label="Source">
        <h2 ref={headingRef} tabIndex={-1} className="library-title">
          Where unit #{s.unit.unit_id} came from: learning record #{s.entry.id}
        </h2>
        {nav}
        <p className="hint">
          The trail from what the learner wrote, through how it was interpreted, to the unit. Read-only: opening it
          records nothing and runs no analysis or extraction.
        </p>
      </section>

      <section className="panel library-section" aria-labelledby="src-unit">
        <h3 id="src-unit">The unit (#{s.unit.unit_id})</h3>
        <p>
          <strong>{s.unit.canonical}</strong>: {s.unit.statement}
        </p>
        {s.unit.example ? <FrenchExample text={s.unit.example} /> : null}
        <p className="hint">
          Now:{" "}
          {s.annotation.status === "invalid" ? (
            "marked INVALID (not a usable unit)"
          ) : s.annotation.current_concept_id !== null ? (
            <>
              filed under{" "}
              <button type="button" className="link-button" onClick={() => onOpenConcept(s.annotation.current_concept_id!)}>
                concept #{s.annotation.current_concept_id}
              </button>{" "}
              (CURRENT SAME)
            </>
          ) : (
            "not filed under any concept"
          )}{" "}
          · {s.unit.kind} · admission {s.unit.admission.replace("_", " ")}
        </p>
      </section>

      <section className="panel library-section current" aria-labelledby="src-entry">
        <h3 id="src-entry">Original learning record #{s.entry.id}</h3>
        <dl className="unit-evidence">
          <Row label="What the learner wrote">
            <span className="french">{s.entry.original_input}</span>
          </Row>
          <Row label="Context">{s.entry.original_context || <em>none</em>}</Row>
          <Row label="Recorded">{s.entry.created_at}</Row>
        </dl>
      </section>

      <section className={`panel library-section ${isCurrent ? "current" : "history"}`} aria-labelledby="src-extraction">
        <h3 id="src-extraction">Extraction v{s.extraction.version}</h3>
        <p className="hint">An extraction is the step that turned this record into units. A record can be extracted more than once.</p>
        <p>
          {isCurrent
            ? "This is the record's current extraction."
            : `Historical: this is not the record's current extraction${
                s.current_extraction.extraction_id !== null
                  ? ` (the current one is extraction #${s.current_extraction.extraction_id}, ${
                      s.current_extraction.selection_mode === "pinned" ? "pinned by a person" : "selected automatically"
                    })`
                  : ""
              }. The unit is kept as evidence but does not count as support.`}
        </p>
        <p className="hint">
          Extraction #{s.extraction.id} by {s.extraction.extractor}, {s.extraction.created_at}.
        </p>
      </section>

      <section className="panel library-section" aria-labelledby="src-interp">
        <h3 id="src-interp">Interpretation this extraction used: analysis v{interp.analysis.version}</h3>
        <p className="hint">How the record was understood at the time the units were made, including any human correction then in force.</p>
        <dl className="unit-evidence">
          <Row label="Review">
            {resolutionText[interp.effective.resolution] ?? interp.effective.resolution}
            {interp.feedback ? ` (feedback #${interp.feedback.id}, ${interp.feedback.status})` : " (no feedback at extraction time)"}
          </Row>
          {interp.effective.effective ? (
            <>
              <Row label="Category">{interp.effective.effective.category}</Row>
              <Row label="Explanation used">{interp.effective.effective.explanation}</Row>
            </>
          ) : (
            <Row label="Explanation used">none: the interpretation was rejected</Row>
          )}
          {interp.effective.resolution === "corrected" ? (
            <Row label="Before correction">
              {interp.effective.original.category}: {interp.effective.original.explanation}
            </Row>
          ) : null}
          <Row label="Produced by">{interp.analysis.analyzer}</Row>
        </dl>
        <p className="hint">
          {newer
            ? `The record now has a newer analysis (v${newer.version}); this unit was derived from v${interp.analysis.version}.`
            : `Analysis v${interp.analysis.version} is still the record's latest analysis.`}
        </p>
      </section>
    </div>
  );
}
