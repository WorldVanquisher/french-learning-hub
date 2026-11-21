import { useEffect, useRef, useState } from "react";
import { LanguageSelect, useI18n, type Msg, msg, Text } from "./i18n";
import { useWorkspaceShell, WorkspaceBrand } from "./workspace";

// The entry page of the private workspace, as a local preview (`/?portal`).
//
// It is served only by the private server (the public demo build replaces the
// whole workbench, this file included, with an empty module), reads nothing
// but the server's readiness when asked, and shows no learning record.
//
// FLH has no accounts or sign-in: the private workspace serves one learner and
// is reachable only where its server runs. The entry state says exactly that;
// "Open the private workspace" checks that the local server is ready (GET
// /readyz) and then opens it. Pending and failure are distinct states.
//
// The public demo link comes from the build (VITE_FLH_PUBLIC_DEMO_URL, an
// https address); without one, the page says so and links nowhere.

export const PORTAL_QUERY = "portal";
export const WORKSPACE_ENTRY = "/#/home";

export function isPortalPreview(search: string = window.location.search): boolean {
  return new URLSearchParams(search).has(PORTAL_QUERY);
}

// The public demo's address, only when it is an https URL without credentials.
export function publicDemoUrl(raw: string | undefined = import.meta.env.VITE_FLH_PUBLIC_DEMO_URL): URL | null {
  if (!raw) return null;
  try {
    const u = new URL(raw);
    return u.protocol === "https:" && u.username === "" && u.password === "" && u.hostname !== "" ? u : null;
  } catch {
    return null;
  }
}

type Entry = { kind: "idle" } | { kind: "checking" } | { kind: "unavailable"; detail: Msg };

const API_BASE = import.meta.env.VITE_FLH_API_BASE || "/api";

export function PortalPreview({ navigate = (href: string) => window.location.assign(href) }: { navigate?: (href: string) => void }) {
  const { t } = useI18n();
  useWorkspaceShell();
  const [entry, setEntry] = useState<Entry>({ kind: "idle" });
  const heading = useRef<HTMLHeadingElement>(null);
  const demo = publicDemoUrl();
  // Coming back with the browser's Back (a page restored from its cache) starts
  // again from the entry state, never from a check that was left pending.
  useEffect(() => {
    const onShow = (e: PageTransitionEvent) => {
      if (e.persisted) {
        setEntry({ kind: "idle" });
        heading.current?.focus();
      }
    };
    window.addEventListener("pageshow", onShow);
    return () => window.removeEventListener("pageshow", onShow);
  }, []);
  const enter = async () => {
    setEntry({ kind: "checking" });
    try {
      const res = await fetch(`${API_BASE}/readyz`, { cache: "no-store", signal: AbortSignal.timeout(5000) });
      if (res.ok) {
        navigate(WORKSPACE_ENTRY);
        return;
      }
      setEntry({ kind: "unavailable", detail: msg("portal.entry.status", { status: res.status }) });
    } catch (e) {
      setEntry({ kind: "unavailable", detail: msg(e instanceof DOMException && e.name === "TimeoutError" ? "portal.entry.timeout" : "portal.entry.noAnswer") });
    }
  };
  return (
    <div className="portal">
      <header className="portal-top">
        <WorkspaceBrand />
        <LanguageSelect />
      </header>
      <main className="portal-main">
        <section className="portal-hero" aria-labelledby="portal-heading">
          <p className="ws-kicker">{t("portal.kicker")}</p>
          <h1 id="portal-heading" ref={heading} tabIndex={-1}>
            {t("portal.title")}
          </h1>
          <p className="portal-lead">{t("portal.lead")}</p>
          <ol className="portal-steps" aria-label={t("portal.steps.label")}>
            <li>{t("portal.step1")}</li>
            <li>{t("portal.step2")}</li>
            <li>{t("portal.step3")}</li>
            <li>{t("portal.step4")}</li>
          </ol>
        </section>
        <div className="portal-cards">
          <section className="panel portal-entry" aria-labelledby="portal-entry-heading">
            <h2 id="portal-entry-heading">{t("portal.entry.heading")}</h2>
            <p className="portal-state" data-entry-state="signed-out">
              {t("portal.entry.state")}
            </p>
            <div className="actions">
              <button type="button" className="primary" id="portal-enter" onClick={enter} disabled={entry.kind === "checking"} aria-describedby="portal-entry-status">
                {t("portal.entry.enter")}
              </button>
            </div>
            <div id="portal-entry-status">
              {entry.kind === "checking" ? (
                <p className="portal-pending" role="status" aria-busy="true" data-entry-state="checking">
                  {t("portal.entry.checking")}
                </p>
              ) : entry.kind === "unavailable" ? (
                <div className="banner error portal-error" role="alert" data-entry-state="unavailable">
                  {t("portal.entry.unavailable")} <Text message={entry.detail} />{" "}
                  <button type="button" className="ghost" onClick={enter}>
                    {t("common.tryAgain")}
                  </button>
                </div>
              ) : null}
            </div>
          </section>
          <section className="panel portal-demo" aria-labelledby="portal-demo-heading">
            <h2 id="portal-demo-heading">{t("portal.demo.heading")}</h2>
            <p>{t("portal.demo.body")}</p>
            {demo ? (
              <p>
                <a href={demo.href} id="portal-demo-link" rel="noopener">
                  {t("portal.demo.link", { host: demo.host })}
                </a>
              </p>
            ) : (
              <p className="hint" data-demo-link="unset">
                {t("portal.demo.unset")}
              </p>
            )}
          </section>
        </div>
        <p className="hint portal-note">{t("portal.note")}</p>
      </main>
    </div>
  );
}
