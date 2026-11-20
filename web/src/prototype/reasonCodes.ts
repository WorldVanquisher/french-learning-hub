// Extraction 2.2 withdrawal reason codes (flh_practice_feed_additions_v1), in
// Workbooks' words. The result is a message reference, so a language switch
// re-renders it. An unknown code is shown verbatim with a general sentence:
// Workbooks never guesses what a new code means.
import type { MessageKey } from "../i18n";

// The merged contract (tools/extraction/PRACTICE.md §13) lists five codes.
const KNOWN: Record<string, MessageKey> = {
  knowledge_changed: "feedPractice.rev.code.knowledge_changed",
  awaiting_confirmation: "feedPractice.rev.code.awaiting_confirmation",
  rejected: "feedPractice.rev.code.rejected",
  rule_not_approved: "feedPractice.rev.code.rule_not_approved",
  absent: "feedPractice.rev.code.absent",
};

export const isKnownReasonCode = (code: string) => Object.prototype.hasOwnProperty.call(KNOWN, code);

export function reasonCodeMessage(code: string, since: number): { key: MessageKey; vars: Record<string, string | number> } {
  return isKnownReasonCode(code) ? { key: KNOWN[code], vars: { revision: since } } : { key: "feedPractice.rev.code.unknown", vars: { code, revision: since } };
}
