import { useState } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import { useI18n, type MessageKey } from "../i18n";
import type {
  ListeningDaily,
  ListeningNotification,
  ListeningNotifyOutcome,
  ListeningPrepareOutcome,
  ListeningPullRun,
  ListeningSourceFailure,
} from "../types/listening";
import { randomOperationId } from "./annotationOperation";

// Daily Listening in the private workbench: the "Pull now" button and the last
// pull, and explicit notification retries on a lesson.
//
// Every write carries a key generated per attempt. When no response arrives,
// the page first looks the key up; only if nothing is recorded does it offer to
// send the SAME request again (same key: the server replays, never repeats).
// A failed or unknown outcome is never retried automatically; an unknown one
// needs an explicit, acknowledged retry with a new key.

const describe = (e: unknown) =>
  e instanceof ApiError ? `(${e.status}) ${e.message}` : e instanceof Error ? e.message : String(e);

const when = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
};

const sourceFailureKey: Record<ListeningSourceFailure, MessageKey> = {
  source_timeout: "listening.daily.source.source_timeout",
  source_unavailable: "listening.daily.source.source_unavailable",
  source_refused: "listening.daily.source.source_refused",
  invalid_response: "listening.daily.source.invalid_response",
};
const prepareKey: Record<ListeningPrepareOutcome, MessageKey> = {
  disabled: "listening.daily.prepare.disabled",
  nothing_to_prepare: "listening.daily.prepare.nothing_to_prepare",
  daily_cap_reached: "listening.daily.prepare.daily_cap_reached",
  completed: "listening.daily.prepare.completed",
  failed: "listening.daily.prepare.failed",
  unknown: "listening.daily.prepare.unknown",
};
const notifyKey: Record<ListeningNotifyOutcome, MessageKey> = {
  disabled: "listening.daily.notify.disabled",
  nothing_ready: "listening.daily.notify.nothing_ready",
  sent: "listening.daily.notify.sent",
  failed: "listening.daily.notify.failed",
  unknown: "listening.daily.notify.unknown",
};

export function PullRunSummary({ run }: { run: ListeningPullRun }) {
  const { t } = useI18n();
  const status: MessageKey =
    run.status === "running" ? "listening.daily.run.running" : run.status === "interrupted" ? "listening.daily.run.interrupted" : "listening.daily.run.finished";
  return (
    <div className="listening-run" role="group" aria-label={t("listening.daily.run.region")}>
      <p>
        {t(run.trigger === "scheduled" ? "listening.daily.run.scheduled" : "listening.daily.run.manual", { when: when(run.started_at) })}{" "}
        <span className="tag">{t(status)}</span>
      </p>
      {run.status === "finished" ? (
        <ul className="listening-steps">
          <li>
            {run.source.outcome === "ok"
              ? t("listening.daily.source.ok", { created: run.items.created, known: run.items.known, skipped: run.items.skipped })
              : run.source.outcome === "failed"
                ? t("listening.daily.source.failed", { reason: t(sourceFailureKey[run.source.failure ?? "source_unavailable"]) })
                : t("listening.daily.source.disabled")}
          </li>
          <li>{t(prepareKey[run.preparation.outcome ?? "disabled"])}</li>
          <li>{t(notifyKey[run.notification.outcome ?? "disabled"])}</li>
        </ul>
      ) : run.status === "interrupted" ? (
        <p className="hint">{t("listening.daily.run.interruptedHint")}</p>
      ) : null}
    </div>
  );
}

type PullState =
  | { status: "idle" }
  | { status: "sending"; key: string }
  | { status: "done"; run: ListeningPullRun }
  | { status: "busy"; run: ListeningPullRun | null }
  | { status: "unknown"; key: string; run: ListeningPullRun | null }
  | { status: "error"; message: string };

