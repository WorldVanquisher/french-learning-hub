import { createContext } from "react";

// A record's draft holders (FeedbackPanel) report here whether the open record
// has unsaved input, so Learning Records never discards it silently when another
// record is opened (from another view or the list) or the record is closed.
// Outside Learning Records nothing listens.
export const UnsavedDraftContext = createContext<(hasDraft: boolean) => void>(() => {});
