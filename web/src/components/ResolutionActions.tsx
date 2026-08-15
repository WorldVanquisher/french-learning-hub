import type { CurrentMembership, RelationKind } from "../types/concept";

// The decision the reviewer is about to make. NEW is handled by the parent (it
// needs the edited identity); the rest act on a selected existing concept.
export type ActionKind = "same" | "new" | "broader" | "narrower" | "related" | "invalid";

// ResolutionActions renders the six human decisions as unmistakable buttons and
// routes SAME correctly: when the unit already has a current SAME membership and the
// reviewer picks a DIFFERENT concept, this is an explicit ReassignSame — never a
// create+seed reassignment path. The parent performs the request; this component
// only decides which decisions are currently valid and labels them clearly.
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
          className="invalid"
          disabled={busy || membership === null}
          onClick={() => onAct("invalid")}
          title="Mark the candidate invalid: clears any current SAME membership and records the rejection as evidence."
        >
          INVALID
        </button>
      </div>

      <p className="hint">
        {hasSelection
          ? "SAME / BROADER / NARROWER / RELATED act on the selected concept above."
          : "Select a concept above to enable SAME and the relation actions, or create a NEW CONCEPT."}
        {" "}
        BROADER / NARROWER / RELATED record a non-membership relation — they do not
        make the unit a SAME member. INVALID is enabled only when a current SAME
        membership exists to clear.
      </p>
    </div>
  );
}
