import { useEffect, useRef, useState, type FormEvent } from "react";
import * as api from "../api/client";
import { ApiError, NetworkError } from "../api/client";
import { useI18n } from "../i18n";
import type { KindConcept } from "../types/notebook";
import type { LibrarySource } from "../types/library";
import type {
  VocabularyExample,
  VocabularyItem,
  VocabularyList,
} from "../types/vocabulary";
import { ConceptKinds } from "./ConceptKinds";
import { RecallPractice } from "./RecallPractice";
import {
  setVocabularyQuery,
  setVocabularySavedOnly,
  vocabularyQuery,
  vocabularySavedOnly,
} from "./vocabularyMemory";

// Vocabulary (Workbooks, private): the learner's saved terms. A term is saved
// from an approved vocabulary Concept with one of its approved examples
// (PUT /vocabulary/{concept}); it is found again by search (GET /vocabulary?q=),
// reviewed with the existing Recall Practice, and can be removed (DELETE),
// which keeps its examples, the Concept and any history. Every control of this
// feature lives in this component; the notebook and the shell only mount it.
// Learner and French text is rendered as text, never as HTML.

type Load<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: T };
type Screen =
  | { kind: "list" }
  | { kind: "source"; unitId: number; conceptId: number; review?: number }
  | { kind: "review"; conceptId: number; session: number };
type Refocus =
  | { kind: "row"; conceptId: number }
  | { kind: "after-remove"; index: number }
  | { kind: "control"; id: string };
type Notice = { tone: "error" | "info"; text: string; retry?: () => void };

const describe = (e: unknown) =>
  e instanceof ApiError
    ? `(${e.status}) ${e.message}`
    : e instanceof Error
      ? e.message
      : String(e);
const rowId = (conceptId: number) => `vocab-row-${conceptId}`;
const isVocabularyList = (x: unknown): x is VocabularyList =>
  !!x &&
  typeof x === "object" &&
  (x as VocabularyList).schema_version === "vocabulary_v1" &&
  Array.isArray((x as VocabularyList).items);
const ctl = (what: string, conceptId: number) => `vocab-${what}-${conceptId}`;

