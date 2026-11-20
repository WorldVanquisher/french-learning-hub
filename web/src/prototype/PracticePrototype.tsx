import { useLayoutEffect, useRef } from "react";
import { useI18n, type MessageKey } from "../i18n";
import { outcomeCounts } from "./practiceFeed";
import { applyWaiting, arrive, closePanel, focusSoon, openPanel, setDelay, usePracticeVisit } from "./practiceStore";
import { availability, current, nextIndex, timeline, todaySet, type PickReason } from "./practiceSession";
import { PracticeLog } from "./PracticeLog";
import { TutorSessions } from "./TutorSessions";

// Review Today's practice prototype panel (PROTOTYPE, private workbench), on
// the extraction lane's SEALED Extraction 2.1 fixtures. It starts a visit with
// a small actionable set ("today's practice"), lists each approved concept as
// a `practice` row with reason `practice_outcome`, shows what a source
// revision withdrew or restored, and holds the two fixture tutor sessions and
// this visit's log. Collapsed by default so a learner's own queue is never
// mixed with synthetic data. Everything here, including whether the panel is
// open, DISAPPEARS ON RELOAD; nothing is stored or sent.

const pickKey: Record<PickReason, MessageKey> = {
  personal_correction: "feedPractice.today.personal_correction",
  missed_last_time: "feedPractice.today.missed_last_time",
  not_an_option_last_time: "feedPractice.today.not_an_option_last_time",
  revealed_last_time: "feedPractice.today.revealed_last_time",
  self_checked_last_time: "feedPractice.today.self_checked_last_time",
  not_tried_yet: "feedPractice.today.not_tried_yet",
};
const kindKey: Record<string, MessageKey> = {
  explain: "feedPractice.kind.explain",
  choose: "feedPractice.kind.choose",
  produce: "feedPractice.kind.produce",
};
export const openerId = (sourceId: string) => `practice-open-${sourceId}`;
export const startId = (practiceId: string) => `practice-start-${practiceId}`;
export const noticeId = (sourceId: string) => `practice-notice-${sourceId}`;

