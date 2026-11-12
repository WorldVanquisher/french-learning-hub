import { useEffect } from "react";
import { useI18n } from "../i18n";

// A request from the Mistake Notebook to show the exact item a record came
// from (FLH sections v1). version is the transcript or passage version of that
// exercise; item is 1-based.
export interface NotebookTarget {
  exerciseId: number;
  item: number;
  version: number;
}

export const notebookItemDomId = (skill: "listening" | "reading", exerciseId: number, item: number) => `${skill}-item-${exerciseId}-${item}`;

// NotebookOrigin says which saved item the lesson was opened for, and whether
// that exact item is the one shown. When the lesson now shows another version
// or exercise, it says so instead of pointing at a different question: the
// saved item stays, exactly as it was saved, in the Mistake Notebook.
export function NotebookOrigin({
  skill,
  target,
  shownExerciseId,
  currentVersion,
}: {
  skill: "listening" | "reading";
  target: NotebookTarget;
  shownExerciseId: number | null;
  currentVersion: number | null;
}) {
  const { t } = useI18n();
  const shown = shownExerciseId === target.exerciseId;
  useEffect(() => {
    if (shown) document.getElementById(notebookItemDomId(skill, target.exerciseId, target.item))?.scrollIntoView?.({ block: "center" });
  }, [shown, skill, target.exerciseId, target.item]);
  const where = t(skill === "reading" ? "sections.origin.reading" : "sections.origin.listening", {
    n: target.item,
    exercise: target.exerciseId,
    version: target.version,
  });
  const state = shown
    ? t("sections.origin.shown", { n: target.item })
    : currentVersion !== null && currentVersion !== target.version
      ? t("sections.origin.newer", { version: currentVersion })
      : t("sections.origin.elsewhere");
  return (
    <div className="banner notebook-origin" role="status">
      {where} {state}
    </div>
  );
}
