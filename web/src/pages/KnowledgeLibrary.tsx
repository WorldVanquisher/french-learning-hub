import { useEffect, useRef, useState, type FormEvent, type MutableRefObject, type ReactNode } from "react";
import { markMatches, matchedFeatures } from "./libraryHighlight";
import { addRecent, clearRecent, readRecent, removeRecent, type RecentSearch } from "./recentSearches";
import * as api from "../api/client";
import { ApiError } from "../api/client";
import type {
  HybridSearch,
  LibraryConcept,
  LibraryHistoricalUnit,
  LibraryQuery,
  LibrarySearch,
  LibrarySearchResult,
  LibrarySearchMode,
  LibrarySource,
  LibraryStateFilter,
  LibraryUnit,
  PublicDemoInfo,
  SemanticSearch,
} from "../types/library";
import { useI18n, type I18n, type MessageKey } from "../i18n";
import { RecallPractice } from "./RecallPractice";
import { DEMO_EXAMPLES } from "../demo/examples";
import { ExamplePicker, ExampleScreen, focusExampleCard } from "../demo/ExampleScreen";
import { hashForScreen, linkFromHash, queryToSearch, sameSearch, searchToQuery, type LinkSearch } from "../demo/deepLink";
import { EvidenceCard } from "../demo/EvidenceCard";
import { compareCardId, ComparePicker, CompareScreen } from "../demo/CompareScreen";
import { findComparison, type SideResolution } from "../demo/comparisons";
import { readCompareVisit, writeCompareVisit } from "../demo/visit";
import { StartPoints, TourBar, TOUR_STEPS } from "../demo/Landing";
import { adoptEntry, entryKey, focusControl, focusFallback, pushEntry, readEntry, replaceEntry, stepsBack } from "../demo/history";
import { NoMatchHelp, RecordedTime, SearchProblem, SuggestedSearches } from "../demo/DemoStates";

// One search outcome per submitted query. Semantic and hybrid modes need a
// query; with an empty one nothing is requested (browsing is keyword search's job).
type SearchOutcome =
  | { kind: "keyword"; data: LibrarySearch }
  | { kind: "semantic"; data: SemanticSearch }
  | { kind: "hybrid"; data: HybridSearch }
  | { kind: "needs-query" };

// `code` is the HTTP status of a failed read, when the server answered.
type Load<T> = { status: "loading" } | { status: "error"; message: string; code?: number } | { status: "ready"; data: T };

// The library's own navigation: results → concept → source. The query stays in
// this component's state, so returning shows the same search and results.
// Recall practice (private workbench only) is opened from a Concept; a source
// opened from practice keeps that practice session (`practice`) mounted.
// The public demo's guided examples (`example`) are a second starting point: a
// Concept or source opened from one keeps its key (`from`), so their back
// actions return to that example instead of the search results.
type Screen =
  | { kind: "results" }
  | { kind: "example"; example: string; step?: number }
  | { kind: "compare"; compare: string }
  // `from`: the guided example, `compare`: the comparison it was opened from (public demo).
  | { kind: "concept"; conceptId: number; from?: string; compare?: string }
  | { kind: "practice"; conceptId: number; session: number }
  | { kind: "source"; conceptId: number; unitId: number; practice?: number; from?: string; compare?: string };

const resultButtonId = (conceptId: number) => `library-result-${conceptId}`;

// A public demo build (VITE_FLH_PUBLIC_DEMO=1, fixed at build time): the
// private workbench's recall practice is never offered there, so its code is
// left out of that bundle altogether (R2-054; check_bundle.py).
const PUBLIC_DEMO_BUILD = import.meta.env.VITE_FLH_PUBLIC_DEMO === "1";

// Public demo: the 60-second tour's example and comparison (demo/Landing.tsx).
const TOUR = { example: "imparfait", compare: "imparfait-passe-compose" } as const;

function describeError(error: unknown): string {
  if (error instanceof ApiError) return `(${error.status}) ${error.message}`;
  return error instanceof Error ? error.message : String(error);
}

// useLoad runs one GET per key and applies only the latest answer. Data loaded
// for an earlier key is never shown under the current key (no stale results
// labelled with a new query while the new request is in flight).
function useLoad<T>(key: string, load: () => Promise<T>, retry: number): Load<T> {
  const [state, setState] = useState<{ key: string; retry: number; load: Load<T> }>({ key, retry, load: { status: "loading" } });
  useEffect(() => {
    let active = true;
    setState({ key, retry, load: { status: "loading" } });
    load()
      .then((data) => active && setState({ key, retry, load: { status: "ready", data } }))
      .catch(
        (error: unknown) =>
          active &&
          setState({
            key,
            retry,
            load: { status: "error", message: describeError(error), code: error instanceof ApiError ? error.status : undefined },
          }),
      );
    return () => {
      active = false;
    };
    // `load` is recreated each render; `key` and `retry` identify the request.
  }, [key, retry]);
  return state.key === key && state.retry === retry ? state.load : { status: "loading" };
}

// useFocusedHeading moves keyboard focus to a screen's heading when it opens and
// again when its content replaces the loading state. Public demo: when the
// visitor came back to this screen (`returnFocus`, demo/history.ts), the
// control they left it by is focused instead once the content is there.
function useFocusedHeading(status: string, returnFocus?: MutableRefObject<string | null>) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const id = returnFocus?.current;
    if (id && status !== "loading") {
      returnFocus.current = null;
      const el = document.getElementById(id);
      if (el && ref.current?.closest("main")?.contains(el) && focusControl(el)) return;
    }
    ref.current?.focus();
  }, [status]);
  return ref;
}

// Display names of the backend's matched-field identifiers; unknown ones are shown as given.
const fieldLabels: Record<string, MessageKey> = {
  target: "library.field.target",
  pedagogical_intent: "library.field.pedagogical_intent",
  scope: "library.field.scope",
  identity_features: "library.field.identity_features",
  unit_canonical: "library.field.unit_canonical",
  unit_statement: "library.field.unit_statement",
  unit_example: "library.field.unit_example",
};
const fieldList = (i: I18n, fields: string[]) =>
  fields.map((f) => (fieldLabels[f] ? i.t(fieldLabels[f]) : f)).join(i.t("library.fieldSeparator"));

// Machine values such as needs_review or verified_unchanged: English shows them
// with spaces as before; other languages show their status label.
const spaced = (i: I18n, value: string) => (i.locale === "en" ? value.replace("_", " ") : i.status(value));

const resultsLabelKey: Record<LibrarySearchMode, MessageKey> = {
  keyword: "library.resultsLabel.keyword",
  semantic: "library.resultsLabel.semantic",
  hybrid: "library.resultsLabel.hybrid",
};
const modeSearchKey: Record<LibrarySearchMode, MessageKey> = {
  keyword: "library.allConcepts",
  semantic: "library.modeSearch.semantic",
  hybrid: "library.modeSearch.hybrid",
};
const needsQueryKey: Record<LibrarySearchMode, MessageKey> = {
  keyword: "library.needsQuery.semantic",
  semantic: "library.needsQuery.semantic",
  hybrid: "library.needsQuery.hybrid",
};
const searchFailedKey: Record<LibrarySearchMode, MessageKey> = {
  keyword: "library.searchFailed.keyword",
  semantic: "library.searchFailed.semantic",
  hybrid: "library.searchFailed.hybrid",
};

