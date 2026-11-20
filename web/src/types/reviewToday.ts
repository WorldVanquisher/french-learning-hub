import type { NotebookItem } from "./notebook";
import type { SpeakingQueueItem } from "./speaking";

// GET /review-today (review_today_v1): derived on every read, nothing stored.
export type ReviewTodaySource = "speaking" | "notebook";

export interface ReviewTodayItem {
  key: string; // stable: "speaking:exercise:<id>" or "notebook:entry:<id>"
  source: ReviewTodaySource;
  // An explicit reason code: a Speaking queue reason, or "retry_marked".
  reason: SpeakingQueueItem["reason"] | "retry_marked";
  priority: number; // ordinal, 0 = most urgent
  since: string;
  since_day?: string | null; // the local day of `since` in the requested zone
  speaking: SpeakingQueueItem | null;
  notebook: NotebookItem | null;
  // Other marked notebook records for the same question (another revision of
  // the lesson): this one item stands for them all; "Done for today" clears all.
  also_entry_ids?: number[];
  // The readable next-review recommendation (existing scheduling ladder).
  schedule?: ReviewSchedule;
}

export interface ReviewScheduleStep {
  day: string; // local day in the requested zone
  interval_days: number; // calendar days from today
  rule: string; // the traceable rule, e.g. "ladder n=2 +3d from 2026-11-20 (last attempt)"
}

export interface ReviewSchedule {
  class: "recovery" | "review" | "new";
  due_day: string;
  rule: string;
  if_completed: ReviewScheduleStep;
  if_missed: ReviewScheduleStep;
}

export interface ReviewToday {
  schema_version: "review_today_v1";
  generated_at: string;
  zone?: string; // the zone the local days are in (UTC when none was sent)
  today?: string;
  items: ReviewTodayItem[];
  // Saved work kept out of the queue, counted for its links.
  history: { notebook_items: number; speaking_exercises: number; speaking_takes: number };
  sources: { speaking: boolean; notebook: boolean };
}

// GET /learning-week?zone= (learning_week_v1): seven local days, derived on
// every read. Each count is one stored item per kind and day.
export interface LearningWeekDay {
  day: string; // YYYY-MM-DD in the learner's zone
  production: number;
  reviewed: number;
  own_corrections: number;
  provider_feedback: number;
}

export interface LearningCorrection {
  skill: "speaking" | "writing";
  title: string;
  version: number;
  prior_version: number; // 0: the machine transcript
  day: string;
  at: string;
  exercise_id?: number;
  take_id?: number;
  take_number?: number;
  task_id?: number;
}

export interface LearningWeek {
  schema_version: "learning_week_v1";
  generated_at: string;
  zone: string;
  from: string;
  to: string;
  days: LearningWeekDay[];
  totals: {
    production: number;
    reviewed: number;
    own_corrections: number;
    provider_feedback: number;
    distinct_exercises: number;
    active_days: number;
    duplicates_ignored: number;
  };
  sparse: boolean;
  min_for_shares: number;
  production_share: number | null;
  corrections: LearningCorrection[];
  sources: { speaking: boolean; writing: boolean; notebook: boolean };
}
