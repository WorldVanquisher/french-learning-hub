import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import * as api from "../api/client";
import { ApiError } from "../api/client";
import { useI18n, type MessageKey } from "../i18n";
import { markMatches, matchedFeatures, normalizeWord } from "../pages/libraryHighlight";
import type { LibraryConcept, LibrarySearchResult, LibrarySource, LibraryUnit } from "../types/library";
import { CopyLink } from "./CopyLink";

// Public demo: "Why it matched" under a keyword result. It explains the match
// from the result's own metadata (the search's normalized `tokens`, the
// result's `match_tier` and `matched_fields`) and shows the wording those
// tokens reach: the Concept's own fields, then the wording of the units filed
// under it with the learner's question each was taken from, and a link to
// each unit's source record. It reads only the existing GETs (the Concept and
// each shown unit's source), on request, and changes nothing: what matched,
// the order and every stored text are the server's. The marks use the
// server's rule (a word whose accent-free lowercase form starts with a token;
// libraryHighlight.tsx), so a token marks the same words the server matched.

const WORD = /[\p{L}\p{M}\p{N}]+/gu;
const UNITS_SHOWN = 3;
const EXCERPT = 160;

export interface TokenHit {
  token: string;
  // The first word the token reaches in the texts, as written there; null when
  // none of the texts shown contains it.
  word: string | null;
  // The word is the token itself (accents and case aside), not a longer word it begins.
  exact: boolean;
}

// locateTokens says, for each token, which word of the texts it reached first:
// a whole word when there is one, otherwise the first word it begins.
export function locateTokens(texts: readonly string[], tokens: readonly string[]): TokenHit[] {
  return tokens.map((token) => {
    let prefix: string | null = null;
    for (const text of texts) {
      for (const m of text.matchAll(WORD)) {
        const norm = normalizeWord(m[0]);
        if (norm === token) return { token, word: m[0], exact: true };
        if (prefix === null && token.length >= 2 && norm.startsWith(token)) prefix = m[0];
      }
    }
    return { token, word: prefix, exact: false };
  });
}

const reaches = (text: string | null | undefined, tokens: readonly string[]) => Boolean(text) && typeof markMatches(text!, tokens) !== "string";

// excerpt shortens a long text to a window around its first matched word, cut
// at spaces, with "…" where it was cut. Short texts are returned whole.
export function excerpt(text: string, tokens: readonly string[], max = EXCERPT): { text: string; cut: boolean } {
  if (text.length <= max) return { text, cut: false };
  let first = 0;
  for (const m of text.matchAll(WORD)) {
    if (tokens.some((t) => t.length >= 2 && normalizeWord(m[0]).startsWith(t))) {
      first = m.index ?? 0;
      break;
    }
  }
  let start = Math.max(0, first - Math.floor(max / 3));
  if (start > 0) {
    const space = text.indexOf(" ", start);
    start = space >= 0 && space < first ? space + 1 : start;
  }
  let end = Math.min(text.length, start + max);
  if (end < text.length) {
    const space = text.lastIndexOf(" ", end);
    end = space > first ? space : end;
  }
  return { text: `${start > 0 ? "…" : ""}${text.slice(start, end).trim()}${end < text.length ? "…" : ""}`, cut: true };
}

const conceptFields: Array<{ field: "target" | "pedagogical_intent" | "scope"; label: MessageKey }> = [
  { field: "target", label: "demo.evidence.field.target" },
  { field: "pedagogical_intent", label: "demo.evidence.field.pedagogical_intent" },
  { field: "scope", label: "demo.evidence.field.scope" },
];
const unitFields: Array<{ field: "canonical" | "example" | "statement"; label: MessageKey }> = [
  { field: "canonical", label: "demo.evidence.field.canonical" },
  { field: "example", label: "demo.evidence.field.example" },
  { field: "statement", label: "demo.evidence.field.statement" },
];

// The CURRENT SAME members the server's unit-wording match reads: supporting
// units and members that do not support, once each, by unit ID.
function members(detail: LibraryConcept): LibraryUnit[] {
  const seen = new Set<number>();
  return [...detail.supporting_units, ...detail.non_supporting_members].filter((u) => !seen.has(u.unit_id) && seen.add(u.unit_id));
}

const failure = (e: unknown) => (e instanceof ApiError ? `(${e.status}) ${e.message}` : e instanceof Error ? e.message : String(e));

type Load<T> = { status: "loading" } | { status: "error"; message: string; code?: number } | { status: "ready"; data: T };

// R2-022/025: why a member does not support the Concept, from the unit's own
// fields: an earlier, replaced extraction, or an admission other than active.
// The wording never claims more than those fields say.
function memberReason(unit: LibraryUnit): "superseded" | "admission" | "other" {
  if (unit.in_current_extraction === false) return "superseded";
  if (unit.admission && unit.admission !== "active") return "admission";
  return "other";
}

