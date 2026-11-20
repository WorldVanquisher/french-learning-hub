import type { ReactNode } from "react";
import { useI18n, type Locale } from "../i18n";
import { DEMO_EXAMPLES } from "./examples";
import { DEMO_QUERIES, followUpFor, showsKey } from "./queries";
import { MAX_QUERY_BYTES, MAX_QUERY_WORDS, queryProblem } from "./searchLimits";

// SearchProblem replaces a failed public-demo search's results. A search the
// server refused (400) names the limit it broke and offers to edit the search,
// since running it again cannot help; any other failure offers to run that same
// search again, named, so it is clear what the button retries. Either way the
// last search that worked stays below, labelled, so a failure never empties
// the page.
export function SearchProblem({
  query,
  code,
  message,
  failed,
  onRetry,
  onEdit,
  previous,
}: {
  query: string;
  code?: number;
  message: string;
  // The failed search's own wording ("Could not search the knowledge library: {message}").
  failed: string;
  onRetry: () => void;
  onEdit: () => void;
  previous?: { q: string; results: ReactNode } | null;
}) {
  const { t, tn } = useI18n();
  const problem = code === 400 ? queryProblem(query) : null;
  const q = query.trim();
  return (
    <>
      <div className="banner error demo-search-problem" role="alert">
        {problem?.kind === "words"
          ? t("demo.search.tooManyWords", { q, count: problem.count, max: MAX_QUERY_WORDS })
          : problem?.kind === "bytes"
            ? t("demo.search.tooLong", { count: problem.count, max: MAX_QUERY_BYTES })
            : problem?.kind === "no-word"
              ? t("demo.search.noWord", { q })
              : code === 400
                ? t("demo.search.refused", { message })
                : failed}{" "}
        {code === 400 ? (
          <button type="button" className="ghost" id="demo-search-edit" onClick={onEdit}>
            {t("demo.search.edit")}
          </button>
        ) : (
          <button type="button" className="ghost" id="demo-search-retry" onClick={onRetry}>
            {q ? t("demo.search.retry", { q }) : t("demo.search.retryAll")}
          </button>
        )}
      </div>
      {previous ? (
        <section className="demo-previous" aria-labelledby="demo-previous-heading">
          <p id="demo-previous-heading" className="hint">
            {previous.q ? tn("demo.search.previous", { q: <span lang="fr">{previous.q}</span> }) : t("demo.search.previousAll")}
          </p>
          {previous.results}
        </section>
      ) : null}
    </>
  );
}

// SuggestedSearches lists the demo's suggested keyword searches, each with the
// search behaviour it shows, collapsed by default so the start screen stays
// short. Each button runs an ordinary keyword search; nothing is recorded.
export function SuggestedSearches({ onSearch }: { onSearch: (q: string) => void }) {
  const { t, tp } = useI18n();
  return (
    <details className="demo-details demo-suggested">
      <summary>{tp("demo.queries.summary", DEMO_QUERIES.length)}</summary>
      <ul className="demo-suggested-list">
        {DEMO_QUERIES.map((x, i) => (
          <li key={x.q}>
            <button type="button" className="ghost" id={`demo-query-${i}`} aria-describedby={`demo-query-${i}-shows`} onClick={() => onSearch(x.q)}>
              <span lang="fr">{x.q}</span>
            </button>{" "}
            <span className="hint" id={`demo-query-${i}-shows`}>
              {t(showsKey(x.shows))}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

// NoMatchHelp follows a public demo search that found nothing: how keyword
// matching works, the guided examples' own queries (which match in every demo
// build that has those examples) and a way to see every Concept. Each button
// runs an ordinary keyword search; nothing is recorded.
//
// For a suggested query that finds nothing (queries.ts), it first names that
// query's own follow-up: a related search and a guided example.
export function NoMatchHelp({
  onSearch,
  query = "",
  onOpenExample,
}: {
  onSearch: (q: string) => void;
  query?: string;
  onOpenExample?: (key: string) => void;
}) {
  const { t } = useI18n();
  const follow = followUpFor(query);
  // The examples' own queries, without the follow-up's (offered first, above).
  const queries = [...new Set(DEMO_EXAMPLES.map((e) => e.query))].filter((q) => q !== follow?.q);
  const example = follow?.example ? DEMO_EXAMPLES.find((e) => e.key === follow.example) : undefined;
  return (
    <section className="panel demo-no-match-help" aria-labelledby="demo-no-match-heading">
      {follow ? (
        <div className="demo-follow-up">
          <p>{t("demo.queries.followUp", { q: query.trim() })}</p>
          <div className="actions">
            <button type="button" className="primary" id="demo-follow-up-search" onClick={() => onSearch(follow.q)}>
              {t("demo.noMatch.try", { q: follow.q })}
            </button>
            {example && onOpenExample ? (
              <button type="button" className="ghost" id="demo-follow-up-example" onClick={() => onOpenExample(example.key)}>
                {t("demo.missing.openExample", { title: t(example.title) })}
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
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
