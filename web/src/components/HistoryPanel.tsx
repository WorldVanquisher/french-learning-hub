import { useState } from "react";
import type { UnitConceptLink } from "../types/concept";

// HistoryPanel is a secondary, collapsible view of the append-only resolution
// events for the selected concept/unit. It exists for debugging and research value:
// so we can later inspect WHY the dataset contains a given label. It is not required
// to be visually polished. It never implies current authority — that lives in the
// MembershipPanel.
export function HistoryPanel({
  title,
  links,
  loading,
  unitId,
}: {
  title: string;
  links: UnitConceptLink[];
  loading?: boolean;
  unitId?: number;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="panel history">
      <h2 style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>Resolution history</span>
        <button className="ghost" onClick={() => setOpen((v) => !v)} style={{ padding: "2px 10px" }}>
          {open ? "hide" : "show"}
        </button>
      </h2>
      <p className="hint">{title}</p>
      {open ? (
        loading ? (
          <p className="value">Loading history…</p>
        ) : links.length === 0 ? (
          <p className="value">
            <em>No resolution events recorded yet.</em>
          </p>
        ) : (
          <ul className="history-list">
            {links.map((l) => {
              // Highlight this unit's own events when a unitId is provided.
              const mine = unitId !== undefined && l.unit_id === unitId;
              const relClass = l.status === "rejected" ? "rejected" : l.relation;
              return (
                <li key={l.id} style={mine ? { background: "#faf5ff" } : undefined}>
                  <div className="row1">
                    <span className={`rel ${relClass}`}>
                      {l.relation}
                      {l.status === "rejected" ? " (INVALID)" : ""}
                    </span>
                    <span className="st">status={l.status}</span>
                    <span className="st">src={l.decision_source}</span>
                    {l.score !== null ? <span className="st">score={l.score}</span> : null}
                  </div>
                  <div className="row1">
                    <span className="st">link #{l.id}</span>
                    <span className="st">unit {l.unit_id}</span>
                    <span className="st">concept {l.concept_id}</span>
                    <span className="st">resolver {l.resolver_version}</span>
                    {l.supersedes_link_id !== null ? (
                      <span className="st">supersedes #{l.supersedes_link_id}</span>
                    ) : null}
                  </div>
                  <div className="row1">
                    <span className="st">{l.created_at}</span>
                  </div>
                </li>
              );
            })}
          </ul>
        )
      ) : null}
    </div>
  );
}