// KnowledgeLibrary is a GET-only view of curated Concepts. Searching, opening a
// Concept, or following a source records nothing and calls no provider; every
// status shown is a backend fact.
//
// With `demo` (FLH-073 public demo) keyword search stays free text, while
// semantic and hybrid search run only the demo's preset queries.
export function KnowledgeLibrary({
  demo,
  intro,
  about,
  guided = false,
  openRequest = null,
  onOpenRecord,
  searchRequest = null,
  onSearchChange,
}: {
  demo?: PublicDemoInfo;
  // Public demo only: text shown above the search on the starting screen, and
  // the guided examples (`guided`). The workbench passes neither.
  intro?: ReactNode;
  // Public demo only: shown after the guided examples, before the search.
  about?: ReactNode;
  guided?: boolean;
  // A Concept another workbench view asked to open (a record's filed unit, a
  // confirmed suggestion). The nonce makes a repeated request open it again.
  openRequest?: { conceptId: number; nonce: number } | null;
  // Opens a source record in Learning Records (private workbench only).
  onOpenRecord?: (entryId: number) => void;
  // Private workbench: a keyword search the address names (sectionAddress.ts),
  // applied at start and whenever its nonce changes; and every keyword search
  // shown, reported so the address can name it.
  searchRequest?: { q: string; state: LibraryStateFilter; nonce: number } | null;
  onSearchChange?: (search: { q: string; state: LibraryStateFilter }) => void;
} = {}) {
  const i18n = useI18n();
  const { t, tn } = i18n;
  // The public demo opens the screen and search a direct link names
  // (demo/deepLink.ts); the workbench always starts on an empty search.
  const [link] = useState(() => (demo ? linkFromHash(window.location.hash, demo.presets.map((p) => p.id)) : null));
  const initial = link && demo ? searchToQuery(link.search, demo.presets) : null;
  // The workbench starts on the search its address names, if any.
  const [addressed] = useState<LibraryQuery | null>(() => (!demo && searchRequest ? { q: searchRequest.q, state: searchRequest.state } : null));
  const [draft, setDraft] = useState<LibraryQuery>(() =>
    initial ? { q: initial.mode === "keyword" ? initial.query.q : "", state: initial.query.state } : (addressed ?? { q: "", state: "all" }),
  );
  const [draftPreset, setDraftPreset] = useState<string>(initial?.query.preset ?? demo?.presets[0]?.id ?? "");
  const [query, setQuery] = useState<LibraryQuery>(initial?.query ?? addressed ?? { q: "", state: "all" });
  const [draftMode, setDraftMode] = useState<LibrarySearchMode>(initial?.mode ?? "keyword");
  const [mode, setMode] = useState<LibrarySearchMode>(initial?.mode ?? "keyword");
  const [screen, setScreenState] = useState<Screen>(() => link?.screen ?? { kind: "results" });
  // The public demo keeps each screen in the browser history (demo/history.ts),
  // so the browser's or phone's Back and Forward walk the screens instead of
  // leaving the demo, and in-page back actions are the same moves. The
  // workbench has its own views and keeps no history here.
  const screenRef = useRef(screen);
  screenRef.current = screen;
  const searchRef = useRef<LinkSearch>(queryToSearch(query, mode));
  searchRef.current = queryToSearch(query, mode);
  const trailRef = useRef<string[]>([]);
  // Public demo: the control to focus on the screen the visitor came back to
  // (the one that left it; demo/history.ts), and whether the link that opened
  // the page matched nothing (shown on the start screen until the next move).
  const focusReturn = useRef<string | null>(null);
  // Public demo: the visitor came back to the start or results screen (Back,
  // Forward, an in-page back) and focus has not settled there yet.
  const returning = useRef(false);
  // Public demo: a search the visitor just submitted, whose first result (or
  // what it found instead) is brought into view once it is shown.
  const revealResults = useRef(false);
  const searchFormRef = useRef<HTMLFormElement>(null);
  const lastKeyword = useRef<{ query: LibraryQuery; data: LibrarySearch } | null>(null);
  const [badLink, setBadLink] = useState(() => Boolean(link?.malformed));
  const setScreen = (next: Screen, search: LinkSearch = searchRef.current) => {
    if (demo) {
      trailRef.current = pushEntry(next, search, trailRef.current);
      focusReturn.current = null;
      returning.current = false;
      setBadLink(false);
    }
    setScreenState(next);
  };
  // An in-page back action: the browser's Back when the screen it names is
  // earlier in this visit, otherwise that screen replaces the current entry.
  const goBack = (target: Screen) => {
    if (demo) {
      const steps = stepsBack(trailRef.current, entryKey(target, searchRef.current));
      if (steps > 0) {
        window.history.go(-steps);
        return;
      }
      trailRef.current = replaceEntry(target, searchRef.current, trailRef.current);
      focusReturn.current = null;
      returning.current = target.kind === "results";
      setBadLink(false);
    }
    setScreenState(target);
  };
  // A submitted search. In the demo, one that changes the results is a new
  // history entry, so Back returns to the previous results.
  const runSearch = (nextQuery: LibraryQuery, nextMode: LibrarySearchMode) => {
    setQuery(nextQuery);
    setMode(nextMode);
    const next = queryToSearch(nextQuery, nextMode);
    if (demo && !sameSearch(next, searchRef.current)) {
      searchRef.current = next;
      trailRef.current = pushEntry({ kind: "results" }, next, trailRef.current);
      focusReturn.current = null;
      returning.current = false;
      revealResults.current = true;
      setBadLink(false);
    }
  };
  // Shows the search a history entry or a link names, in the form and the results.
  const applySearch = (search: LinkSearch) => {
    const next = searchToQuery(search, demo?.presets ?? []);
    setQuery(next.query);
    setMode(next.mode);
    setDraftMode(next.mode);
    setDraft({ q: next.mode === "keyword" ? next.query.q : "", state: next.query.state });
    if (next.query.preset) setDraftPreset(next.query.preset);
  };
  const [retry, setRetry] = useState(0);
  const returnTo = useRef<number | null>(null);
  const returnToExample = useRef<string | null>(null);
  // Each start of recall practice is a new, empty session.
  const practiceSession = useRef(0);

  const search = useLoad<SearchOutcome>(
    `${mode}\u0000${query.state}\u0000${query.q}\u0000${query.preset ?? ""}\u0000${query.limit ?? ""}`,
    async (): Promise<SearchOutcome> => {
      if (mode === "keyword") return { kind: "keyword", data: await api.searchLibrary(query) };
      if (!query.q) return { kind: "needs-query" };
      if (demo) {
        if (mode === "hybrid") return { kind: "hybrid", data: await api.demoHybridSearch(query) };
        return { kind: "semantic", data: await api.demoSemanticSearch(query) };
      }
      if (mode === "hybrid") return { kind: "hybrid", data: await api.hybridSearchLibrary(query) };
      return { kind: "semantic", data: await api.semanticSearchLibrary(query) };
    },
    retry,
  );

  useEffect(() => {
    if (!demo) return;
    const presetIds = demo.presets.map((p) => p.id);
    // This entry: keep the trail a reload kept, otherwise this visit starts here.
    // The address is rewritten to the screen's own link (a malformed one becomes `/`).
    const kept = readEntry<Screen>(window.history.state);
    const key = entryKey(screenRef.current, searchRef.current);
    trailRef.current = replaceEntry(
      screenRef.current,
      searchRef.current,
      kept && kept.flhTrail[kept.flhTrail.length - 1] === key ? kept.flhTrail : [key],
    );
    const onPop = (event: PopStateEvent) => {
      const entry = readEntry<Screen>(event.state);
      let next: Screen;
      let search: LinkSearch;
      if (entry) {
        next = entry.flhLibrary;
        search = entry.flhSearch;
        trailRef.current = entry.flhTrail;
        focusReturn.current = entry.flhFocus ?? null;
        returning.current = next.kind === "results";
        setBadLink(false);
      } else {
        // A fragment typed or pasted into the address bar has no saved state.
        const linked = linkFromHash(window.location.hash, presetIds);
        next = linked.screen;
        search = linked.search;
        trailRef.current = adoptEntry(next, search, trailRef.current);
        focusReturn.current = null;
        returning.current = false;
        setBadLink(linked.malformed);
      }
      const left = screenRef.current;
      if (next.kind === "results") {
        if (left.kind === "example") returnToExample.current = left.example;
        else if (left.kind === "compare") focusReturn.current = focusReturn.current ?? compareCardId(left.compare);
        else if ((left.kind === "concept" || left.kind === "source") && left.from) returnToExample.current = left.from;
        else if (left.kind === "concept" || left.kind === "source") returnTo.current = left.conceptId;
      }
      if (!sameSearch(search, searchRef.current)) applySearch(search);
      setScreenState(next);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
    // The listener only calls state setters and reads refs.
  }, [demo]);

  // On return, focus the result the reader opened. Detail screens focus their own heading.
  // Public demo: the control that left this entry comes first (demo/history.ts),
  // once the results it may be among are shown; when nothing it names is on the
  // page once the search has settled, the heading of what is shown.
  useEffect(() => {
    if (screen.kind !== "results") return;
    const back = focusReturn.current ? document.getElementById(focusReturn.current) : null;
    if (back && !back.closest("[hidden]") && focusControl(back)) {
      focusReturn.current = null;
      returnToExample.current = null;
      returnTo.current = null;
      returning.current = false;
      return;
    }
    if (focusReturn.current && search.status !== "loading") focusReturn.current = null;
    if (returnToExample.current !== null) {
      focusExampleCard(returnToExample.current);
      returnToExample.current = null;
      returnTo.current = null;
    } else if (returnTo.current !== null && search.status === "ready") {
      document.getElementById(resultButtonId(returnTo.current))?.focus();
      returnTo.current = null;
    }
    if (demo && returning.current && search.status !== "loading") {
      returning.current = false;
      returnTo.current = null;
      const active = document.activeElement;
      if (!(active instanceof HTMLElement) || !active.closest("main") || active.closest("[hidden]")) {
        const searchShown = query.q !== "" || query.state !== "all" || mode !== "keyword";
        const heading = document.getElementById(searchShown ? "demo-search-heading" : "demo-examples-heading");
        if (heading) focusFallback(heading);
      }
    }
  }, [screen, search.status]);

  // Public demo: bring a submitted search's first result (or its no-match help,
  // or its error) into view with the smallest scroll, leaving focus where it is.
  // Without it a phone shows no change at all when Search is pressed.
  useEffect(() => {
    if (!revealResults.current || screen.kind !== "results" || search.status === "loading") return;
    revealResults.current = false;
    const area = searchFormRef.current?.nextElementSibling;
    const target = area?.querySelector(".library-result, .demo-no-match, [role=alert]") ?? area;
    if (target instanceof HTMLElement) target.scrollIntoView?.({ block: "nearest" });
    // The field the visitor typed in stays in view too: when showing the whole
    // result pushed it off the top (a 320 px phone), the field goes near the
    // top (8 px clear, so subpixel layout cannot leave it a fraction above) and
    // the result's beginning stays on screen below it.
    const field = document.activeElement;
    if (field instanceof HTMLElement && field.id === "library-query" && field.getBoundingClientRect().top < 0)
      window.scrollBy?.(0, field.getBoundingClientRect().top - 8);
  }, [screen, search.status]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const preset = demo && draftMode !== "keyword" ? demo.presets.find((p) => p.id === draftPreset) : undefined;
    runSearch(preset ? { q: preset.text, state: draft.state, preset: preset.id } : { q: draft.q.trim(), state: draft.state }, draftMode);
    if (!demo && draftMode === "keyword" && draft.q.trim() && recent) keepRecent(addRecent(recent, { q: draft.q.trim(), state: draft.state }));
  };
  const backToResults = (conceptId: number) => {
    returnTo.current = conceptId;
    goBack({ kind: "results" });
  };
  const openConcept = (conceptId: number, from?: string) => setScreen({ kind: "concept", conceptId, from });
  const openExample = (key: string) => setScreen({ kind: "example", example: key });
  // Public demo: a comparison (demo/comparisons.ts), the way back to the start
  // from it (focus on its card), and back to it from a Concept or source.
  // `practice`: open it on its choose-first question (R2) instead of the pair;
  // that is the comparison's in-page state for this visit, not part of its link.
  const openCompare = (key: string, practice = false) => {
    writeCompareVisit(key, { ...readCompareVisit(key), practice });
    setScreen({ kind: "compare", compare: key });
  };
  const backFromCompare = (key: string) => {
    goBack({ kind: "results" });
    if (demo && !focusReturn.current) focusReturn.current = compareCardId(key);
  };
  const backToCompare = (key: string) => goBack({ kind: "compare", compare: key });
  const comparisonTitle = (key: string | undefined) => {
    const c = findComparison(key);
    return c ? t("demo.compare.backTo", { title: t(c.title) }) : null;
  };
  // Public demo: the walkthrough step each example was last shown at, so the
  // way back from its Concept or evidence returns to that step's entry.
  const exampleStep = useRef<Record<string, number | undefined>>({});
  if (screen.kind === "example") exampleStep.current[screen.example] = screen.step;
  const backToExample = (key: string) =>
    goBack(exampleStep.current[key] ? { kind: "example", example: key, step: exampleStep.current[key] } : { kind: "example", example: key });
  const backFromExample = (key: string) => {
    returnToExample.current = key;
    goBack({ kind: "results" });
  };
  // Public demo (R2-038): from a link that names nothing, back to the search,
  // with the search field focused.
  const searchLibrary = () => {
    goBack({ kind: "results" });
    focusReturn.current = "library-query";
  };
  // The guided example a Concept or source was opened from, if any.
  const fromExample = (key: string | undefined) => (key ? DEMO_EXAMPLES.find((e) => e.key === key) : undefined);
  // Public demo: the 60-second tour (R2, demo/Landing.tsx): the imparfait
  // example's question, its comparison, then the source of the comparison's
  // first unit. Kept in this page's memory only; the step shown follows the
  // screen, so Back and Forward move along it too.
  const [tour, setTour] = useState(false);
  const [tourSource, setTourSource] = useState<{ conceptId: number; unitId: number } | null>(null);
  const tourStep = !tour
    ? 0
    : screen.kind === "example" && screen.example === TOUR.example
      ? 1
      : screen.kind === "compare" && screen.compare === TOUR.compare
        ? 2
        : screen.kind === "source" && screen.compare === TOUR.compare
          ? 3
          : 0;
  const tourReached = useRef(1);
  if (tourStep > 0) tourReached.current = tourStep;
  const tourGo = (step: number) => {
    if (step === 1) openExample(TOUR.example);
    else if (step === 2) openCompare(TOUR.compare);
    else if (step === 3 && tourSource) setScreen({ kind: "source", conceptId: tourSource.conceptId, unitId: tourSource.unitId, compare: TOUR.compare });
  };
  const startTour = () => {
    setTour(true);
    tourReached.current = 1;
    tourGo(1);
  };
  // Leaving the tour keeps the screen; focus goes to the screen's own heading.
  const leaveTour = () => {
    setTour(false);
    const focusHeading = () => {
      const heading = [...document.querySelectorAll<HTMLElement>("main h2[tabindex='-1']")].find((h) => !h.closest("[hidden]"));
      heading?.focus();
    };
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(focusHeading);
    else setTimeout(focusHeading, 0);
  };
  // A keyword search started by the page itself (an example this build lacks,
  // or a suggestion after a search found nothing), shown in the form too.
  const searchFor = (q: string) => {
    setDraft({ q, state: "all" });
    setDraftMode("keyword");
    if (screenRef.current.kind === "results") {
      runSearch({ q, state: "all" }, "keyword");
      return;
    }
    const next = { q, state: "all" as const };
    setQuery(next);
    setMode("keyword");
    searchRef.current = queryToSearch(next, "keyword");
    setScreen({ kind: "results" }, searchRef.current);
    if (demo) revealResults.current = true;
  };
  const requestedNonce = openRequest?.nonce ?? null;
  const requestedConcept = openRequest?.conceptId ?? null;
  useEffect(() => {
    if (requestedNonce !== null && requestedConcept !== null) setScreen({ kind: "concept", conceptId: requestedConcept });
  }, [requestedNonce, requestedConcept]);
  // Workbench: a search the address asks for (Back/Forward, an edited address).
  const requestedSearch = demo ? null : searchRequest;
  const appliedSearch = useRef(requestedSearch?.nonce ?? null);
  useEffect(() => {
    if (!requestedSearch || appliedSearch.current === requestedSearch.nonce) return;
    appliedSearch.current = requestedSearch.nonce;
    const next = { q: requestedSearch.q, state: requestedSearch.state };
    setDraft(next);
    setDraftMode("keyword");
    setQuery(next);
    setMode("keyword");
    setScreenState({ kind: "results" });
  }, [requestedSearch]);
  // Workbench: the address names the keyword search shown (semantic and hybrid
  // searches are not part of it).
  useEffect(() => {
    if (demo || !onSearchChange) return;
    onSearchChange(mode === "keyword" ? { q: query.q, state: query.state } : { q: "", state: "all" });
  }, [demo, onSearchChange, mode, query.q, query.state]);
  // Workbench: recent keyword searches, kept only in this browser (recentSearches.ts).
  const [recent, setRecent] = useState<RecentSearch[] | null>(() => (demo ? [] : readRecent()));
  const [recentUnsaved, setRecentUnsaved] = useState(false);
  const keepRecent = (next: RecentSearch[] | null) => {
    if (next === null) setRecentUnsaved(true);
    else {
      setRecent(next);
      setRecentUnsaved(false);
    }
  };
  const runRecent = (r: RecentSearch) => {
    setDraft({ q: r.q, state: r.state });
    setDraftMode("keyword");
    runSearch({ q: r.q, state: r.state }, "keyword");
    if (recent) keepRecent(addRecent(recent, r));
  };
  const resultsLabel = query.q ? t(resultsLabelKey[mode], { q: query.q }) : t(modeSearchKey[mode]);
  const strong = (key: MessageKey) => <strong>{t(key)}</strong>;
  // How search works. The workbench keeps it in the form; the public demo shows
  // it after the results, so a submitted search's results follow the form
  // directly instead of several screens of explanation on a phone.
  const searchHelp = (
    <>
      <p className="hint">
        {tn("library.terms", { concept: strong("library.term.concept"), unit: strong("library.term.unit") })}
      </p>
      <p className="hint">{t("library.searchScope")}</p>
      {demo ? (
        <p className="hint">{tn("library.semantic.demo", { semantic: strong("library.mode.semantic") })}</p>
      ) : (
        <p className="hint">{tn("library.semantic.full", { semantic: strong("library.mode.semantic") })}</p>
      )}
      <p className="hint">{tn("library.hybrid.explain", { hybrid: strong("library.mode.hybrid") })}</p>
    </>
  );
  // The practice session on screen, or kept mounted behind a source opened from it.
  const practice =
    screen.kind === "practice"
      ? { conceptId: screen.conceptId, session: screen.session }
      : screen.kind === "source" && screen.practice !== undefined
        ? { conceptId: screen.conceptId, session: screen.practice }
        : null;

  // A keyword search's results (and, in the public demo, the last search that
  // worked, shown under a failed one).
  const keywordResults = (data: LibrarySearch, shown: LibraryQuery) => (
    <Results
      search={{ status: "ready", data }}
      query={shown}
      onOpen={openConcept}
      onRetry={() => setRetry((n) => n + 1)}
      onShowMore={() => runSearch({ ...shown, limit: MAX_LIBRARY_LIMIT }, "keyword")}
      demo={Boolean(demo)}
      evidence={
        demo
          ? {
              href: (conceptId, unitId) => hashForScreen({ kind: "source", conceptId, unitId }, searchRef.current) || "#",
              open: (conceptId, unitId) => setScreen({ kind: "source", conceptId, unitId }),
            }
          : undefined
      }
      noMatchHelp={
        guided ? (
          <NoMatchHelp
            query={query.q}
            onOpenExample={openExample}
            onSearch={(q) => {
              searchFor(q);
              document.getElementById("library-query")?.focus();
            }}
          />
        ) : undefined
      }
    />
  );
  // Public demo: the last keyword search that worked, kept for when one fails.
  if (demo && search.status === "ready" && search.data.kind === "keyword") lastKeyword.current = { query, data: search.data.data };
  const previousKeyword =
    demo && search.status === "error" && lastKeyword.current && !sameQuery(lastKeyword.current.query, query) ? lastKeyword.current : null;
  // R2-045 (public demo): one polite status region, on the page before any
  // search, says that a submitted search is running and then what it found.
  // (A status line inserted with its text, as the results below are, is not
  // announced by every screen reader.)
  // Its own wording, so it never repeats a visible line word for word.
  const found =
    search.status !== "ready" || search.data.kind === "needs-query"
      ? 0
      : search.data.kind === "keyword"
        ? search.data.data.total_matches
        : search.data.data.results.length;
  // What was searched: the words, or a status filter used without words.
  const subject = query.q || (query.state !== "all" ? i18n.status(query.state) : "");
  const announcement =
    !demo || !subject || screen.kind !== "results"
      ? ""
      : search.status === "loading"
        ? t("demo.announce.searching", { q: subject })
        : search.status === "error"
          ? t("demo.announce.failed", { q: subject, message: search.message })
          : found === 0
            ? t("demo.announce.none", { q: subject })
            : i18n.tp("demo.announce.found", found, { q: subject });
  return (
    <main className="library">
      {demo ? (
        <p className="visually-hidden" role="status" id="demo-search-status">
          {announcement}
        </p>
      ) : null}
      {demo && tour ? (
        <TourBar
          step={tourStep}
          canNext={tourStep !== 2 || tourSource !== null}
          onNext={() => tourGo(Math.min(tourStep + 1, TOUR_STEPS))}
          onResume={() => tourGo(tourReached.current)}
          onLeave={leaveTour}
        />
      ) : null}
      <div hidden={screen.kind !== "results"}>
        {demo && badLink ? (
          <div className="banner info demo-bad-link" role="status">
            {t("demo.link.malformed")}
            {guided ? (
              <>
                {" "}
                {/* A concrete way on: the first guided example, as a new entry. */}
                <button type="button" className="ghost" id="demo-bad-link-example" onClick={() => openExample(DEMO_EXAMPLES[0].key)}>
                  {t("demo.missing.openExample", { title: t(DEMO_EXAMPLES[0].title) })}
                </button>
              </>
            ) : null}
          </div>
        ) : null}
        {intro}
        {guided ? <StartPoints onTour={startTour} /> : null}
        {guided ? <ExamplePicker onOpen={openExample} /> : null}
        {guided ? <ComparePicker onOpen={(key) => openCompare(key)} onPractice={(key) => openCompare(key, true)} /> : null}
        {about}
        {guided ? (
          <>
            <h2 className="demo-section-heading" id="demo-search-heading" tabIndex={-1}>
              {t("demo.search.heading")}
            </h2>
            {/* R2-033: searching is not browsing. */}
            <p className="hint demo-start-hint">{t("demo.start.hint")}</p>
          </>
        ) : null}
        <form className="panel library-search" role="search" onSubmit={submit} ref={searchFormRef}>
          {demo && draftMode !== "keyword" ? (
            <label htmlFor="library-preset">{t("library.exampleQuery")}</label>
          ) : (
            <label htmlFor="library-query">{t("library.searchLabel")}</label>
          )}
          <div className="discovery-search-row">
            {demo && draftMode !== "keyword" ? (
              <select id="library-preset" value={draftPreset} onChange={(e) => setDraftPreset(e.target.value)}>
                {demo.presets.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}: “{p.text}”
                  </option>
                ))}
              </select>
            ) : (
              <input
                id="library-query"
                type="search"
                value={draft.q}
                placeholder={t("library.placeholder")}
                onChange={(e) => setDraft({ ...draft, q: e.target.value })}
              />
            )}
            <select
              aria-label={t("library.stateFilter")}
              value={draft.state}
              onChange={(e) => setDraft({ ...draft, state: e.target.value as LibraryStateFilter })}
            >
              <option value="all">{t("library.state.all")}</option>
              <option value="active">{t("library.state.active")}</option>
              <option value="orphaned">{t("library.state.orphaned")}</option>
              <option value="retired">{t("library.state.retired")}</option>
            </select>
            <button type="submit" className="primary" id={demo ? "library-search-submit" : undefined}>
              {t("library.search")}
            </button>
            <button
              type="button"
              className="ghost"
              onClick={() => {
                setDraft({ q: "", state: "all" });
                setDraftMode("keyword");
                runSearch({ q: "", state: "all" }, "keyword");
              }}
            >
              {t("common.clear")}
            </button>
          </div>
          <fieldset className="library-mode">
            <legend>{t("library.mode")}</legend>
            <label>
              <input
                type="radio"
                name="library-mode"
                value="keyword"
                checked={draftMode === "keyword"}
                onChange={() => setDraftMode("keyword")}
              />{" "}
              {t("library.mode.keyword")}
            </label>{" "}
            <label>
              <input
                type="radio"
                name="library-mode"
                value="semantic"
                checked={draftMode === "semantic"}
                onChange={() => setDraftMode("semantic")}
              />{" "}
              {t("library.mode.semantic")}
            </label>{" "}
            <label>
              <input
                type="radio"
                name="library-mode"
                value="hybrid"
                checked={draftMode === "hybrid"}
                onChange={() => setDraftMode("hybrid")}
              />{" "}
              {t("library.mode.hybrid")}
            </label>
          </fieldset>
          {demo ? (
            <p className="hint" role="note">
              {tn("library.demo.note", { label: strong("library.demo.label") })}
            </p>
          ) : null}
          {guided ? (
            <SuggestedSearches
              onSearch={(q) => {
                searchFor(q);
                document.getElementById("library-query")?.focus();
              }}
            />
          ) : null}
          {demo ? null : (
            <RecentSearches
              recent={recent}
              unsaved={recentUnsaved}
              onRun={runRecent}
              onRemove={(r) => recent && keepRecent(removeRecent(recent, r))}
              onClear={() => keepRecent(clearRecent())}
            />
          )}
          {demo ? null : searchHelp}
        </form>
        {search.status === "ready" && search.data.kind === "keyword" ? (
          keywordResults(search.data.data, query)
        ) : search.status === "ready" && search.data.kind === "semantic" ? (
          <SemanticResults data={search.data.data} query={query} onOpen={openConcept} mechanical={demo ? !demo.artifact.real_model : false} />
        ) : search.status === "ready" && search.data.kind === "hybrid" ? (
          <HybridResults data={search.data.data} query={query} onOpen={openConcept} mechanical={demo ? !demo.artifact.real_model : false} />
        ) : search.status === "ready" ? (
          <p className="empty" role="status">{t(needsQueryKey[mode])}</p>
        ) : search.status === "loading" ? (
          // Public demo: announced by the search status region (R2-045), so
          // this line is not a second live region saying the same.
          <p className="empty" role={demo ? undefined : "status"}>
            {t("library.searching")}
          </p>
        ) : demo ? (
          <SearchProblem
            query={query.q}
            code={search.code}
            message={search.message}
            failed={t(searchFailedKey[mode], { message: search.message })}
            onRetry={() => setRetry((n) => n + 1)}
            onEdit={() => {
              const input = document.getElementById("library-query");
              if (input instanceof HTMLInputElement) {
                input.focus();
                input.select();
              }
            }}
            previous={previousKeyword ? { q: previousKeyword.query.q, results: keywordResults(previousKeyword.data, previousKeyword.query) } : null}
          />
        ) : (
          <div className="banner error" role="alert">
            {t(searchFailedKey[mode], { message: search.message })}{" "}
            <button type="button" className="ghost" onClick={() => setRetry((n) => n + 1)}>
              {t("common.tryAgain")}
            </button>
          </div>
        )}
        {demo ? <div className="panel demo-search-help">{searchHelp}</div> : null}
      </div>
      {screen.kind === "example" && guided && fromExample(screen.example) ? (
        <ExampleScreen
          key={`example-${screen.example}`}
          example={fromExample(screen.example)!}
          onBack={() => backFromExample(screen.example)}
          onSearch={searchFor}
          onOpenExample={openExample}
          onOpenComparison={(key) => openCompare(key)}
          onOpenConcept={(conceptId) => openConcept(conceptId, screen.example)}
          onOpenSource={(conceptId, unitId) => setScreen({ kind: "source", conceptId, unitId, from: screen.example })}
          step={screen.step}
          onStep={(step) => setScreen({ kind: "example", example: screen.example, step })}
          returnFocus={focusReturn}
        />
      ) : null}
      {screen.kind === "compare" && guided && findComparison(screen.compare) ? (
        <CompareScreen
          key={`compare-${screen.compare}`}
          comparison={findComparison(screen.compare)!}
          onBack={() => backFromCompare(screen.compare)}
          onSearch={searchFor}
          onOpenComparison={(key) => openCompare(key)}
          onOpenExample={openExample}
          onReady={(sides: SideResolution[]) => {
            const first = sides[0];
            if (screen.compare === TOUR.compare && first?.kind === "found" && first.source)
              setTourSource({ conceptId: first.concept.id, unitId: first.unit.unit_id });
          }}
          href={(conceptId, unitId) =>
            hashForScreen(
              unitId ? { kind: "source", conceptId, unitId, compare: screen.compare } : { kind: "concept", conceptId, compare: screen.compare },
              searchRef.current,
            ) || "#"
          }
          onOpenConcept={(conceptId) => setScreen({ kind: "concept", conceptId, compare: screen.compare })}
          onOpenSource={(conceptId, unitId) => setScreen({ kind: "source", conceptId, unitId, compare: screen.compare })}
          returnFocus={focusReturn}
        />
      ) : null}
      {screen.kind === "concept" ? (
        <ConceptScreen
          key={`concept-${screen.conceptId}`}
          conceptId={screen.conceptId}
          backLabel={
            comparisonTitle(screen.compare) ??
            (fromExample(screen.from)
              ? t("demo.example.backTo", { title: t(fromExample(screen.from)!.title) })
              : t("library.backTo", { label: resultsLabel }))
          }
          walkthrough={Boolean(guided && fromExample(screen.from))}
          onBack={() =>
            findComparison(screen.compare) ? backToCompare(screen.compare!) : screen.from ? backToExample(screen.from) : backToResults(screen.conceptId)
          }
          onOpenConcept={(conceptId) => setScreen({ kind: "concept", conceptId, from: screen.from, compare: screen.compare })}
          onOpenSource={(unitId) => setScreen({ kind: "source", conceptId: screen.conceptId, unitId, from: screen.from, compare: screen.compare })}
          demo={Boolean(demo)}
          returnFocus={demo ? focusReturn : undefined}
          onOpenExample={guided ? () => openExample(screen.from ?? DEMO_EXAMPLES[0].key) : undefined}
          onSearchLibrary={guided ? searchLibrary : undefined}
          exampleTitle={guided ? t(fromExample(screen.from ?? DEMO_EXAMPLES[0].key)!.title) : undefined}
          // The public demo has no recall practice.
          onPractice={
            demo
              ? undefined
              : () => setScreen({ kind: "practice", conceptId: screen.conceptId, session: ++practiceSession.current })
          }
        />
      ) : null}
      {practice && !PUBLIC_DEMO_BUILD ? (
        <div hidden={screen.kind !== "practice"}>
          <RecallPractice
            key={`practice-${practice.session}`}
            conceptId={practice.conceptId}
            visible={screen.kind === "practice"}
            onExit={() => openConcept(practice.conceptId)}
            onOpenSource={(unitId) =>
              setScreen({ kind: "source", conceptId: practice.conceptId, unitId, practice: practice.session })
            }
          />
        </div>
      ) : null}
      {screen.kind === "source" ? (
        <SourceScreen
          key={`source-${screen.unitId}`}
          unitId={screen.unitId}
          conceptId={screen.conceptId}
          backText={
            comparisonTitle(screen.compare) ??
            (fromExample(screen.from)
              ? t("demo.example.backTo", { title: t(fromExample(screen.from)!.title) })
              : t("library.backTo", { label: resultsLabel }))
          }
          walkthrough={Boolean(guided && fromExample(screen.from))}
          onBackToConcept={() => goBack({ kind: "concept", conceptId: screen.conceptId, from: screen.from, compare: screen.compare })}
          onBackToResults={() =>
            findComparison(screen.compare)
              ? backToCompare(screen.compare!)
              : screen.from
                ? backToExample(screen.from)
                : backToResults(screen.conceptId)
          }
          onBackToPractice={
            screen.practice !== undefined
              ? () => setScreen({ kind: "practice", conceptId: screen.conceptId, session: screen.practice! })
              : undefined
          }
          onOpenConcept={(conceptId) => setScreen({ kind: "concept", conceptId, from: screen.from, compare: screen.compare })}
          onOpenRecord={onOpenRecord}
          demo={Boolean(demo)}
          returnFocus={demo ? focusReturn : undefined}
          onOpenExample={guided ? () => openExample(screen.from ?? DEMO_EXAMPLES[0].key) : undefined}
          onSearchLibrary={guided ? searchLibrary : undefined}
          exampleTitle={guided ? t(fromExample(screen.from ?? DEMO_EXAMPLES[0].key)!.title) : undefined}
        />
      ) : null}
    </main>
  );
}

