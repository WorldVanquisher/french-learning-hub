import type { Concept } from "../types/concept";
import { useI18n } from "../i18n";

// CandidateConceptCard shows one existing concept from either the deterministic
// exact-signature resolver or retrieval-only catalog discovery. The containing
// section communicates that provenance. Selecting the card creates no annotation;
// it only targets a later explicit SAME / DISTINCT / relation action.
export function CandidateConceptCard({
  concept,
  selected,
  onSelect,
}: {
  concept: Concept;
  selected: boolean;
  onSelect: () => void;
}) {
  const { t, tn, status } = useI18n();
  const features = Object.entries(concept.identity_features ?? {});
  return (
    <div className={`candidate${selected ? " selected" : ""}`}>
      <div className="head">
        <strong>{tn("candidate.heading", { id: <span className="mono">#{concept.id}</span> })}</strong>
        <span className={`tag ${concept.state}`}>{status(concept.state)}</span>
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
        <span className="value">{concept.scope || <em>{t("common.unset")}</em>}</span>
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
        <span className="label">{t("candidate.lifecycleSupport")}</span>
        <span className="value">
          {status(concept.lifecycle_state)} / {status(concept.support_state)}
        </span>
      </div>
      <div className="field-row">
        <span className="label">{t("candidate.preferredUnit")}</span>
        <span className="value">
          {concept.preferred_unit_id !== null ? (
            <span className="mono">{concept.preferred_unit_id}</span>
          ) : (
            <em>{t("common.none")}</em>
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
        {selected ? t("candidate.selected") : t("candidate.select")}
      </button>
    </div>
  );
}
