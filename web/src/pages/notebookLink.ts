import { ApiError } from "../api/client";
import type { SourceRef, SourceType } from "../types/notebook";

// sourceRef is the optional source_ref a save path sends with its capture
// (Mistake Notebook v1): the exact stored item, by the record's id and the
// item's 1-based position. attempt is included only when the learner chose to.
export function sourceRef(type: SourceType, recordId: number, index: number, attempt = ""): SourceRef {
  const ref: SourceRef = { type, record_id: recordId, item: index + 1 };
  if (attempt.trim()) ref.attempt = attempt.trim();
  return ref;
}

// alreadySaved returns the record an item was already saved as (the server's
// 409 source_already_saved), or null.
export function alreadySaved(e: unknown): number | null {
  if (!(e instanceof ApiError) || e.status !== 409) return null;
  const body = e.body as { code?: string; entry_id?: number } | undefined;
  return body?.code === "source_already_saved" && typeof body.entry_id === "number" ? body.entry_id : null;
}
