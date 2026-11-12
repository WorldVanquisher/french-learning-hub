import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PublicDemoApp from "../PublicDemoApp";
import { RecordedTime } from "./DemoStates";
import { demoServer, QUESTION, type DemoServerOptions } from "./demoTestServer";

// The first-visit walkthrough (question → extracted units → Concept → source
// evidence) and its loading, empty and unavailable states, in English and
// 简体中文. Learner text, unit wording and Concept titles are fixture data and
// stay as written in both languages.

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
  try {
    window.localStorage.clear();
  } catch {
    // storage unavailable: English, as the app itself does
  }
});

const UI = {
  en: {
    exampleCard: /One question, two pronouns/,
    exampleTitle: "One question, two pronouns",
    extracted: /What was extracted: 2 units/,
    evidenceStep: /The source evidence/,
    evidenceHint: /This question is learning record #9\. Its units come from extraction v1, which used interpretation v1/,
    openEvidence: "See the evidence for “y remplace à + lieu”",
    step4: "Step 4 of 4 · Source evidence",
    step3: "Step 3 of 4 · Concept",
    next3: /Next, open “View source record” on any unit/,
    backToExample: "← Back to the example “One question, two pronouns”",
    openConcept: "Open the Concept and its evidence",
    search: "Search",
    searchLabel: "Search learned material",
    noMatch: "No concepts match “subjonctiff”.",
    noMatchHeading: "Nothing found? Try one of these",
    noMatchHow: /Keyword search matches the beginning of words/,
    tryPronouns: "Search “pronouns”",
    showAll: "Show all Concepts",
    empty: "This demo build has no Concepts to show.",
    loading: "Loading the demo…",
    unavailable: "The demo is unavailable: (503) unavailable",
    tryAgain: "Try again",
    exampleLoading: "Loading the example…",
    exampleFailed: /Could not load this example: \(503\)/,
  },
  "zh-CN": {
    exampleCard: /一个问题，两个代词/,
    exampleTitle: "一个问题，两个代词",
    extracted: /提取结果：2 个单元/,
    evidenceStep: /来源证据/,
    evidenceHint: /这个问题是学习记录 #9。它的单元来自提取 v1，该提取使用了解释 v1/,
    openEvidence: "查看“y remplace à + lieu”的证据",
    step4: "第 4 步，共 4 步 · 来源证据",
    step3: "第 3 步，共 4 步 · 概念",
    next3: /下一步：在任意单元上打开“查看来源记录”/,
    backToExample: "← 返回示例“一个问题，两个代词”",
    openConcept: "打开概念及其证据",
    search: "搜索",
    searchLabel: "搜索已学内容",
    noMatch: "没有概念匹配“subjonctiff”。",
    noMatchHeading: "没有找到？试试这些",
    noMatchHow: /关键词搜索按词首匹配/,
    tryPronouns: "搜索“pronouns”",
    showAll: "显示全部概念",
    empty: "此演示构建中没有可显示的概念。",
    loading: "正在加载演示…",
    unavailable: "演示不可用：(503) unavailable",
    tryAgain: "再试一次",
    exampleLoading: "正在加载示例…",
    exampleFailed: /无法加载此示例：\(503\)/,
  },
} as const;
type Locale = keyof typeof UI;
const LOCALES = Object.keys(UI) as Locale[];

const renderDemo = (locale: Locale, opts?: DemoServerOptions) => {
  window.localStorage.setItem("flh.ui-locale.v1", locale);
  const server = demoServer(opts);
  render(<StrictMode><PublicDemoApp /></StrictMode>);
  return server;
};

