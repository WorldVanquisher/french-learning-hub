import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api/client";
import { ApiError } from "../api/client";
import type { UnitTarget } from "../navigation";
import { InspectorItem } from "./AnnotationInspector";
import { UnitCorrections, type ConceptCatalog } from "./UnitCorrections";
import type { Inspection } from "./unitCorrection";
import { useI18n } from "../i18n";

type Load<T> =
  | { status: "loading" }
  | { status: "error"; message: string; notFound: boolean }
  | { status: "ready"; data: T };

function describeError(error: unknown): string {
  if (error instanceof ApiError) return `(${error.status}) ${error.message}`;
  return error instanceof Error ? error.message : String(error);
}

// UnitInspection shows one unit opened from a record: its backend-derived
// effective annotation and whether the unit belongs to the record's current
// extraction, as the backend reports both now. Opening it records nothing. Stored
// labels of a historical unit are shown for reference only, never as a review or
// correction candidate. A current-extraction unit that was already reviewed (CURRENT
// SAME or INVALID) can be corrected through explicit, confirmed actions.
export function UnitInspection({
  focus,
  onBack,
  onReview,
}: {
  focus: UnitTarget;
  onBack: () => void;
  onReview: () => void;
}) {
  const { t } = useI18n();
  const [load, setLoad] = useState<Load<Inspection>>({ status: "loading" });
  const [catalog, setCatalog] = useState<ConceptCatalog>({ status: "loading" });
  const [reloadCount, setReloadCount] = useState(0);
  const [catalogCount, setCatalogCount] = useState(0);
  const [writing, setWriting] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  // Only the latest inspection read is applied, and none after leaving the view.
  const readRequest = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  const readInspection = useCallback(
    () =>
      Promise.all([api.getEffectiveAnnotation(focus.unitId), api.getCurrentExtraction(focus.entryId)]).then(
        ([item, current]): Inspection => ({ item, current }),
      ),
    [focus.unitId, focus.entryId],
  );

  useEffect(() => {
    const request = ++readRequest.current;
    setLoad({ status: "loading" });
    readInspection()
      .then((data) => {
        if (mounted.current && request === readRequest.current) setLoad({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (!mounted.current || request !== readRequest.current) return;
        setLoad({
          status: "error",
          message: describeError(error),
          notFound: error instanceof ApiError && error.isNotFound,
        });
      });
  }, [readInspection, reloadCount]);

  // refresh re-reads the inspection for a correction and shows it. A read that a
  // newer one superseded resolves null; a failed read keeps what is shown and
  // rejects, so the caller can report it.
  const refresh = useCallback(async (): Promise<Inspection | null> => {
    const request = ++readRequest.current;
    const data = await readInspection();
    if (!mounted.current || request !== readRequest.current) return null;
    setLoad({ status: "ready", data });
    return data;
  }, [readInspection]);

  // Concept names are a convenience for reading; references stay visible by ID
  // without them. A reassignment target can only be chosen from a loaded catalog.
  useEffect(() => {
    let active = true;
    setCatalog({ status: "loading" });
    api.listConcepts()
      .then((concepts) => {
        if (active) setCatalog({ status: "ready", concepts });
      })
      .catch((error: unknown) => {
        if (active) setCatalog({ status: "error", message: describeError(error) });
      });
    return () => {
      active = false;
    };
  }, [catalogCount]);

  const conceptsById = useMemo(
    () => new Map(catalog.status === "ready" ? catalog.concepts.map((c) => [c.id, c]) : []),
    [catalog],
  );

  return (
    <main>
      <section className="panel record-context" aria-label={t("focus.context")}>
        <h2 ref={headingRef} tabIndex={-1}>
          {t("inspection.heading", { unit: focus.unitId, record: focus.entryId })}
        </h2>
        <p className="hint">{t("inspection.hint")}</p>
        <button type="button" className="ghost" onClick={onBack} disabled={writing}>
          {t("focus.back", { id: focus.entryId })}
        </button>
      </section>

      {load.status === "loading" ? (
        <div className="empty">{t("inspection.loading")}</div>
      ) : load.status === "error" ? (
        <div className="banner error" role="alert">
          {load.notFound
            ? t("inspection.notFound", { id: focus.unitId })
            : t("inspection.failed", { id: focus.unitId, message: load.message })}{" "}
          {!load.notFound ? (
            <button type="button" className="ghost" onClick={() => setReloadCount((n) => n + 1)}>
              {t("common.retry")}
            </button>
          ) : null}
        </div>
      ) : (
        <>
          <Currency inspection={load.data} focus={focus} onReview={onReview} />
          <InspectorItem item={load.data.item} concepts={conceptsById} />
          {/* A correction's re-read replaces only the data, so this stays mounted
              and its outcome stays visible. */}
          <UnitCorrections
            inspection={load.data}
            catalog={catalog}
            onReloadCatalog={() => setCatalogCount((n) => n + 1)}
            refresh={refresh}
            onPendingChange={setWriting}
          />
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
  const { t, status } = useI18n();
  const { item, current } = inspection;
  const mode = status(current.selection_mode);
  if (current.current_extraction_id === null) {
    return <div className="banner info">{t("currency.none", { mode })}</div>;
  }
  if (item.unit.extraction_id !== current.current_extraction_id) {
    return (
      <div className="banner info" aria-label={t("currency.region")}>
        <strong>{t("currency.historical")}</strong>{" "}
        {t("currency.historical.detail", { unitExtraction: item.unit.extraction_id, current: current.current_extraction_id, mode })}
      </div>
    );
  }
  const unresolved = item.snapshot.status === "unresolved";
  return (
    <div className="banner info" aria-label={t("currency.region")}>
      {t("currency.current", { mode })}
      {item.unit.extraction_id !== focus.extractionId ? <>{" "}{t("currency.changed")}</> : null}
      {unresolved ? (
        <>
          {" "}{t("currency.unresolved")}{" "}
          <button type="button" className="ghost" onClick={onReview}>
            {t("currency.openReview", { id: item.unit.id })}
          </button>
        </>
      ) : (
        <>{" "}{t("currency.notAwaiting", { status: status(item.snapshot.status) })}</>
      )}
    </div>
  );
}
