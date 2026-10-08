import { useEffect, useRef, useState, type ReactNode } from "react";

// Outcome of one explicit write request, shown next to the action. It describes
// only the write; re-reading stored state afterwards is a separate RefreshState.
// - succeeded: the server confirmed the write.
// - rejected: the server answered with an error, so it reported the write as not
//   performed.
// - uncertain: no response arrived, so the write may or may not have happened.
export type Outcome =
  | { kind: "succeeded"; text: ReactNode }
  | { kind: "rejected"; text: ReactNode }
  | { kind: "uncertain"; text: ReactNode };

const outcomeClass: Record<Outcome["kind"], string> = {
  succeeded: "banner success",
  rejected: "banner error",
  uncertain: "banner info",
};

export function OutcomeBanner({ outcome }: { outcome: Outcome | null }) {
  if (!outcome) return null;
  return (
    <div className={outcomeClass[outcome.kind]} role={outcome.kind === "succeeded" ? "status" : "alert"}>
      {outcome.kind === "uncertain" ? <strong>Outcome unknown. </strong> : null}
      {outcome.text}
    </div>
  );
}

// RefreshState tracks the GET that re-reads stored state after a write. Until it
// succeeds the UI must not claim that what it shows reflects the write.
export type RefreshState =
  | { kind: "idle" }
  | { kind: "refreshing" }
  | { kind: "refreshed" }
  | { kind: "failed"; message: string };

// RefreshBanner reports the post-write re-read separately from the write outcome.
export function RefreshBanner({ refresh, what }: { refresh: RefreshState; what: string }) {
  switch (refresh.kind) {
    case "idle":
      return null;
    case "refreshing":
      return (
        <p className="hint" role="status">
          Re-reading {what} from the server…
        </p>
      );
    case "refreshed":
      return (
        <p className="hint" role="status">
          {what.charAt(0).toUpperCase() + what.slice(1)} re-read from the server.
        </p>
      );
    case "failed":
      return (
        <div className="banner error" role="alert">
          Could not re-read {what} from the server ({refresh.message}). What is shown may be out of
          date; reload it before acting again.
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
          {pending ? `${label} — waiting for the server…` : `${label}…`}
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
          Cancel
        </button>
      </div>
    </div>
  );
}
