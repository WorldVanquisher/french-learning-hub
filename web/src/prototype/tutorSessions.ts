// Two tutoring sessions from the sealed fixture (no agent was run): the study
// packet each agent received, what it sent back, and the read-only review of
// that return. Session 1 is Codex on packet pk-e2920fe276cb; the learner then
// accepted c1 in the extraction tool, and session 2 is Claude Code on the next
// packet (pk-afdb387f3af6), which names that change under "continuity".

import { parsePreview, parseReturn, review, type ReviewedProposal } from "./agentReturn";
import { ContractError, type Packet } from "./practiceFeed";

export interface TutorSession {
  n: number;
  agent: string;
  packet: Packet;
  markdown: string;
  note: string;
  proposals: ReviewedProposal[];
}

export function agentReturnOf(n: number, packet: Packet, markdown: string, ret: unknown, preview: unknown): TutorSession {
  if (packet.mode !== "study" || packet.rubrics_included) throw new ContractError(`session ${n}: the agent must have received a study packet`);
  if (!markdown.includes(packet.packet_id)) throw new ContractError(`session ${n}: the packet text does not name ${packet.packet_id}`);
  const r = parseReturn(ret);
  return { n, agent: r.agent, packet, markdown, note: r.note, proposals: review(packet, r, parsePreview(preview)) };
}