// ResultMeta is the stored Concept type and scope (data) followed by the counts.
function ResultMeta({
  concept,
  members,
  supporting,
  marks,
}: {
  concept: LibraryConcept["concept"];
  members: number;
  supporting: number;
  // A keyword result: the search's tokens and the fields that matched, so the
  // matching words of the type and scope are marked (libraryHighlight.tsx).
  marks?: { tokens: readonly string[]; fields: readonly string[] };
}) {
  const { tp } = useI18n();
  const shown = (field: string, text: string) => (marks && marks.fields.includes(field) ? markMatches(text, marks.tokens) : text);
  return (
    <div className="hint">
      {shown("pedagogical_intent", concept.pedagogical_intent)}
      {concept.scope ? <> · {shown("scope", concept.scope)}</> : ""} · {tp("library.resultMeta", members, { supporting, id: concept.id })}
    </div>
  );
}

// MatchedWords lists a keyword search's normalized tokens (the words every
// result matched, AND semantics), each marked. Public demo only.
function MatchedWords({ tokens }: { tokens: readonly string[] }) {
  const { t } = useI18n();
  return (
    <>
      {tokens.map((token, i) => (
        <span key={token}>
          {i > 0 ? t("library.fieldSeparator") : ""}
          <mark>{token}</mark>
        </span>
      ))}
    </>
  );
}

