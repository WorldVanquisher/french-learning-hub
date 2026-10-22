import { useCallback, useEffect, useState, type ReactNode } from "react";
import * as api from "../api/client";
import { ApiError } from "../api/client";
import type { LibraryConcept, LibrarySource, LibraryUnit } from "../types/library";
import type { CurrentMembership } from "../types/concept";
import { useI18n } from "../i18n";
import { StoredText } from "./ExplanationText";

// FLH-093: read-only content views that make a membership decision readable.
// Every fact comes from the existing Knowledge Library read endpoints, which own
// derived support (current extraction + active admission + CURRENT SAME); the
// browser never decides what counts as support and never summarizes a Concept.
// Nothing here writes, and each read starts only when the reviewer asks for it
// (expanding, selecting, or opening a source).

// Number of supporting units rendered before "Show all"; the response itself is
// complete, and the count says how many are shown.
export const SUPPORT_PREVIEW = 3;

type Read<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "unavailable" }
  | { status: "error"; message: string };

// useRead reads one resource by ID. A response for an ID that is no longer
// requested (selection changed, panel closed, unmounted) is discarded, so a slow
// answer for an earlier candidate can never be shown for the current one.
function useRead<T>(id: number | null, read: (id: number) => Promise<T>): [Read<T> | null, () => void] {
  const [state, setState] = useState<{ id: number; read: Read<T> } | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (id === null) return;
    let active = true;
    setState({ id, read: { status: "loading" } });
    read(id).then(
      (data) => {
        if (active) setState({ id, read: { status: "ready", data } });
      },
      (e: unknown) => {
        if (!active) return;
        if (e instanceof ApiError && e.status === 404) setState({ id, read: { status: "unavailable" } });
        else setState({ id, read: { status: "error", message: e instanceof ApiError ? `(${e.status}) ${e.message}` : e instanceof Error ? e.message : String(e) } });
      },
    );
    return () => {
      active = false;
    };
  }, [id, read, attempt]);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  if (id === null) return [null, retry];
  return [state?.id === id ? state.read : { status: "loading" }, retry];
}

// A response without the fields rendered below is reported as a failed read,
// never rendered partially or allowed to break the review page.
const unexpected = () => new Error("unexpected response from the server");
const readConcept = async (id: number) => {
  const data = await api.getLibraryConcept(id);
  if (!data?.concept || !Array.isArray(data.supporting_units) || !Array.isArray(data.non_supporting_members) || !Array.isArray(data.historical_units)) throw unexpected();
  return data;
};
const readSource = async (id: number) => {
  const data = await api.getLibraryUnitSource(id);
  if (!data?.entry || !data.unit || !data.extraction) throw unexpected();
  return data;
};

// UnitSourceDisclosure opens a unit's original learning record inline, so the
// reviewer never leaves the page (position, selection and drafts are kept).
export function UnitSourceDisclosure({ unitId }: { unitId: number }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <div className="source-disclosure">
      <button type="button" className="ghost" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {open ? t("content.source.hide", { id: unitId }) : t("content.source.show", { id: unitId })}
      </button>
      {open ? <UnitSource unitId={unitId} /> : null}
    </div>
  );
}

function UnitSource({ unitId }: { unitId: number }) {
  const { t, tn } = useI18n();
  const [read, retry] = useRead<LibrarySource>(unitId, readSource);
  if (!read || read.status === "loading") return <p className="hint" role="status">{t("content.source.loading", { id: unitId })}</p>;
  if (read.status === "unavailable") return <p className="hint" role="status">{t("content.source.unavailable", { id: unitId })}</p>;
  if (read.status === "error") {
    return (
      <div className="banner error" role="alert">
        {t("content.source.failed", { id: unitId, message: read.message })}{" "}
        <button type="button" className="ghost" onClick={retry}>
          {t("common.retry")}
        </button>
      </div>
    );
  }
  const { entry, unit, extraction } = read.data;
  return (
    <section className="source-view" aria-label={t("content.source.region", { id: unitId })}>
      <p className="label">{t("content.source.record", { id: entry.id })}</p>
      <p className="french pre-wrap">{entry.original_input}</p>
      <p className="label">{t("record.originalContext")}</p>
      <p className="french pre-wrap">{entry.original_context || <em>{t("record.noContext")}</em>}</p>
      <p className="hint">
        {tn(unit.in_current_extraction ? "content.source.extraction.current" : "content.source.extraction.historical", {
          version: <>{extraction.version}</>,
          extractor: <span className="mono">{extraction.extractor}</span>,
        })}
      </p>
    </section>
  );
}

// EvidenceItem shows one unit's knowledge statement first, then its example and
// provenance, with its original record one click away.
function EvidenceItem({ unit, note }: { unit: LibraryUnit; note?: ReactNode }) {
  const { t, status } = useI18n();
  return (
    <li className="evidence-item">
      <p className="french statement">
        <StoredText primary={unit.statement} variants={unit.statements} kind="statement" />
      </p>
      {unit.example ? (
        <p className="french">
          <span className="label">{t("content.example")}</span> {unit.example}
        </p>
      ) : null}
      {note ? <p className="hint">{note}</p> : null}
      <p className="hint">
        {t("content.unitMeta", {
          id: unit.unit_id,
          kind: unit.kind,
          record: unit.entry_id,
          version: unit.extraction_version,
          admission: status(unit.admission),
        })}
      </p>
      <UnitSourceDisclosure key={unit.unit_id} unitId={unit.unit_id} />
    </li>
  );
}

