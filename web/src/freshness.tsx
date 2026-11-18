import { useEffect, useState } from "react";
import { useI18n } from "./i18n";

// Frontend freshness: tells a visitor when the server now serves a newer
// build than the one this page is running.
//
// One release holds both the server and the built page, so the server and the
// page it serves always match. A tab opened before an upgrade keeps running the
// old page, though, and may then call routes or load files the new release no
// longer has. Built pages name their entry script by content hash
// (/assets/index-XXXXXXXX.js); the server's current index.html (no-cache)
// names the current one. When they differ, this page is out of date.
//
// The check reads only GET / (a page the server already serves to everyone),
// when the tab becomes visible again and when a lazily loaded part of the page
// fails to load (Vite's vite:preloadError), at most once a minute. It never
// reloads by itself: reloading discards whatever the page keeps only in memory
// (drafts, recorded audio), so the visitor decides. Development servers (no
// hashed entry script) are never checked.

const ENTRY = /<script\b[^>]*\btype="module"[^>]*\bsrc="(\/assets\/[^"]+\.js)"/;

// entryScript returns the hashed entry script a page names, or null.
export function entryScript(html: string): string | null {
  const m = ENTRY.exec(html);
  return m ? m[1] : null;
}

// runningEntry is the entry script of the page this code runs in.
export function runningEntry(doc: Document = document): string | null {
  const el = doc.querySelector<HTMLScriptElement>('script[type="module"][src^="/assets/"]');
  const src = el?.getAttribute("src") ?? null;
  return src && /\.js$/.test(src) ? src : null;
}

export type Freshness = "current" | "newer";

// checkFreshness compares the running entry with the server's current page.
// Anything it cannot tell (no hashed entry, a failed or odd response) counts as
// current: the notice appears only on positive evidence.
export async function checkFreshness(running: string | null, fetchImpl: typeof fetch = fetch): Promise<Freshness> {
  if (!running) return "current";
  try {
    const res = await fetchImpl("/", { cache: "no-store", credentials: "same-origin" });
    if (!res.ok) return "current";
    const served = entryScript(await res.text());
    return served && served !== running ? "newer" : "current";
  } catch {
    return "current";
  }
}

const MIN_INTERVAL_MS = 60_000;

// useNewerVersion is true once the server is seen to serve a newer build.
export function useNewerVersion(fetchImpl?: typeof fetch): boolean {
  const [newer, setNewer] = useState(false);
  useEffect(() => {
    const running = runningEntry();
    if (!running) return;
    let active = true;
    let last = 0;
    const check = (force = false) => {
      const now = Date.now();
      if (!force && now - last < MIN_INTERVAL_MS) return;
      last = now;
      void checkFreshness(running, fetchImpl).then((f) => {
        if (active && f === "newer") setNewer(true);
      });
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") check();
    };
    // A lazily loaded part failed: most often its file is gone after a release.
    const onPreloadError = () => check(true);
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("vite:preloadError", onPreloadError);
    return () => {
      active = false;
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("vite:preloadError", onPreloadError);
    };
  }, [fetchImpl]);
  return newer;
}

// VersionNotice says that a newer version is available and offers a reload.
export function VersionNotice({ newer, keepsDrafts }: { newer: boolean; keepsDrafts: boolean }) {
  const { t } = useI18n();
  if (!newer) return null;
  return (
    <div className="banner info version-notice" role="status">
      {t(keepsDrafts ? "app.newerVersion.workbench" : "app.newerVersion.demo")}{" "}
      <button type="button" onClick={() => window.location.reload()}>
        {t("app.newerVersion.reload")}
      </button>
    </div>
  );
}
