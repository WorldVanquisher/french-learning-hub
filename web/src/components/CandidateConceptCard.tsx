import { useState } from "react";
import type { Concept } from "../types/concept";
import { useI18n } from "../i18n";
import { ConceptContent } from "./ConceptContent";

// CandidateConceptCard shows one existing concept from either the deterministic
// exact-signature resolver or retrieval-only catalog discovery. The containing
// section communicates that provenance. Selecting the card creates no annotation;
// it only targets a later explicit SAME / DISTINCT / relation action. Expanding
// its contents (FLH-093) is a read of the Concept's current support, on demand.
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
  const [open, setOpen] = useState(false);
  const features = Object.entries(concept.identity_features ?? {});
  return (
    <div className={`candidate${selected ? " selected" : ""}`}>
      <div className="head">
        <strong className="concept-target">{concept.target}</strong>
        <span className={`tag ${concept.state}`}>{status(concept.state)}</span>
      </div>
      <p className="hint">
        {t("content.intentScope", { intent: concept.pedagogical_intent, scope: concept.scope || t("library.notSet") })}{" "}
        · {tn("candidate.heading", { id: <span className="mono">#{concept.id}</span> })}
      </p>
      <div className="actions">
        <button className={selected ? "primary" : "ghost"} onClick={onSelect} aria-pressed={selected}>
          {selected ? t("candidate.selected") : t("candidate.select")}
        </button>
        <button type="button" className="ghost" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? t("content.hide", { id: concept.id }) : t("content.show", { id: concept.id })}
        </button>
      </div>
      {open ? <ConceptContent conceptId={concept.id} /> : null}
      <details className="raw">
        <summary>{t("content.technical")}</summary>
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
      </details>
    </div>
  );
}
