import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { checkFreshness, entryScript, runningEntry, useNewerVersion, VersionNotice } from "./freshness";
import { LocaleProvider } from "./i18n";

// A tab opened before an upgrade learns that a newer build is served, from
// GET / only, and is offered a reload (never reloaded automatically).

const page = (entry: string) =>
  `<!doctype html><html><head><script type="module" crossorigin src="${entry}"></script><link rel="stylesheet" href="/assets/index-AAAAAAAA.css"></head><body><div id="root"></div></body></html>`;

function htmlFetch(body: string, status = 200) {
  return vi.fn(async () => new Response(body, { status, headers: { "Content-Type": "text/html" } })) as unknown as typeof fetch;
}

afterEach(() => {
  cleanup();
  document.head.querySelectorAll("script[data-test-entry]").forEach((n) => n.remove());
  vi.restoreAllMocks();
});

describe("entry script detection", () => {
  it("reads the hashed module entry from built HTML and from the running page", () => {
    expect(entryScript(page("/assets/index-cad4BS9h.js"))).toBe("/assets/index-cad4BS9h.js");
    expect(entryScript(`<script type="module" src="/src/main.tsx"></script>`)).toBeNull();
    expect(entryScript("not html")).toBeNull();
    expect(runningEntry()).toBeNull();
    const s = document.createElement("script");
    s.type = "module";
    s.setAttribute("src", "/assets/index-cad4BS9h.js");
    s.dataset.testEntry = "1";
    document.head.appendChild(s);
    expect(runningEntry()).toBe("/assets/index-cad4BS9h.js");
  });
});

describe("checkFreshness", () => {
  it("is newer only on positive evidence", async () => {
    expect(await checkFreshness("/assets/index-old00000.js", htmlFetch(page("/assets/index-new00000.js")))).toBe("newer");
    expect(await checkFreshness("/assets/index-same0000.js", htmlFetch(page("/assets/index-same0000.js")))).toBe("current");
    expect(await checkFreshness(null, htmlFetch(page("/assets/index-new00000.js")))).toBe("current");
    expect(await checkFreshness("/assets/index-old00000.js", htmlFetch("upstream error", 502))).toBe("current");
    expect(await checkFreshness("/assets/index-old00000.js", htmlFetch("<html>maintenance</html>"))).toBe("current");
    const failing = vi.fn(async () => {
      throw new TypeError("offline");
    }) as unknown as typeof fetch;
    expect(await checkFreshness("/assets/index-old00000.js", failing)).toBe("current");
  });

  it("asks for GET / without the cache", async () => {
    const f = htmlFetch(page("/assets/index-new00000.js"));
    await checkFreshness("/assets/index-old00000.js", f);
    expect(f).toHaveBeenCalledWith("/", { cache: "no-store", credentials: "same-origin" });
  });
});

function Probe({ fetchImpl }: { fetchImpl: typeof fetch }) {
  const newer = useNewerVersion(fetchImpl);
  return (
    <LocaleProvider>
      <VersionNotice newer={newer} keepsDrafts />
    </LocaleProvider>
  );
}

describe("VersionNotice", () => {
  it("appears after a failed lazy load when the server serves a newer build, and offers a reload", async () => {
    const s = document.createElement("script");
    s.type = "module";
    s.setAttribute("src", "/assets/index-old00000.js");
    s.dataset.testEntry = "1";
    document.head.appendChild(s);
    const f = htmlFetch(page("/assets/index-new00000.js"));
    render(<Probe fetchImpl={f} />);
    expect(screen.queryByRole("status")).toBeNull();
    await act(async () => {
      window.dispatchEvent(new Event("vite:preloadError"));
    });
    const notice = await screen.findByRole("status");
    expect(notice).toHaveTextContent("A newer version of the workbench is on the server");
    expect(notice).toHaveTextContent("unsaved drafts and recorded audio");
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("never checks a development page (no hashed entry)", async () => {
    const f = htmlFetch(page("/assets/index-new00000.js"));
    render(<Probe fetchImpl={f} />);
    await act(async () => {
      window.dispatchEvent(new Event("vite:preloadError"));
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(f).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).toBeNull();
  });
});
