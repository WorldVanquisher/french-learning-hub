// Vitest setup: adds jest-dom matchers (toBeInTheDocument, etc.) to expect().
import "@testing-library/jest-dom/vitest";

// The workbench keeps its section in the address (sectionAddress.ts) and
// jsdom keeps one window per test file, so every test starts at "/".
import { afterEach } from "vitest";
afterEach(() => {
  window.history.replaceState(null, "", "/");
  // Recent Knowledge Library searches (pages/recentSearches.ts) are kept in
  // localStorage; each test starts without them.
  try {
    window.localStorage.removeItem("flh.library.recent.v1");
  } catch {
    // storage unavailable: nothing to reset
  }
});