export const evidenceToggleId = (conceptId: number) => `demo-ev-toggle-${conceptId}`;
export const evidenceSourceId = (conceptId: number, unitId: number) => `demo-ev-src-${conceptId}-${unitId}`;

export function EvidenceCard({
  result,
  tokens,
  sourceHref,
  onOpenSource,
}: {
  result: LibrarySearchResult;
  tokens: readonly string[] | undefined;
  // The source record's link (a demo fragment) and the in-page move to it.
  sourceHref: (unitId: number) => string;
  onOpenSource: (unitId: number) => void;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const id = result.concept.id;
  const toggle = useRef<HTMLButtonElement>(null);
  const close = () => {
    setOpen(false);
    toggle.current?.focus();
  };
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      close();
    }
  };
  return (
    <div className="demo-evidence">
      <button
        type="button"
        className="ghost demo-evidence-toggle"
        id={evidenceToggleId(id)}
        ref={toggle}
        aria-expanded={open}
        aria-controls={`demo-ev-${id}`}
        onClick={() => setOpen(!open)}
      >
        {t(open ? "demo.evidence.hide" : "demo.evidence.show")}
      </button>
      {open ? (
        <section id={`demo-ev-${id}`} className="demo-evidence-card" aria-labelledby={`demo-ev-heading-${id}`} onKeyDown={onKeyDown}>
          <h3 id={`demo-ev-heading-${id}`} className="demo-evidence-heading">
            {t("demo.evidence.heading", { target: result.concept.target })}
          </h3>
          <Evidence result={result} tokens={tokens} sourceHref={sourceHref} onOpenSource={onOpenSource} />
        </section>
      ) : null}
    </div>
  );
}

