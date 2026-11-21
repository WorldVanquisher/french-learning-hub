import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { LocaleProvider } from "./i18n";
import { isPortalPreview, PortalPreview, publicDemoUrl, WORKSPACE_ENTRY } from "./portal";

// The private workspace's local entry preview (portal.tsx): what it says about
// sign-in, what it reads, its distinct pending and failure states, and the
// public demo link taken only from an https build setting.

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
  window.history.replaceState(null, "", "/");
});

const renderPortal = (navigate = vi.fn()) => {
  render(
    <LocaleProvider>
      <PortalPreview navigate={navigate} />
    </LocaleProvider>,
  );
  return navigate;
};

describe("the entry preview's address and demo link", () => {
  it("is only the ?portal address", () => {
    expect(isPortalPreview("?portal")).toBe(true);
    expect(isPortalPreview("?portal=1")).toBe(true);
    expect(isPortalPreview("")).toBe(false);
    expect(isPortalPreview("?q=portal")).toBe(false);
  });

  it("links the public demo only from an https address without credentials", () => {
    expect(publicDemoUrl("https://demo.example.invalid/")?.host).toBe("demo.example.invalid");
    for (const bad of [undefined, "", "http://demo.example.invalid/", "javascript:alert(1)", "https://user:pw@demo.example.invalid/", "/relative", "not a url"]) expect(publicDemoUrl(bad), String(bad)).toBeNull();
  });
});

describe("the entry preview", () => {
  it("names the workflow, says truthfully that there is no sign-in, and reads nothing on its own", () => {
    const fetchSpy = vi.fn();
    globalThis.fetch = fetchSpy as unknown as typeof fetch;
    renderPortal();
    expect(screen.getByRole("heading", { level: 1, name: "Turn your French questions into rules you can practise" })).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "How it works" })).getAllByRole("listitem")).toHaveLength(4);
    expect(screen.getByText(/^Not signed in: FLH has no accounts\./)).toBeInTheDocument();
    // No build setting: no link, and it says so.
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("This build has no public demo address; it is set when the demo is deployed.")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(document.documentElement.dataset.shell).toBe("workspace");
  });

  it("shows a pending check, then opens the workspace when the local server is ready", async () => {
    let answer!: (r: Response) => void;
    globalThis.fetch = vi.fn(() => new Promise<Response>((r) => (answer = r))) as unknown as typeof fetch;
    const navigate = renderPortal();
    fireEvent.click(screen.getByRole("button", { name: "Open the private workspace" }));
    expect(screen.getByRole("status")).toHaveTextContent("Checking that the local FLH server is ready…");
    expect(screen.getByRole("button", { name: "Open the private workspace" })).toBeDisabled();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(vi.mocked(globalThis.fetch).mock.calls[0][0]).toBe("/api/readyz");
    await act(async () => answer(new Response(JSON.stringify({ status: "ready" }), { status: 200 })));
    expect(navigate).toHaveBeenCalledWith(WORKSPACE_ENTRY);
  });

  it("shows a failure distinctly from the pending state, with its cause and a retry", async () => {
    globalThis.fetch = vi.fn(async () => new Response("{}", { status: 503 })) as unknown as typeof fetch;
    const navigate = renderPortal();
    fireEvent.click(screen.getByRole("button", { name: "Open the private workspace" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The local FLH server is not ready, so the workspace was not opened. Nothing was sent or stored. It answered with status 503.");
    expect(screen.queryByRole("status")).toBeNull();
    expect(navigate).not.toHaveBeenCalled();
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }) as unknown as typeof fetch;
    fireEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(/It could not be reached\./)).toBeInTheDocument();
  });

  it("links the public demo by its host when the build names one", () => {
    vi.stubEnv("VITE_FLH_PUBLIC_DEMO_URL", "https://demo.example.invalid/");
    renderPortal();
    expect(screen.getByRole("link", { name: "Open the public demo (demo.example.invalid)" })).toHaveAttribute("href", "https://demo.example.invalid/");
  });

  it("replaces the workbench only on its own address", () => {
    globalThis.fetch = vi.fn(async () => new Response(JSON.stringify({ reviewable_units: [], concepts: [] }), { status: 200 })) as unknown as typeof fetch;
    window.history.replaceState(null, "", "/?portal");
    const { unmount } = render(<App />);
    expect(screen.getByRole("heading", { level: 1, name: "Turn your French questions into rules you can practise" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Workbench views" })).toBeNull();
    unmount();
    window.history.replaceState(null, "", "/#/home");
    render(<App />);
    expect(screen.getByRole("navigation", { name: "Workbench views" })).toBeInTheDocument();
  });
});

describe("the entry preview's copy (UI-078)", () => {
  it("never implies that the public demo can write, save or sign anyone in, in either language", () => {
    for (const locale of ["en", "zh-CN"]) {
      window.localStorage.setItem("flh.ui-locale.v1", locale);
      renderPortal();
      const demo = screen.getByRole("region", { name: locale === "en" ? "Try FLH without an account" : "无需账户试用 FLH" });
      const text = demo.textContent ?? "";
      if (locale === "en") {
        expect(text).toContain("read-only");
        expect(text).toContain("nothing you do there is saved");
        expect(text).not.toMatch(/sign up|create an account|log in to save|your records there|upload/i);
      } else {
        expect(text).toContain("只读");
        expect(text).toContain("不会被保存");
      }
      cleanup();
      window.localStorage.removeItem("flh.ui-locale.v1");
    }
  });
});
