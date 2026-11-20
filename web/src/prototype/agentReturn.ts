// Agent returns (PROTOTYPE, private workbench): what a tutoring agent sent back
// after a study packet (flh_agent_proposals_v1), and the extraction lane's
// read-only classification of it (flh_agent_import_preview_v1). Nothing here is
// applied: accepting a correction is the learner's decision in the extraction
// tool (`practice accept`), and the prototype can only mark one as accepted for
// this visit (page state).
//
// classify() re-derives each class from the packet with the extraction lane's
// documented rules (PRACTICE.md §5, packet.import_preview). The page shows the
// sealed preview only when both agree, so a stale or altered preview is caught
// instead of trusted; agentReturn.test.ts checks parity on both sealed returns.

import { ContractError, frNorm, type Packet } from "./practiceFeed";

export const PROPOSALS_SCHEMA = "flh_agent_proposals_v1";
export const PREVIEW_SCHEMA = "flh_agent_import_preview_v1";
export type ProposalClass = "accepted_candidate" | "duplicate" | "conflict" | "unknown_reference" | "invalid";
export const CLASSES: ProposalClass[] = ["accepted_candidate", "duplicate", "conflict", "unknown_reference", "invalid"];

export interface Proposal {
  proposal_id: string;
  type: string;
  rationale: string;
  evidence_ids: string[];
  target_id?: string;
  text?: string;
  knowledge_ids?: string[];
  kind?: string;
  prompt?: string;
  options?: string[];
  answer?: string;
  accepted?: string[];
  raw: Record<string, unknown>;
}

export interface AgentReturn {
  agent: string;
  packet_id: string;
  note: string;
  proposals: Proposal[];
}

export interface PreviewRow {
  proposal_id: string;
  class: ProposalClass;
  why: string; // the preview's sentence (producer text, shown verbatim)
  flags: string[];
}

export interface ReturnPreview {
  agent: string;
  packet_id: string;
  packet_matches: boolean;
  rows: PreviewRow[];
}

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const sList = (v: unknown): string[] => (Array.isArray(v) ? v.filter((s): s is string => typeof s === "string") : []);
const sOpt = (v: unknown): string | undefined => (typeof v === "string" ? v : undefined);

export function parseReturn(x: unknown): AgentReturn {
  if (!isObj(x) || x.schema !== PROPOSALS_SCHEMA || !Array.isArray(x.proposals)) throw new ContractError(`not a ${PROPOSALS_SCHEMA} document`);
  return {
    agent: typeof x.agent === "string" ? x.agent : "unknown",
    packet_id: typeof x.packet_id === "string" ? x.packet_id : "",
    note: typeof x.fixture_note === "string" ? x.fixture_note : "",
    proposals: x.proposals.map((p, i): Proposal => {
      const o = isObj(p) ? p : {};
      return {
        proposal_id: typeof o.proposal_id === "string" && o.proposal_id ? o.proposal_id : `#${i + 1}`,
        type: typeof o.type === "string" ? o.type : "",
        rationale: typeof o.rationale === "string" ? o.rationale : "",
        evidence_ids: sList(o.evidence_ids),
        target_id: sOpt(o.target_id),
        text: sOpt(o.text),
        knowledge_ids: Array.isArray(o.knowledge_ids) ? sList(o.knowledge_ids) : undefined,
        kind: sOpt(o.kind),
        prompt: sOpt(o.prompt),
        options: Array.isArray(o.options) ? sList(o.options) : undefined,
        answer: sOpt(o.answer),
        accepted: Array.isArray(o.accepted) ? sList(o.accepted) : undefined,
        raw: o,
      };
    }),
  };
}

export function parsePreview(x: unknown): ReturnPreview {
  if (!isObj(x) || x.schema !== PREVIEW_SCHEMA || !Array.isArray(x.rows)) throw new ContractError(`not a ${PREVIEW_SCHEMA} document`);
  return {
    agent: typeof x.agent === "string" ? x.agent : "unknown",
    packet_id: typeof x.packet_id === "string" ? x.packet_id : "",
    packet_matches: x.packet_matches === true,
    rows: x.rows.map((r, i) => {
      if (!isObj(r) || typeof r.proposal_id !== "string" || !CLASSES.includes(r.class as ProposalClass))
        throw new ContractError(`preview row ${i + 1}: needs proposal_id and a known class`);
      return { proposal_id: r.proposal_id, class: r.class as ProposalClass, why: typeof r.why === "string" ? r.why : "", flags: sList(r.flags) };
    }),
  };
}

export interface Classified {
  proposal_id: string;
  class: ProposalClass;
  why: string;
}

