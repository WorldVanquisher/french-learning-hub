// In-app navigation between a record's extracted units and the Concept Review or
// Inspector views. There is no router: App keeps the Learning Records view
// mounted while another view is shown, so returning restores the record, its
// viewed extraction, filters, drafts, and list position as they were.

// UnitTarget names one extracted unit to open elsewhere. It carries only what the
// target view needs to re-read backend state; it is never treated as authority.
export interface UnitTarget {
  kind: "review" | "inspect";
  entryId: number;
  unitId: number;
  // The extraction the unit belongs to, as shown when navigation started.
  extractionId: number;
  extractionVersion: number;
}

// The element that receives focus when the reader returns to the record.
export const unitFocusId = (unitId: number) => `extracted-unit-${unitId}`;
export const recordHeadingId = (entryId: number) => `record-heading-${entryId}`;
