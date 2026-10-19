import type { CurrentMembership, RelationKind } from "../types/concept";
import { useI18n } from "../i18n";

// The decision the reviewer is about to make. NEW is handled by the parent (it
// needs the edited identity); SAME / relations / DISTINCT act on a selected existing
// concept; INVALID is a unit-level judgment that needs no selection.
export type ActionKind =
  | "same"
  | "new"
  | "broader"
  | "narrower"
  | "related"
  | "distinct"
  | "invalid";

// ResolutionActions renders the human decisions as unmistakable buttons and routes
// SAME correctly: when the unit already has a current SAME membership and the reviewer
// picks a DIFFERENT concept, this is an explicit ReassignSame — never a create+seed
// reassignment path. INVALID is a unit-level judgment (available for a freshly
// unresolved unit, not gated on membership); DISTINCT records an explicit negative
// pair against the selected concept without changing membership. The parent performs
// the request; this component only decides which decisions are currently valid.
// keyedUnavailable disables the keyed decisions (relations and DISTINCT) when the
// browser cannot keep their operation keys; SAME, NEW CONCEPT and INVALID are unkeyed.
export function ResolutionActions({
  membership,
  selectedConceptId,
  busy,
  keyedUnavailable = false,
  onAct,
}: {
  membership: CurrentMembership | null;
  selectedConceptId: number | null;
  busy: boolean;
  keyedUnavailable?: boolean;
  onAct: (action: ActionKind) => void;
}) {
  const { t } = useI18n();
  const hasSelection = selectedConceptId !== null;
  const alreadyMember =
    membership !== null && selectedConceptId !== null && membership.concept_id === selectedConceptId;

  // SAME label reflects whether this will establish or move a membership.
  const sameLabel = membership
    ? alreadyMember
      ? t("resolution.same.current")
      : t("resolution.same.reassign")
    : t("resolution.same.selected");

  const relation = (kind: RelationKind) => (
    <button className="ghost" disabled={busy || keyedUnavailable || !hasSelection} onClick={() => onAct(kind)}>
      {kind.toUpperCase()}
    </button>
  );

  return (
    <div className="panel">
      <h2>{t("resolution.title")}</h2>
      <div className="actions">
        <button
          className="same"
          disabled={busy || !hasSelection || alreadyMember}
          onClick={() => onAct("same")}
          title={membership ? t("resolution.same.reassign.title") : t("resolution.same.title")}
        >
          {sameLabel}
        </button>

        <button
          className="primary"
          disabled={busy}
          onClick={() => onAct("new")}
          title={t("resolution.new.title")}
        >
          NEW CONCEPT
        </button>

        {relation("broader")}
        {relation("narrower")}
        {relation("related")}

        <button
          className="ghost"
          disabled={busy || keyedUnavailable || !hasSelection}
          onClick={() => onAct("distinct")}
          title={t("resolution.distinct.title")}
        >
          DISTINCT
        </button>

        <button
          className="invalid"
          disabled={busy}
          onClick={() => onAct("invalid")}
          title={t("resolution.invalid.title")}
        >
          INVALID
        </button>
      </div>

      <p className="hint">
        {hasSelection ? t("resolution.hint.selected") : t("resolution.hint.unselected")}{" "}
        {t("resolution.hint.rules")}
        {keyedUnavailable ? <>{" "}{t("resolution.hint.keyedDisabled")}</> : null}
      </p>
    </div>
  );
}