describe.each(LOCALES)("first-visit walkthrough (%s)", (locale) => {
  const ui = UI[locale];

  it("shows question → units → Concept → evidence on the example, and names the step on the screens after it", async () => {
    renderDemo(locale);
    fireEvent.click(await screen.findByRole("button", { name: ui.exampleCard }));
    await screen.findByText(QUESTION);
    expect(screen.getByRole("heading", { name: ui.extracted })).toBeInTheDocument();
    const step4 = screen.getByRole("region", { name: ui.evidenceStep });
    expect(within(step4).getByText(ui.evidenceHint)).toBeInTheDocument();

    fireEvent.click(within(step4).getByRole("button", { name: ui.openEvidence }));
    expect(await screen.findByText(ui.step4)).toBeInTheDocument();
    expect(screen.getByText(QUESTION)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: ui.backToExample }));
    await screen.findByRole("heading", { level: 2, name: ui.exampleTitle });

    fireEvent.click(screen.getByRole("button", { name: ui.openConcept }));
    expect(await screen.findByText(ui.step3)).toBeInTheDocument();
    expect(screen.getByText(ui.next3)).toBeInTheDocument();
  });

  it("names no step on a Concept or evidence opened from a search", async () => {
    renderDemo(locale);
    fireEvent.change(await screen.findByLabelText(ui.searchLabel), { target: { value: "pronouns" } });
    fireEvent.click(screen.getByRole("button", { name: ui.search }));
    fireEvent.click(await screen.findByRole("button", { name: "the pronouns y and en" }));
    await screen.findByRole("heading", { level: 2, name: /the pronouns y and en/ });
    expect(screen.queryByText(ui.step3)).toBeNull();
    expect(screen.queryByText(ui.next3)).toBeNull();
  });

  it("follows a search that found nothing with searches that work and a way to see every Concept", async () => {
    renderDemo(locale);
    const input = await screen.findByLabelText(ui.searchLabel);
    fireEvent.change(input, { target: { value: "subjonctiff" } });
    fireEvent.click(screen.getByRole("button", { name: ui.search }));
    expect(await screen.findByText(ui.noMatch)).toHaveAttribute("role", "status");
    const help = screen.getByRole("region", { name: ui.noMatchHeading });
    expect(within(help).getByText(ui.noMatchHow)).toBeInTheDocument();
    expect(within(help).getAllByRole("button")).toHaveLength(4);

    fireEvent.click(within(help).getByRole("button", { name: ui.tryPronouns }));
    expect(await screen.findByRole("button", { name: "the pronouns y and en" })).toBeInTheDocument();
    expect(input).toHaveValue("pronouns");
    expect(input).toHaveFocus();

    fireEvent.change(input, { target: { value: "zzz" } });
    fireEvent.click(screen.getByRole("button", { name: ui.search }));
    fireEvent.click(within(await screen.findByRole("region", { name: ui.noMatchHeading })).getByRole("button", { name: ui.showAll }));
    expect(await screen.findByRole("button", { name: "subjunctive after « il faut que »" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "the pronouns y and en" })).toBeInTheDocument();
    expect(input).toHaveValue("");
  });

  it("describes an empty catalog as this demo build's, without search suggestions", async () => {
    renderDemo(locale, { empty: true });
    expect(await screen.findByText(ui.empty)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: ui.noMatchHeading })).toBeNull();
  });

  it("states loading and an unavailable demo, and recovers in place", async () => {
    const fail: Record<string, number> = { "/knowledge-library/demo": 503 };
    renderDemo(locale, { fail });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(ui.unavailable);
    delete fail["/knowledge-library/demo"];
    fireEvent.click(within(alert).getByRole("button", { name: ui.tryAgain }));
    expect(await screen.findByRole("button", { name: ui.exampleCard })).toBeInTheDocument();
    cleanup();

    const server = demoServer();
    server.hold("/knowledge-library/demo");
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    expect(await screen.findByText(ui.loading)).toHaveAttribute("role", "status");
    server.release("/knowledge-library/demo");
    expect(await screen.findByRole("button", { name: ui.exampleCard })).toBeInTheDocument();
  });

  it("states a loading and a failed example, with a retry", async () => {
    const server = renderDemo(locale);
    server.hold("/knowledge-library/units/12/source");
    fireEvent.click(await screen.findByRole("button", { name: ui.exampleCard }));
    expect(await screen.findByText(ui.exampleLoading)).toHaveAttribute("role", "status");
    server.release("/knowledge-library/units/12/source");
    await screen.findByText(QUESTION);
    cleanup();
    window.history.replaceState(null, "", "/");

    renderDemo(locale, { fail: { "/knowledge-library/concepts/12": 503 } });
    fireEvent.click(await screen.findByRole("button", { name: ui.exampleCard }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(ui.exampleFailed);
    expect(within(alert).getByRole("button", { name: ui.tryAgain })).toBeInTheDocument();
  });
});

describe("recorded time on the evidence screen", () => {
  it("shows the stored moment as a UTC date and time in the interface language, keeping the exact value", () => {
    const { container, unmount } = render(<RecordedTime value="2026-11-10T08:30:00Z" locale="en" />);
    const time = container.querySelector("time")!;
    expect(time).toHaveAttribute("dateTime", "2026-11-10T08:30:00Z");
    expect(time).toHaveAttribute("title", "2026-11-10T08:30:00Z");
    expect(time.textContent).toMatch(/Nov 10, 2026/);
    expect(time.textContent).toMatch(/UTC/);
    unmount();
    const zh = render(<RecordedTime value="2026-11-10T08:30:00.663577728Z" locale="zh-CN" />);
    expect(zh.container.querySelector("time")!.textContent).toMatch(/2026年11月10日/);
    zh.unmount();
    const raw = render(<RecordedTime value="not a date" locale="en" />);
    expect(raw.container.textContent).toBe("not a date");
    expect(raw.container.querySelector("time")).toBeNull();
  });

  it("is what the demo's evidence screen shows", async () => {
    window.history.replaceState(null, "", "/#concept=12&unit=12");
    demoServer();
    render(<StrictMode><PublicDemoApp /></StrictMode>);
    await screen.findByRole("heading", { level: 3, name: "Original learning record #9" });
    await waitFor(() => expect(document.querySelector("time")).toHaveAttribute("dateTime", "2026-11-10T08:30:00Z"));
  });
});
