import type { CurrentMembership } from "../types/concept";
import { useI18n } from "../i18n";

// MembershipPanel shows the unit's CURRENT SAME membership, read exclusively from
// GET /knowledge-units/{id}/concept-membership. It is styled distinctly from the
// history panel because current authority and historical evidence must never be
// confused: a superseded event can still read status='accepted', but only this
// projection says what the unit belongs to NOW.
export function MembershipPanel({ membership }: { membership: CurrentMembership | null }) {
  const { t } = useI18n();
  if (!membership) {
    return (
      <div className="panel membership none">
        <h2>{t("membership.title")}</h2>
        <p className="value">
          <strong>{t("membership.none")}</strong> {t("membership.none.detail")}
        </p>
      </div>
    );
  }
  return (
    <div className="panel membership">
      <h2>{t("membership.authority")}</h2>
      <div className="field-row">
        <span className="label">{t("membership.conceptId")}</span>
        <span className="value mono">{membership.concept_id}</span>
      </div>
      <div className="field-row">
        <span className="label">{t("membership.linkId")}</span>
        <span className="value mono">{membership.link_id}</span>
      </div>
      <div className="field-row">
        <span className="label">{t("membership.updatedAt")}</span>
        <span className="value">{membership.updated_at}</span>
      </div>
      <p className="hint">{t("membership.hint")}</p>
    </div>
  );
}
