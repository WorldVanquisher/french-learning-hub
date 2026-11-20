import { useI18n, type MessageKey } from "../i18n";

// The public demo's first screen (R2): a small set of ways in for a visitor
// with no query, one compact row under the introduction so the first example
// still begins on a 320 px phone's first screen. Browsing (prepared examples
// and comparisons) and searching (the visitor's own words over the whole
// synthetic library) are separate entries; the search section says how they
// differ. The entries move focus within the page (no history entry); the tour
// opens its first screen.
export function StartPoints({ onTour }: { onTour: () => void }) {
  const { t } = useI18n();
  // Focus a section's heading (or the search field) and bring it into view.
  const jump = (id: string) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.focus({ preventScroll: true });
    el.scrollIntoView?.({ block: "start" });
  };
  return (
    <nav className="demo-start" aria-label={t("demo.start.heading")}>
      <ul className="demo-start-list">
        <li>
          <button type="button" className="primary" id="demo-start-tour" onClick={onTour}>
            {t("demo.start.tour")}
          </button>
        </li>
        <li>
          <button type="button" className="ghost" id="demo-start-browse" onClick={() => jump("demo-examples-heading")}>
            {t("demo.start.browse")}
          </button>
        </li>
        <li>
          <button type="button" className="ghost" id="demo-start-compare" onClick={() => jump("demo-compare-picker-heading")}>
            {t("demo.start.compare")}
          </button>
        </li>
        <li>
          <button type="button" className="ghost" id="demo-start-search" onClick={() => jump("library-query")}>
            {t("demo.start.search")}
          </button>
        </li>
      </ul>
    </nav>
  );
}

// The 60-second tour (R2): a learner's question, the comparison of the two
// rules taken from it, and the source record they came from. The tour is a
// path through the ordinary screens (each its own history entry and link);
// this bar only says where the visitor is on it and offers the next step.
// Leaving it keeps the visitor exactly where they are. It lives in this page's
// memory: a reload or a shared link has no tour.
export const TOUR_STEPS = 3;
const STEP_TITLE: readonly MessageKey[] = ["demo.tour.step.1", "demo.tour.step.2", "demo.tour.step.3"];
const STEP_HINT: readonly MessageKey[] = ["demo.tour.hint.1", "demo.tour.hint.2", "demo.tour.hint.3"];

export function TourBar({
  step,
  canNext,
  onNext,
  onResume,
  onLeave,
}: {
  // 1–3 on the path; 0 when the visitor has left the path (Back, another screen).
  step: number;
  canNext: boolean;
  onNext: () => void;
  onResume: () => void;
  onLeave: () => void;
}) {
  const { t } = useI18n();
  return (
    <nav className="panel demo-tour" aria-label={t("demo.tour.label")}>
      {step > 0 ? (
        <>
          <p className="demo-tour-where" id="demo-tour-where">
            {t("demo.tour.where", { n: step, total: TOUR_STEPS, title: t(STEP_TITLE[step - 1]) })}
          </p>
          <p className="hint">{t(STEP_HINT[step - 1])}</p>
        </>
      ) : (
        <p className="demo-tour-where" id="demo-tour-where">
          {t("demo.tour.off")}
        </p>
      )}
      <div className="actions">
        {step > 0 && step < TOUR_STEPS ? (
          <button type="button" className="primary" id="demo-tour-next" disabled={!canNext} onClick={onNext}>
            {t("demo.tour.next", { title: t(STEP_TITLE[step]) })}
          </button>
        ) : step === TOUR_STEPS ? (
          <button type="button" className="primary" id="demo-tour-finish" onClick={onLeave}>
            {t("demo.tour.finish")}
          </button>
        ) : (
          <button type="button" className="primary" id="demo-tour-resume" onClick={onResume}>
            {t("demo.tour.resume")}
          </button>
        )}
        {step !== TOUR_STEPS ? (
          <button type="button" className="ghost" id="demo-tour-leave" onClick={onLeave}>
            {t("demo.tour.leave")}
          </button>
        ) : null}
      </div>
    </nav>
  );
}