// ConceptContent shows what one Concept currently contains: identity, the
// preferred representative unit if one was chosen, and the backend-derived
// current support. Filed-but-not-supporting and historical units are counted,
// never shown as support. Technical identity is available but collapsed.
export function ConceptContent({ conceptId }: { conceptId: number }) {
  const { t, status } = useI18n();
  const [read, retry] = useRead<LibraryConcept>(conceptId, readConcept);
  const [showAll, setShowAll] = useState(false);
  if (!read || read.status === "loading") {
    return <p className="hint" role="status">{t("content.loading", { id: conceptId })}</p>;
  }
  if (read.status === "unavailable") {
    return <p className="hint" role="status">{t("content.unavailable", { id: conceptId })}</p>;
  }
  if (read.status === "error") {
    return (
      <div className="banner error" role="alert">
        {t("content.failed", { id: conceptId, message: read.message })}{" "}
        <button type="button" className="ghost" onClick={retry}>
          {t("common.retry")}
        </button>
      </div>
    );
  }
  const data = read.data;
  const c = data.concept;
  const preferred = data.preferred_unit;
  const preferredSupports = preferred !== null && data.supporting_units.some((u) => u.unit_id === preferred.unit_id);
  // The preferred unit is shown once, above the rest of the support.
  const others = data.supporting_units.filter((u) => u.unit_id !== preferred?.unit_id);
  const shown = showAll ? others : others.slice(0, SUPPORT_PREVIEW);
  const features = Object.entries(c.identity_features ?? {});
  return (
    <section className="concept-content" aria-label={t("content.region", { id: c.id })}>
      <p className="concept-target">{c.target}</p>
      <p className="hint">
        {t("content.intentScope", { intent: c.pedagogical_intent, scope: c.scope || t("library.notSet") })}
      </p>
      <p>
        <span className={`tag ${c.state}`}>{status(c.state)}</span>{" "}
        {c.state === "retired"
          ? t("content.support.retired")
          : data.supporting_units.length === 0
            ? t("content.support.none")
            : t("content.support.count", { count: data.supporting_units.length })}
      </p>

      {preferred ? (
        <div className="content-block">
          <h4>{t("content.preferred")}</h4>
          <ul className="evidence-list">
            <EvidenceItem
              unit={preferred}
              note={preferredSupports ? t("content.preferred.supporting") : t("content.preferred.notSupporting")}
            />
          </ul>
        </div>
      ) : null}

      {data.supporting_units.length > 0 && (others.length > 0 || !preferred) ? (
        <div className="content-block">
          <h4>{preferred && preferredSupports ? t("content.support.otherTitle") : t("content.support.title")}</h4>
          <ul className="evidence-list">
            {shown.map((u) => (
              <EvidenceItem key={u.unit_id} unit={u} />
            ))}
          </ul>
          {others.length > SUPPORT_PREVIEW ? (
            <p className="hint">
              {showAll
                ? t("content.support.allShown", { total: others.length })
                : t("content.support.showing", { shown: shown.length, total: others.length })}{" "}
              <button type="button" className="ghost" onClick={() => setShowAll((s) => !s)}>
                {showAll ? t("content.support.showFewer") : t("content.support.showAll", { total: others.length })}
              </button>
            </p>
          ) : null}
        </div>
      ) : null}

      {data.non_supporting_members.length > 0 ? (
        <p className="hint">{t("content.notSupporting", { count: data.non_supporting_members.length })}</p>
      ) : null}
      {data.historical_units.length > 0 ? (
        <p className="hint">{t("content.history", { count: data.historical_units.length })}</p>
      ) : null}

      <details className="raw">
        <summary>{t("content.technical")}</summary>
        <div className="field-row">
          <span className="label">concept id</span>
          <span className="value mono">{c.id}</span>
        </div>
        <div className="field-row">
          <span className="label">{t("candidate.lifecycleSupport")}</span>
          <span className="value">
            {status(c.lifecycle_state)} / {status(c.support_state)}
          </span>
        </div>
        <div className="field-row">
          <span className="label">identity_features</span>
          <span className="value">
            {features.length === 0 ? <em>{t("common.none")}</em> : features.map(([k, v]) => (
              <span key={k} className="mono" style={{ marginRight: 6 }}>
                {k}={v}
              </span>
            ))}
          </span>
        </div>
        <div className="field-row">
          <span className="label">signature</span>
          <span className="value mono">{c.signature}</span>
        </div>
      </details>
    </section>
  );
}

// MembershipComparison shows the selected Concept's current content beside the
// incoming unit (the unit card is the neighbouring column, so its text is not
// repeated) and states what SAME and NEW CONCEPT do before either is sent. It
// reads only; the decision buttons stay in ResolutionActions.
export function MembershipComparison({
  conceptId,
  membership,
}: {
  conceptId: number | null;
  membership: CurrentMembership | null;
}) {
  const { t } = useI18n();
  return (
    <section className="panel comparison" aria-label={t("compare.region")}>
      <h2>{t("compare.title")}</h2>
      {conceptId === null ? (
        <p className="hint">{t("compare.none")}</p>
      ) : (
        <>
          <h3>{t("compare.concept", { id: conceptId })}</h3>
          <ConceptContent key={conceptId} conceptId={conceptId} />
          <p className="hint">
            {membership !== null && membership.concept_id !== conceptId
              ? t("compare.reassignMeaning", { from: membership.concept_id, to: conceptId })
              : t("compare.sameMeaning", { id: conceptId })}
          </p>
        </>
      )}
      <p className="hint">{t("compare.newMeaning")}</p>
    </section>
  );
}
