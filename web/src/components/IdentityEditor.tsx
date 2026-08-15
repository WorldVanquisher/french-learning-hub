import { useState } from "react";
import type { ConceptIdentity } from "../types/concept";

// IdentityEditor lets the reviewer edit a candidate identity before creating a NEW
// CONCEPT. It starts from the backend-derived candidate identity. It is deliberately
// small: target / pedagogical_intent / scope plus a minimal key/value editor for
// identity_features. This UI is how we discover which identity attributes are
// actually useful — it is not a large linguistics form.
export function IdentityEditor({
  value,
  onChange,
}: {
  value: ConceptIdentity;
  onChange: (next: ConceptIdentity) => void;
}) {
  // Features are edited as an ordered pair list so a blank key can exist while
  // typing; they are collapsed back to a map on every change.
  const [pairs, setPairs] = useState<Array<[string, string]>>(() =>
    Object.entries(value.identity_features ?? {}),
  );

  function pushFeatures(next: Array<[string, string]>) {
    setPairs(next);
    const map: Record<string, string> = {};
    for (const [k, v] of next) {
      if (k.trim() !== "") map[k] = v;
    }
    onChange({ ...value, identity_features: map });
  }

  return (
    <div className="identity-editor">
      <label htmlFor="id-target">target</label>
      <input
        id="id-target"
        value={value.target}
        onChange={(e) => onChange({ ...value, target: e.target.value })}
      />

      <label htmlFor="id-intent">pedagogical_intent</label>
      <input
        id="id-intent"
        value={value.pedagogical_intent}
        onChange={(e) => onChange({ ...value, pedagogical_intent: e.target.value })}
      />

      <label htmlFor="id-scope">scope</label>
      <input
        id="id-scope"
        value={value.scope}
        onChange={(e) => onChange({ ...value, scope: e.target.value })}
      />

      <label>identity_features</label>
      {pairs.map(([k, v], i) => (
        <div className="feature-row" key={i}>
          <input
            aria-label={`feature key ${i}`}
            placeholder="key"
            value={k}
            onChange={(e) => {
              const next = pairs.slice();
              next[i] = [e.target.value, v];
              pushFeatures(next);
            }}
          />
          <input
            aria-label={`feature value ${i}`}
            placeholder="value"
            value={v}
            onChange={(e) => {
              const next = pairs.slice();
              next[i] = [k, e.target.value];
              pushFeatures(next);
            }}
          />
          <button
            className="ghost"
            aria-label={`remove feature ${i}`}
            onClick={() => pushFeatures(pairs.filter((_, j) => j !== i))}
          >
            ✕
          </button>
        </div>
      ))}
      <button className="ghost" style={{ marginTop: 8 }} onClick={() => pushFeatures([...pairs, ["", ""]])}>
        + add feature
      </button>
      <p className="hint">
        Fields are normalized server-side (lowercased, whitespace-collapsed) before
        the identity signature is computed.
      </p>
    </div>
  );
}