function Evidence({
  result,
  tokens,
  sourceHref,
  onOpenSource,
}: {
  result: LibrarySearchResult;
  tokens: readonly string[] | undefined;
  sourceHref: (unitId: number) => string;
  onOpenSource: (unitId: number) => void;
}) {
  const { t, tp, tn } = useI18n();
  const fields = Array.isArray(result.matched_fields) ? result.matched_fields : [];
  const words = Array.isArray(tokens) ? tokens.filter((w) => typeof w === "string" && w.length > 0) : [];
  const details = fields.length > 0 && words.length > 0 && (result.match_tier === "identity" || result.match_tier === "unit_evidence");
  const [load, setLoad] = useState<Load<LibraryConcept>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [all, setAll] = useState(false);
  const firstMore = useRef<HTMLElement | null>(null);
  const focusMore = useRef(false);
  useEffect(() => {
    if (!details) return;
    let live = true;
    setLoad({ status: "loading" });
    api.getLibraryConcept(result.concept.id).then(
      (data) => live && setLoad({ status: "ready", data }),
      (e: unknown) => live && setLoad({ status: "error", message: failure(e) }),
    );
    return () => {
      live = false;
    };
  }, [details, result.concept.id, attempt]);
  useEffect(() => {
    if (focusMore.current && all) {
      focusMore.current = false;
      firstMore.current?.focus();
    }
  }, [all]);
  // No match details: the result names no matched field or no search words
  // (an older server, or a result that was not matched by words at all).
  if (!details) return <p className="hint demo-evidence-empty">{t("demo.evidence.noDetails")}</p>;
  if (load.status === "loading") return <p className="hint" role="status">{t("demo.evidence.loading")}</p>;
  if (load.status === "error")
    return (
      <div className="banner error" role="alert">
        {t("demo.evidence.failed", { message: load.message })}{" "}
        <button type="button" className="ghost" onClick={() => setAttempt(attempt + 1)}>
          {t("common.tryAgain")}
        </button>
      </div>
    );
  const concept = load.data.concept;
  const shownConcept = conceptFields.filter(({ field }) => fields.includes(field) && reaches(concept[field], words));
  const features = fields.includes("identity_features") ? matchedFeatures(concept.identity_features, words, 3) : [];
  const featureText = Object.keys(concept.identity_features ?? {})
    .sort()
    .map((k) => `${k}: ${typeof concept.identity_features[k] === "string" ? concept.identity_features[k] : JSON.stringify(concept.identity_features[k])}`);
  // Units whose own wording the words reach, those reaching the most words first.
  const units = members(load.data)
    .map((u) => ({ u, reached: words.filter((w) => unitFields.some(({ field }) => reaches(u[field], [w]))).length }))
    .filter((x) => x.reached > 0)
    .sort((a, b) => b.reached - a.reached || a.u.unit_id - b.u.unit_id)
    .map((x) => x.u);
  const shownUnits = all ? units : units.slice(0, UNITS_SHOWN);
  const hits = locateTokens(
    [
      ...shownConcept.map(({ field }) => concept[field]),
      ...(features.length ? featureText : []),
      ...units.flatMap((u) => unitFields.map(({ field }) => u[field] ?? "")),
    ],
    words,
  );
  return (
    <>
      <p className="demo-evidence-tier" data-tier={result.match_tier}>
        {t(result.match_tier === "identity" ? "demo.evidence.tier.identity" : "demo.evidence.tier.unit")}
      </p>
      <p className="hint">{t("demo.evidence.words")}</p>
      <ul className="demo-evidence-words">
        {hits.map((h) => (
          <li key={h.token} data-match={h.word ? (h.exact ? "exact" : "prefix") : "unseen"}>
            {h.word
              ? tn(h.exact ? "demo.evidence.word.exact" : "demo.evidence.word.prefix", {
                  token: h.token,
                  word: <mark>{h.word}</mark>,
                })
              : t("demo.evidence.word.unseen", { token: h.token })}
          </li>
        ))}
      </ul>
      <h4 className="demo-evidence-group">{t("demo.evidence.inConcept")}</h4>
      {shownConcept.length || features.length ? (
        <dl className="demo-evidence-fields">
          {shownConcept.map(({ field, label }) => (
            <div key={field}>
              <dt>{t(label)}</dt>
              <dd dir="auto">{markMatches(concept[field], words)}</dd>
            </div>
          ))}
          {features.length ? (
            <div>
              <dt>{t("demo.evidence.field.identity_features")}</dt>
              <dd dir="auto">
                {features.map((node, i) => (
                  <span key={i}>
                    {i > 0 ? " · " : ""}
                    {node}
                  </span>
                ))}
              </dd>
            </div>
          ) : null}
        </dl>
      ) : (
        <p className="hint">{t("demo.evidence.inConceptNone")}</p>
      )}
      <h4 className="demo-evidence-group">{t("demo.evidence.inUnits")}</h4>
      {units.length === 0 ? (
        <p className="hint">{t("demo.evidence.inUnitsNone")}</p>
      ) : (
        <ul className="demo-evidence-units">
          {shownUnits.map((u, i) => (
            <UnitEvidence
              key={u.unit_id}
              conceptId={concept.id}
              conceptTitle={concept.target}
              supports={load.data.supporting_units.some((s) => s.unit_id === u.unit_id)}
              unit={u}
              tokens={words}
              href={sourceHref(u.unit_id)}
              onOpen={() => onOpenSource(u.unit_id)}
              linkRef={all && i === UNITS_SHOWN ? firstMore : undefined}
            />
          ))}
        </ul>
      )}
      {!all && units.length > UNITS_SHOWN ? (
        <button
          type="button"
          className="ghost"
          onClick={() => {
            focusMore.current = true;
            setAll(true);
          }}
        >
          {tp("demo.evidence.more", units.length - UNITS_SHOWN)}
        </button>
      ) : null}
    </>
  );
}