export function PracticePrototype({ onOpen }: { onOpen: (sourceId: string, focusItem: string | null, returnTo: string) => void }) {
  const { t, tp } = useI18n();
  const { panel, error, catalog, visit, delayMs } = usePracticeVisit();
  // The open button is replaced by the panel once the fixtures are checked
  // (asynchronously): focus its heading in the same commit, so focus never
  // rests on the page body in between.
  const heading = useRef<HTMLHeadingElement>(null);
  const focusOnReady = useRef(false);
  useLayoutEffect(() => {
    if (panel !== "loading" && panel !== "closed" && focusOnReady.current) {
      focusOnReady.current = false;
      heading.current?.focus();
    }
  }, [panel]);
  if (panel === "closed" || panel === "loading")
    return (
      <section className="today-prototype" aria-label={t("feedPractice.panel.region")}>
        <button
          type="button"
          className="ghost"
          aria-expanded={false}
          aria-disabled={panel === "loading"}
          onClick={() => {
            if (panel === "loading") return;
            focusOnReady.current = true;
            void openPanel();
          }}
        >
          {panel === "loading" ? t("feedPractice.panel.loading") : t("feedPractice.panel.open")}
        </button>
      </section>
    );
  const picks = catalog ? todaySet(catalog, visit) : [];
  return (
    <section className="today-prototype" aria-label={t("feedPractice.panel.region")}>
      <h3 id="practice-panel-heading" ref={heading} tabIndex={-1}>
        {t("feedPractice.panel.heading")}
      </h3>
      <button type="button" className="ghost" aria-expanded={true} onClick={closePanel}>
        {t("feedPractice.panel.close")}
      </button>
      <p className="hint" data-ephemeral="page">
        {t("feedPractice.panel.note")}
      </p>
      {panel === "error" || !catalog ? (
        <div className="banner error" role="alert" data-fixture="refused">
          {t("feedPractice.panel.failed", { message: error ?? "" })}
        </div>
      ) : (
        <>
          <details className="feed-provenance" data-fixture="verified" data-handoff={catalog.source.handoff_sha256sums}>
            <summary>{t("feedPractice.fixture.summary", { count: catalog.documents.length, sums: catalog.source.handoff_sha256sums.slice(0, 12) })}</summary>
            <p className="hint">{t("feedPractice.fixture.how", { tar: catalog.source.snapshot_tar_sha256.slice(0, 12) })}</p>
            <ul className="listening-steps feed-docs">
              {catalog.documents.map((d) => (
                <li key={d.name} data-doc={d.name} data-origin={d.origin}>
                  <code>{d.name}</code> <span className="tag">{t(d.origin === "sealed" ? "feedPractice.fixture.sealed" : "feedPractice.fixture.generated")}</span> <code>{d.sha256.slice(0, 12)}</code>
                </li>
              ))}
            </ul>
          </details>

          <h4 id="practice-today-heading">{tp("feedPractice.today.heading", picks.length)}</h4>
          {picks.length ? (
            <ol className="listening-list today-queue feed-today" aria-labelledby="practice-today-heading">
              {picks.map((p) => (
                <li key={`${p.sourceId}/${p.item.practice_id}`} data-practice={p.item.practice_id} data-pick-reason={p.reason}>
                  <p>
                    <span className="tag">{t(kindKey[p.item.kind])}</span> <span className="reading-example-title">{p.concept}</span>{" "}
                    <span lang="fr" className="french">
                      {p.item.prompt}
                    </span>
                  </p>
                  <p className="hint">{t(pickKey[p.reason], { id: p.personalId ?? "" })}</p>
                  <div className="actions">
                    <button type="button" className="primary" id={startId(p.item.practice_id)} onClick={() => onOpen(p.sourceId, p.item.practice_id, startId(p.item.practice_id))}>
                      {t("feedPractice.today.start")}
                    </button>
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <p className="hint" data-today="empty">
              {t("feedPractice.today.empty")}
            </p>
          )}

          <h4>{t("feedPractice.panel.list")}</h4>
          <ol className="listening-list today-queue" aria-label={t("feedPractice.panel.list")}>
            {catalog.timelines.map((tl) => {
              const st = current(catalog, visit, tl.sourceId);
              const d = st.data;
              const c = outcomeCounts(st.feed.items);
              const nxt = nextIndex(catalog, visit, tl.sourceId);
              const waiting = visit.waiting[tl.sourceId];
              const withdrawn = st.feed.withdrawn?.length ?? 0;
              const restored = st.feed.items.filter((it) => availability(catalog, visit, tl.sourceId, it.practice_id).code === "restored_same_id").length;
              const s = st.feed.source;
              return (
                <li
                  key={tl.sourceId}
                  data-source="practice"
                  data-reason="practice_outcome"
                  data-source-id={tl.sourceId}
                  data-revision={s.revision}
                  data-key={`practice:source:${tl.sourceId}:r${s.revision}`}
                >
                  <p>
                    <span className="tag">{t("feedPractice.panel.sourceTag")}</span> <span className="tag">{t("feedPractice.tag.synthetic")}</span>{" "}
                    <span className="reading-example-title" lang="fr">
                      {tl.concept}
                    </span>{" "}
                    <span className="tag">{t("feedPractice.rev.tag", { revision: s.revision })}</span>
                  </p>
                  {d ? (
                    <p>
                      {tp("feedPractice.panel.reason", d.items.length, {
                        missed: c.incorrect,
                        revealed: c.revealed,
                        selfCheck: c.self_check,
                        correct: c.correct,
                      })}
                    </p>
                  ) : null}
                  {withdrawn && waiting === undefined ? (
                    <p data-reason-code="withdrawn_source_revised" id={noticeId(tl.sourceId)} tabIndex={-1}>
                      {tp("feedPractice.rev.rowWithdrawn", withdrawn, { revision: s.revision })}
                    </p>
                  ) : null}
                  {restored && waiting === undefined ? (
                    <p data-reason-code="restored_same_id" id={noticeId(tl.sourceId)} tabIndex={-1}>
                      {tp("feedPractice.rev.rowRestored", restored, { revision: s.revision })}
                    </p>
                  ) : null}
                  <p className="hint" data-based-on="practice">
                    {d
                      ? t("feedPractice.panel.basedOn", { source: s.source_id, revision: s.revision, sha: s.revision_sha256.slice(0, 12), tutor: d.tutorId })
                      : t("feedPractice.rev.basedOnNoItems", { source: s.source_id, revision: s.revision, sha: s.revision_sha256.slice(0, 12), feed: st.feedName })}
                  </p>
                  {waiting !== undefined ? (
                    <div className="banner warning" role="alert" data-reason-code="revision_waiting" id={noticeId(tl.sourceId)} tabIndex={-1}>
                      <p>{t("feedPractice.rev.waiting", { revision: timeline(catalog, tl.sourceId).states[waiting].feed.source.revision })}</p>
                      <div className="actions">
                        <button
                          type="button"
                          onClick={() => {
                            applyWaiting(tl.sourceId);
                            focusSoon(noticeId(tl.sourceId));
                          }}
                        >
                          {t("feedPractice.rev.apply", { revision: timeline(catalog, tl.sourceId).states[waiting].feed.source.revision })}
                        </button>
                      </div>
                    </div>
                  ) : null}
                  <div className="actions">
                    <button type="button" className="primary" id={openerId(tl.sourceId)} onClick={() => onOpen(tl.sourceId, null, openerId(tl.sourceId))}>
                      {t("feedPractice.panel.openConcept")}
                    </button>
                    {nxt !== null && waiting === undefined ? (
                      <button
                        type="button"
                        className="ghost"
                        data-simulate={tl.sourceId}
                        onClick={() => {
                          arrive(tl.sourceId);
                          focusSoon(noticeId(tl.sourceId));
                        }}
                      >
                        {t("feedPractice.rev.simulate", { revision: timeline(catalog, tl.sourceId).states[nxt].feed.source.revision })}
                      </button>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ol>
          <div className="feed-controls">
            <label className="checkbox">
              <input type="checkbox" checked={delayMs > 0} onChange={(e) => setDelay(e.target.checked ? 2000 : 0)} /> {t("feedPractice.delay.label")}
            </label>
            <p className="hint">{t("feedPractice.delay.hint")}</p>
          </div>
          <TutorSessions catalog={catalog} visit={visit} />
          <PracticeLog catalog={catalog} visit={visit} onPractise={(sourceId, pid) => onOpen(sourceId, pid, openerId(sourceId))} />
        </>
      )}
    </section>
  );
}
