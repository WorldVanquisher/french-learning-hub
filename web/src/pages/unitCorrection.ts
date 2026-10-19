import * as api from "../api/client";
import type { EffectiveAnnotationItem } from "../types/concept";
import type { CurrentExtraction } from "../types/learning";

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
  | { kind: "none"; reason: string };

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
    return { kind: "none", reason: "The effective snapshot does not match this unit, so no correction is offered." };
  }
  if (current.current_extraction_id === null || unit.extraction_id !== current.current_extraction_id) {
    return {
      kind: "none",
      reason: "Historical units are read-only here: corrections are offered only for units of the record's current extraction.",
    };
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
    return { kind: "none", reason: "This unit has no CURRENT SAME membership and is not INVALID; review it in Concept Review." };
  }
  return { kind: "none", reason: "The backend state of this unit offers no correction here." };
}

export function describeCorrection(c: Correction): string {
  switch (c.kind) {
    case "reassign":
      return `REASSIGN SAME concept #${c.fromConceptId} → concept #${c.toConceptId}`;
    case "invalid":
      return "INVALID";
    case "restore":
      return "RESTORE";
  }
}

// sendCorrection performs the write once and returns the confirmed result text.
// It never retries.
export async function sendCorrection(c: Correction): Promise<string> {
  switch (c.kind) {
    case "reassign": {
      const link = await api.reassignSame(c.unitId, c.toConceptId);
      return `Moved unit #${c.unitId}'s CURRENT SAME membership from concept #${c.fromConceptId} to concept #${link.concept_id} (SAME event #${link.id}).`;
    }
    case "invalid": {
      const res = await api.markUnitInvalid(c.unitId);
      return res.judgment
        ? `Marked unit #${c.unitId} INVALID (judgment #${res.judgment.id}); its SAME membership to concept #${c.fromConceptId} was cleared.`
        : `The server reports unit #${c.unitId} as INVALID.`;
    }
    case "restore": {
      const res = await api.restoreUnit(c.unitId);
      return res.judgment
        ? `Restored unit #${c.unitId} (judgment #${res.judgment.id}). It is unresolved and awaits Concept Review.`
        : `The server recorded nothing new: unit #${c.unitId} was not INVALID anymore.`;
    }
  }
}

export type Evidence = { found: boolean; text: string };

// checkCorrection reads the current authority a correction with an unknown
// outcome would have changed. `found: false` never proves the request failed: it
// may still be in progress on the server, or something else changed the unit.
export async function checkCorrection(c: Correction): Promise<Evidence> {
  switch (c.kind) {
    case "reassign": {
      const m = (await api.getCurrentMembership(c.unitId)).current_membership;
      return m && m.concept_id === c.toConceptId
        ? { found: true, text: `The unit's CURRENT SAME membership is concept #${m.concept_id} (link #${m.link_id}).` }
        : {
            found: false,
            text: m ? `The unit's CURRENT SAME membership is concept #${m.concept_id}, not #${c.toConceptId}.` : "The unit has no CURRENT SAME membership.",
          };
    }
    case "invalid": {
      const env = await api.getUnitInvalid(c.unitId);
      return env.invalid
        ? { found: true, text: `The unit is INVALID (judgment #${env.history[0]?.id ?? "?"}).` }
        : { found: false, text: "The unit is not INVALID." };
    }
    case "restore": {
      const env = await api.getUnitInvalid(c.unitId);
      const latest = env.history[0];
      // Only a judgment newer than the INVALID one being withdrawn counts.
      return !env.invalid && latest && latest.id > c.judgmentId
        ? { found: true, text: `The unit is no longer INVALID (judgment #${latest.id}).` }
        : { found: false, text: env.invalid ? "The unit is still INVALID." : "No judgment newer than the withdrawn one is stored." };
    }
  }
}
