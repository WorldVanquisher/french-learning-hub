// FLH-083 UI localization: default language, switching and persistence, storage
// failures, catalog parity, formatting, data boundaries, and switching while a
// draft or an unknown outcome exists. All data is synthetic.
import { StrictMode } from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import App from "../App";
import { CaptureImport } from "../components/CaptureImport";
import { ReviewQueue } from "../pages/ReviewQueue";
import { KnowledgeLibrary } from "../pages/KnowledgeLibrary";
import { en } from "./en";
import { zhCN } from "./zh-CN";
import {
  format,
  formatEn,
  LanguageSelect,
  LOCALE_STORAGE_KEY,
  LocaleProvider,
  msg,
  readStoredLocale,
  useI18n,
} from ".";

type Reply = { status?: number; body: unknown } | "network-error";

// routeFetch answers "METHOD /api/path" (query string ignored); anything else is 404.
function routeFetch(handlers: Record<string, Reply | (() => Reply)>) {
  const calls: string[] = [];
  globalThis.fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const path = new URL(String(input), "http://localhost").pathname;
    calls.push(`${method} ${path}`);
    const h = handlers[`${method} ${path}`];
    const reply = h === undefined ? { status: 404, body: { error: "not found" } } : typeof h === "function" ? h() : h;
    if (reply === "network-error") throw new TypeError("Failed to fetch");
    return new Response(JSON.stringify(reply.body), { status: reply.status ?? 200, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
  return calls;
}

function setBrowserLanguage(language: string) {
  vi.spyOn(window.navigator, "language", "get").mockReturnValue(language);
  vi.spyOn(window.navigator, "languages", "get").mockReturnValue([language]);
}

const chooseLanguage = (value: "en" | "zh-CN") => {
  const select = screen.getAllByRole("combobox").find((el) => (el as HTMLSelectElement).querySelector('option[value="zh-CN"]'));
  fireEvent.change(select!, { target: { value } });
};

// An in-memory Storage for this file, so these tests behave the same whether
// localStorage comes from jsdom or (on Node 25+ without
// --no-experimental-webstorage) from Node itself.
function memoryStorage(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (k: string) => (data.has(k) ? data.get(k)! : null),
    key: (i: number) => [...data.keys()][i] ?? null,
    removeItem: (k: string) => void data.delete(k),
    setItem: (k: string, v: string) => void data.set(k, String(v)),
  };
}
beforeAll(() => {
  Object.defineProperty(window, "localStorage", { value: memoryStorage(), configurable: true });
});

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.lang = "fr"; // the static index.html value; the app must replace it
});
afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("default language and persistence", () => {
  it("starts in English even when the browser prefers Chinese", async () => {
    setBrowserLanguage("zh-CN");
    routeFetch({ "GET /api/reviewable-units": { body: { reviewable_units: [] } }, "GET /api/concepts": { body: { concepts: [] } } });
    render(<StrictMode><App /></StrictMode>);
    expect(screen.getByRole("heading", { level: 1, name: "Concept Review" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Learning Records" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("en");
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBeNull(); // nothing saved until an explicit choice
    expect(await screen.findByText("No units are awaiting review. 🎉")).toBeInTheDocument();
  });

  it("switches immediately, sets the document language, and keeps the explicit choice across reloads", async () => {
    routeFetch({ "GET /api/reviewable-units": { body: { reviewable_units: [] } }, "GET /api/concepts": { body: { concepts: [] } } });
    const first = render(<App />);
    await screen.findByText("No units are awaiting review. 🎉");
    chooseLanguage("zh-CN");
    expect(screen.getByRole("heading", { level: 1, name: "概念审阅" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "工作台视图" })).toBeInTheDocument();
    expect(screen.getByText("没有等待审阅的单元。🎉")).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("zh-CN");
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("zh-CN");
    first.unmount();
    render(<App />); // a reload: the explicit choice is read back
    expect(screen.getByRole("heading", { level: 1, name: "概念审阅" })).toBeInTheDocument();
    chooseLanguage("en");
    expect(screen.getByRole("heading", { level: 1, name: "Concept Review" })).toBeInTheDocument();
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("en");
    expect(document.documentElement.lang).toBe("en");
  });

  it("falls back to English for an invalid saved value", () => {
    for (const bad of ["zh", "fr", "ZH-CN", "", "{\"x\":1}"]) {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, bad);
      expect(readStoredLocale()).toBe("en");
    }
  });

  it("works without browser storage: English by default, switching still works, and the unsaved choice is reported", () => {
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    expect(readStoredLocale()).toBe("en");
    render(
      <LocaleProvider>
        <LanguageSelect />
        <Probe />
      </LocaleProvider>,
    );
    expect(screen.getByTestId("probe")).toHaveTextContent("Learning Records");
    chooseLanguage("zh-CN");
    expect(screen.getByTestId("probe")).toHaveTextContent("学习记录");
    expect(screen.getByRole("status")).toHaveTextContent("此浏览器无法保存语言选择");
  });
});

function Probe() {
  const { t } = useI18n();
  return <p data-testid="probe">{t("nav.records")}</p>;
}

describe("catalogs", () => {
  const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

  it("has exactly the English keys and the same placeholders in every message", () => {
    expect(Object.keys(zhCN).sort()).toEqual(Object.keys(en).sort());
    for (const key of Object.keys(en) as Array<keyof typeof en>) {
      expect({ key, p: placeholders(zhCN[key]) }).toEqual({ key, p: placeholders(en[key]) });
      expect(zhCN[key].trim(), key).not.toBe("");
    }
  });

  it("defines every plural as a .one/.other pair and puts no markup in messages", () => {
    const keys = Object.keys(en);
    for (const key of keys.filter((k) => k.endsWith(".one"))) expect(keys).toContain(key.replace(/\.one$/, ".other"));
    for (const key of keys.filter((k) => k.endsWith(".other"))) expect(keys).toContain(key.replace(/\.other$/, ".one"));
    for (const text of [...Object.values(en), ...Object.values(zhCN)]) expect(text).not.toMatch(/<\/?[a-z]/i);
  });

  it("keeps the stored-decision vocabulary untranslated", () => {
    for (const key of ["decision.label.invalid", "correction.label.restore"] as const) expect(zhCN[key]).toBe(en[key]);
    expect(zhCN["decision.label.same"]).toContain("SAME");
    expect(zhCN["resolution.hint.rules"]).toMatch(/BROADER.*NARROWER.*RELATED.*DISTINCT.*INVALID/);
  });
});

describe("formatting", () => {
  it("interpolates, resolves nested messages, and leaves unknown placeholders visible", () => {
    expect(format("en", "record.heading", { id: 7 })).toBe("Record #7");
    expect(format("zh-CN", "record.heading", { id: 7 })).toBe("记录 #7");
    expect(format("en", "review.rejected", { label: msg("decision.label.same", { id: 3 }), error: "(409) conflict" })).toBe(
      "The server did not record SAME → concept #3 (409) conflict.",
    );
    expect(format("zh-CN", "review.rejected", { label: msg("decision.label.same", { id: 3 }), error: "(409) conflict" })).toBe(
      "服务器没有记录 SAME → 概念 #3 (409) conflict。",
    );
    expect(format("en", "record.heading")).toBe("Record #{id}");
    expect(formatEn(msg("check.invalid.found", { judgment: 9 }))).toBe("The unit is INVALID (judgment #9).");
  });

  it("selects English plural forms and fills node templates without markup in strings", () => {
    function Plural() {
      const { tp, tn } = useI18n();
      return (
        <>
          <p>{tp("records.showing", 1)}</p>
          <p>{tp("records.showing", 3)}</p>
          <p data-testid="nodes">{tn("library.foundIn", { fields: <em>title</em> })}</p>
        </>
      );
    }
    render(<Plural />);
    expect(screen.getByText("Showing 1 record.")).toBeInTheDocument();
    expect(screen.getByText("Showing 3 records.")).toBeInTheDocument();
    expect(screen.getByTestId("nodes").querySelector("em")).toHaveTextContent("title");
  });
});

describe("data boundaries", () => {
  it("never translates learner content, French examples, provenance or raw server errors", async () => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "zh-CN");
    const learnerInput = "Pourquoi « il faut que je fasse » ?";
    routeFetch({
      "GET /api/knowledge-library/concepts": {
        body: {
          schema_version: "knowledge_library_search_v1", query: "", tokens: [], state: "all", limit: 20, total_matches: 1, truncated: false,
          results: [{
            concept: { id: 1, identity_schema_version: "fr_l2_concept_identity_v1", target: "subjunctive after il faut que", pedagogical_intent: "grammar", scope: "", identity_features: {}, signature: "s", preferred_unit_id: null, state: "active", lifecycle_state: "normal", support_state: "supported", created_at: "t", updated_at: "t" },
            match_tier: "browse", matched_fields: [], current_member_count: 1, supporting_unit_count: 1,
          }],
        },
      },
      "GET /api/knowledge-library/concepts/1": { status: 500, body: { error: "database is locked (internal detail)" } },
    });
    render(
      <LocaleProvider>
        <KnowledgeLibrary />
      </LocaleProvider>,
    );
    const result = await screen.findByRole("button", { name: "subjunctive after il faut que" }); // stored target, untranslated
    expect(screen.getByText("1 个概念。")).toBeInTheDocument();
    expect(screen.getByText("活跃")).toHaveClass("tag", "active"); // display label; the raw value still drives the class
    expect(screen.getByText(/grammar ·/)).toBeInTheDocument(); // stored type, untranslated
    fireEvent.click(result);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("无法加载概念 #1：(500) database is locked (internal detail)");
    expect(learnerInput).toContain("il faut que"); // fixture sanity: French learner text below stays as written
  });

  it("keeps filter option values as wire values while labels are translated", async () => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "zh-CN");
    const calls = routeFetch({
      "GET /api/learning-records": { body: { records: [], next_before_entry_id: null } },
      "GET /api/reviewable-units": { body: { reviewable_units: [] } },
      "GET /api/concepts": { body: { concepts: [] } },
    });
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "学习记录" }));
    const select = (await screen.findByText("记录状态")).querySelector("select")!;
    const accepted = within(select).getByRole("option", { name: "已接受" }) as HTMLOptionElement;
    expect(accepted.value).toBe("accepted");
    fireEvent.change(select, { target: { value: "accepted" } });
    await waitFor(() => expect(calls.some((c) => c.startsWith("GET /api/learning-records"))).toBe(true));
    const request = (globalThis.fetch as unknown as { mock: { calls: Array<[string]> } }).mock.calls
      .map(([url]) => String(url))
      .filter((url) => url.includes("learning-records"))
      .pop();
    expect(request).toContain("state=accepted");
  });
});

