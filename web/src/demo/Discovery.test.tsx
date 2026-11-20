import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PublicDemoApp from "../PublicDemoApp";
import { demoServer } from "./demoTestServer";

// Suggested searches and the follow-up of the one that finds nothing (queries.ts).

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
});

const renderDemo = (url: string, locale?: string) => {
  if (locale) window.localStorage.setItem("flh.ui-locale.v1", locale);
  window.history.pushState(null, "", url);
  const s = demoServer();
  render(<StrictMode><PublicDemoApp /></StrictMode>);
  return s;
};

describe("suggested searches", () => {
  it("are collapsed under the search form, say what each shows, and run an ordinary keyword search", async () => {
    const s = renderDemo("/");
    const summary = await screen.findByText("Suggested searches (6)");
    const details = summary.closest("details")!;
    expect(details.open).toBe(false);
    fireEvent.click(summary);
    const pronoms = within(details).getByRole("button", { name: "pronoms" });
    expect(pronoms).toHaveAccessibleDescription("finds nothing, and shows where to go instead");
    expect(within(details).getByRole("button", { name: "remplace" })).toHaveAccessibleDescription(
      "found only in the wording of a unit, not in a Concept's title",
    );
    fireEvent.click(within(details).getByRole("button", { name: "tu me manques" }));
    await waitFor(() => expect(window.location.hash).toBe("#q=tu+me+manques"));
    expect(document.getElementById("library-query")).toHaveValue("tu me manques");
    expect(s.calls.every((c) => c.method === "GET")).toBe(true);
  });

  it("follow a search that finds nothing with its related search and example", async () => {
    renderDemo("/#q=pronoms");
    expect(await screen.findByText("Nothing in this demo build matches “pronoms”, but related evidence exists:")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Search “pronouns”" }));
    await waitFor(() => expect(window.location.hash).toBe("#q=pronouns"));
    expect(await screen.findByRole("button", { name: /the pronouns y and en/ })).toBeInTheDocument();
    cleanup();
    renderDemo("/#q=Pronoms");
    fireEvent.click(await screen.findByRole("button", { name: "Open the example “One question, two pronouns”" }));
    // The search stays in front of the screen, so Back returns to it.
    await waitFor(() => expect(window.location.hash).toBe("#q=Pronoms&example=y-en"));
  });

  it("offer no follow-up for other searches that find nothing", async () => {
    renderDemo("/#q=zzz");
    expect(await screen.findByText("Nothing found? Try one of these")).toBeInTheDocument();
    expect(screen.queryByText(/but related evidence exists/)).toBeNull();
  });

  it("read the same in 简体中文", async () => {
    renderDemo("/#q=pronoms", "zh-CN");
    expect(await screen.findByText("此演示构建中没有与“pronoms”匹配的内容，但有相关的证据：")).toBeInTheDocument();
    expect(screen.getByText("建议的搜索（6）")).toBeInTheDocument();
  });
});