export function VocabularyBook({
  onOpenConcept,
}: {
  onOpenConcept?: (conceptId: number) => void;
}) {
  const { t, tp, locale } = useI18n();
  const [text, setText] = useState(vocabularyQuery);
  const [query, setQuery] = useState(vocabularyQuery);
  const [epoch, setEpoch] = useState(0);
  // Re-reads are numbered; a focus request after a save or a removal waits for
  // the re-read list (refocusEpoch), so it never lands on a row about to disappear.
  const epochRef = useRef(0);
  const refocusEpoch = useRef(0);
  const [loadedEpoch, setLoadedEpoch] = useState(-1);
  const reread = () => {
    const next = ++epochRef.current;
    setEpoch(next);
    return next;
  };
  const [list, setList] = useState<Load<VocabularyList>>({ status: "loading" });
  const [savedIds, setSavedIds] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [announce, setAnnounce] = useState("");
  const [savedOnly, setSavedOnlyState] = useState(vocabularySavedOnly);
  const [screen, setScreen] = useState<Screen>({ kind: "list" });
  const [refocus, setRefocus] = useState<Refocus | null>(null);
  const [adding, setAdding] = useState<{
    conceptId: number;
    load: Load<{ unit_id: number; canonical: string; question: string }[]>;
  } | null>(null);
  const session = useRef(0);
  const listRef = useRef<HTMLOListElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const day = (iso: string) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(locale);
  };

  // One read for the rows shown (searched) and, when searching, one for the
  // set of saved Concepts (marking the approved list); without a query they are the same.
  useEffect(() => {
    let live = true;
    setList((l) => (l.status === "ready" ? l : { status: "loading" }));
    const reading = epoch;
    const shown = api.getVocabulary(query);
    const all = query.trim() ? api.getVocabulary("") : shown;
    Promise.all([shown, all]).then(
      ([s, a]) => {
        if (!live) return;
        // An older or unexpected server: say so instead of failing the page.
        if (!isVocabularyList(s) || !isVocabularyList(a)) {
          setList({ status: "error", message: t("vocabulary.unexpected") });
          setLoadedEpoch(reading);
          return;
        }
        setList({ status: "ready", data: s });
        setSavedIds(new Set(a.items.map((i) => i.concept_id)));
        setLoadedEpoch(reading);
      },
      (e: unknown) => {
        if (!live) return;
        setList({ status: "error", message: describe(e) });
        setLoadedEpoch(reading);
      },
    );
    return () => {
      live = false;
    };
  }, [query, epoch]);

  // Focus is given back once the buttons are enabled again and the list is read.
  useEffect(() => {
    if (
      !refocus ||
      busy !== null ||
      screen.kind !== "list" ||
      list.status === "loading" ||
      loadedEpoch < refocusEpoch.current
    )
      return;
    requestAnimationFrame(() => {
      const rows = [
        ...(listRef.current?.querySelectorAll<HTMLElement>(
          "li[data-concept]",
        ) ?? []),
      ];
      let el: HTMLElement | null = null;
      if (refocus.kind === "row")
        el =
          document
            .getElementById(rowId(refocus.conceptId))
            ?.querySelector<HTMLElement>("h3") ?? null;
      else if (refocus.kind === "after-remove")
        el =
          (
            rows[refocus.index] ?? rows[refocus.index - 1]
          )?.querySelector<HTMLElement>("h3") ?? null;
      else el = document.getElementById(refocus.id);
      (el ?? headingRef.current)?.focus();
    });
    setRefocus(null);
  }, [refocus, busy, screen, list, loadedEpoch]);

  const failure = (e: unknown, action: "save" | "remove") =>
    e instanceof NetworkError
      ? t(
          action === "save"
            ? "vocabulary.saveNoAnswer"
            : "vocabulary.removeNoAnswer",
        )
      : t(
          action === "save"
            ? "vocabulary.saveFailed"
            : "vocabulary.removeFailed",
          { message: describe(e) },
        );

  const save = async (conceptId: number, term: string, unitId?: number) => {
    setBusy(`save:${conceptId}`);
    setNotice(null);
    try {
      let unit = unitId;
      if (unit === undefined) {
        const d = await api.getLibraryConcept(conceptId);
        unit = (
          d.supporting_units.find(
            (u) => u.unit_id === d.concept.preferred_unit_id,
          ) ?? d.supporting_units[0]
        )?.unit_id;
        if (unit === undefined) {
          setNotice({
            tone: "error",
            text: t("vocabulary.noExample", { term }),
          });
          setRefocus({ kind: "control", id: ctl("save", conceptId) });
          return;
        }
      }
      const r = await api.saveVocabulary(conceptId, unit);
      setAnnounce(
        r.saved_now
          ? t("vocabulary.savedAnnounce", { term })
          : r.example_added
            ? t("vocabulary.exampleAddedAnnounce", { term })
            : t("vocabulary.alreadySaved", { term }),
      );
      setAdding(null);
      refocusEpoch.current = reread();
      setRefocus({ kind: "row", conceptId });
    } catch (e) {
      setNotice({
        tone: "error",
        text: failure(e, "save"),
        retry: () => void save(conceptId, term, unitId),
      });
      setRefocus({
        kind: "control",
        id:
          unitId === undefined ? ctl("save", conceptId) : ctl("add", conceptId),
      });
    } finally {
      setBusy(null);
    }
  };

  const remove = async (it: VocabularyItem, index: number) => {
    const term = it.concept?.target ?? `#${it.concept_id}`;
    setBusy(`remove:${it.concept_id}`);
    setNotice(null);
    try {
      const r = await api.removeVocabulary(it.concept_id);
      setAnnounce(
        r.changed
          ? t("vocabulary.removedAnnounce", { term })
          : t("vocabulary.alreadyRemoved", { term }),
      );
      refocusEpoch.current = reread();
      setRefocus({ kind: "after-remove", index });
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setAnnounce(t("vocabulary.alreadyRemoved", { term }));
        refocusEpoch.current = reread();
        setRefocus({ kind: "after-remove", index });
      } else {
        setNotice({
          tone: "error",
          text: failure(e, "remove"),
          retry: () => void remove(it, index),
        });
        setRefocus({ kind: "control", id: ctl("remove", it.concept_id) });
      }
    } finally {
      setBusy(null);
    }
  };

  const openAdd = async (it: VocabularyItem) => {
    setAdding({ conceptId: it.concept_id, load: { status: "loading" } });
    try {
      const d = await api.getLibraryConcept(it.concept_id);
      const have = new Set(it.examples.map((e) => e.unit_id));
      const units = d.supporting_units.filter((u) => !have.has(u.unit_id));
      const rows = await Promise.all(
        units.map(async (u) => {
          const src = await api
            .getLibraryUnitSource(u.unit_id)
            .catch(() => null);
          return {
            unit_id: u.unit_id,
            canonical: u.canonical,
            question: src?.entry.original_input ?? "",
          };
        }),
      );
      setAdding({
        conceptId: it.concept_id,
        load: { status: "ready", data: rows },
      });
    } catch (e) {
      setAdding({
        conceptId: it.concept_id,
        load: { status: "error", message: describe(e) },
      });
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setVocabularyQuery(text);
    setQuery(text);
  };
  const setSavedOnly = (on: boolean) => {
    setVocabularySavedOnly(on);
    setSavedOnlyState(on);
  };

  const reviewing =
    screen.kind === "review"
      ? screen
      : screen.kind === "source" && screen.review !== undefined
        ? { conceptId: screen.conceptId, session: screen.review }
        : null;

  // This page places focus itself after every save, removal, source and review
  // (once the list is read again), so the workspace shell's focus rescue stays
  // out: data-focus-managed. display: contents keeps the parent's layout.
  return (
    <div className="vocabulary-book" data-focus-managed="">
      <section
        className="panel vocabulary"
        aria-label={t("vocabulary.region")}
        hidden={screen.kind !== "list"}
      >
        <h2 ref={headingRef} tabIndex={-1}>
          {t("vocabulary.heading")}
        </h2>
        <p className="hint">{t("vocabulary.hint")}</p>
        <form
          className="actions"
          onSubmit={submit}
          role="search"
          aria-label={t("vocabulary.search")}
        >
          <input
            type="search"
            value={text}
            onChange={(e) => setText(e.target.value)}
            aria-label={t("vocabulary.search")}
          />
          <button type="submit">{t("vocabulary.searchButton")}</button>
        </form>
        {notice ? (
          <div className={`banner ${notice.tone}`} role="alert">
            {notice.text}{" "}
            {notice.retry ? (
              <button type="button" className="ghost" onClick={notice.retry}>
                {t("common.retry")}
              </button>
            ) : null}
          </div>
        ) : null}
        <p className="visually-hidden" aria-live="polite" aria-atomic="true">
          {announce}
        </p>
        {list.status === "loading" ? (
          <p className="hint" role="status">
            {t("vocabulary.loading")}
          </p>
        ) : list.status === "error" ? (
          <div className="banner error" role="alert">
            {t("vocabulary.failed", { message: list.message })}{" "}
            <button
              type="button"
              className="ghost"
              onClick={() => void reread()}
            >
              {t("common.retry")}
            </button>
          </div>
        ) : list.data.saved === 0 ? (
          <p className="empty" data-empty="book">
            {t("vocabulary.emptyBook")}
          </p>
        ) : list.data.items.length === 0 ? (
          <p className="empty" data-empty="no-match">
            {t("vocabulary.noMatch", { query: list.data.query })}
          </p>
        ) : (
          <>
            <p className="hint" role="status">
              {list.data.query
                ? tp("vocabulary.countMatching", list.data.items.length, {
                    saved: list.data.saved,
                  })
                : tp("vocabulary.count", list.data.saved)}
            </p>
            <ol
              className="listening-list vocabulary-list"
              ref={listRef}
              aria-label={t("vocabulary.list")}
            >
              {list.data.items.map((it, i) => {
                const term = it.concept?.target ?? `#${it.concept_id}`;
                return (
                  <li
                    key={it.concept_id}
                    id={rowId(it.concept_id)}
                    data-concept={it.concept_id}
                  >
                    <h3 tabIndex={-1} lang="fr" className="vocabulary-term">
                      {it.concept
                        ? it.concept.target
                        : t("vocabulary.conceptUnavailable", {
                            id: it.concept_id,
                          })}
                    </h3>
                    <p className="hint">
                      {it.concept && it.concept.state !== "active" ? (
                        <span className="tag">
                          {t(
                            it.concept.state === "retired"
                              ? "vocabulary.state.retired"
                              : "vocabulary.state.orphaned",
                          )}
                        </span>
                      ) : null}{" "}
                      {t("vocabulary.savedOn", { day: day(it.saved_at) })}{" "}
                      {it.concept?.scope ? (
                        <span>
                          {t("vocabulary.scope", { scope: it.concept.scope })}
                        </span>
                      ) : null}
                    </p>
                    <ol
                      className="vocabulary-examples"
                      aria-label={t("vocabulary.examples", { term })}
                    >
                      {it.examples.map((ex) => (
                        <Example
                          key={ex.unit_id}
                          ex={ex}
                          term={term}
                          onOpenSource={() =>
                            setScreen({
                              kind: "source",
                              unitId: ex.unit_id,
                              conceptId: it.concept_id,
                            })
                          }
                        />
                      ))}
                    </ol>
                    <div className="actions">
                      {it.review_units > 0 ? (
                        <button
                          type="button"
                          className="primary"
                          id={ctl("review", it.concept_id)}
                          aria-label={t("vocabulary.reviewLabel", { term })}
                          onClick={() =>
                            setScreen({
                              kind: "review",
                              conceptId: it.concept_id,
                              session: ++session.current,
                            })
                          }
                        >
                          {t("vocabulary.review")}
                        </button>
                      ) : (
                        <span className="hint" data-review="none">
                          {t("vocabulary.noReview")}
                        </span>
                      )}
                      {onOpenConcept && it.concept ? (
                        <button
                          type="button"
                          className="ghost"
                          id={`vocabulary-word-${it.concept_id}`}
                          aria-label={t("vocabulary.openConceptLabel", {
                            term,
                          })}
                          onClick={() => onOpenConcept(it.concept_id)}
                        >
                          {t("vocabulary.openConcept")}
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="ghost"
                        id={ctl("add", it.concept_id)}
                        aria-label={t("vocabulary.addExampleLabel", { term })}
                        onClick={() => void openAdd(it)}
                      >
                        {t("vocabulary.addExample")}
                      </button>
                      <button
                        type="button"
                        className="ghost danger"
                        id={ctl("remove", it.concept_id)}
                        aria-label={t("vocabulary.removeLabel", { term })}
                        disabled={busy !== null}
                        onClick={() => void remove(it, i)}
                      >
                        {busy === `remove:${it.concept_id}`
                          ? t("vocabulary.removing")
                          : t("vocabulary.remove")}
                      </button>
                    </div>
                    {adding?.conceptId === it.concept_id ? (
                      <div
                        className="vocabulary-add"
                        role="group"
                        aria-label={t("vocabulary.addExampleLabel", { term })}
                      >
                        {adding.load.status === "loading" ? (
                          <p className="hint" role="status">
                            {t("vocabulary.loading")}
                          </p>
                        ) : adding.load.status === "error" ? (
                          <p className="banner error" role="alert">
                            {t("vocabulary.failed", {
                              message: adding.load.message,
                            })}
                          </p>
                        ) : adding.load.data.length === 0 ? (
                          <p className="hint">
                            {t("vocabulary.noOtherExample")}
                          </p>
                        ) : (
                          <ul>
                            {adding.load.data.map((u) => (
                              <li key={u.unit_id}>
                                <span lang="fr" className="french">
                                  {u.canonical}
                                </span>{" "}
                                {u.question ? (
                                  <q lang="fr" className="french">
                                    {u.question}
                                  </q>
                                ) : null}{" "}
                                <button
                                  type="button"
                                  disabled={busy !== null}
                                  onClick={() =>
                                    void save(it.concept_id, term, u.unit_id)
                                  }
                                >
                                  {t("vocabulary.addThisExample")}
                                </button>
                              </li>
                            ))}
                          </ul>
                        )}
                        <button
                          type="button"
                          className="link-button"
                          onClick={() => setAdding(null)}
                        >
                          {t("vocabulary.cancel")}
                        </button>
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ol>
          </>
        )}
      </section>
      {screen.kind === "list" ? (
        <ConceptKinds
          kind="vocabulary"
          openId={(c) => `vocabulary-approved-${c.concept_id}`}
          onOpenConcept={onOpenConcept}
          filter={savedOnly ? (c) => savedIds.has(c.concept_id) : undefined}
          filterControl={
            <label className="checkbox">
              <input
                type="checkbox"
                checked={savedOnly}
                onChange={(e) => setSavedOnly(e.target.checked)}
              />{" "}
              {t("vocabulary.savedOnly")}
            </label>
          }
          rowAction={(c: KindConcept) => (
            <>
              {/* Two Concepts can share a spelling (VOC-014): the scope tells them apart. */}
              {c.scope ? (
                <span className="hint">
                  {t("vocabulary.scope", { scope: c.scope })}{" "}
                </span>
              ) : null}
              {savedIds.has(c.concept_id) ? (
                <span className="tag" data-saved="yes">
                  {t("vocabulary.savedTag")}
                </span>
              ) : (
                <button
                  type="button"
                  id={ctl("save", c.concept_id)}
                  aria-label={t("vocabulary.saveLabel", { term: c.target })}
                  disabled={busy !== null}
                  onClick={() => void save(c.concept_id, c.target)}
                >
                  {busy === `save:${c.concept_id}`
                    ? t("vocabulary.saving")
                    : t("vocabulary.save")}
                </button>
              )}
            </>
          )}
        />
      ) : null}
      {reviewing ? (
        <div hidden={screen.kind !== "review"}>
          <RecallPractice
            key={`vocab-review-${reviewing.session}`}
            conceptId={reviewing.conceptId}
            visible={screen.kind === "review"}
            exitLabel={t("vocabulary.endReview")}
            onExit={() => {
              setScreen({ kind: "list" });
              setRefocus({
                kind: "control",
                id: ctl("review", reviewing.conceptId),
              });
            }}
            onOpenSource={(unitId) =>
              setScreen({
                kind: "source",
                unitId,
                conceptId: reviewing.conceptId,
                review: reviewing.session,
              })
            }
          />
        </div>
      ) : null}
      {screen.kind === "source" ? (
        <VocabularySourceView
          unitId={screen.unitId}
          fromReview={screen.review !== undefined}
          onBack={() => {
            if (screen.review !== undefined)
              setScreen({
                kind: "review",
                conceptId: screen.conceptId,
                session: screen.review,
              });
            else {
              setScreen({ kind: "list" });
              setRefocus({
                kind: "control",
                id: `vocab-source-${screen.unitId}`,
              });
            }
          }}
        />
      ) : null}
    </div>
  );
}

function Example({
  ex,
  term,
  onOpenSource,
}: {
  ex: VocabularyExample;
  term: string;
  onOpenSource: () => void;
}) {
  const { t } = useI18n();
  const meaning = (lang: "en" | "zh") => ex.meanings[lang];
  return (
    <li
      className="vocabulary-example"
      data-unit={ex.unit_id}
      data-status={ex.status}
    >
      {ex.status === "missing" ? (
        <p className="hint" data-source="missing">
          {t("vocabulary.exampleMissing", {
            record: ex.entry_id,
            version: ex.extraction_version,
          })}
        </p>
      ) : (
        <>
          <p>
            <span lang="fr" className="french vocabulary-wording">
              {ex.term}
            </span>{" "}
            {ex.kind ? <span className="tag">{ex.kind}</span> : null}
          </p>
          <dl className="vocabulary-facts">
            <dt>
              {t("vocabulary.meaning", { extractor: ex.extractor ?? "?" })}
            </dt>
            <dd>
              {meaning("en") === null && meaning("zh") === null ? (
                <>
                  <span>{ex.meaning}</span>{" "}
                  <span className="hint">
                    {t("vocabulary.languagesNotRecorded")}
                  </span>
                </>
              ) : (
                <>
                  <span lang="en" data-meaning="en">
                    {meaning("en") ??
                      t("vocabulary.notRecorded", { lang: "EN" })}
                  </span>
                  {" · "}
                  <span lang="zh" data-meaning="zh">
                    {meaning("zh") ??
                      t("vocabulary.notRecorded", { lang: "中文" })}
                  </span>
                </>
              )}
            </dd>
            {ex.sentence ? (
              <>
                <dt>{t("vocabulary.sentence")}</dt>
                <dd lang="fr" className="french">
                  {ex.sentence}
                </dd>
              </>
            ) : null}
            {ex.source ? (
              <>
                <dt>{t("vocabulary.yourWords")}</dt>
                <dd className="vocabulary-own-words">
                  <q lang="fr" className="french">
                    {ex.source.original_input}
                  </q>
                  {ex.source.original_context ? (
                    <>
                      {" "}
                      <q lang="fr" className="french hint">
                        {ex.source.original_context}
                      </q>
                    </>
                  ) : null}
                </dd>
              </>
            ) : null}
          </dl>
          <p className="hint" data-revision={ex.extraction_version}>
            {t("vocabulary.from", {
              record: ex.entry_id,
              version: ex.extraction_version,
            })}{" "}
            {ex.status === "not_current" ? (
              <span className="tag">{t("vocabulary.notCurrent")}</span>
            ) : null}{" "}
            {ex.newer_extraction ? (
              <span className="tag">{t("vocabulary.newerExtraction")}</span>
            ) : null}
          </p>
        </>
      )}
      <button
        type="button"
        className="link-button"
        id={`vocab-source-${ex.unit_id}`}
        aria-label={t("vocabulary.openSourceLabel", { term: ex.term ?? term })}
        onClick={onOpenSource}
      >
        {t("vocabulary.openSource")}
      </button>
    </li>
  );
}

// The provenance of one example, read from the Knowledge Library (read-only).
function VocabularySourceView({
  unitId,
  fromReview,
  onBack,
}: {
  unitId: number;
  fromReview: boolean;
  onBack: () => void;
}) {
  const { t } = useI18n();
  const [src, setSrc] = useState<Load<LibrarySource>>({ status: "loading" });
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    let live = true;
    api.getLibraryUnitSource(unitId).then(
      (data) => live && setSrc({ status: "ready", data }),
      (e: unknown) =>
        live &&
        setSrc({
          status: "error",
          message:
            e instanceof ApiError && e.status === 404
              ? t("vocabulary.sourceGone")
              : describe(e),
        }),
    );
    return () => {
      live = false;
    };
  }, [unitId]);
  useEffect(() => {
    if (src.status !== "loading") headingRef.current?.focus();
  }, [src.status]);
  const back = (
    <button type="button" className="ghost" onClick={onBack}>
      {fromReview ? t("vocabulary.backToReview") : t("vocabulary.backToList")}
    </button>
  );
  return (
    <section
      className="panel vocabulary-source"
      aria-label={t("vocabulary.sourceRegion")}
    >
      {back}
      <h2 ref={headingRef} tabIndex={-1}>
        {t("vocabulary.sourceHeading")}
      </h2>
      {src.status === "loading" ? (
        <p className="hint" role="status">
          {t("vocabulary.loading")}
        </p>
      ) : src.status === "error" ? (
        <p className="banner error" role="alert" data-source="unavailable">
          {src.message}
        </p>
      ) : (
        <dl className="vocabulary-facts">
          <dt>{t("vocabulary.sourceQuestion")}</dt>
          <dd>
            <q lang="fr" className="french">
              {src.data.entry.original_input}
            </q>
          </dd>
          <dt>{t("vocabulary.sourceContext")}</dt>
          <dd>
            <q lang="fr" className="french">
              {src.data.entry.original_context}
            </q>
          </dd>
          <dt>{t("vocabulary.sourceUnit")}</dt>
          <dd>
            <span lang="fr" className="french">
              {src.data.unit.canonical}
            </span>{" "}
            — {src.data.unit.statement}
          </dd>
          <dt>{t("vocabulary.sourceExtraction")}</dt>
          <dd>
            {t("vocabulary.sourceExtractionFacts", {
              version: src.data.extraction.version,
              extractor: src.data.extraction.extractor,
              current: src.data.unit.in_current_extraction
                ? t("vocabulary.yes")
                : t("vocabulary.no"),
            })}
          </dd>
        </dl>
      )}
    </section>
  );
}
