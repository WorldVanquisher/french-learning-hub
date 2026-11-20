import type { MessageKey } from "../i18n";
import discovery from "./discovery.json";

// The public demo's suggested keyword searches (discovery.json): each shows one
// search behaviour on the synthetic catalog, and one shows what to do when a
// search finds nothing. Keyword search only, so no query needs an embedding.
// The package check (scripts/validation/demo_candidate/check_examples.py)
// verifies each query's stated behaviour against the running package.
export type QueryBehaviour = "unit_wording" | "identity_details" | "all_words" | "accents" | "word_beginning" | "no_match";

export interface DemoQuery {
  q: string;
  shows: QueryBehaviour;
  // For a query that finds nothing: a related search, and a guided example.
  followUp?: { q: string; example?: string };
}

const SHOWS: Readonly<Record<QueryBehaviour, MessageKey>> = {
  unit_wording: "demo.queries.shows.unit_wording",
  identity_details: "demo.queries.shows.identity_details",
  all_words: "demo.queries.shows.all_words",
  accents: "demo.queries.shows.accents",
  word_beginning: "demo.queries.shows.word_beginning",
  no_match: "demo.queries.shows.no_match",
};

export const showsKey = (b: QueryBehaviour) => SHOWS[b];

export const DEMO_QUERIES: readonly DemoQuery[] = discovery.queries
  .filter((x): x is typeof x & { shows: QueryBehaviour } => x.shows in SHOWS)
  .map((x) => ({ q: x.q, shows: x.shows, ...("follow_up" in x && x.follow_up ? { followUp: x.follow_up } : {}) }));

const same = (a: string, b: string) => a.trim().toLocaleLowerCase("fr") === b.trim().toLocaleLowerCase("fr");

// The follow-up of a suggested query that finds nothing, for the query just run.
export const followUpFor = (q: string) => DEMO_QUERIES.find((x) => x.followUp && same(x.q, q))?.followUp;
