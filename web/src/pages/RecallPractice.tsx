import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import * as api from "../api/client";
import { ApiError } from "../api/client";
import { StoredText } from "../components/ExplanationText";
import { recorded } from "../explanationLanguage";
import { useI18n, type MessageKey } from "../i18n";
import type { LibraryConcept, LibrarySource } from "../types/library";
import type { ExplanationVariants } from "../types/learning";

// Recall practice v1: a short, private, session-only practice over a Concept's
// current support. It is a read-only view in the sense of FLH: it uses only the
// existing Knowledge Library GETs, writes nothing (no attempt, self-check or score
// is stored anywhere) and calls no provider. It is never rendered in the public demo.
//
// Authority: the candidate units are the backend's `supporting_units` (current
// extraction + active admission + CURRENT SAME). Each candidate's source is read
// again and must still say so; a unit that moved, became INVALID or historical, a
// failed or missing read, and a record without question text are listed with the
// reason and cannot be selected. Nothing is preselected: the learner chooses.
//
// While a question is shown, the Concept title, statements, examples and the
// recorded context stay hidden. The attempt text lives only in this component's
// state: it is never sent, logged or written to browser storage, and it is
// cleared when the learner moves on or leaves practice.

// Supporting units offered for selection (in backend order), and the most that
// one session can hold.
export const PRACTICE_CANDIDATES = 10;
export const PRACTICE_MAX = 5;

type Read<T> = { status: "loading" } | { status: "ready"; data: T } | { status: "unavailable" } | { status: "error"; message: string };

const describe = (e: unknown) =>
  e instanceof ApiError ? `(${e.status}) ${e.message}` : e instanceof Error ? e.message : String(e);
const unexpected = () => new Error("unexpected response from the server");

// One practice card: the learner's original question and the stored answer
// material for one supporting unit, as read from its source at selection time.
export interface PracticeCard {
  unitId: number;
  entryId: number;
  question: string;
  statement: string;
  statements: ExplanationVariants | undefined;
  example: string | null;
}

type Exclusion = "moved" | "invalid" | "historical" | "admission";
type Candidate =
  | { unitId: number; status: "loading" }
  | { unitId: number; status: "error"; message: string }
  | { unitId: number; status: "unavailable" }
  | { unitId: number; status: "excluded"; reason: Exclusion; admission: string }
  | { unitId: number; status: "no-question"; entryId: number }
  | { unitId: number; status: "ready"; card: PracticeCard };

// classify re-checks one supporting unit against its freshly read source. The
// source endpoint reports the unit's current extraction, admission and effective
// annotation; the browser only compares them with this Concept.
export function classify(conceptId: number, unitId: number, read: Read<LibrarySource> | undefined): Candidate {
  if (!read || read.status === "loading") return { unitId, status: "loading" };
  if (read.status === "unavailable") return { unitId, status: "unavailable" };
  if (read.status === "error") return { unitId, status: "error", message: read.message };
  const s = read.data;
  const admission = String(s.unit.admission);
  if (s.annotation.status === "invalid") return { unitId, status: "excluded", reason: "invalid", admission };
  if (s.annotation.current_concept_id !== conceptId) return { unitId, status: "excluded", reason: "moved", admission };
  if (!s.unit.in_current_extraction) return { unitId, status: "excluded", reason: "historical", admission };
  if (admission !== "active") return { unitId, status: "excluded", reason: "admission", admission };
  if (!s.entry.original_input.trim()) return { unitId, status: "no-question", entryId: s.entry.id };
  return {
    unitId,
    status: "ready",
    card: {
      unitId,
      entryId: s.entry.id,
      question: s.entry.original_input,
      statement: s.unit.statement,
      statements: s.unit.statements,
      example: s.unit.example,
    },
  };
}

const exclusionKey: Record<Exclusion, MessageKey> = {
  moved: "practice.candidate.moved",
  invalid: "practice.candidate.invalid",
  historical: "practice.candidate.historical",
  admission: "practice.candidate.admission",
};

type SelfCheck = "recalled" | "again" | "skipped";
const resultKey: Record<SelfCheck, MessageKey> = {
  recalled: "practice.result.recalled",
  again: "practice.result.again",
  skipped: "practice.result.skipped",
};

type Phase =
  | { kind: "setup" }
  | { kind: "card"; pass: 1 | 2; queue: PracticeCard[]; index: number; revealed: boolean }
  | { kind: "summary"; pass: 1 | 2; queue: PracticeCard[] };

