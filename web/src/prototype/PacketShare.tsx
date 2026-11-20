import { useRef, useState } from "react";
import { useI18n } from "../i18n";
import type { Packet } from "./practiceFeed";

// A study packet for another agent, previewed beside the copy action: what it
// is about (scope, source revision), what it holds and what it never holds,
// then its Markdown exactly as the extraction lane exported it. The clipboard
// may be refused: the text is then shown and selected for the learner to copy.
// Showing or hiding the text never touches the learner's drafts (they live in
// the visit store), and Escape in the text closes it.
export function PacketShare({ packet, markdown, feedSha, idPrefix }: { packet: Packet; markdown: string; feedSha: string | null; idPrefix: string }) {
  const { t, tp } = useI18n();
  const [state, setState] = useState<"idle" | "copied" | "selected">("idle");
  const [shown, setShown] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const s = packet.source;
  const copy = async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("no clipboard");
      await navigator.clipboard.writeText(markdown);
      setState("copied");
    } catch {
      setShown(true);
      setState("selected");
      requestAnimationFrame(() => {
        area.current?.focus();
        area.current?.select();
      });
    }
  };
  const textId = `${idPrefix}-text`;
  return (
    <div className="feed-packet" data-packet={packet.packet_id}>
      <h4>{t("feedPractice.share.heading")}</h4>
      <ul className="listening-steps feed-share" aria-label={t("feedPractice.share.heading")}>
        <li data-share="packet">{t("feedPractice.packet.what", { id: packet.packet_id })}</li>
        <li data-share="scope">{t("feedPractice.share.scope", { concept: packet.concept, source: s.source_id, revision: s.revision, sha: s.revision_sha256.slice(0, 12), schema: packet.schema })}</li>
        <li data-share="has">{t("feedPractice.packet.has")}</li>
        <li data-share="contents">
          {t("feedPractice.share.contents", {
            knowledge: packet.knowledge.length,
            excerpts: packet.evidence.length,
            exercises: packet.exercise_ids.length,
            chars: markdown.length,
          })}
        </li>
        {packet.last_confusion || packet.next_exercise ? (
          <li data-share="left-off">
            {t("feedPractice.share.leftOff", {
              confusion: packet.last_confusion ? packet.last_confusion.forms.join(" / ") : "—",
              next: packet.next_exercise?.id ?? "—",
            })}
          </li>
        ) : null}
        {packet.continuity ? (
          <li data-share="continuity">{tp("feedPractice.share.continuity", packet.continuity.changed.length, { previous: packet.continuity.previous_packet_id })}</li>
        ) : null}
        <li data-share="excluded">{t("feedPractice.packet.hasNot")}</li>
        <li data-share="this-visit">{t("feedPractice.packet.thisVisit")}</li>
        {feedSha ? <li className="hint">{t("feedPractice.share.basedOn", { feed: feedSha.slice(0, 12) })}</li> : null}
      </ul>
      <div className="actions">
        <button type="button" className="primary" onClick={() => void copy()}>
          {t("feedPractice.packet.copy")}
        </button>
        <button type="button" className="ghost" ref={toggle} aria-expanded={shown} aria-controls={shown ? textId : undefined} onClick={() => setShown((v) => !v)}>
          {shown ? t("feedPractice.packet.hide") : t("feedPractice.packet.show")}
        </button>
      </div>
      <p role="status" aria-live="polite" data-copy={state}>
        {state === "copied"
          ? t("feedPractice.packet.copied", { id: packet.packet_id, chars: markdown.length })
          : state === "selected"
            ? t("feedPractice.packet.selected")
            : ""}
      </p>
      <p className="hint">{t("feedPractice.packet.howTo")}</p>
      {shown ? (
        <>
          <label htmlFor={textId}>{t("feedPractice.packet.textLabel", { id: packet.packet_id })}</label>
          <textarea
            id={textId}
            ref={area}
            className="feed-packet-text"
            readOnly
            rows={12}
            value={markdown}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.preventDefault();
                setShown(false);
                requestAnimationFrame(() => toggle.current?.focus());
              }
            }}
          />
        </>
      ) : null}
    </div>
  );
}
