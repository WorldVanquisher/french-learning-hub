// Vocabulary's page memory: the search and the "saved only" filter survive
// opening a source, a review or another notebook view and coming back. Module
// memory for the page's lifetime only: never in browser storage, never sent.

let query = "";
let savedOnly = false;

export const vocabularyQuery = (): string => query;
export const setVocabularyQuery = (q: string): void => {
  query = q;
};
export const vocabularySavedOnly = (): boolean => savedOnly;
export const setVocabularySavedOnly = (on: boolean): void => {
  savedOnly = on;
};
export const resetVocabularyMemory = (): void => {
  query = "";
  savedOnly = false;
};