describe("switching keeps drafts and unknown outcomes", () => {
  const CAPTURE = '{ "capture_id": "flh-083-test", "schema_version": "learning_capture_v1", "original_input": "Je voudrais un café" }';

  it("keeps a capture draft and its unknown outcome, re-rendering the banner in the new language", async () => {
    routeFetch({ "POST /api/captures": "network-error" });
    render(
      <LocaleProvider>
        <LanguageSelect />
        <CaptureImport onImported={() => undefined} onOpenRecord={() => undefined} />
      </LocaleProvider>,
    );
    const textarea = screen.getByLabelText("Capture JSON") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: CAPTURE } });
    fireEvent.click(screen.getByRole("button", { name: "Import capture" }));
    expect(await screen.findByText(/Outcome unknown\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check import status" })).toBeInTheDocument();

    chooseLanguage("zh-CN");
    expect((screen.getByLabelText("捕获 JSON") as HTMLTextAreaElement).value).toBe(CAPTURE); // draft unchanged
    const banner = screen.getByRole("alert");
    expect(banner).toHaveTextContent("结果未知。");
    expect(banner).toHaveTextContent("未收到响应，因此该捕获可能已存储，也可能未存储。再次导入前请先检查其状态。");
    expect(screen.getByRole("button", { name: "检查导入状态" })).toBeInTheDocument(); // still checkable

    chooseLanguage("en");
    expect(screen.getByRole("alert")).toHaveTextContent("Check its status before importing again.");
  });

  it("keeps an unknown Concept Review decision blocked and visible across a switch, sending nothing again", async () => {
    const unit = {
      unit_id: 6, kind: "grammar", canonical: "ne … plus", statement: "« Ne … plus » marque la fin d'une action.", example: null,
      confidence: 0.9, candidate_identity: { target: "ne plus", pedagogical_intent: "grammar", scope: "", identity_features: {} }, signature: "s",
    };
    const calls = routeFetch({
      "GET /api/reviewable-units": { body: { reviewable_units: [unit] } },
      "GET /api/concepts": { body: { concepts: [] } },
      "GET /api/knowledge-units/6/concept-membership": { body: { unit_id: 6, current_membership: null } },
      "GET /api/knowledge-units/6/concept-resolution": { body: { unit_id: 6, decision: "no_match", matches: [] } },
      "GET /api/knowledge-units/6/invalid": { body: { unit_id: 6, invalid: false, history: [] } },
      "POST /api/knowledge-units/6/invalid": "network-error",
    });
    render(
      <StrictMode>
        <LocaleProvider>
          <LanguageSelect />
          <ReviewQueue />
        </LocaleProvider>
      </StrictMode>,
    );
    expect(await screen.findByText("« Ne … plus » marque la fin d'une action.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search existing concepts"), { target: { value: "draft query kept" } });
    fireEvent.click(await screen.findByRole("button", { name: "INVALID" }));
    expect(await screen.findByRole("heading", { name: "Outcome of INVALID still unknown" })).toBeInTheDocument();
    const posts = () => calls.filter((c) => c === "POST /api/knowledge-units/6/invalid").length;
    expect(posts()).toBe(1);

    chooseLanguage("zh-CN");
    expect(screen.getByRole("heading", { name: "INVALID 的结果仍未知" })).toBeInTheDocument();
    expect(screen.getByText(/结果未知。/)).toBeInTheDocument();
    expect(screen.getByText("« Ne … plus » marque la fin d'une action.")).toBeInTheDocument(); // learner content as stored
    expect((screen.getByLabelText("搜索已有概念") as HTMLInputElement).value).toBe("draft query kept");
    expect(screen.getByRole("button", { name: "INVALID" })).toBeDisabled(); // still blocked by the unknown outcome
    expect(screen.getByText("单元 #6 的决定会等待，直到检查找到它，或您允许另一个决定。")).toBeInTheDocument();
    expect(posts()).toBe(1); // switching re-renders; it never resends
  });
});
