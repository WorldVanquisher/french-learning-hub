import type { ReviewableUnit } from "../types/concept";
import { useI18n } from "../i18n";

// UnitCard shows the immutable KnowledgeUnit evidence and its derived default
// candidate identity. This is an experimental annotation UI, so technical identity
// information (signature, features) is shown, not hidden.
export function UnitCard({ unit }: { unit: ReviewableUnit }) {
  const { t } = useI18n();
  const id = unit.candidate_identity;
  const features = Object.entries(id.identity_features ?? {});
  return (
    <div className="panel">
      <h2>{t("unitCard.title")}</h2>
      <div className="field-row">
        <span className="label">{t("unitCard.unitId")}</span>
        <span className="value mono">{unit.unit_id}</span>
      </div>
      <div className="field-row">
        <span className="label">{t("unitCard.kind")}</span>
        <span className="value">{unit.kind}</span>
      </div>
      <div className="field-row">
        <span className="label">{t("unitCard.canonical")}</span>
        <span className="value french">{unit.canonical}</span>
      </div>
      <div className="field-row">
        <span className="label">{t("unitCard.statement")}</span>
        <span className="value french">{unit.statement}</span>
      </div>
      {unit.example ? (
        <div className="field-row">
          <span className="label">{t("unitCard.example")}</span>
          <span className="value french">{unit.example}</span>
        </div>
      ) : null}
      <div className="field-row">
        <span className="label">{t("unitCard.confidence")}</span>
        <span className="value">{unit.confidence.toFixed(2)}</span>
      </div>

      <h2 style={{ marginTop: 16 }}>{t("unitCard.identity")}</h2>
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
        <span className="value">{id.scope || <em>{t("common.unset")}</em>}</span>
      </div>
      <div className="field-row">
        <span className="label">identity_features</span>
        <span className="value">
          {features.length === 0 ? (
            <em>{t("common.none")}</em>
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