// FeatureSnippet shows the identity details a keyword search matched, with the
// matching words marked (libraryHighlight.tsx), in the Concept's own wording.
function FeatureSnippet({ features, tokens }: { features: Record<string, unknown>; tokens: readonly string[] }) {
  const shown = matchedFeatures(features, tokens);
  if (shown.length === 0) return null;
  return (
    <div className="library-snippet" dir="auto">
      {shown.map((node, i) => (
        <span key={i}>
          {i > 0 ? " · " : ""}
          {node}
        </span>
      ))}
    </div>
  );
}

// RecentSearches lists the workbench's recent keyword searches and says where
// they are kept. Nothing is shown before the first search; a browser that
// refuses storage is told the list is not kept.
function RecentSearches({
  recent,
  unsaved,
  onRun,
  onRemove,
  onClear,
}: {
  recent: RecentSearch[] | null;
  unsaved: boolean;
  onRun: (r: RecentSearch) => void;
  onRemove: (r: RecentSearch) => void;
  onClear: () => void;
}) {
  const { t, status } = useI18n();
  if (recent === null || unsaved) return <p className="hint">{t("library.recent.unavailable")}</p>;
  if (recent.length === 0) return null;
  const label = (r: RecentSearch) => (r.state === "all" ? r.q : t("library.recent.withState", { q: r.q, state: status(r.state) }));
  return (
    <div className="library-recent" role="group" aria-labelledby="library-recent-heading">
      <span id="library-recent-heading" className="label">
        {t("library.recent.heading")}
      </span>{" "}
      <ul>
        {recent.map((r) => (
          <li key={`${r.state}\u0000${r.q}`}>
            <button type="button" className="ghost" onClick={() => onRun(r)}>
              <span lang="fr" dir="auto">
                {label(r)}
              </span>
            </button>
            <button type="button" className="ghost recent-remove" aria-label={t("library.recent.remove", { q: label(r) })} onClick={() => onRemove(r)}>
              ×
            </button>
          </li>
        ))}
      </ul>{" "}
      <button type="button" className="ghost" onClick={onClear}>
        {t("library.recent.clear")}
      </button>
      <p className="hint">{t("library.recent.storage")}</p>
    </div>
  );
}