// DailyPanel shows the settings, today's cap and the last pull, and "Pull now".
export function DailyPanel({ daily, onPulled }: { daily: ListeningDaily; onPulled: () => void }) {
  const { t } = useI18n();
  const [state, setState] = useState<PullState>({ status: "idle" });

  // check looks the key up after a lost response; it never sends a pull.
  const check = async (key: string) => {
    try {
      const run = await api.getListeningPullRun(key);
      if (run.status === "running") setState({ status: "unknown", key, run });
      else {
        setState({ status: "done", run });
        onPulled();
      }
    } catch {
      setState({ status: "unknown", key, run: null });
    }
  };
  const send = async (key: string) => {
    setState({ status: "sending", key });
    try {
      const run = await api.pullListening(key);
      setState({ status: "done", run });
      onPulled();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        const body = e.body as { run?: ListeningPullRun } | undefined;
        setState({ status: "busy", run: body?.run ?? null });
      } else if (e instanceof NetworkError || (e instanceof ApiError && e.status >= 500 && e.status !== 503)) {
        await check(key);
      } else {
        setState({ status: "error", message: describe(e) });
      }
    }
  };

  const last = state.status === "done" ? state.run : daily.last_run;
  const p = daily.preparation;
  return (
    <section className="panel listening-daily" aria-label={t("listening.daily.region")}>
      <h2>{t("listening.daily.heading")}</h2>
      {!daily.pull_enabled ? (
        <p className="hint">{t("listening.daily.off")}</p>
      ) : (
        <>
          <ul className="listening-steps">
            <li>{daily.source.enabled ? t("listening.daily.setting.source") : t("listening.daily.setting.sourceOff")}</li>
            <li>
              {p.enabled
                ? t("listening.daily.setting.prepare", { cap: p.daily_cap, timezone: p.timezone, used: p.used_today, today: p.today })
                : t("listening.daily.setting.prepareOff")}
            </li>
            <li>
              {daily.notification.enabled
                ? t("listening.daily.setting.notify", { channel: daily.notification.channel ?? "" })
                : t("listening.daily.setting.notifyOff")}
            </li>
          </ul>
          <p className="hint">{t("listening.daily.hint")}</p>
          <div className="actions">
            <button type="button" className="primary" disabled={state.status === "sending"} onClick={() => send(randomOperationId())}>
              {state.status === "sending" ? t("listening.daily.pulling") : t("listening.daily.pull")}
            </button>
          </div>
        </>
      )}
      {state.status === "busy" ? (
        <div className="banner info" role="status">
          {state.run
            ? t("listening.daily.busy", { when: when(state.run.started_at), trigger: t(state.run.trigger === "scheduled" ? "listening.daily.trigger.scheduled" : "listening.daily.trigger.manual") })
            : t("listening.daily.busyUnknown")}
        </div>
      ) : state.status === "unknown" ? (
        <div className="banner info" role="alert">
          {state.run ? t("listening.daily.stillRunning") : t("listening.daily.unknown")}{" "}
          <button type="button" className="ghost" onClick={() => check(state.key)}>
            {t("listening.daily.checkAgain")}
          </button>
          {!state.run ? (
            <button type="button" className="ghost" onClick={() => send(state.key)}>
              {t("listening.daily.sendSame")}
            </button>
          ) : null}
        </div>
      ) : state.status === "error" ? (
        <div className="banner error" role="alert">
          {t("listening.daily.failed", { message: state.message })}
        </div>
      ) : null}
      {last ? (
        <>
          <h3>{t("listening.daily.lastHeading")}</h3>
          <PullRunSummary run={last} />
        </>
      ) : daily.pull_enabled ? (
        <p className="hint">{t("listening.daily.never")}</p>
      ) : null}
    </section>
  );
}

const notificationStateKey: Record<ListeningNotification["state"], MessageKey> = {
  in_progress: "listening.notify.state.in_progress",
  sent: "listening.notify.state.sent",
  failed: "listening.notify.state.failed",
  unknown: "listening.notify.state.unknown",
};

type RetryState =
  | { status: "idle" }
  | { status: "sending"; key: string }
  | { status: "unknown"; key: string; confirm: boolean }
  | { status: "error"; message: string };

// NotificationsSection lists a lesson's notifications and, for the latest one
// of an exercise when it failed or its outcome is unknown, an explicit retry.
export function NotificationsSection({
  notifications,
  enabled,
  onChanged,
}: {
  notifications: ListeningNotification[];
  enabled: boolean;
  onChanged: () => void;
}) {
  const { t } = useI18n();
  const [state, setState] = useState<RetryState>({ status: "idle" });
  if (notifications.length === 0) return null;
  const latest = notifications[0];

  const check = async (key: string, confirm: boolean) => {
    try {
      await api.getListeningNotification(key);
      setState({ status: "idle" });
      onChanged();
    } catch {
      setState({ status: "unknown", key, confirm });
    }
  };
  const send = async (key: string, confirm: boolean) => {
    setState({ status: "sending", key });
    try {
      await api.retryListeningNotification(latest.exercise_id, key, confirm);
      setState({ status: "idle" });
      onChanged();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setState({ status: "idle" });
        onChanged(); // the re-read shows the attempt that blocked it
      } else if (e instanceof NetworkError || (e instanceof ApiError && e.status >= 500 && e.status !== 503)) {
        await check(key, confirm);
      } else {
        setState({ status: "error", message: describe(e) });
      }
    }
  };
  const canRetry = enabled && (latest.state === "failed" || latest.state === "unknown");
  return (
    <section className="panel" aria-label={t("listening.notify.region")}>
      <h3>{t("listening.notify.heading")}</h3>
      <ul className="listening-steps">
        {notifications.map((n) => (
          <li key={n.id}>
            {t(n.trigger === "pull" ? "listening.notify.byPull" : "listening.notify.byYou", { channel: n.channel, when: when(n.started_at) })}{" "}
            <span className="tag">{t(notificationStateKey[n.state])}</span>
          </li>
        ))}
      </ul>
      {latest.state === "unknown" ? (
        <p className="hint">{t("listening.notify.unknownHint")}</p>
      ) : latest.state === "failed" ? (
        <p className="hint">{t(latest.failure_code === "refused" ? "listening.notify.refusedHint" : "listening.notify.notSentHint")}</p>
      ) : null}
      {canRetry ? (
        <div className="actions">
          <button
            type="button"
            className={latest.state === "unknown" ? "ghost" : "primary"}
            disabled={state.status === "sending"}
            onClick={() => send(randomOperationId(), latest.state === "unknown")}
          >
            {t(latest.state === "unknown" ? "listening.notify.retryUnknown" : "listening.notify.retry")}
          </button>
        </div>
      ) : null}
      {state.status === "unknown" ? (
        <div className="banner info" role="alert">
          {t("listening.notify.lost")}{" "}
          <button type="button" className="ghost" onClick={() => check(state.key, state.confirm)}>
            {t("listening.daily.checkAgain")}
          </button>
          <button type="button" className="ghost" onClick={() => send(state.key, state.confirm)}>
            {t("listening.daily.sendSame")}
          </button>
        </div>
      ) : state.status === "error" ? (
        <div className="banner error" role="alert">
          {t("listening.notify.failed", { message: state.message })}
        </div>
      ) : null}
    </section>
  );
}