// classify mirrors the extraction lane's rules, in their order: invalid,
// unknown reference, duplicate (current wording, an earlier proposal, or a
// prompt already in the packet), conflict (replacing a learner correction; a
// choose answer outside its options; an expected answer using a known
// confusion), else an accepted candidate that still needs the learner.
export function classify(packet: Packet, ret: AgentReturn): Classified[] {
  const kids = new Set(packet.knowledge.map((k) => k.id));
  const eids = new Set(packet.evidence.map((e) => e.evidence_id));
  const know = new Map(packet.knowledge.map((k) => [k.id, k]));
  const wrong = packet.known_confusions.map((w) => frNorm(w));
  const prompts = new Set(packet.exercise_prompts.map(frNorm));
  const seenText = new Map<string, string>();
  const seenPrompt = new Map<string, string>();
  return ret.proposals.map((p): Classified => {
    const c = (cls: ProposalClass, why: string): Classified => ({ proposal_id: p.proposal_id, class: cls, why });
    const r = p.raw;
    if (!r.proposal_id || !r.type || !r.rationale || !Array.isArray(r.evidence_ids) || (p.type !== "correction" && p.type !== "exercise"))
      return c("invalid", "needs proposal_id, type (correction | exercise), rationale and an evidence_ids list");
    const unknown = [...new Set(p.evidence_ids)].filter((e) => !eids.has(e)).sort();
    if (p.type === "correction") {
      const t = p.target_id ?? "";
      if (!p.text) return c("invalid", "a correction needs text");
      if (!kids.has(t) || unknown.length)
        return c("unknown_reference", "unknown " + [...(!kids.has(t) ? [`target ${t}`] : []), ...unknown.map((e) => `evidence ${e}`)].join(", "));
      const key = `${t}\u0000${frNorm(p.text)}`;
      const current = know.get(t)!;
      if (frNorm(p.text) === frNorm(current.text ?? "") || seenText.has(key))
        return c("duplicate", "same wording as " + (seenText.has(key) ? seenText.get(key)! : `the current ${t}`));
      seenText.set(key, p.proposal_id);
      if (current.raw.learner_corrected === true)
        return c("conflict", `the learner already corrected ${t}; replacing a learner correction needs the learner's own decision`);
      return c("accepted_candidate", "");
    }
    const kn = p.knowledge_ids ?? [];
    const miss = [...new Set(kn)].filter((k) => !kids.has(k)).sort();
    if (!kn.length || !["explain", "choose", "produce"].includes(p.kind ?? "") || !p.prompt)
      return c("invalid", "an exercise needs knowledge_ids, kind (explain | choose | produce) and prompt");
    if (miss.length || unknown.length) return c("unknown_reference", "unknown " + [...miss.map((m) => `knowledge ${m}`), ...unknown.map((e) => `evidence ${e}`)].join(", "));
    const np = frNorm(p.prompt);
    if (prompts.has(np) || seenPrompt.has(np)) return c("duplicate", "the same prompt is already " + (prompts.has(np) ? "in the packet" : `proposed by ${seenPrompt.get(np)}`));
    seenPrompt.set(np, p.proposal_id);
    const answers = [p.answer ?? "", ...(p.accepted ?? [])];
    const bad = answers.filter((a) => a && wrong.some((w) => ` ${frNorm(a)} `.includes(` ${w} `)));
    if (p.kind === "choose" && !(p.options ?? []).includes(p.answer ?? "\u0000")) return c("conflict", "the answer is not one of the options");
    if (bad.length) return c("conflict", `an expected answer uses a known confusion: '${bad[0]}'`);
    return c("accepted_candidate", "");
  });
}

export interface ReviewedProposal {
  proposal: Proposal;
  class: ProposalClass;
  why: string;
  flags: string[];
  current: string | null; // the wording a correction would replace
  targetOrigin: string | null;
}

// review joins a return, its sealed preview and the packet. It refuses a
// preview about another packet, a row for an unknown proposal, a proposal
// without a row, and any class the rules above do not reproduce.
export function review(packet: Packet, ret: AgentReturn, preview: ReturnPreview): ReviewedProposal[] {
  if (preview.packet_id !== packet.packet_id) throw new ContractError(`the preview is about ${preview.packet_id}, not packet ${packet.packet_id}`);
  if (ret.packet_id !== packet.packet_id || !preview.packet_matches) throw new ContractError(`the return names ${ret.packet_id}, not packet ${packet.packet_id}`);
  const mine = classify(packet, ret);
  if (preview.rows.length !== ret.proposals.length) throw new ContractError("the preview does not list every proposal");
  return ret.proposals.map((p, i) => {
    const row = preview.rows[i];
    if (row.proposal_id !== p.proposal_id) throw new ContractError(`preview row ${i + 1} is ${row.proposal_id}, not ${p.proposal_id}`);
    if (row.class !== mine[i].class) throw new ContractError(`${p.proposal_id}: the preview says ${row.class}, the documented rules give ${mine[i].class}`);
    const target = p.type === "correction" && p.target_id ? packet.knowledge.find((k) => k.id === p.target_id) ?? null : null;
    return { proposal: p, class: row.class, why: row.why || mine[i].why, flags: row.flags, current: target?.text ?? null, targetOrigin: target?.origin ?? null };
  });
}
