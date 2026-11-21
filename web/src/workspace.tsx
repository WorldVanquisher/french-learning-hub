import { useEffect, useLayoutEffect, useRef, type ReactNode } from "react";
import { useI18n } from "./i18n";
import { VIEW_COPY, VIEW_GROUPS, type View } from "./workbenchViews";
// The workspace styles travel with the workbench module, so the public demo
// build (which replaces ./App, and with it this file, by an empty module) carries
// none of them. Every rule is scoped to :root[data-shell="workspace"] anyway.
import "./workspace.css";

// The private workspace shell (workspace.css): a sidebar of grouped sections on
// wide screens and a single scrolling row of sections on narrow ones, beside or
// above the section's own content. It is layout only: the sections, their
// order, their buttons (aria-pressed), the address and history (sectionAddress)
// and every view's behaviour are unchanged.
//
// Only the private workbench sets `data-shell="workspace"` on <html>, so every
// workspace.css rule (all scoped to it) never reaches the public demo, which
// renders PublicDemoApp and never this file.

export const WORKSPACE_SHELL = "workspace";

// Set before the first paint, and removed when the workbench unmounts (tests,
// or another app on the page).
export function useWorkspaceShell() {
  useLayoutEffect(() => {
    document.documentElement.dataset.shell = WORKSPACE_SHELL;
    return () => {
      delete document.documentElement.dataset.shell;
    };
  }, []);
}

export function WorkspaceNav({ view, onShow }: { view: View; onShow: (v: View) => void }) {
  const { t } = useI18n();
  const nav = useRef<HTMLElement>(null);
  // On a narrow screen the sections scroll sideways in one row: keep the current
  // one in that row's view. Only the row scrolls, never the page.
  useEffect(() => {
    const row = nav.current;
    const current = row?.querySelector<HTMLElement>('button[aria-pressed="true"]');
    if (!row || !current || row.scrollWidth <= row.clientWidth) return;
    const left = current.offsetLeft - row.offsetLeft;
    if (left < row.scrollLeft || left + current.offsetWidth > row.scrollLeft + row.clientWidth) {
      row.scrollLeft = Math.max(0, left - (row.clientWidth - current.offsetWidth) / 2);
    }
  }, [view]);
  return (
    <nav ref={nav} className="view-tabs ws-nav" aria-label={t("nav.label")}>
      {VIEW_GROUPS.map((g) => (
        <div key={g.key} className="ws-nav-group" role="group" aria-labelledby={`ws-nav-group-${g.key}`}>
          <p className="ws-nav-group-label" id={`ws-nav-group-${g.key}`}>
            {t(g.label)}
          </p>
          {g.views.map((v) => (
            <button key={v} type="button" aria-pressed={view === v} data-view={v} onClick={() => onShow(v)}>
              {t(VIEW_COPY[v].tab)}
            </button>
          ))}
        </div>
      ))}
    </nav>
  );
}

// The brand line at the top of the sidebar: the app name (not translated) and
// what this is.
export function WorkspaceBrand() {
  const { t } = useI18n();
  return (
    <div className="ws-brand">
      <span className="ws-brand-mark" aria-hidden="true">
        FLH
      </span>
      <span className="ws-brand-text">
        <strong>French Learning Hub</strong>
        <small>{t("ws.brand.private")}</small>
      </span>
    </div>
  );
}

export function WorkspaceSettings({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  return (
    <div className="ws-settings" role="group" aria-label={t("ws.settings")}>
      {children}
    </div>
  );
}

const FOCUSABLE = 'a[href], button, input, select, textarea, summary, [tabindex]:not([tabindex="-1"])';

// Focus never falls silently to the page in the workspace:
// - a focused control that is removed (a list item deleted, a step replaced) hands
//   focus to its nearest surviving neighbour in document order, within the closest
//   container that still exists;
// - a focused control that is disabled while a request runs gets focus back when it
//   is enabled again.
// It acts only while focus is on the page (body), never after a pointer press
// elsewhere, and never inside [data-focus-managed] (components that place focus
// themselves, such as ExplicitAction).
export function useFocusRescue() {
  useEffect(() => {
    let last: HTMLElement | null = null;
    let next: HTMLElement[] = [];
    let prev: HTMLElement[] = [];
    let ancestors: HTMLElement[] = [];
    let managed = false;
    // The last focused control was disabled after it got focus (a request is running).
    let wasDisabled = false;
    let waitEnable: MutationObserver | null = null;
    let frame = 0;
    const usable = (e: HTMLElement) => e.isConnected && !e.closest("[hidden]") && !(e as HTMLButtonElement).disabled && (e.checkVisibility?.() ?? true);
    const onFocusIn = (ev: FocusEvent) => {
      const t = ev.target;
      if (!(t instanceof HTMLElement) || t === document.body) return;
      waitEnable?.disconnect();
      waitEnable = null;
      last = t;
      wasDisabled = false;
      const all = Array.from(document.querySelectorAll<HTMLElement>(FOCUSABLE));
      const at = all.indexOf(t);
      next = at >= 0 ? all.slice(at + 1, at + 25) : [];
      prev = at >= 0 ? all.slice(Math.max(0, at - 25), at).reverse() : [];
      ancestors = [];
      for (let p = t.parentElement; p; p = p.parentElement) ancestors.push(p);
      managed = Boolean(t.closest("[data-focus-managed]"));
    };
    const onPointer = (ev: PointerEvent) => {
      if (!(ev.target instanceof Element) || !ev.target.closest(FOCUSABLE)) last = null;
    };
    const rescue = () => {
      const active = document.activeElement;
      if (!last || managed || (active && active !== document.body)) return;
      const el = last;
      if (el.isConnected) {
        if (!(el as HTMLButtonElement).disabled) {
          // Enabled again after a disabled spell, focus still on the page: give it back.
          if (wasDisabled) {
            wasDisabled = false;
            el.focus();
          }
          return;
        }
        wasDisabled = true;
        if (waitEnable) return;
        waitEnable = new MutationObserver(() => {
          if ((el as HTMLButtonElement).disabled) return;
          waitEnable?.disconnect();
          waitEnable = null;
          const now = document.activeElement;
          if (last === el && el.isConnected && (!now || now === document.body)) el.focus();
        });
        waitEnable.observe(el, { attributes: true, attributeFilter: ["disabled"] });
        return;
      }
      const container = ancestors.find((p) => p.isConnected);
      const target = [...next, ...prev].find((e) => usable(e) && (!container || container.contains(e)));
      last = null;
      target?.focus();
    };
    const observer = new MutationObserver(() => {
      if (last && (last as HTMLButtonElement).disabled) wasDisabled = true;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(rescue);
    });
    observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["disabled"] });
    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("pointerdown", onPointer, true);
    return () => {
      observer.disconnect();
      waitEnable?.disconnect();
      cancelAnimationFrame(frame);
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("pointerdown", onPointer, true);
    };
  }, []);
}
