import { useEffect, useMemo, useState } from "react";
import * as api from "../api/client";
import type {
  Concept,
  EffectiveAnnotationItem,
  EffectiveAnnotationStatus,
} from "../types/concept";

type StatusFilter = "all" | EffectiveAnnotationStatus;
type SameSourceFilter = "all" | "human" | "automatic";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function ConceptReference({
  conceptId,
  concepts,
}: {
  conceptId: number;
  concepts: Map<number, Concept>;
}) {
  const concept = concepts.get(conceptId);
  if (!concept) {
    return <span>Concept #{conceptId}</span>;
  }
  return (
    <span>
      <span className="mono">#{conceptId}</span> {concept.target}
      {concept.pedagogical_intent ? (
        <span className="concept-intent"> — {concept.pedagogical_intent}</span>
      ) : null}
    </span>
  );
}

function Provenance({
  source,
  eventId,
  resolverVersion,
  createdAt,
}: {
  source: string;
  eventId: number;
  resolverVersion?: string;
  createdAt?: string;
}) {
  return (
    <div className="annotation-provenance">
      <span>source: <span className="mono">{source}</span></span>
      <span>event #{eventId}</span>
      {resolverVersion ? <span>resolver: {resolverVersion}</span> : null}
      {createdAt ? <time dateTime={createdAt}>{createdAt}</time> : null}
    </div>
  );
}