export function RecallPractice({
  conceptId,
  visible,
  onExit,
  onOpenSource,
}: {
  conceptId: number;
  // False while the learner looks at a source opened from practice; the session
  // stays mounted (and its state kept) meanwhile.
  visible: boolean;
  onExit: () => void;
  onOpenSource: (unitId: number) => void;
}) {
  const { t, tp } = useI18n();
  const [conceptRetry, setConceptRetry] = useState(0);
  const [concept, setConcept] = useState<Read<LibraryConcept>>({ status: "loading" });
  const [sources, setSources] = useState<Record<number, Read<LibrarySource>>>({});
  // The latest read per unit, from one sequence that only increases, so an
  // answer from a superseded read can never match a newer one.
  const tokens = useRef<Record<number, number>>({});
  const sequence = useRef(0);
  const [selected, setSelected] = useState<number[]>([]);
  const [phase, setPhase] = useState<Phase>({ kind: "setup" });
  const [results, setResults] = useState<{ 1: Record<number, SelfCheck>; 2: Record<number, SelfCheck> }>({ 1: {}, 2: {} });
  const [attempt, setAttempt] = useState("");
  const headingRef = useRef<HTMLHeadingElement>(null);

  // One source read per candidate; a later read for the same unit (Retry, or a
  // StrictMode replay) supersedes an earlier one, whose answer is discarded.
  const readSource = useCallback((unitId: number) => {
    const token = ++sequence.current;
    tokens.current[unitId] = token;
    setSources((prev) => ({ ...prev, [unitId]: { status: "loading" } }));
    api.getLibraryUnitSource(unitId).then(
      (data) => {
        if (tokens.current[unitId] !== token) return;
        const ok = data?.unit?.unit_id === unitId && !!data.entry && !!data.annotation && typeof data.entry.original_input === "string";
        setSources((prev) => ({ ...prev, [unitId]: ok ? { status: "ready", data } : { status: "error", message: unexpected().message } }));
      },
      (e: unknown) => {
        if (tokens.current[unitId] !== token) return;
        const read: Read<LibrarySource> =
          e instanceof ApiError && e.status === 404 ? { status: "unavailable" } : { status: "error", message: describe(e) };
        setSources((prev) => ({ ...prev, [unitId]: read }));
      },
    );
  }, []);

  useEffect(() => {
    let active = true;
    setConcept({ status: "loading" });
    api.getLibraryConcept(conceptId).then(
      (data) => {
        if (!active) return;
        if (!data?.concept || !Array.isArray(data.supporting_units)) {
          setConcept({ status: "error", message: unexpected().message });
          return;
        }
        setConcept({ status: "ready", data });
        if (data.concept.state !== "retired") data.supporting_units.slice(0, PRACTICE_CANDIDATES).forEach((u) => readSource(u.unit_id));
      },
      (e: unknown) => {
        if (!active) return;
        setConcept(e instanceof ApiError && e.status === 404 ? { status: "unavailable" } : { status: "error", message: describe(e) });
      },
    );
    return () => {
      active = false;
      // Discard any source answer that arrives after this read was replaced.
      tokens.current = Object.fromEntries(Object.keys(tokens.current).map((k) => [k, -1]));
    };
  }, [conceptId, conceptRetry, readSource]);

  const focusKey = phase.kind === "card" ? `card-${phase.pass}-${phase.index}` : `${phase.kind}-${"pass" in phase ? phase.pass : 0}-${concept.status}`;
  useEffect(() => {
    if (visible) headingRef.current?.focus();
  }, [focusKey, visible]);

  const exit = (
    <button type="button" className="ghost" onClick={onExit}>
      {t("practice.exit", { id: conceptId })}
    </button>
  );
  const shell = (heading: string, body: ReactNode) => (
    <section className="panel practice" aria-label={t("practice.region")}>
      <h2 ref={headingRef} tabIndex={-1} className="library-title">
        {heading}
      </h2>
      <div className="actions">{exit}</div>
      {body}
    </section>
  );
  const title = t("practice.heading", { id: conceptId });

  if (concept.status === "loading") return shell(title, <p className="hint" role="status">{t("practice.loading", { id: conceptId })}</p>);
  if (concept.status === "unavailable") return shell(title, <p className="hint" role="status">{t("practice.unavailable", { id: conceptId })}</p>);
  if (concept.status === "error")
    return shell(
      title,
      <div className="banner error" role="alert">
        {t("practice.failed", { id: conceptId, message: concept.message })}{" "}
        <button type="button" className="ghost" onClick={() => setConceptRetry((n) => n + 1)}>
          {t("common.retry")}
        </button>
      </div>,
    );

  const d = concept.data;
  if (d.concept.state === "retired") return shell(title, <p className="hint" role="status">{t("practice.entry.retired")}</p>);
  if (d.supporting_units.length === 0) return shell(title, <p className="hint" role="status">{t("practice.entry.noSupport")}</p>);

  const candidates = d.supporting_units.slice(0, PRACTICE_CANDIDATES).map((u) => classify(conceptId, u.unit_id, sources[u.unit_id]));
  const ready = candidates.flatMap((c) => (c.status === "ready" ? [c.card] : []));

  if (phase.kind === "setup") {
    const chosen = ready.filter((card) => selected.includes(card.unitId));
    const settled = candidates.every((c) => c.status !== "loading");
    const toggle = (unitId: number) =>
      setSelected((prev) => (prev.includes(unitId) ? prev.filter((id) => id !== unitId) : prev.length >= PRACTICE_MAX ? prev : [...prev, unitId]));
    const start = () => {
      if (chosen.length === 0) return;
      setResults({ 1: {}, 2: {} });
      setAttempt("");
      setPhase({ kind: "card", pass: 1, queue: chosen, index: 0, revealed: false });
    };
    return shell(
      title,
      <>
        <p className="hint">{t("practice.setup.intro", { max: PRACTICE_MAX })}</p>
        {d.supporting_units.length > PRACTICE_CANDIDATES ? (
          <p className="hint">{t("practice.setup.truncated", { shown: PRACTICE_CANDIDATES, total: d.supporting_units.length })}</p>
        ) : null}
        <fieldset className="practice-candidates">
          <legend>{t("practice.setup.listLabel")}</legend>
          <ul>
            {candidates.map((c) => (
              <li key={c.unitId}>
                <CandidateRow
                  candidate={c}
                  checked={selected.includes(c.unitId)}
                  full={selected.length >= PRACTICE_MAX}
                  onToggle={() => toggle(c.unitId)}
                  onRetry={() => readSource(c.unitId)}
                />
              </li>
            ))}
          </ul>
        </fieldset>
        {selected.length >= PRACTICE_MAX ? (
          <p className="hint" role="status">
            {t("practice.setup.limit", { max: PRACTICE_MAX })}
          </p>
        ) : null}
        {settled && ready.length === 0 ? (
          <p className="hint" role="status">
            {t("practice.setup.none")}
          </p>
        ) : null}
        <div className="actions">
          <button type="button" className="primary" disabled={chosen.length === 0} onClick={start}>
            {chosen.length === 0 ? t("practice.setup.chooseFirst") : tp("practice.setup.start", chosen.length)}
          </button>
        </div>
      </>,
    );
  }

  if (phase.kind === "card") {
    const card = phase.queue[phase.index];
    const check = (result: SelfCheck) => {
      setResults((prev) => ({ ...prev, [phase.pass]: { ...prev[phase.pass], [card.unitId]: result } }));
      setAttempt("");
      if (phase.index + 1 < phase.queue.length) setPhase({ ...phase, index: phase.index + 1, revealed: false });
      else setPhase({ kind: "summary", pass: phase.pass, queue: phase.queue });
    };
    const heading = t(phase.pass === 1 ? "practice.card.heading" : "practice.card.headingSecond", {
      n: phase.index + 1,
      total: phase.queue.length,
    });
    const attemptId = `practice-attempt-${card.unitId}`;
    return shell(
      heading,
      <>
        <p className="label">{t("practice.card.fromRecord", { record: card.entryId })}</p>
        <p className="french pre-wrap practice-question">{card.question}</p>
        <div className="practice-attempt">
          <label htmlFor={attemptId}>{t("practice.card.attempt")}</label>
          <textarea
            id={attemptId}
            value={attempt}
            autoComplete="off"
            rows={3}
            onChange={(e) => setAttempt(e.target.value)}
          />
          <p className="hint">{t("practice.card.attemptHint")}</p>
        </div>
        {!phase.revealed ? (
          <div className="actions">
            <button type="button" className="primary" onClick={() => setPhase({ ...phase, revealed: true })}>
              {t("practice.card.reveal")}
            </button>
            <button type="button" className="ghost" onClick={() => check("skipped")}>
              {t("practice.check.skip")}
            </button>
          </div>
        ) : (
          <>
            <Reveal card={card} onOpenSource={() => onOpenSource(card.unitId)} />
            <div className="actions" role="group" aria-label={t("practice.check.label")}>
              <button type="button" className="primary" onClick={() => check("recalled")}>
                {t("practice.check.recalled")}
              </button>
              <button type="button" onClick={() => check("again")}>
                {t("practice.check.again")}
              </button>
              <button type="button" className="ghost" onClick={() => check("skipped")}>
                {t("practice.check.skip")}
              </button>
            </div>
            <p className="hint">{t("practice.check.hint")}</p>
          </>
        )}
      </>,
    );
  }

  // Summary of the pass that just finished.
  const passResults = results[phase.pass];
  const count = (r: SelfCheck) => phase.queue.filter((card) => passResults[card.unitId] === r).length;
  const again = phase.queue.filter((card) => passResults[card.unitId] === "again");
  return shell(
    t(phase.pass === 1 ? "practice.summary.heading" : "practice.summary.headingSecond"),
    <>
      <p role="status">{t("practice.summary.counts", { recalled: count("recalled"), again: count("again"), skipped: count("skipped") })}</p>
      <ul className="practice-summary">
        {phase.queue.map((card) => (
          <li key={card.unitId}>
            {t("practice.summary.item", { record: card.entryId, result: t(resultKey[passResults[card.unitId] ?? "skipped"]) })}
          </li>
        ))}
      </ul>
      <p className="hint">{t("practice.summary.nothingSaved")}</p>
      <div className="actions">
        {phase.pass === 1 && again.length > 0 ? (
          <button
            type="button"
            className="primary"
            onClick={() => {
              setAttempt("");
              setPhase({ kind: "card", pass: 2, queue: again, index: 0, revealed: false });
            }}
          >
            {tp("practice.summary.second", again.length)}
          </button>
        ) : null}
        <button
          type="button"
          className="ghost"
          onClick={() => {
            // A new selection starts from a fresh read of current support.
            setSelected([]);
            setSources({});
            setResults({ 1: {}, 2: {} });
            setPhase({ kind: "setup" });
            setConceptRetry((n) => n + 1);
          }}
        >
          {t("practice.summary.newSelection")}
        </button>
      </div>
      {phase.pass === 2 ? <p className="hint">{t("practice.summary.lastPass")}</p> : null}
    </>,
  );
}

