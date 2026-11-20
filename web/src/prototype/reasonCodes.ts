// Extraction 2.2 withdrawal reason codes (flh_practice_feed_additions_v1), in
// Workbooks' words. The result is a message reference, so a language switch
// re-renders it. An unknown code is shown verbatim with a general sentence:
// Workbooks never guesses what a new code means.
import type { MessageKey } from "../i18n";

const KNOWN: Record<string, MessageKey> = {
  rule_not_approved: "feedPractice.rev.code.rule_not_approved",
  awaiting_confirmation: "feedPractice.rev.code.awaiting_confirmation",
};

export const isKnownReasonCode = (code: string) => Object.prototype.hasOwnProperty.call(KNOWN, code);

export function reasonCodeMessage(code: string, since: number): { key: MessageKey; vars: Record<string, string | number> } {
  return isKnownReasonCode(code) ? { key: KNOWN[code], vars: { revision: since } } : { key: "feedPractice.rev.code.unknown", vars: { code, revision: since } };
}
