import type { Concept } from "../types/concept";

// CandidateConceptCard shows one existing concept the current unit might resolve to
// (from the deterministic exact-signature resolver). It surfaces the identity, the
// derived effective state, and the preferred representation, and lets the reviewer
// select it as the target for a SAME / relation decision.
export function CandidateConceptCard({
  concept,
  selected,
  onSelect,
}: {
  concept: Concept;
  selected: boolean;
  onSelect: () => void;
}) {
  const features = Object.entries(concept.identity_features ?? {});
  return (
    <div className={`candidate${selected ? " selected" : ""}`}>
      <div className="head">
        <strong>
          concept <span className="mono">#{concept.id}</span>
        </strong>
        <span className={`tag ${concept.state}`}>{concept.state}</span>
      </div>
      <div className="field-row">
        <span className="label">target</span>
        <span className="value">{concept.target}</span>
      </div>
      <div className="field-row">
        <span className="label">intent</span>
        <span className="value">{concept.pedagogical_intent}</span>
      </div>
      <div className="field-row">
        <span className="label">scope</span>
        <span className="value">{concept.scope || <em>(unset)</em>}</span>
      </div>
      {features.length > 0 ? (
        <div className="field-row">
          <span className="label">features</span>
          <span className="value">
            {features.map(([k, v]) => (
              <span key={k} className="mono" style={{ marginRight: 6 }}>
                {k}={v}
              </span>
            ))}
          </span>
        </div>
      ) : null}
      <div className="field-row">
        <span className="label">lifecycle / support</span>
        <span className="value">
          {concept.lifecycle_state} / {concept.support_state}
        </span>
      </div>
      <div className="field-row">
        <span className="label">preferred unit</span>
        <span className="value">
          {concept.preferred_unit_id !== null ? (
            <span className="mono">{concept.preferred_unit_id}</span>
          ) : (
            <em>(none)</em>
          )}
        </span>
      </div>
      <div className="field-row">
        <span className="label">signature</span>
        <span className="value mono">{concept.signature}</span>
      </div>
      <button
        className={selected ? "primary" : "ghost"}
        style={{ marginTop: 8 }}
        onClick={onSelect}
        aria-pressed={selected}
      >
        {selected ? "selected" : "select this concept"}
      </button>
    </div>
  );
}