function CandidateRow({
  candidate: c,
  checked,
  full,
  onToggle,
  onRetry,
}: {
  candidate: Candidate;
  checked: boolean;
  full: boolean;
  onToggle: () => void;
  onRetry: () => void;
}) {
  const { t, status } = useI18n();
  if (c.status === "ready") {
    const id = `practice-candidate-${c.unitId}`;
    return (
      <div className="practice-candidate">
        <input id={id} type="checkbox" checked={checked} disabled={!checked && full} onChange={onToggle} />{" "}
        <label htmlFor={id}>
          {t("practice.candidate.label", { record: c.card.entryId })}{" "}
          <span className="french pre-wrap">{c.card.question}</span>
        </label>
      </div>
    );
  }
  if (c.status === "loading") return <p className="hint" role="status">{t("practice.candidate.loading", { id: c.unitId })}</p>;
  if (c.status === "error")
    return (
      <div className="banner error" role="alert">
        {t("practice.candidate.failed", { id: c.unitId, message: c.message })}{" "}
        <button type="button" className="ghost" onClick={onRetry}>
          {t("common.retry")}
        </button>
      </div>
    );
  if (c.status === "unavailable") return <p className="hint">{t("practice.candidate.unavailable", { id: c.unitId })}</p>;
  if (c.status === "no-question") return <p className="hint">{t("practice.candidate.noQuestion", { id: c.unitId, record: c.entryId })}</p>;
  return <p className="hint">{t(exclusionKey[c.reason], { id: c.unitId, admission: status(c.admission) })}</p>;
}

