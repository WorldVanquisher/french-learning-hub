import { useEffect, useRef, useState, type ReactNode } from "react";
import { useI18n, type Msg } from "../i18n";

// Outcome of one explicit write request, shown next to the action. It describes
// only the write; re-reading stored state afterwards is a separate RefreshState.
// - succeeded: the server confirmed the write.
// - rejected: the server answered with an error, so it reported the write as not
//   performed.
// - uncertain: no response arrived, so the write may or may not have happened.
// `text` is rendered in the current locale, so a banner shown before a language
// switch follows it; raw server details inside it are never translated.
export type Outcome =
  | { kind: "succeeded"; text: Msg }
  | { kind: "rejected"; text: Msg }
  | { kind: "uncertain"; text: Msg };

const outcomeClass: Record<Outcome["kind"], string> = {
  succeeded: "banner success",
  rejected: "banner error",
  uncertain: "banner info",
};

export function OutcomeBanner({ outcome }: { outcome: Outcome | null }) {
  const { t, render } = useI18n();
  if (!outcome) return null;
  return (
    <div className={outcomeClass[outcome.kind]} role={outcome.kind === "succeeded" ? "status" : "alert"}>
      {outcome.kind === "uncertain" ? <strong>{t("outcome.unknown")}</strong> : null}
      {render(outcome.text)}
    </div>
  );
}

const capitalizeFirst = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

// RefreshState tracks the GET that re-reads stored state after a write. Until it
// succeeds the UI must not claim that what it shows reflects the write.
export type RefreshState =
  | { kind: "idle" }
  | { kind: "refreshing" }
  | { kind: "refreshed" }
  | { kind: "failed"; message: string };

// RefreshBanner reports the post-write re-read separately from the write outcome.
// `what` names the re-read data (a noun phrase) in the current locale.
export function RefreshBanner({ refresh, what }: { refresh: RefreshState; what: Msg }) {
  const { t, render } = useI18n();
  const noun = String(render(what) ?? "");
  switch (refresh.kind) {
    case "idle":
      return null;
    case "refreshing":
      return (
        <p className="hint" role="status">
          {t("refresh.refreshing", { what: noun })}
        </p>
      );
    case "refreshed":
      return (
        <p className="hint" role="status">
          {capitalizeFirst(t("refresh.refreshed", { what: noun }))}
        </p>
      );
    case "failed":
      return (
        <div className="banner error" role="alert">
          {t("refresh.failed", { what: noun, message: refresh.message })}
        </div>
      );
  }
}

// ExplicitAction is a two-step write control. The first button only reveals what
// the request will do; the request is sent once, by the confirm button. While it
// is pending the control is disabled, and a synchronous guard also drops a second
// confirm that arrives before React re-renders. Nothing is ever retried
// automatically.
export function ExplicitAction({
  label,
  confirmLabel,
  explanation,
  pending,
  disabledReason,
  onConfirm,
}: {
  label: string;
  confirmLabel: string;
  explanation: ReactNode;
  pending: boolean;
  // When set, the action stays unavailable and this explains why (for example,
  // an unknown outcome that has not been checked against stored state yet).
  disabledReason?: string | null;
  onConfirm: () => Promise<void>;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const inFlight = useRef(false);
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) confirmRef.current?.focus();
  }, [open]);

  async function confirm() {
    if (inFlight.current) return;
    inFlight.current = true;
    setOpen(false);
    try {
      await onConfirm();
    } finally {
      inFlight.current = false;
    }
  }

  if (!open || disabledReason) {
    return (
      <>
        <button type="button" className="ghost" disabled={pending || Boolean(disabledReason)} onClick={() => setOpen(true)}>
          {pending ? t("action.waiting", { label }) : t("action.open", { label })}
        </button>
        {disabledReason && !pending ? <p className="hint">{disabledReason}</p> : null}
      </>
    );
  }

  return (
    <div className="explicit-action" role="group" aria-label={label}>
      <div className="hint explicit-action-explanation">{explanation}</div>
      <div className="actions">
        <button ref={confirmRef} type="button" className="primary" disabled={pending} onClick={() => void confirm()}>
          {confirmLabel}
        </button>
        <button type="button" className="ghost" onClick={() => setOpen(false)}>
          {t("common.cancel")}
        </button>
      </div>
    </div>
  );
}
