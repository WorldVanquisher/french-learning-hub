import * as api from "../api/client";
import type { EffectiveAnnotationItem } from "../types/concept";
import type { CurrentExtraction } from "../types/learning";
import { msg, type MessageRef } from "../i18n";

// What the focused inspection shows for one unit: its backend-derived effective
// annotation and the record's current extraction selection, read together.
export type Inspection = { item: EffectiveAnnotationItem; current: CurrentExtraction };

// The backend facts a correction was confirmed against. Immediately before
// sending, they are read again; any difference means the reviewer saw a state
// that no longer exists, so nothing is sent.
export type CorrectionBasis = {
  currentExtractionId: number | null;
  unitExtractionId: number;
  status: string;
  sameLinkId: number | null;
  judgmentId: number | null;
};

// One explicit correction of an already reviewed current-extraction unit. Each
// maps to an existing backend operation; none adds semantics of its own.
export type Correction =
  | { kind: "reassign"; unitId: number; fromConceptId: number; fromLinkId: number; toConceptId: number }
  | { kind: "invalid"; unitId: number; fromConceptId: number; fromLinkId: number }
  | { kind: "restore"; unitId: number; judgmentId: number };

export type Eligibility =
  | { kind: "reassign-or-invalid"; conceptId: number; linkId: number }
  | { kind: "restore"; judgmentId: number }
  | { kind: "none"; reason: MessageRef };

export function basisOf({ item, current }: Inspection): CorrectionBasis {
  return {
    currentExtractionId: current.current_extraction_id,
    unitExtractionId: item.unit.extraction_id,
    status: item.snapshot.status,
    sameLinkId: item.snapshot.current_same?.membership.link_id ?? null,
    judgmentId: item.snapshot.latest_unit_judgment?.id ?? null,
  };
}

export function sameBasis(a: CorrectionBasis, b: CorrectionBasis): boolean {
  return (
    a.currentExtractionId === b.currentExtractionId &&
    a.unitExtractionId === b.unitExtractionId &&
    a.status === b.status &&
    a.sameLinkId === b.sameLinkId &&
    a.judgmentId === b.judgmentId
  );
}

// correctionEligibility decides which existing correction the backend state
// offers. The correction endpoints accept any unit, so the restriction to the
// record's current extraction is applied here, from backend-reported facts only:
// historical units stay read-only on this path.
export function correctionEligibility({ item, current }: Inspection): Eligibility {
  const { unit, snapshot } = item;
  if (snapshot.unit_id !== unit.id) {
    return { kind: "none", reason: msg("correction.none.mismatch") };
  }
  if (current.current_extraction_id === null || unit.extraction_id !== current.current_extraction_id) {
    return { kind: "none", reason: msg("correction.none.historical") };
  }
  if (snapshot.status === "resolved" && snapshot.current_same) {
    return {
      kind: "reassign-or-invalid",
      conceptId: snapshot.current_same.membership.concept_id,
      linkId: snapshot.current_same.membership.link_id,
    };
  }
  if (snapshot.status === "invalid" && snapshot.latest_unit_judgment) {
    return { kind: "restore", judgmentId: snapshot.latest_unit_judgment.id };
  }
  if (snapshot.status === "unresolved") {
    return { kind: "none", reason: msg("correction.none.unresolved") };
  }
  return { kind: "none", reason: msg("correction.none.noOption") };
}

export function describeCorrection(c: Correction): MessageRef {
  switch (c.kind) {
    case "reassign":
      return msg("correction.label.reassign", { from: c.fromConceptId, to: c.toConceptId });
    case "invalid":
      return msg("decision.label.invalid");
    case "restore":
      return msg("correction.label.restore");
  }
}

// sendCorrection performs the write once and returns the confirmed result text.
// It never retries.
export async function sendCorrection(c: Correction): Promise<MessageRef> {
  switch (c.kind) {
    case "reassign": {
      const link = await api.reassignSame(c.unitId, c.toConceptId);
      return msg("correction.sent.reassign", { unit: c.unitId, from: c.fromConceptId, to: link.concept_id, event: link.id });
    }
    case "invalid": {
      const res = await api.markUnitInvalid(c.unitId);
      return res.judgment
        ? msg("correction.sent.invalid", { unit: c.unitId, judgment: res.judgment.id, from: c.fromConceptId })
        : msg("correction.sent.invalidAlready", { unit: c.unitId });
    }
    case "restore": {
      const res = await api.restoreUnit(c.unitId);
      return res.judgment
        ? msg("correction.sent.restore", { unit: c.unitId, judgment: res.judgment.id })
        : msg("correction.sent.restoreNothing", { unit: c.unitId });
    }
  }
}

export type Evidence = { found: boolean; text: MessageRef };

// checkCorrection reads the current authority a correction with an unknown
// outcome would have changed. `found: false` never proves the request failed: it
// may still be in progress on the server, or something else changed the unit.
export async function checkCorrection(c: Correction): Promise<Evidence> {
  switch (c.kind) {
    case "reassign": {
      const m = (await api.getCurrentMembership(c.unitId)).current_membership;
      return m && m.concept_id === c.toConceptId
        ? { found: true, text: msg("correction.check.same", { id: m.concept_id, link: m.link_id }) }
        : {
            found: false,
            text: m ? msg("correction.check.sameOther", { id: m.concept_id, wanted: c.toConceptId }) : msg("correction.check.sameNone"),
          };
    }
    case "invalid": {
      const env = await api.getUnitInvalid(c.unitId);
      return env.invalid
        ? { found: true, text: msg("check.invalid.found", { judgment: env.history[0]?.id ?? "?" }) }
        : { found: false, text: msg("check.invalid.missing") };
    }
    case "restore": {
      const env = await api.getUnitInvalid(c.unitId);
      const latest = env.history[0];
      // Only a judgment newer than the INVALID one being withdrawn counts.
      return !env.invalid && latest && latest.id > c.judgmentId
        ? { found: true, text: msg("correction.check.restored", { judgment: latest.id }) }
        : { found: false, text: msg(env.invalid ? "correction.check.stillInvalid" : "correction.check.noNewer") };
    }
  }
}
