import type { ReviewableUnit } from "../types/concept";

// UnitCard shows the immutable KnowledgeUnit evidence and its derived default
// candidate identity. This is an experimental annotation UI, so technical identity
// information (signature, features) is shown, not hidden.
export function UnitCard({ unit }: { unit: ReviewableUnit }) {
  const id = unit.candidate_identity;
  const features = Object.entries(id.identity_features ?? {});
  return (
    <div className="panel">
      <h2>Knowledge Unit (evidence)</h2>
      <div className="field-row">
        <span className="label">unit id</span>
        <span className="value mono">{unit.unit_id}</span>
      </div>
      <div className="field-row">
        <span className="label">kind</span>
        <span className="value">{unit.kind}</span>
      </div>
      <div className="field-row">
        <span className="label">canonical</span>
        <span className="value french">{unit.canonical}</span>
      </div>
      <div className="field-row">
        <span className="label">statement</span>
        <span className="value french">{unit.statement}</span>
      </div>
      {unit.example ? (
        <div className="field-row">
          <span className="label">example</span>
          <span className="value french">{unit.example}</span>
        </div>
      ) : null}
      <div className="field-row">
        <span className="label">extraction confidence</span>
        <span className="value">{unit.confidence.toFixed(2)}</span>
      </div>

      <h2 style={{ marginTop: 16 }}>Candidate concept identity</h2>
      <div className="field-row">
        <span className="label">target</span>
        <span className="value">{id.target}</span>
      </div>
      <div className="field-row">
        <span className="label">pedagogical_intent</span>
        <span className="value">{id.pedagogical_intent}</span>
      </div>
      <div className="field-row">
        <span className="label">scope</span>
        <span className="value">{id.scope || <em>(unset)</em>}</span>
      </div>
      <div className="field-row">
        <span className="label">identity_features</span>
        <span className="value">
          {features.length === 0 ? (
            <em>(none)</em>
          ) : (
            features.map(([k, v]) => (
              <span key={k} className="mono" style={{ marginRight: 6 }}>
                {k}={v}
              </span>
            ))
          )}
        </span>
      </div>
      <div className="field-row">
        <span className="label">signature</span>
        <span className="value mono">{unit.signature}</span>
      </div>
    </div>
  );
}
