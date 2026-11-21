import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import * as api from "../api/client";
import { ApiError } from "../api/client";
import { useI18n, type MessageKey } from "../i18n";
import type { KindConcept, KindConcepts, KindView } from "../types/notebook";

// The Grammar / Vocabulary / Unclassified views (concept_kind_view_v1) over
// active Concepts, moved out of MistakeNotebook.tsx unchanged so the Vocabulary
// page can reuse it with a Save action on each row.

type Load<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: T };
const describe = (e: unknown) =>
  e instanceof ApiError
    ? `(${e.status}) ${e.message}`
    : e instanceof Error
      ? e.message
      : String(e);

const reasonKey: Record<
  "no_supporting_unit" | "mixed_kinds" | "other_kind",
  MessageKey
> = {
  no_supporting_unit: "notebook.kinds.reason.no_supporting_unit",
  mixed_kinds: "notebook.kinds.reason.mixed_kinds",
  other_kind: "notebook.kinds.reason.other_kind",
};
const kindHint: Record<KindView, MessageKey> = {
  grammar: "notebook.kinds.grammarHint",
  vocabulary: "notebook.kinds.vocabularyHint",
  unclassified: "notebook.kinds.unclassifiedHint",
};

export function ConceptKinds({
  kind,
  onOpenConcept,
  rowAction,
  filter,
  filterControl,
  openId,
}: {
  kind: KindView;
  onOpenConcept?: (conceptId: number) => void;
  // Vocabulary (Workbooks): an extra control on each row (Save), an optional
  // row filter (saved only) and the control that switches it. Other views pass none.
  rowAction?: (c: KindConcept) => ReactNode;
  filter?: (c: KindConcept) => boolean;
  filterControl?: ReactNode;
  // Vocabulary: a stable id for each row's open control (the shell returns focus to it).
  openId?: (c: KindConcept) => string;
}) {
  const { t, tp } = useI18n();
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [state, setState] = useState<Load<KindConcepts>>({ status: "loading" });
  useEffect(() => {
    let active = true;
    setState({ status: "loading" });
    api.getKindConcepts(kind, query).then(
      (data) => active && setState({ status: "ready", data }),
      (e: unknown) =>
        active && setState({ status: "error", message: describe(e) }),
    );
    return () => {
      active = false;
    };
  }, [kind, query]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setQuery(text);
  };
  return (
    <section
      className="panel"
      aria-label={t("notebook.kinds.region", {
        kind: t(`notebook.mode.${kind}` as MessageKey),
      })}
    >
      <h2>{t(`notebook.mode.${kind}` as MessageKey)}</h2>
      <p className="hint">{t(kindHint[kind])}</p>
      <form
        className="actions"
        onSubmit={submit}
        role="search"
        aria-label={t("notebook.kinds.search")}
      >
        <input
          type="search"
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-label={t("notebook.kinds.search")}
        />
        <button type="submit">{t("notebook.kinds.searchButton")}</button>
      </form>
      {state.status === "loading" ? (
        <p className="hint" role="status">
          {t("notebook.loading")}
        </p>
      ) : state.status === "error" ? (
        <div className="banner error" role="alert">
          {t("notebook.kinds.failed", { message: state.message })}
        </div>
      ) : null}
      {filterControl}
      {state.status !== "ready" ? null : state.data.concepts.length === 0 ? (
        <p className="empty">{t("notebook.kinds.empty")}</p>
      ) : (
        <>
          <p className="hint" role="status">
            {tp("notebook.kinds.count", state.data.concepts.length)}{" "}
            {t("notebook.kinds.classified", { n: state.data.classified })}
            {state.data.truncated ? ` ${t("notebook.kinds.truncated")}` : ""}
          </p>
          <ul className="listening-list">
            {state.data.concepts
              .filter((c) => !filter || filter(c))
              .map((c) => (
                <li key={c.concept_id}>
                  {onOpenConcept ? (
                    <button
                      type="button"
                      className="link-button"
                      id={openId?.(c)}
                      onClick={() => onOpenConcept(c.concept_id)}
                    >
                      {c.target}
                    </button>
                  ) : (
                    c.target
                  )}{" "}
                  <span className="hint">
                    {t("notebook.kinds.meta", {
                      id: c.concept_id,
                      intent: c.pedagogical_intent,
                      units: c.supporting_unit_count,
                    })}
                  </span>{" "}
                  {c.kinds.map((k) => (
                    <span key={k} className="tag">
                      {k}
                    </span>
                  ))}{" "}
                  {c.reason ? (
                    <span className="hint">{t(reasonKey[c.reason])}</span>
                  ) : null}
                  {rowAction ? rowAction(c) : null}
                </li>
              ))}
          </ul>
        </>
      )}
    </section>
  );
}
