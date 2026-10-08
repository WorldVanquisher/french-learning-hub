import type { Decision } from "./reviewOutcome";

const storageKey = "flh.annotation-operations.v1";
type StoredDecision = Extract<Decision, { kind: "distinct" | "relation" }> & { operationId: string };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

// Only in-scope action, IDs, relation and key are stored. Storage is origin-local,
// versioned, and written before sending. No credentials or learning text.
export function loadOperations(): StoredDecision[] {
  const raw = window.localStorage.getItem(storageKey);
  if (raw === null) return [];
  const parsed: unknown = JSON.parse(raw);
  if (!parsed || typeof parsed !== "object" || !("version" in parsed) || parsed.version !== 1 ||
      !("operations" in parsed) || !Array.isArray(parsed.operations)) throw new Error("Saved annotation operations cannot be read. Nothing new was sent.");
  const operations: StoredDecision[] = [];
  for (const value of parsed.operations) {
    if (!value || typeof value !== "object" || !uuid.test(value.operationId) ||
        !Number.isSafeInteger(value.unitId) || value.unitId <= 0 ||
        !Number.isSafeInteger(value.conceptId) || value.conceptId <= 0 ||
        !["distinct", "relation"].includes(value.kind) ||
        (value.kind === "relation" && !["broader", "narrower", "related"].includes(value.relation))) {
      throw new Error("Saved annotation operations cannot be read. Nothing new was sent.");
    }
    operations.push(value.kind === "distinct"
      ? { kind: "distinct", unitId: value.unitId, conceptId: value.conceptId, operationId: value.operationId }
      : { kind: "relation", unitId: value.unitId, conceptId: value.conceptId, relation: value.relation, operationId: value.operationId });
  }
  return operations;
}
export function saveOperation(d: Decision): void {
  if (!d.operationId || (d.kind !== "distinct" && d.kind !== "relation")) return;
  const operations = loadOperations();
  const prior = operations.find((op) => op.operationId === d.operationId);
  if (prior && (prior.kind !== d.kind || prior.unitId !== d.unitId || prior.conceptId !== d.conceptId || (prior.kind === "relation" && d.kind === "relation" && prior.relation !== d.relation))) throw new Error("Saved operation payload changed. Nothing was sent.");
  if (!prior) {
    if (operations.some((op) => op.unitId === d.unitId)) throw new Error("Another operation for this unit is unresolved. Nothing was sent.");
    operations.push(d as StoredDecision);
  }
  window.localStorage.setItem(storageKey, JSON.stringify({ version: 1, operations }));
}
export function clearOperation(id: string): void {
  window.localStorage.setItem(storageKey, JSON.stringify({ version: 1, operations: loadOperations().filter((d) => d.operationId !== id) }));
}
export function newOperation(d: Decision): Decision {
  if (d.kind !== "distinct" && d.kind !== "relation") return d;
  // getRandomValues also works on explicitly allowed HTTP origins, where
  // randomUUID may be unavailable because the page is not a secure context.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  const operationId = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  return { ...d, operationId };
}