// Reveal shows the stored reference material for one card: the unit's statement
// in the languages the Explanation-language preference shows, its example if one
// is stored, and the way back to the original source.
function Reveal({ card, onOpenSource }: { card: PracticeCard; onOpenSource: () => void }) {
  const { t } = useI18n();
  // The Reveal button that had focus is gone; the revealed material takes it.
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    headingRef.current?.focus();
  }, []);
  const hasStatement = card.statement.trim() !== "" || recorded(card.statements);
  return (
    <section className="library-section current practice-reveal" aria-labelledby={`practice-reveal-${card.unitId}`}>
      <h3 id={`practice-reveal-${card.unitId}`} ref={headingRef} tabIndex={-1}>
        {t("practice.reveal.heading")}
      </h3>
      <p className="hint">{t("practice.reveal.note", { id: card.unitId })}</p>
      {hasStatement ? (
        <p>
          <StoredText primary={card.statement} variants={card.statements} kind="statement" />
        </p>
      ) : (
        <p className="hint">{t("practice.reveal.noStatement")}</p>
      )}
      {card.example ? (
        <p className="hint">
          {t("library.frenchExample")}{" "}
          <span lang="fr" className="french">
            {card.example}
          </span>
        </p>
      ) : (
        <p className="hint">{t("practice.reveal.noExample")}</p>
      )}
      <button type="button" className="link-button" onClick={onOpenSource}>
        {t("practice.reveal.source", { record: card.entryId })}
      </button>
    </section>
  );
}
