import { useI18n, type Locale } from "../i18n";
import { DEMO_EXAMPLES } from "./examples";

// NoMatchHelp follows a public demo search that found nothing: how keyword
// matching works, the guided examples' own queries (which match in every demo
// build that has those examples) and a way to see every Concept. Each button
// runs an ordinary keyword search; nothing is recorded.
export function NoMatchHelp({ onSearch }: { onSearch: (q: string) => void }) {
  const { t } = useI18n();
  const queries = [...new Set(DEMO_EXAMPLES.map((e) => e.query))];
  return (
    <section className="panel demo-no-match-help" aria-labelledby="demo-no-match-heading">
      <h3 id="demo-no-match-heading">{t("demo.noMatch.heading")}</h3>
      <p className="hint">{t("demo.noMatch.how")}</p>
      <div className="actions">
        {queries.map((q) => (
          <button key={q} type="button" className="ghost" onClick={() => onSearch(q)}>
            {t("demo.noMatch.try", { q })}
          </button>
        ))}
        <button type="button" className="primary" onClick={() => onSearch("")}>
          {t("demo.noMatch.showAll")}
        </button>
      </div>
    </section>
  );
}

// RecordedTime shows a stored timestamp as a date and time in the interface
// language (always UTC, so every visitor sees the same moment); the exact
// stored value stays in the element's `dateTime` and title. A value that is not
// a date is shown as it is.
export function RecordedTime({ value, locale }: { value: string; locale: Locale }) {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) return <>{value}</>;
  const text = new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  }).format(date);
  return (
    <time dateTime={value} title={value}>
      {text}
    </time>
  );
}