// The backend's largest page of keyword results (application.ParseLibrarySearchQuery).
const MAX_LIBRARY_LIMIT = 50;

const sameQuery = (a: LibraryQuery, b: LibraryQuery) => a.q === b.q && a.state === b.state && (a.limit ?? 0) === (b.limit ?? 0) && (a.preset ?? "") === (b.preset ?? "");

function Results({
  search,
  query,
  onOpen,
  onRetry,
  demo = false,
  noMatchHelp,
  onShowMore,
  evidence,
}: {
  search: Load<LibrarySearch>;
  query: LibraryQuery;
  onOpen: (conceptId: number) => void;
  onRetry: () => void;
  // Public demo: an empty catalog is described as the demo build's, and a
  // search or filter that finds nothing is followed by `noMatchHelp`.
  demo?: boolean;
  noMatchHelp?: ReactNode;
  // A truncated search can ask for up to MAX_LIBRARY_LIMIT results (the backend's limit).
  onShowMore?: () => void;
  // Public demo: "Why it matched" under each keyword result (demo/EvidenceCard.tsx),
  // with the link to a matched unit's source record and the move to it.
  evidence?: { href: (conceptId: number, unitId: number) => string; open: (conceptId: number, unitId: number) => void };
}) {
  const i18n = useI18n();
  const { t, tp, tn, status } = i18n;
  if (search.status === "loading") return <p className="empty" role="status">{t("library.searching")}</p>;
  if (search.status === "error")
    return (
      <div className="banner error" role="alert">
        {t("library.searchFailed.keyword", { message: search.message })}{" "}
        <button type="button" className="ghost" onClick={onRetry}>
          {t("common.tryAgain")}
        </button>
      </div>
    );
  const data = search.data;
  // The words named with the count and the "no match" message are the query
  // the server executed (`data.query`), so they always describe these results.
  const executed = typeof data.query === "string" ? data.query : query.q;
  // Match metadata may be absent (an older server): no marks, no field list.
  const tokens = Array.isArray(data.tokens) ? data.tokens : [];
  const matched = (r: LibrarySearchResult) => (Array.isArray(r.matched_fields) ? r.matched_fields : []);
  if (data.results.length === 0) {
    const message = executed
      ? query.state === "all"
        ? t("library.noMatch", { q: executed })
        : t("library.noMatchState", { q: executed, state: status(query.state) })
      : query.state === "all"
        ? t(demo ? "demo.library.empty" : "library.empty")
        : t("library.emptyState", { state: status(query.state) });
    const empty = (
      <div className="empty" role={demo ? undefined : "status"}>
        {message}
      </div>
    );
    return noMatchHelp && (executed || query.state !== "all") ? (
      <div className="demo-no-match">
        {empty}
        {noMatchHelp}
      </div>
    ) : (
      empty
    );
  }
  return (
    <section aria-label={t("library.results")}>
      <p className="hint" role={demo ? undefined : "status"}>
        {data.truncated
          ? t("library.truncated", { shown: data.results.length, total: data.total_matches })
          : executed
            ? tp("library.countMatching", data.total_matches, { q: executed })
            : tp("library.count", data.total_matches)}
        {data.truncated && onShowMore && data.limit < MAX_LIBRARY_LIMIT ? (
          <>
            {" "}
            <button type="button" className="ghost" onClick={onShowMore}>
              {t("library.showMore", { max: Math.min(MAX_LIBRARY_LIMIT, data.total_matches) })}
            </button>
          </>
        ) : null}
      </p>
      <ol className="library-results">
        {data.results.map((r) => (
          <li key={r.concept.id} className="panel library-result">
            <button type="button" className="link-button" id={resultButtonId(r.concept.id)} onClick={() => onOpen(r.concept.id)}>
              {matched(r).includes("target") ? markMatches(r.concept.target, tokens) : r.concept.target}
            </button>{" "}
            <StateTag state={r.concept.state} />
            <ResultMeta
              concept={r.concept}
              members={r.current_member_count}
              supporting={r.supporting_unit_count}
              marks={r.match_tier !== "browse" ? { tokens, fields: matched(r) } : undefined}
            />
            {matched(r).includes("identity_features") ? <FeatureSnippet features={r.concept.identity_features} tokens={tokens} /> : null}
            {r.match_tier !== "browse" && demo ? (
              // Public demo: say which words matched where, from the search's own
              // tokens and matched fields, and offer "Why it matched", which
              // reads the matched wording, including a unit's (EvidenceCard).
              <>
                {matched(r).length > 0 && tokens.length > 0 ? (
                  <div className="hint demo-match">
                    {tn(r.match_tier === "unit_evidence" ? "demo.result.foundInUnits" : "demo.result.foundIn", {
                      words: <MatchedWords tokens={tokens} />,
                      fields: fieldList(i18n, matched(r)),
                    })}
                  </div>
                ) : null}
                {evidence ? (
                  <EvidenceCard
                    key={`${data.query}\u0000${r.concept.id}`}
                    result={r}
                    tokens={tokens}
                    sourceHref={(unitId) => evidence.href(r.concept.id, unitId)}
                    onOpenSource={(unitId) => evidence.open(r.concept.id, unitId)}
                  />
                ) : null}
              </>
            ) : r.match_tier !== "browse" ? (
              <div className="hint">
                {t(r.match_tier === "unit_evidence" ? "library.foundInUnits" : "library.foundIn", {
                  fields: fieldList(i18n, matched(r)),
                })}
              </div>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}

// MechanicalNotice sits next to semantic and hybrid scores in a public demo
// built with mechanical vectors: those scores show ranking mechanics only and
// must never read as evidence that a Concept is relevant.
function MechanicalNotice() {
  const { t, tn } = useI18n();
  return (
    <div className="banner info demo-mechanical-results" role="note">
      {tn("demo.results.mechanical", { strong: <strong>{t("demo.results.mechanical.strong")}</strong> })}
    </div>
  );
}

function SemanticResults({
  data,
  query,
  onOpen,
  mechanical = false,
}: {
  data: SemanticSearch;
  query: LibraryQuery;
  onOpen: (conceptId: number) => void;
  // Public demo with mechanical vectors.
  mechanical?: boolean;
}) {
  const i18n = useI18n();
  const { t, tp, tn, status } = i18n;
  const dropped = data.skipped.stale + data.skipped.missing + data.skipped.incompatible;
  const idx = data.index;
  const lastRunOk = idx.last_run_outcome === "published" || idx.last_run_outcome === "verified_unchanged";
  const outcome = idx.last_run_outcome ? spaced(i18n, idx.last_run_outcome) : "";
  return (
    <section aria-label={t("library.semanticResults")}>
      {mechanical ? <MechanicalNotice /> : null}
      {!lastRunOk && idx.last_run_outcome ? (
        <div className="banner info" role="status">
          {tn(idx.last_error ? "library.lastRun.failedError" : "library.lastRun.failed", {
            outcome,
            error: idx.last_error,
            status: <code>semantic-index status</code>,
            sync: <code>semantic-index sync</code>,
          })}
        </div>
      ) : null}
      <p className="hint" role="status">
        {query.state === "all"
          ? tp("library.semantic.count", data.results.length, { q: data.query, model: idx.model_id })
          : tp("library.semantic.countState", data.results.length, {
              q: data.query,
              state: status(query.state),
              model: idx.model_id,
            })}
      </p>
      <p className="hint">
        {t("library.semantic.index", {
          published: idx.published_at ?? t("library.semantic.unknownTime"),
          operation: idx.last_run_operation || t("library.semantic.noRun"),
          outcome,
        })}
      </p>
      {dropped > 0 || data.filtered_by_state > 0 ? (
        <p className="hint">
          {data.filtered_by_state > 0
            ? tp("library.semantic.droppedFiltered", dropped, { filtered: data.filtered_by_state })
            : tp("library.semantic.dropped", dropped)}
        </p>
      ) : null}
      {data.results.length === 0 ? (
        <p className="empty">{t("library.semantic.none", { q: data.query })}</p>
      ) : (
        <ol className="library-results">
          {data.results.map((r) => (
            <li key={r.concept.id} className="panel library-result">
              <button type="button" className="link-button" id={resultButtonId(r.concept.id)} onClick={() => onOpen(r.concept.id)}>
                {r.concept.target}
              </button>{" "}
              <StateTag state={r.concept.state} />
              <ResultMeta concept={r.concept} members={r.current_member_count} supporting={r.supporting_unit_count} />
              <div className="hint">{t("library.similarity", { value: r.similarity.toFixed(2) })}</div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function HybridResults({
  data,
  query,
  onOpen,
  mechanical = false,
}: {
  data: HybridSearch;
  query: LibraryQuery;
  onOpen: (conceptId: number) => void;
  // Public demo with mechanical vectors.
  mechanical?: boolean;
}) {
  const i18n = useI18n();
  const { t, tp, status } = i18n;
  const kw = data.components.keyword;
  const sem = data.components.semantic;
  const semDropped = sem.skipped.stale + sem.skipped.missing + sem.skipped.incompatible;
  const fusedDropped =
    data.dropped_after_fusion.missing + data.dropped_after_fusion.filtered_by_state + data.dropped_after_fusion.changed_during_search;
  const stateFiltered = query.state !== "all";
  return (
    <section aria-label={t("library.hybridResults")}>
      {mechanical ? <MechanicalNotice /> : null}
      <p className="hint" role="status">
        {data.truncated
          ? t(stateFiltered ? "library.hybrid.truncatedState" : "library.hybrid.truncated", {
              shown: data.results.length,
              total: data.total_candidates,
              q: data.query,
              state: status(query.state),
            })
          : tp(stateFiltered ? "library.hybrid.countState" : "library.hybrid.count", data.results.length, {
              q: data.query,
              state: status(query.state),
            })}
      </p>
      <p className="hint">
        {t(kw.truncated_at_depth ? "library.hybrid.policyCut" : "library.hybrid.policy", {
          depth: data.depth,
          found: kw.total_matches,
          used: kw.returned,
          returned: sem.returned,
          collection: sem.index.collection,
          model: sem.index.model_id,
          policy: data.policy.version,
          k: data.policy.rrf_k,
        })}
      </p>
      {semDropped > 0 || sem.filtered_by_state > 0 || fusedDropped > 0 ? (
        <p className="hint">
          {sem.filtered_by_state > 0
            ? tp("library.hybrid.semDroppedFiltered", semDropped, { filtered: sem.filtered_by_state })
            : tp("library.hybrid.semDropped", semDropped)}{" "}
          {tp("library.hybrid.fusedDropped", fusedDropped)}
        </p>
      ) : null}
      {data.results.length === 0 ? (
        <p className="empty">{t("library.hybrid.none", { q: data.query })}</p>
      ) : (
        <ol className="library-results">
          {data.results.map((r) => (
            <li key={r.concept.id} className="panel library-result">
              <button type="button" className="link-button" id={resultButtonId(r.concept.id)} onClick={() => onOpen(r.concept.id)}>
                {r.concept.target}
              </button>{" "}
              <StateTag state={r.concept.state} />
              <ResultMeta concept={r.concept} members={r.current_member_count} supporting={r.supporting_unit_count} />
              <div className="hint">
                {r.keyword
                  ? t("library.hybrid.keyword", { rank: r.keyword.rank, fields: fieldList(i18n, r.keyword.matched_fields) })
                  : t("library.hybrid.noKeyword")}
                {" · "}
                {r.semantic
                  ? t("library.hybrid.semantic", { rank: r.semantic.rank, value: r.semantic.similarity.toFixed(2) })
                  : t("library.hybrid.noSemantic")}
                {" · "}
                {t("library.hybrid.score", { score: r.fused_score.toFixed(4) })}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function StateTag({ state }: { state: "active" | "orphaned" | "retired" }) {
  const { status } = useI18n();
  return <span className={`tag ${state}`}>{status(state)}</span>;
}

const supportText: Record<string, MessageKey> = {
  active: "library.support.active",
  orphaned: "library.support.orphaned",
  retired: "library.support.retired",
};

// Public demo props of the Concept and source screens: the control to focus on
// the way back, and the guided example a "not in this demo" screen offers.
type DemoReturn = {
  returnFocus?: MutableRefObject<string | null>;
  onOpenExample?: () => void;
  exampleTitle?: string;
  // R2-038: the search, one tap away from a link that names nothing.
  onSearchLibrary?: () => void;
};

// NotInDemo is the public demo's answer to a link naming a Concept or unit this
// build does not have (the server's 404): what happened, a working example to
// continue with, and the search. Retrying cannot help, so it is not offered;
// the return bar above still leads back.
function NotInDemo({ message, onOpenExample, exampleTitle, onSearchLibrary }: { message: string } & DemoReturn) {
  const { t } = useI18n();
  return (
    <div className="banner info demo-not-found" role="status">
      <p>{message}</p>
      {(onOpenExample && exampleTitle) || onSearchLibrary ? (
        <div className="actions">
          {onOpenExample && exampleTitle ? (
            <button type="button" className="primary" id="demo-not-found-example" onClick={onOpenExample}>
              {t("demo.missing.openExample", { title: exampleTitle })}
            </button>
          ) : null}
          {onSearchLibrary ? (
            <button type="button" className="ghost" id="demo-not-found-search" onClick={onSearchLibrary}>
              {t("demo.start.search")}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function ConceptScreen({
  conceptId,
  backLabel,
  onBack,
  onOpenConcept,
  onOpenSource,
  onPractice,
  demo = false,
  walkthrough = false,
  returnFocus,
  onOpenExample,
  exampleTitle,
  onSearchLibrary,
}: {
  conceptId: number;
  backLabel: string;
  onBack: () => void;
  onOpenConcept: (conceptId: number) => void;
  onOpenSource: (unitId: number) => void;
  // Starts recall practice; absent in the public demo, where it is not offered.
  onPractice?: () => void;
  // Public demo presentation: the back action stays in view, identity details
  // fold away, each supporting unit says why it is evidence, and empty
  // curation sections are left out. The data and its meaning are unchanged.
  demo?: boolean;
  // Public demo, opened from a guided example: this is step 3 of its walk.
  walkthrough?: boolean;
} & DemoReturn) {
  const i18n = useI18n();
  const { t, tp, tn, status } = i18n;
  const [retry, setRetry] = useState(0);
  const load = useLoad<LibraryConcept>(String(conceptId), () => api.getLibraryConcept(conceptId), retry);
  const headingRef = useFocusedHeading(load.status, returnFocus);
  const back = (
    <button type="button" className="ghost" onClick={onBack}>
      {backLabel}
    </button>
  );
  if (load.status !== "ready")
    return (
      <>
      {demo ? <nav className="demo-return" aria-label={t("demo.return")}>{back}</nav> : null}
      <section className="panel" aria-label={t("library.concept.region")}>
        <h2 ref={headingRef} tabIndex={-1}>
          {t("library.concept.heading", { id: conceptId })}
        </h2>
        {demo ? null : back}
        {load.status === "loading" ? (
          <p className="hint" role="status">{t("library.concept.loading", { id: conceptId })}</p>
        ) : demo && load.code === 404 ? (
          <NotInDemo message={t("demo.missing.concept", { id: conceptId })} onOpenExample={onOpenExample} exampleTitle={exampleTitle} onSearchLibrary={onSearchLibrary} />
        ) : (
          <div className="banner error" role="alert">
            {t("library.concept.failed", { id: conceptId, message: load.message })}{" "}
            <button type="button" className="ghost" onClick={() => setRetry((n) => n + 1)}>
              {t("common.tryAgain")}
            </button>
          </div>
        )}
      </section>
      </>
    );
  const d = load.data;
  const c = d.concept;
  const features = Object.entries(c.identity_features);
  const identity = (
    <>
      <dl className="unit-evidence">
        <Row label={t("library.row.status")}>{supportText[c.state] ? t(supportText[c.state]) : c.state}</Row>
        <Row label={t("library.row.type")}>{c.pedagogical_intent}</Row>
        <Row label={t("library.row.scope")}>{c.scope || <em>{t("library.notSet")}</em>}</Row>
        <Row label={t("library.row.identity")}>
          {features.length ? features.map(([k, v]) => `${k}: ${v}`).join(" · ") : <em>{t("library.noneLower")}</em>}
        </Row>
      </dl>
      <p className="hint">{t("library.filedVersusSupporting")}</p>
      <p className="hint">
        {t("library.concept.meta", { id: c.id, lifecycle: status(c.lifecycle_state), support: status(c.support_state) })}
      </p>
    </>
  );
  // Within a section a unit appears once, except relations: one unit may hold
  // several distinct relations to this concept, so those rows key by link ID.
  // `section` names the list a card is in: the public demo gives each source
  // button an id from it, so coming back from the source focuses that button.
  const unit = (u: LibraryUnit, note: ReactNode, section: string, key: string | number = u.unit_id) => (
    <UnitCard
      key={key}
      unit={u}
      note={note}
      sourceId={demo ? `library-source-${section}-${key}` : undefined}
      onOpenSource={() => onOpenSource(u.unit_id)}
      // Two units from one record would otherwise share one button name.
      sourceLabel={demo ? t("demo.concept.viewSourceFor", { record: u.entry_id, unit: u.unit_id }) : undefined}
    />
  );
  return (
    <div>
      {demo ? <nav className="demo-return" aria-label={t("demo.return")}>{back}</nav> : null}
      <section className="panel library-concept" aria-label={t("library.concept.region")}>
        {demo ? <p className="demo-eyebrow">{t(walkthrough ? "demo.walk.step3" : "demo.concept.eyebrow")}</p> : null}
        <h2 ref={headingRef} tabIndex={-1} className="library-title">
          {c.target} <StateTag state={c.state} />
        </h2>
        {walkthrough ? <p className="demo-walk-next">{t("demo.walk.next3")}</p> : null}
        {demo ? (
          <details className="demo-details">
            <summary>{t("demo.concept.details")}</summary>
            {identity}
          </details>
        ) : (
          <>
            {back}
            {identity}
          </>
        )}
      </section>

      {onPractice ? (
        <section className="panel library-section" aria-labelledby="lib-practice">
          <h3 id="lib-practice">{t("practice.entry.heading")}</h3>
          {c.state === "retired" ? (
            <p className="hint">{t("practice.entry.retired")}</p>
          ) : d.supporting_units.length === 0 ? (
            <p className="hint">{t("practice.entry.noSupport")}</p>
          ) : (
            <>
              <p className="hint">{t("practice.entry.hint")}</p>
              <button type="button" className="primary" onClick={onPractice}>
                {t("practice.entry.start")}
              </button>
            </>
          )}
        </section>
      ) : null}

      {/* The public demo leaves the section out when no unit was chosen, like
          the other empty curation sections. */}
      {demo && !d.preferred_unit ? null : (
        <section className="panel library-section current" aria-labelledby="lib-preferred">
          <h3 id="lib-preferred">{t("library.preferred")}</h3>
          {d.preferred_unit ? (
            unit(d.preferred_unit, preferredNote(i18n, d.preferred_unit, d), "preferred")
          ) : (
            <p className="hint">{t("library.preferred.none")}</p>
          )}
        </section>
      )}

      <section className="panel library-section current" aria-labelledby="lib-support">
        <h3 id="lib-support">{t("library.supporting", { count: d.supporting_units.length })}</h3>
        {d.supporting_units.length ? (
          d.supporting_units.map((u) => unit(u, demo ? t("demo.concept.whyEvidence", { record: u.entry_id }) : undefined, "supporting"))
        ) : (
          <p className="hint">{t("library.supporting.none")}</p>
        )}
      </section>

      {d.non_supporting_members.length ? (
        <section className="panel library-section" aria-labelledby="lib-members">
          <h3 id="lib-members">{t("library.members", { count: d.non_supporting_members.length })}</h3>
          <p className="hint">{t("library.members.hint")}</p>
          {d.non_supporting_members.map((u) => unit(u, <span>{notSupportingReasons(i18n, u).join(" ")}</span>, "member"))}
        </section>
      ) : null}

      {demo && d.current_relations.length === 0 ? null : (
      <section className="panel library-section" aria-labelledby="lib-relations">
        <h3 id="lib-relations">{t("library.relations", { count: d.current_relations.length })}</h3>
        <p className="hint">{t("library.relations.hint")}</p>
        {d.current_relations.length ? (
          d.current_relations.map((r) =>
            unit(
              r.unit,
              <span>
                {tn("library.relations.note", {
                  relation: <strong>{r.relation.toUpperCase()}</strong>,
                  unit: r.unit.unit_id,
                  link: r.link_id,
                  source: r.decision_source,
                })}
              </span>,
              "relation",
              r.link_id,
            ),
          )
        ) : (
          <p className="hint">{t("library.relations.none")}</p>
        )}
      </section>
      )}

      {demo && d.historical_units.length === 0 ? null : (
      <section className="panel library-section history" aria-labelledby="lib-history">
        <h3 id="lib-history">{t("library.history", { count: d.historical_units.length })}</h3>
        <p className="hint">{tp("library.history.hint", d.history_event_count)}</p>
        {d.historical_units.length
          ? d.historical_units.map((h) => unit(h.unit, <HistoricalNote h={h} onOpenConcept={onOpenConcept} />, "history"))
          : <p className="hint">{t("library.history.none")}</p>}
      </section>
      )}
    </div>
  );
}

function preferredNote(i: I18n, u: LibraryUnit, d: LibraryConcept): string {
  const supporting = d.supporting_units.some((s) => s.unit_id === u.unit_id);
  return supporting
    ? i.t("library.preferred.supporting")
    : i.t("library.preferred.notSupporting", { reasons: notSupportingReasons(i, u).join(" ") });
}

function notSupportingReasons(i: I18n, u: LibraryUnit): string[] {
  const reasons: string[] = [];
  if (!u.in_current_extraction)
    reasons.push(i.t("library.reason.oldExtraction", { version: u.extraction_version, record: u.entry_id }));
  if (u.admission === "suppressed") reasons.push(i.t("library.reason.suppressed"));
  else if (u.admission !== "active") reasons.push(i.t("library.reason.waiting", { admission: spaced(i, u.admission) }));
  return reasons;
}

function HistoricalNote({ h, onOpenConcept }: { h: LibraryHistoricalUnit; onOpenConcept: (id: number) => void }) {
  const { t, tn, status } = useI18n();
  const e = h.latest_event;
  return (
    <span>
      {h.effective_status === "invalid"
        ? t("library.historical.invalid")
        : h.current_concept_id !== null
          ? tn("library.historical.moved", {
              concept: (
                <button type="button" className="link-button" onClick={() => onOpenConcept(h.current_concept_id!)}>
                  {t("library.conceptLink", { id: h.current_concept_id })}
                </button>
              ),
            })
          : t("library.historical.unfiled")}
      {!h.unit.in_current_extraction ? <>{" "}{t("library.historical.oldExtraction", { version: h.unit.extraction_version })}</> : ""}{" "}
      {t("library.historical.lastDecision", {
        relation: e.relation.toUpperCase(),
        status: status(e.status),
        source: e.decision_source,
        id: e.id,
      })}
    </span>
  );
}

function UnitCard({
  unit,
  note,
  onOpenSource,
  sourceLabel,
  sourceId,
}: {
  unit: LibraryUnit;
  note?: ReactNode;
  onOpenSource: () => void;
  // Public demo: an accessible name for the source button that also names the unit.
  sourceLabel?: string;
  // Public demo: the source button's id, to focus it again on the way back.
  sourceId?: string;
}) {
  const i18n = useI18n();
  const { t } = i18n;
  return (
    <article className="library-unit" aria-label={t("inspector.unit", { id: unit.unit_id })}>
      <div className="library-unit-head">
        <strong>{unit.canonical}</strong>{" "}
        <span className={`tag ${unit.in_current_extraction ? "active" : "retired"}`}>
          {unit.in_current_extraction ? t("library.unit.current") : t("library.unit.older", { version: unit.extraction_version })}
        </span>
      </div>
      <p>{unit.statement}</p>
      {unit.example ? <FrenchExample text={unit.example} /> : null}
      {note ? <p className="hint">{note}</p> : null}
      <div className="hint">
        {t("library.unit.meta", {
          id: unit.unit_id,
          kind: unit.kind,
          record: unit.entry_id,
          version: unit.extraction_version,
          admission: spaced(i18n, unit.admission),
        })}{" "}
        <button type="button" className="link-button" onClick={onOpenSource} aria-label={sourceLabel} id={sourceId}>
          {t("library.unit.viewSource", { id: unit.entry_id })}
        </button>
      </div>
    </article>
  );
}

// The French example is learner-facing study material: always shown as written, marked lang="fr".
function FrenchExample({ text }: { text: string }) {
  const { t } = useI18n();
  return (
    <p className="hint">
      {t("library.frenchExample")}{" "}
      <span lang="fr" className="french">
        {text}
      </span>
    </p>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

const resolutionText: Record<string, MessageKey> = {
  unreviewed: "library.resolution.unreviewed",
  accepted: "library.resolution.accepted",
  corrected: "library.resolution.corrected",
  rejected: "library.resolution.rejected",
};

// Public demo: a Concept's title for the evidence screen's labels, read once
// through the allowlisted Concept read. While it loads, or if the read fails,
// the labels name the Concept by its number only, as before.
function useConceptTitle(conceptId: number | null): string | null {
  const [title, setTitle] = useState<{ id: number; target: string } | null>(null);
  useEffect(() => {
    if (conceptId === null) return;
    let active = true;
    api
      .getLibraryConcept(conceptId)
      .then((d) => {
        if (active) setTitle({ id: conceptId, target: d.concept.target });
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [conceptId]);
  return title && title.id === conceptId ? title.target : null;
}

function SourceScreen({
  unitId,
  conceptId,
  backText,
  onBackToConcept,
  onBackToResults,
  onBackToPractice,
  onOpenConcept,
  onOpenRecord,
  demo = false,
  walkthrough = false,
  returnFocus,
  onOpenExample,
  exampleTitle,
  onSearchLibrary,
}: {
  unitId: number;
  conceptId: number;
  // Public demo, opened from a guided example: this is the last step of its walk.
  walkthrough?: boolean;
  // The second back action's full text: to the search results, or to the
  // guided example the source was opened from.
  backText: string;
  onBackToConcept: () => void;
  onBackToResults: () => void;
  // Set when the source was opened from recall practice: the only way back is
  // to that session, which is kept as it was left.
  onBackToPractice?: () => void;
  onOpenConcept: (conceptId: number) => void;
  onOpenRecord?: (entryId: number) => void;
  // Public demo presentation: the learner's question first, why this record is
  // shown, and the back actions kept in view; the extraction and interpretation
  // (the provenance trail) stay visible after the unit.
  demo?: boolean;
} & DemoReturn) {
  const i18n = useI18n();
  const { t, tn, status } = i18n;
  const [retry, setRetry] = useState(0);
  const load = useLoad<LibrarySource>(String(unitId), () => api.getLibraryUnitSource(unitId), retry);
  const headingRef = useFocusedHeading(load.status, returnFocus);
  // Public demo: name the Concept, not only its number, once its title is read.
  const conceptTitle = useConceptTitle(demo ? conceptId : null);
  const nav = onBackToPractice ? (
    <div className="actions">
      <button type="button" className="ghost" onClick={onBackToPractice}>
        {t("practice.source.back")}
      </button>
    </div>
  ) : (
    <div className="actions">
      <button type="button" className="ghost" onClick={onBackToConcept}>
        {conceptTitle !== null
          ? t("demo.source.backToConceptNamed", { id: conceptId, title: conceptTitle })
          : t("library.source.backToConcept", { id: conceptId })}
      </button>
      <button type="button" className="ghost" onClick={onBackToResults}>
        {backText}
      </button>
    </div>
  );
  if (load.status !== "ready")
    return (
      <>
      {demo ? <nav className="demo-return" aria-label={t("demo.return")}>{nav}</nav> : null}
      <section className="panel" aria-label={t("library.source.region")}>
        <h2 ref={headingRef} tabIndex={-1}>
          {t("library.source.heading", { id: unitId })}
        </h2>
        {demo ? null : nav}
        {load.status === "loading" ? (
          <p className="hint" role="status">{t("library.source.loading", { id: unitId })}</p>
        ) : demo && load.code === 404 ? (
          <NotInDemo message={t("demo.missing.source", { id: unitId })} onOpenExample={onOpenExample} exampleTitle={exampleTitle} onSearchLibrary={onSearchLibrary} />
        ) : (
          <div className="banner error" role="alert">
            {t("library.source.failed", { id: unitId, message: load.message })}{" "}
            <button type="button" className="ghost" onClick={() => setRetry((n) => n + 1)}>
              {t("common.tryAgain")}
            </button>
          </div>
        )}
      </section>
      </>
    );
  const s = load.data;
  const interp = s.source_interpretation;
  const isCurrent = s.unit.in_current_extraction;
  const newer = s.latest_analysis && s.latest_analysis.id !== interp.analysis.id ? s.latest_analysis : null;
  const resolution = resolutionText[interp.effective.resolution]
    ? t(resolutionText[interp.effective.resolution])
    : interp.effective.resolution;
  const processing = (
    <>
      <section className={`panel library-section ${isCurrent ? "current" : "history"}`} aria-labelledby="src-extraction">
        <h3 id="src-extraction">{t("library.source.extraction", { version: s.extraction.version })}</h3>
        <p className="hint">{t("library.source.extraction.hint")}</p>
        <p>
          {isCurrent
            ? t("library.source.extraction.current")
            : s.current_extraction.extraction_id === null
              ? t("library.source.extraction.historical")
              : t(
                  s.current_extraction.selection_mode === "pinned"
                    ? "library.source.extraction.historicalPinned"
                    : "library.source.extraction.historicalAutomatic",
                  { id: s.current_extraction.extraction_id },
                )}
        </p>
        <p className="hint">
          {t("library.source.extraction.meta", {
            id: s.extraction.id,
            extractor: s.extraction.extractor,
            created: s.extraction.created_at,
          })}
        </p>
      </section>

      <section className="panel library-section" aria-labelledby="src-interp">
        <h3 id="src-interp">{t("library.source.interpretation", { version: interp.analysis.version })}</h3>
        <p className="hint">{t("library.source.interpretation.hint")}</p>
        <dl className="unit-evidence">
          <Row label={t("library.source.review")}>
            {interp.feedback
              ? t("library.source.review.feedback", { resolution, id: interp.feedback.id, status: status(interp.feedback.status) })
              : t("library.source.review.none", { resolution })}
          </Row>
          {interp.effective.effective ? (
            <>
              <Row label={t("effective.category")}>{interp.effective.effective.category}</Row>
              <Row label={t("library.source.explanationUsed")}>{interp.effective.effective.explanation}</Row>
            </>
          ) : (
            <Row label={t("library.source.explanationUsed")}>{t("library.source.rejected")}</Row>
          )}
          {interp.effective.resolution === "corrected" ? (
            <Row label={t("library.source.beforeCorrection")}>
              {interp.effective.original.category}: {interp.effective.original.explanation}
            </Row>
          ) : null}
          <Row label={t("library.source.producedBy")}>{interp.analysis.analyzer}</Row>
        </dl>
        <p className="hint">
          {newer
            ? t("library.source.newer", { newer: newer.version, version: interp.analysis.version })
            : t("library.source.latest", { version: interp.analysis.version })}
        </p>
      </section>
    </>
  );
  return (
    <div>
      {demo ? <nav className="demo-return" aria-label={t("demo.return")}>{nav}</nav> : null}
      <section className="panel" aria-label={t("library.source.region")}>
        {walkthrough ? <p className="demo-eyebrow">{t("demo.walk.step4")}</p> : null}
        <h2 ref={headingRef} tabIndex={-1} className="library-title">
          {t("library.source.title", { unit: s.unit.unit_id, record: s.entry.id })}
        </h2>
        {demo ? null : nav}
        {demo && s.annotation.status !== "invalid" && s.annotation.current_concept_id !== null ? (
          <p className="demo-why">
            {tn("demo.source.why", {
              concept: (
                <button
                  type="button"
                  className="link-button"
                  id="demo-source-concept"
                  onClick={() => onOpenConcept(s.annotation.current_concept_id!)}
                >
                  {conceptTitle !== null && s.annotation.current_concept_id === conceptId
                    ? t("demo.conceptNamed", { id: conceptId, title: conceptTitle })
                    : t("library.conceptLink", { id: s.annotation.current_concept_id })}
                </button>
              ),
              unit: s.unit.unit_id,
            })}
          </p>
        ) : null}
        <p className="hint">{t("library.source.hint")}</p>
      </section>
      {demo ? (
        <>
      <section className="panel library-section current" aria-labelledby="src-entry">
        <h3 id="src-entry">{t("library.source.entry", { id: s.entry.id })}</h3>
        {demo ? (
          <blockquote className="demo-question french" dir="auto">
            {s.entry.original_input}
          </blockquote>
        ) : null}
        <dl className="unit-evidence">
          {demo ? null : (
            <Row label={t("library.source.wrote")}>
              <span className="french">{s.entry.original_input}</span>
            </Row>
          )}
          <Row label={t("library.source.context")}>
            {s.entry.original_context ? (
              demo ? <bdi>{s.entry.original_context}</bdi> : s.entry.original_context
            ) : (
              <em>{t("library.noneLower")}</em>
            )}
          </Row>
          <Row label={t("library.source.recorded")}>
            <RecordedTime value={s.entry.created_at} locale={i18n.locale} />
          </Row>
        </dl>
        {onOpenRecord ? (
          <button type="button" className="ghost" onClick={() => onOpenRecord(s.entry.id)}>
            {t("library.source.openRecord", { id: s.entry.id })}
          </button>
        ) : null}
      </section>

      <section className="panel library-section" aria-labelledby="src-unit">
        <h3 id="src-unit">{t("library.source.unit", { id: s.unit.unit_id })}</h3>
        <p>
          <strong>{s.unit.canonical}</strong>: {s.unit.statement}
        </p>
        {s.unit.example ? <FrenchExample text={s.unit.example} /> : null}
        <p className="hint">
          {s.annotation.status === "invalid"
            ? t("library.source.now.invalid")
            : s.annotation.current_concept_id !== null
              ? tn("library.source.now.filed", {
                  concept: (
                    <button type="button" className="link-button" onClick={() => onOpenConcept(s.annotation.current_concept_id!)}>
                      {conceptTitle !== null && s.annotation.current_concept_id === conceptId
                    ? t("demo.conceptNamed", { id: conceptId, title: conceptTitle })
                    : t("library.conceptLink", { id: s.annotation.current_concept_id })}
                    </button>
                  ),
                })
              : t("library.source.now.none")}{" "}
          {t("library.source.nowMeta", { kind: s.unit.kind, admission: spaced(i18n, s.unit.admission) })}
        </p>
      </section>
          {processing}
        </>
      ) : (
        <>
      <section className="panel library-section" aria-labelledby="src-unit">
        <h3 id="src-unit">{t("library.source.unit", { id: s.unit.unit_id })}</h3>
        <p>
          <strong>{s.unit.canonical}</strong>: {s.unit.statement}
        </p>
        {s.unit.example ? <FrenchExample text={s.unit.example} /> : null}
        <p className="hint">
          {s.annotation.status === "invalid"
            ? t("library.source.now.invalid")
            : s.annotation.current_concept_id !== null
              ? tn("library.source.now.filed", {
                  concept: (
                    <button type="button" className="link-button" onClick={() => onOpenConcept(s.annotation.current_concept_id!)}>
                      {conceptTitle !== null && s.annotation.current_concept_id === conceptId
                    ? t("demo.conceptNamed", { id: conceptId, title: conceptTitle })
                    : t("library.conceptLink", { id: s.annotation.current_concept_id })}
                    </button>
                  ),
                })
              : t("library.source.now.none")}{" "}
          {t("library.source.nowMeta", { kind: s.unit.kind, admission: spaced(i18n, s.unit.admission) })}
        </p>
      </section>

      <section className="panel library-section current" aria-labelledby="src-entry">
        <h3 id="src-entry">{t("library.source.entry", { id: s.entry.id })}</h3>
        {demo ? (
          <blockquote className="demo-question french" dir="auto">
            {s.entry.original_input}
          </blockquote>
        ) : null}
        <dl className="unit-evidence">
          {demo ? null : (
            <Row label={t("library.source.wrote")}>
              <span className="french">{s.entry.original_input}</span>
            </Row>
          )}
          <Row label={t("library.source.context")}>
            {s.entry.original_context ? (
              demo ? <bdi>{s.entry.original_context}</bdi> : s.entry.original_context
            ) : (
              <em>{t("library.noneLower")}</em>
            )}
          </Row>
          <Row label={t("library.source.recorded")}>{s.entry.created_at}</Row>
        </dl>
        {onOpenRecord ? (
          <button type="button" className="ghost" onClick={() => onOpenRecord(s.entry.id)}>
            {t("library.source.openRecord", { id: s.entry.id })}
          </button>
        ) : null}
      </section>
          {processing}
        </>
      )}
    </div>
  );
}
