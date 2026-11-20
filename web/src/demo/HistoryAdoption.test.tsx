import { StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { KnowledgeLibrary } from "../pages/KnowledgeLibrary";
import { LocaleProvider } from "../i18n";
import type { PublicDemoInfo } from "../types/library";
import { demoServer, info } from "./demoTestServer";

// The demo adopts the history entry it opens on (demo/history.ts) in the same
// commit that first shows its screen. Were that adoption left to a passive
// effect, a click landing after the screen is shown but before the effect ran
// would push the next screen first, and the late adoption would then rewrite
// that new entry as the start: the address would stop naming the screen, and
// Back from the screen after it would skip one (src/demo/Navigation.test.tsx
// saw this on a loaded CI runner).

let root: Root | null = null;
let host: HTMLElement | null = null;
const actEnvironment = (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT;

afterEach(() => {
  root?.unmount();
  host?.remove();
  root = null;
  host = null;
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = actEnvironment;
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

it("adopts its entry before a first click can push the next screen", async () => {
  window.history.pushState(null, "", "/");
  demoServer();
  // A render React schedules by itself, as when the demo description arrives
  // (not inside act(), which would run every effect before returning).
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = false;
  const page = document.body.appendChild(document.createElement("div"));
  host = page;
  // Click the first example as soon as its button is in the page: right after
  // the commit that shows it, before React runs that commit's passive effects.
  const clicked = new Promise<void>((resolve) => {
    const watch = new MutationObserver(() => {
      const open = Array.from(page.querySelectorAll("button")).find((b) => (b.textContent ?? "").includes("One question, two pronouns"));
      if (!open) return;
      watch.disconnect();
      open.click();
      resolve();
    });
    watch.observe(page, { childList: true, subtree: true });
  });
  root = createRoot(page);
  root.render(
    <StrictMode>
      <LocaleProvider>
        <KnowledgeLibrary demo={info() as unknown as PublicDemoInfo} guided />
      </LocaleProvider>
    </StrictMode>,
  );
  await clicked;
  await new Promise((resolve) => setTimeout(resolve, 50));

  expect(window.location.hash).toBe("#example=y-en");
  expect((window.history.state as { flhLibrary?: unknown } | null)?.flhLibrary).toEqual({ kind: "example", example: "y-en" });
  expect((window.history.state as { flhTrail?: string[] } | null)?.flhTrail).toEqual(["#", "#example=y-en"]);
});
