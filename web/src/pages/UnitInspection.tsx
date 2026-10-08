import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api/client";
import { ApiError } from "../api/client";
import type { Concept, EffectiveAnnotationItem } from "../types/concept";
import type { CurrentExtraction } from "../types/learning";
import type { UnitTarget } from "../navigation";
import { InspectorItem } from "./AnnotationInspector";

type Load<T> =
  | { status: "loading" }
  | { status: "error"; message: string; notFound: boolean }
  | { status: "ready"; data: T };

type Inspection = { item: EffectiveAnnotationItem; current: CurrentExtraction };

function describeError(error: unknown): string {
  if (error instanceof ApiError) return `(${error.status}) ${error.message}`;
  return error instanceof Error ? error.message : String(error);
}

// UnitInspection is a GET-only view of one unit opened from a record. It shows
// the unit's backend-derived effective annotation and whether the unit belongs to
// the record's current extraction, as the backend reports both now. Stored labels
// of a historical unit are shown only for reference, never as a review candidate.
export function UnitInspection({
  focus,
  onBack,
  onReview,
}: {
  focus: UnitTarget;
  onBack: () => void;
  onReview: () => void;
}) {
  const [load, setLoad] = useState<Load<Inspection>>({ status: "loading" });
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [reloadCount, setReloadCount] = useState(0);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  useEffect(() => {
    let active = true;
    setLoad({ status: "loading" });
    Promise.all([api.getEffectiveAnnotation(focus.unitId), api.getCurrentExtraction(focus.entryId)])
      .then(([item, current]) => {
        if (active) setLoad({ status: "ready", data: { item, current } });
      })
      .catch((error: unknown) => {
        if (!active) return;
        setLoad({
          status: "error",
          message: describeError(error),
          notFound: error instanceof ApiError && error.isNotFound,
        });
      });
    // Concept names are a convenience; references stay visible by ID without them.
    api.listConcepts()
      .then((loaded) => {
        if (active) setConcepts(loaded);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [focus.unitId, focus.entryId, reloadCount]);

  const conceptsById = useMemo(() => new Map(concepts.map((c) => [c.id, c])), [concepts]);

  return (
    <main>
      <section className="panel record-context" aria-label="Record context">
        <h2 ref={headingRef} tabIndex={-1}>
          Unit #{focus.unitId} from record #{focus.entryId}
        </h2>
        <p className="hint">Read-only inspection. Opening this view records nothing.</p>
        <button type="button" className="ghost" onClick={onBack}>
          ← Back to record #{focus.entryId}
        </button>
      </section>

      {load.status === "loading" ? (
        <div className="empty">Loading the unit&apos;s annotation…</div>
      ) : load.status === "error" ? (
        <div className="banner error" role="alert">
          {load.notFound
            ? `Unit #${focus.unitId} was not found on the server. Return to the record and reload its extractions.`
            : `Could not load unit #${focus.unitId}: ${load.message}`}{" "}
          {!load.notFound ? (
            <button type="button" className="ghost" onClick={() => setReloadCount((n) => n + 1)}>
              Retry
            </button>
          ) : null}
        </div>
      ) : (
        <>
          <Currency inspection={load.data} focus={focus} onReview={onReview} />
          <InspectorItem item={load.data.item} concepts={conceptsById} />
        </>
      )}
    </main>
  );
}

function Currency({
  inspection,
  focus,
  onReview,
}: {
  inspection: Inspection;
  focus: UnitTarget;
  onReview: () => void;
}) {
  const { item, current } = inspection;
  const mode = current.selection_mode;
  if (current.current_extraction_id === null) {
    return (
      <div className="banner info">
        The record has no current extraction ({mode} selection), so this unit is not reviewable and
        gives no concept support. Its stored labels are shown for reference.
      </div>
    );
  }
  if (item.unit.extraction_id !== current.current_extraction_id) {
    return (
      <div className="banner info" aria-label="Unit currency">
        <strong>Historical unit.</strong> It belongs to extraction #{item.unit.extraction_id}, which is not
        the record&apos;s current extraction (#{current.current_extraction_id}, {mode} selection). Its stored
        labels are shown for reference; it is not reviewable and gives no concept support while another
        version is current.
      </div>
    );
  }
  const unresolved = item.snapshot.status === "unresolved";
  return (
    <div className="banner info" aria-label="Unit currency">
      This unit belongs to the record&apos;s current extraction ({mode} selection).
      {item.unit.extraction_id !== focus.extractionId
        ? " The current extraction changed since the record was shown; return to the record and reload it."
        : null}
      {unresolved ? (
        <>
          {" "}It has no current SAME membership and is not INVALID.{" "}
          <button type="button" className="ghost" onClick={onReview}>
            Open unit #{item.unit.id} in Concept Review
          </button>
        </>
      ) : (
        ` It is ${item.snapshot.status}, so it is not awaiting review.`
      )}
    </div>
  );
}
