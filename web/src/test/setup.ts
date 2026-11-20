// Vitest setup: adds jest-dom matchers (toBeInTheDocument, etc.) to expect().
import "@testing-library/jest-dom/vitest";

// The workbench keeps its section in the address (sectionAddress.ts) and
// jsdom keeps one window per test file, so every test starts at "/".
import { afterEach } from "vitest";
import { resetReviewTodayMemory } from "../pages/reviewTodayMemory";
afterEach(() => {
  window.history.replaceState(null, "", "/");
  // Review Today's page memory (hidden steps, the item to return to) lives for
  // the page's lifetime, which is the whole test file here: each test starts
  // without it, as after a reload.
  resetReviewTodayMemory();
  // Recent Knowledge Library searches (pages/recentSearches.ts) are kept in
  // localStorage; each test starts without them.
  try {
    window.localStorage.removeItem("flh.library.recent.v1");
  } catch {
    // storage unavailable: nothing to reset
  }
});
