// FLH-097: the one generation request whose outcome is not yet known. Only its
// Idempotency-Key and unit IDs are stored (no learning text, no credentials),
// versioned, origin-local, and written BEFORE the request is sent, so a lost
// response or a reload can look the request up instead of sending a new one.

const storageKey = "flh.concept-suggestion-requests.v1";
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export type PendingSuggestionRequest = { operationId: string; unitIds: number[] };

// Browser storage could not be read, parsed or written. Nothing is sent then.
export class SuggestionStorageError extends Error {}

export function loadPendingRequest(): PendingSuggestionRequest | null {
  let parsed: unknown;
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (raw === null) return null;
    parsed = JSON.parse(raw);
  } catch {
    throw new SuggestionStorageError("Saved suggestion request cannot be read.");
  }
  if (!parsed || typeof parsed !== "object" || (parsed as { version?: unknown }).version !== 1) {
    throw new SuggestionStorageError("Saved suggestion request is not readable.");
  }
  const pending = (parsed as { pending?: unknown }).pending;
  if (pending === null) return null;
  const p = pending as { operationId?: unknown; unitIds?: unknown };
  if (typeof p.operationId !== "string" || !uuid.test(p.operationId) || !Array.isArray(p.unitIds) ||
      p.unitIds.length === 0 || !p.unitIds.every((id) => Number.isSafeInteger(id) && id > 0)) {
    throw new SuggestionStorageError("Saved suggestion request is not readable.");
  }
  return { operationId: p.operationId, unitIds: p.unitIds as number[] };
}

function write(pending: PendingSuggestionRequest | null): void {
  try {
    window.localStorage.setItem(storageKey, JSON.stringify({ version: 1, pending }));
  } catch {
    throw new SuggestionStorageError("Browser storage could not be written.");
  }
}

export function savePendingRequest(pending: PendingSuggestionRequest): void {
  write(pending);
}

// clearPendingRequest forgets the request only when it is still the saved one.
export function clearPendingRequest(operationId: string): void {
  let current: PendingSuggestionRequest | null = null;
  try {
    current = loadPendingRequest();
  } catch {
    // Unreadable storage: overwrite it with "nothing pending".
  }
  if (current === null || current.operationId === operationId) write(null);
}