// One unit whose wording matched: its matched fields (long ones shortened
// around the first match, with a way to read them whole), the learner's
// question it was taken from, what it supports (whether it currently supports
// the Concept, from the Concept read's supporting units), and the link to its
// source record. A source that cannot be read degrades this unit only.
function UnitEvidence({
  conceptId,
  conceptTitle,
  supports,
  unit,
  tokens,
  href,
  onOpen,
  linkRef,
}: {
  conceptId: number;
  conceptTitle: string;
  supports: boolean;
  unit: LibraryUnit;
  tokens: readonly string[];
  href: string;
  onOpen: () => void;
  linkRef?: { current: HTMLElement | null };
}) {
  const { t } = useI18n();
  const [source, setSource] = useState<Load<LibrarySource>>({ status: "loading" });
  const [whole, setWhole] = useState(false);
  useEffect(() => {
    let live = true;
    api.getLibraryUnitSource(unit.unit_id).then(
      (data) => live && setSource({ status: "ready", data }),
      (e: unknown) => live && setSource({ status: "error", message: failure(e), code: e instanceof ApiError ? e.status : undefined }),
    );
    return () => {
      live = false;
    };
  }, [unit.unit_id]);
  const [context, setContext] = useState(false);
  const reason = supports ? null : memberReason(unit);
  const shown = unitFields.filter(({ field }) => reaches(unit[field], tokens));
  const texts = shown.map(({ field }) => excerpt(unit[field] ?? "", tokens));
  const cut = texts.some((x) => x.cut);
  const entry = source.status === "ready" ? source.data.entry.id : unit.entry_id;
  const open = (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    onOpen();
  };
  return (
    <li className="demo-evidence-unit">
      <dl className="demo-evidence-fields">
        {shown.map(({ field, label }, i) => (
          <div key={field}>
            <dt>{t(label)}</dt>
            <dd dir="auto">{markMatches(whole ? (unit[field] ?? "") : texts[i].text, tokens)}</dd>
          </div>
        ))}
        <div data-excerpt={source.status === "ready" ? (reaches(source.data.entry.original_input, tokens) ? "match" : "no-match") : source.status === "error" ? (source.code === 404 ? "none" : "failed") : "loading"}>
          <dt>{t("demo.evidence.question", { entry })}</dt>
          {source.status === "ready" ? (
            <dd>
              {/* R2-024: the smallest relevant excerpt first; the whole text on request. */}
              <blockquote className="demo-evidence-question" dir="auto">
                {markMatches(whole ? source.data.entry.original_input : excerpt(source.data.entry.original_input, tokens).text, tokens)}
              </blockquote>
              {/* R2-025: say when the words are not in the question itself. */}
              {reaches(source.data.entry.original_input, tokens) ? null : <p className="hint demo-evidence-note">{t("demo.evidence.notInQuestion")}</p>}
              {context ? (
                <div className="demo-evidence-context" id={`demo-ev-ctx-${conceptId}-${unit.unit_id}`}>
                  <p className="label">{t("demo.evidence.context.label")}</p>
                  <p dir="auto">{source.data.entry.original_context || t("demo.evidence.context.none")}</p>
                  {source.data.source_interpretation?.effective?.effective ? (
                    <>
                      <p className="label">{t("demo.evidence.context.interpretation")}</p>
                      <p dir="auto">{source.data.source_interpretation.effective.effective.explanation}</p>
                    </>
                  ) : null}
                </div>
              ) : null}
            </dd>
          ) : source.status === "error" ? (
            // R2-025: no excerpt (the record is not in this build) reads apart from a failed read.
            <dd className="hint">
              {source.code === 404 ? t("demo.evidence.noExcerpt", { unit: unit.unit_id }) : t("demo.evidence.questionFailed", { message: source.message })}
            </dd>
          ) : (
            <dd className="hint">{t("demo.evidence.questionLoading")}</dd>
          )}
        </div>
        <div data-support={supports ? "supports" : "member"} data-reason={reason ?? undefined}>
          <dt>{t("demo.evidence.support")}</dt>
          <dd dir="auto">
            {/* R2-022: an explicit label, then the sentence that says it in full. */}
            <span className="tag demo-support-badge">{t(supports ? "demo.evidence.badge.supports" : "demo.evidence.badge.member")}</span>{" "}
            {t(
              supports
                ? "demo.evidence.supports"
                : reason === "superseded"
                  ? "demo.evidence.member.superseded"
                  : reason === "admission"
                    ? "demo.evidence.member.admission"
                    : "demo.evidence.member",
              { id: conceptId, title: conceptTitle, admission: unit.admission },
            )}
            {reason === "superseded" ? <span className="hint demo-evidence-note"> {t("demo.evidence.superseded")}</span> : null}
          </dd>
        </div>
      </dl>
      <div className="actions">
        <a
          href={href}
          id={evidenceSourceId(conceptId, unit.unit_id)}
          ref={linkRef as { current: HTMLAnchorElement | null } | undefined}
          onClick={open}
        >
          {t("demo.evidence.openSource", { unit: unit.unit_id, entry })}
        </a>
        {cut || (source.status === "ready" && excerpt(source.data.entry.original_input, tokens).cut) ? (
          <button type="button" className="ghost" aria-expanded={whole} onClick={() => setWhole(!whole)}>
            {t(whole ? "demo.evidence.shorter" : "demo.evidence.whole")}
          </button>
        ) : null}
        {source.status === "ready" ? (
          // R2-023/026: the question's recorded context and interpretation, here, on request.
          <button
            type="button"
            className="ghost"
            id={`demo-ev-ctx-toggle-${conceptId}-${unit.unit_id}`}
            aria-expanded={context}
            aria-controls={context ? `demo-ev-ctx-${conceptId}-${unit.unit_id}` : undefined}
            onClick={() => setContext(!context)}
          >
            {t(context ? "demo.evidence.context.hide" : "demo.evidence.context.show")}
          </button>
        ) : null}
        {/* R2-027: a short public link to this unit's evidence (no search, no progress). */}
        <CopyLink
          fragment={`#concept=${conceptId}&unit=${unit.unit_id}`}
          id={`demo-ev-copy-${conceptId}-${unit.unit_id}`}
          label="demo.evidence.copy"
          vars={{ unit: unit.unit_id }}
          done="demo.link.copied"
        />
      </div>
    </li>
  );
}
