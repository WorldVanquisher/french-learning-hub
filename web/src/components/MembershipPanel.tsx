import type { CurrentMembership } from "../types/concept";

// MembershipPanel shows the unit's CURRENT SAME membership, read exclusively from
// GET /knowledge-units/{id}/concept-membership. It is styled distinctly from the
// history panel because current authority and historical evidence must never be
// confused: a superseded event can still read status='accepted', but only this
// projection says what the unit belongs to NOW.
export function MembershipPanel({ membership }: { membership: CurrentMembership | null }) {
  if (!membership) {
    return (
      <div className="panel membership none">
        <h2>Current membership</h2>
        <p className="value">
          <strong>No current SAME membership.</strong> This unit belongs to no
          concept right now — it is unresolved (or was explicitly marked invalid).
        </p>
      </div>
    );
  }
  return (
    <div className="panel membership">
      <h2>Current membership (authority)</h2>
      <div className="field-row">
        <span className="label">concept id</span>
        <span className="value mono">{membership.concept_id}</span>
      </div>
      <div className="field-row">
        <span className="label">in-force link id</span>
        <span className="value mono">{membership.link_id}</span>
      </div>
      <div className="field-row">
        <span className="label">updated at</span>
        <span className="value">{membership.updated_at}</span>
      </div>
      <p className="hint">
        Read from the current-membership projection, not inferred from the event
        history below.
      </p>
    </div>
  );
}