function InspectorItem({
  item,
  concepts,
}: {
  item: EffectiveAnnotationItem;
  concepts: Map<number, Concept>;
}) {
  const { unit, snapshot } = item;
  const corrupt = snapshot.unit_id !== unit.id;

  return (
    <article className="inspector-card" aria-label={`Unit #${unit.id}`}>
      <div className="inspector-card-head">
        <h2>Unit #{unit.id}</h2>
        <span className={`status-tag ${snapshot.status}`}>{snapshot.status}</span>
      </div>

      {corrupt ? (
        <div className="banner error" role="alert">
          Corrupt effective snapshot: unit ID {snapshot.unit_id} does not match Unit #{unit.id}.
        </div>
      ) : null}

      <dl className="unit-evidence">
        <div><dt>Kind</dt><dd>{unit.kind}</dd></div>
        <div><dt>Canonical</dt><dd className="french">{unit.canonical}</dd></div>
        <div><dt>Statement</dt><dd className="french">{unit.statement}</dd></div>
        {unit.example ? <div><dt>Example</dt><dd className="french">{unit.example}</dd></div> : null}
        <div><dt>Confidence</dt><dd>{unit.confidence}</dd></div>
      </dl>

      <section className="annotation-section" aria-label="CURRENT SAME">
        <h3>CURRENT SAME</h3>
        {snapshot.current_same ? (
          <>
            <ConceptReference
              conceptId={snapshot.current_same.membership.concept_id}
              concepts={concepts}
            />
            <Provenance
              source={snapshot.current_same.decision.decision_source}
              eventId={snapshot.current_same.decision.id}
              resolverVersion={snapshot.current_same.decision.resolver_version}
              createdAt={snapshot.current_same.decision.created_at}
            />
          </>
        ) : (
          <p className="hint">No CURRENT SAME membership.</p>
        )}
      </section>

      {snapshot.distinctions.length > 0 ? (
        <section className="annotation-section" aria-label="Effective DISTINCT">
          <h3>Effective DISTINCT</h3>
          <ul className="annotation-list">
            {snapshot.distinctions.map((distinction) => (
              <li key={distinction.id}>
                <strong>DISTINCT → </strong>
                <ConceptReference conceptId={distinction.concept_id} concepts={concepts} />
                <Provenance
                  source={distinction.decision_source}
                  eventId={distinction.id}
                  resolverVersion={distinction.resolver_version}
                  createdAt={distinction.created_at}
                />
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {snapshot.relations.length > 0 ? (
        <section className="annotation-section" aria-label="Effective relations">
          <h3>Effective relations</h3>
          <ul className="annotation-list">
            {snapshot.relations.map((relation) => (
              <li key={relation.id}>
                <strong>{relation.relation.toUpperCase()} → </strong>
                <ConceptReference conceptId={relation.concept_id} concepts={concepts} />
                <Provenance
                  source={relation.decision_source}
                  eventId={relation.id}
                  resolverVersion={relation.resolver_version}
                  createdAt={relation.created_at}
                />
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {snapshot.status === "invalid" && snapshot.latest_unit_judgment ? (
        <section className="annotation-section invalid-provenance" aria-label="INVALID provenance">
          <h3>INVALID provenance</h3>
          <Provenance
            source={snapshot.latest_unit_judgment.decision_source}
            eventId={snapshot.latest_unit_judgment.id}
            createdAt={snapshot.latest_unit_judgment.created_at}
          />
          {snapshot.latest_unit_judgment.note ? <p>{snapshot.latest_unit_judgment.note}</p> : null}
        </section>
      ) : null}
    </article>
  );
}

// AnnotationInspector is a GET-only view of the backend's M11-A projection. It
// displays the returned effective facts verbatim and never derives their authority.
export function AnnotationInspector() {
  const [items, setItems] = useState<EffectiveAnnotationItem[]>([]);
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [loadingItems, setLoadingItems] = useState(true);
  const [loadingConcepts, setLoadingConcepts] = useState(true);
  const [itemsError, setItemsError] = useState<string | null>(null);
  const [conceptsError, setConceptsError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [sameSourceFilter, setSameSourceFilter] = useState<SameSourceFilter>("all");

  useEffect(() => {
    let active = true;
    api.listEffectiveAnnotations()
      .then((loaded) => {
        if (active) setItems(loaded);
      })
      .catch((error: unknown) => {
        if (active) setItemsError(errorMessage(error));
      })
      .finally(() => {
        if (active) setLoadingItems(false);
      });

    api.listConcepts()
      .then((loaded) => {
        if (active) setConcepts(loaded);
      })
      .catch((error: unknown) => {
        if (active) setConceptsError(errorMessage(error));
      })
      .finally(() => {
        if (active) setLoadingConcepts(false);
      });

    return () => {
      active = false;
    };
  }, []);

  const conceptsById = useMemo(
    () => new Map(concepts.map((concept) => [concept.id, concept])),
    [concepts],
  );

  const filteredItems = useMemo(
    () => items.filter((item) => {
      if (statusFilter !== "all" && item.snapshot.status !== statusFilter) return false;
      if (sameSourceFilter === "all") return true;
      const source = item.snapshot.current_same?.decision.decision_source;
      return sameSourceFilter === "human"
        ? source === "human"
        : source === "resolver:automatic";
    }),
    [items, sameSourceFilter, statusFilter],
  );

  if (loadingItems) {
    return <div className="empty">Loading effective annotations…</div>;
  }

  if (itemsError) {
    return <div className="banner error" role="alert">Could not load effective annotations: {itemsError}</div>;
  }

  return (
    <main>
      <div className="banner info">
        Read-only view of M11-A effective annotation state. This page does not create or change annotation authority.
      </div>

      {loadingConcepts ? <div className="banner info">Loading Concept catalog…</div> : null}
      {conceptsError ? (
        <div className="banner error" role="alert">
          Could not load the Concept catalog: {conceptsError}. Referenced concepts are shown by ID.
        </div>
      ) : null}

      <div className="inspector-filters" aria-label="Inspector filters">
        <label>
          Annotation status
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}>
            <option value="all">All</option>
            <option value="resolved">Resolved</option>
            <option value="unresolved">Unresolved</option>
            <option value="invalid">Invalid</option>
          </select>
        </label>
        <label>
          CURRENT SAME source
          <select value={sameSourceFilter} onChange={(event) => setSameSourceFilter(event.target.value as SameSourceFilter)}>
            <option value="all">All</option>
            <option value="human">Human</option>
            <option value="automatic">Automatic</option>
          </select>
        </label>
      </div>

      {items.length === 0 ? (
        <div className="empty">No KnowledgeUnits exist in the current extraction.</div>
      ) : filteredItems.length === 0 ? (
        <div className="empty">No effective annotations match these filters.</div>
      ) : (
        <div className="inspector-list">
          {filteredItems.map((item) => (
            <InspectorItem key={item.unit.id} item={item} concepts={conceptsById} />
          ))}
        </div>
      )}
    </main>
  );
}
