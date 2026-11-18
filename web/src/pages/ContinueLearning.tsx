import { useEffect, useState } from "react";
import * as api from "../api/client";
import { useI18n, type MessageKey } from "../i18n";

// Continue learning (learning home): the most recent item the learner started
// in each skill section, read from saved work through the existing list
// endpoints. Reading it changes nothing and stores nothing in the browser.
//
// "Started" is the item's created_at: a Listening lesson counts once the
// learner has given it a transcript (a playlist pull alone is not the
// learner's start), a Reading lesson, Writing task or Speaking exercise as
// soon as it exists. Each section is read separately, so one that fails to
// load is named and the others are still shown.

export type ContinueSkill = "listening" | "reading" | "writing" | "speaking";

export interface ContinueItem {
  skill: ContinueSkill;
  id: number;
  title: string;
  createdAt: string;
  // Extra context for the line: a counted message (plural forms in both catalogs).
  detail: { key: "home.continue.writingVersions" | "home.continue.speakingTakes"; count: number } | null;
}

export interface ContinueResult {
  items: ContinueItem[]; // newest first, at most one per skill
  failed: ContinueSkill[];
}

type Fetchers = {
  listening: () => Promise<ContinueItem[]>;
  reading: () => Promise<ContinueItem[]>;
  writing: () => Promise<ContinueItem[]>;
  speaking: () => Promise<ContinueItem[]>;
};

export const defaultFetchers: Fetchers = {
  listening: async () =>
    (await api.listListening()).materials
      .filter((m) => m.transcript_version !== null)
      .map((m) => ({ skill: "listening", id: m.material.id, title: m.material.title, createdAt: m.material.created_at, detail: null })),
  reading: async () =>
    (await api.listReading()).lessons.map((l) => ({ skill: "reading", id: l.lesson.id, title: l.lesson.title, createdAt: l.lesson.created_at, detail: null })),
  writing: async () =>
    (await api.listWritingTasks()).tasks.map((w) => ({
      skill: "writing",
      id: w.task.id,
      title: w.task.title,
      createdAt: w.task.created_at,
      detail: { key: "home.continue.writingVersions", count: w.versions },
    })),
  speaking: async () =>
    (await api.listSpeakingExercises()).exercises.map((s) => ({
      skill: "speaking",
      id: s.exercise.id,
      title: s.exercise.title,
      createdAt: s.exercise.created_at,
      detail: { key: "home.continue.speakingTakes", count: s.takes },
    })),
};

const SKILLS: readonly ContinueSkill[] = ["listening", "reading", "writing", "speaking"];

// newest returns the item started last (ties: the higher ID, i.e. created later).
function newest(items: ContinueItem[]): ContinueItem | null {
  let best: ContinueItem | null = null;
  for (const it of items) {
    if (!best || it.createdAt > best.createdAt || (it.createdAt === best.createdAt && it.id > best.id)) best = it;
  }
  return best;
}

export async function loadContinue(fetchers: Fetchers = defaultFetchers): Promise<ContinueResult> {
  const settled = await Promise.allSettled(SKILLS.map((s) => fetchers[s]()));
  const items: ContinueItem[] = [];
  const failed: ContinueSkill[] = [];
  settled.forEach((r, i) => {
    if (r.status === "rejected") failed.push(SKILLS[i]);
    else {
      const n = newest(r.value);
      if (n) items.push(n);
    }
  });
  items.sort((a, b) => (a.createdAt === b.createdAt ? b.id - a.id : a.createdAt < b.createdAt ? 1 : -1));
  return { items, failed };
}

const SKILL_NAME: Record<ContinueSkill, MessageKey> = {
  listening: "nav.listening",
  reading: "nav.reading",
  writing: "nav.writing",
  speaking: "nav.speaking",
};

export function ContinueLearning({ onContinue, fetchers }: { onContinue: (item: ContinueItem) => void; fetchers?: Fetchers }) {
  const { t, tp, locale } = useI18n();
  const [state, setState] = useState<{ status: "loading" } | { status: "ready"; result: ContinueResult }>({ status: "loading" });
  useEffect(() => {
    let active = true;
    void loadContinue(fetchers).then((result) => active && setState({ status: "ready", result }));
    return () => {
      active = false;
    };
  }, [fetchers]);
  const date = (iso: string) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(d);
  };
  return (
    <section className="panel continue-learning" aria-labelledby="continue-heading">
      <h2 id="continue-heading">{t("home.continue.heading")}</h2>
      {state.status === "loading" ? (
        <p className="hint" role="status">
          {t("home.continue.loading")}
        </p>
      ) : (
        <>
          {state.result.items.length === 0 && state.result.failed.length === 0 ? <p className="empty">{t("home.continue.empty")}</p> : null}
          {state.result.items.length > 0 ? (
            <ul className="continue-items">
              {state.result.items.map((it) => (
                <li key={`${it.skill}-${it.id}`} className="continue-item">
                  <span className="tag">{t(SKILL_NAME[it.skill])}</span>{" "}
                  <span className="continue-title" lang="fr" dir="auto">
                    {it.title}
                  </span>
                  <span className="hint continue-meta">
                    {t("home.continue.started", { date: date(it.createdAt) })}
                    {it.detail ? ` · ${tp(it.detail.key, it.detail.count)}` : ""}
                  </span>
                  <button type="button" onClick={() => onContinue(it)} aria-label={t("home.continue.openNamed", { section: t(SKILL_NAME[it.skill]), title: it.title })}>
                    {t("home.continue.open")}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          {state.result.failed.length > 0 ? (
            <p className="hint" role="status">
              {t("home.continue.partial", { sections: state.result.failed.map((s) => t(SKILL_NAME[s])).join(t("library.fieldSeparator")) })}
            </p>
          ) : null}
          <p className="hint">{t("home.continue.hint")}</p>
        </>
      )}
    </section>
  );
}
