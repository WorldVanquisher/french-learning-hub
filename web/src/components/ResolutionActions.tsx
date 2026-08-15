import type { CurrentMembership, RelationKind } from "../types/concept";

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
export function ResolutionActions({
  membership,
  selectedConceptId,
  busy,
  onAct,
}: {
  membership: CurrentMembership | null;
  selectedConceptId: number | null;
  busy: boolean;
  onAct: (action: ActionKind) => void;
}) {
  const hasSelection = selectedConceptId !== null;
  const alreadyMember =
    membership !== null && selectedConceptId !== null && membership.concept_id === selectedConceptId;

  // SAME label reflects whether this will establish or move a membership.
  const sameLabel = membership
    ? alreadyMember
      ? "SAME (already current)"
      : "REASSIGN SAME → selected"
    : "SAME → selected";

  const relation = (kind: RelationKind) => (
    <button className="ghost" disabled={busy || !hasSelection} onClick={() => onAct(kind)}>
      {kind.toUpperCase()}
    </button>
  );

  return (
    <div className="panel">
      <h2>Human decision</h2>
      <div className="actions">
        <button
          className="same"
          disabled={busy || !hasSelection || alreadyMember}
          onClick={() => onAct("same")}
          title={
            membership
              ? "Move this unit's current SAME membership to the selected concept (ReassignSame)."
              : "Resolve this unresolved unit SAME to the selected concept."
          }
        >
          {sameLabel}
        </button>

        <button
          className="primary"
          disabled={busy}
          onClick={() => onAct("new")}
          title="Create a new concept from the edited identity; seeds SAME only when the unit is unresolved."
        >
          NEW CONCEPT
        </button>

        {relation("broader")}
        {relation("narrower")}
        {relation("related")}

        <button
          className="ghost"
          disabled={busy || !hasSelection}
          onClick={() => onAct("distinct")}
          title="Record that this unit is NOT the same learning identity as the selected concept (an explicit negative pair). Does not create or change SAME membership; the unit stays reviewable."
        >
          DISTINCT
        </button>

        <button
          className="invalid"
          disabled={busy}
          onClick={() => onAct("invalid")}
          title="Mark this KnowledgeUnit an invalid candidate for concept resolution. Works for a freshly unresolved unit and also clears any current SAME membership."
        >
          INVALID
        </button>
      </div>

      <p className="hint">
        {hasSelection
          ? "SAME / BROADER / NARROWER / RELATED / DISTINCT act on the selected concept above."
          : "Select a concept above to enable SAME, the relation actions, and DISTINCT, or create a NEW CONCEPT."}
        {" "}
        BROADER / NARROWER / RELATED record a non-membership relation and DISTINCT
        records an explicit negative pair — none of these make the unit a SAME member,
        and all keep it reviewable. INVALID is always available: it marks the unit
        itself an invalid candidate (clearing any current SAME membership) and removes
        it from the queue.
      </p>
    </div>
  );
}
