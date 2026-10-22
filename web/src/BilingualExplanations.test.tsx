import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { EXPLANATION_STORAGE_KEY, ExplanationLanguageProvider, ExplanationLanguageSelect } from "./explanationLanguage";
import { EffectiveText, StoredText } from "./components/ExplanationText";
import { FeedbackPanel } from "./components/FeedbackPanel";
import { LanguageSelect, LocaleProvider } from "./i18n";
import type { Analysis, EffectiveExplanations } from "./types/learning";

// FLH-095: stored English/Chinese explanations. All content is synthetic.

const EN = "Ne … plus marks a habit that has stopped.";
const ZH = "「ne … plus」表示习惯已经停止。";

beforeEach(() => window.localStorage.clear());
afterEach(cleanup);

function calls() {
  const list: Array<{ method: string; path: string; body: unknown }> = [];
  globalThis.fetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const path = new URL(String(url), "http://localhost").pathname;
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    list.push({ method, path, body });
    const reply = method === "GET" ? { feedback: [] } : { id: 31, analysis_id: 7, status: (body as { status: string }).status, user_note: "", created_at: "t" };
    return new Response(JSON.stringify(reply), { status: method === "GET" ? 200 : 201, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
  return list;
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <LocaleProvider>
      <ExplanationLanguageProvider>
        <LanguageSelect />
        <ExplanationLanguageSelect />
        {children}
      </ExplanationLanguageProvider>
    </LocaleProvider>
  );
}

const pick = (mode: string) => fireEvent.change(screen.getByLabelText("Explanation language"), { target: { value: mode } });

describe("StoredText", () => {
  it("labels a text whose language was not recorded instead of calling it English or Chinese", () => {
    render(<Shell><StoredText primary="Legacy explanation." variants={undefined} kind="explanation" /></Shell>);
    expect(screen.getByText("Legacy explanation.")).toBeInTheDocument();
    const tags = Array.from(document.querySelectorAll(".lang-tag")).map((el) => el.textContent);
    expect(tags).toEqual(["language not recorded"]);
  });

  it("shows both stored languages by default, then only the chosen one, and states a missing one", () => {
    const list = calls();
    render(
      <Shell>
        <StoredText primary={EN} variants={{ en: EN, zh: ZH }} kind="explanation" />
        <div data-testid="english-only"><StoredText primary={EN} variants={{ en: EN, zh: null }} kind="statement" /></div>
      </Shell>,
    );
    expect(screen.getAllByText(EN)).toHaveLength(2);
    expect(screen.getByText(ZH)).toHaveAttribute("lang", "zh-Hans");
    expect(screen.getByText("No Chinese statement is stored for this unit.")).toBeInTheDocument();

    pick("zh");
    expect(screen.queryAllByText(EN)).toHaveLength(0); // never substituted for the missing Chinese text
    expect(screen.getByText(ZH)).toBeInTheDocument();
    expect(within(screen.getByTestId("english-only")).getByText("No Chinese statement is stored for this unit.")).toBeInTheDocument();
    expect(window.localStorage.getItem(EXPLANATION_STORAGE_KEY)).toBe("zh");

    pick("en");
    expect(screen.queryByText(ZH)).toBeNull();
    expect(screen.getAllByText(EN)).toHaveLength(2);
    expect(list).toHaveLength(0); // switching reads nothing and writes nothing
  });

  it("keeps the explanation language independent of the application language", () => {
    render(<Shell><StoredText primary={EN} variants={{ en: EN, zh: ZH }} kind="explanation" /></Shell>);
    fireEvent.change(screen.getByLabelText("Language"), { target: { value: "zh-CN" } });
    // The UI is now Chinese, yet the stored English text is still shown.
    expect(screen.getByLabelText("说明语言")).toHaveValue("both");
    expect(screen.getByText(EN)).toBeInTheDocument();
    expect(screen.getByText(ZH)).toBeInTheDocument();
    expect(window.localStorage.getItem(EXPLANATION_STORAGE_KEY)).toBeNull();
  });
});

describe("EffectiveText", () => {
  const effective = (en: EffectiveExplanations["en"], zh: EffectiveExplanations["zh"]): EffectiveExplanations => ({ en, zh });

  it("shows each language's basis, never presenting outdated or unreviewed text as reviewed", () => {
    render(
      <Shell>
        <EffectiveText
          fallback="人工更正。"
          original={EN}
          originalVariants={{ en: EN, zh: ZH }}
          effective={effective({ text: EN, basis: "outdated" }, { text: "人工更正。", basis: "corrected" })}
        />
      </Shell>,
    );
    expect(screen.getByText("generated before a correction in another language; may be outdated")).toBeInTheDocument();
    expect(screen.getByText("corrected by a person")).toBeInTheDocument();
    expect(screen.queryByText("Correction (language not recorded)")).toBeNull();
  });

  it("labels a correction whose language was not recorded", () => {
    render(
      <Shell>
        <EffectiveText
          fallback="Unspecified fix."
          original={EN}
          originalVariants={{ en: EN, zh: ZH }}
          effective={effective({ text: EN, basis: "outdated" }, { text: ZH, basis: "outdated" })}
        />
      </Shell>,
    );
    expect(screen.getByText("Correction (language not recorded)")).toBeInTheDocument();
    expect(screen.getByText("Unspecified fix.")).toBeInTheDocument();
    expect(screen.getAllByText("generated before a correction in another language; may be outdated")).toHaveLength(2);
  });

  it("shows a legacy effective explanation as before", () => {
    render(<Shell><EffectiveText fallback="Old." original="Old." originalVariants={undefined} effective={undefined} /></Shell>);
    expect(screen.getByText("Old.")).toBeInTheDocument();
    expect(screen.getByText("language not recorded")).toBeInTheDocument();
  });
});

describe("FeedbackPanel with explanation languages", () => {
  const bilingual: Analysis = {
    id: 7, entry_id: 3, version: 1, category: "grammar", explanation: EN, explanations: { en: EN, zh: ZH },
    confidence: 0.8, uncertainty: "", analyzer: "openai:m:fr_l2_taxonomy_v1.explanation_en_zh_v1", created_at: "t",
  };
  const legacy: Analysis = { ...bilingual, explanation: "Legacy.", explanations: undefined, analyzer: "rule-based:v2:fr_l2_taxonomy_v1" };

  function panel(analysis: Analysis) {
    return (
      <Shell>
        <FeedbackPanel analysis={analysis} latest={analysis} effectiveFeedbackId={null} effectiveResolution="unreviewed"
          effectiveRefresh={{ kind: "idle" }} onRecorded={() => undefined} />
      </Shell>
    );
  }

  it("records only the languages shown: accepting with English shown does not approve Chinese", async () => {
    const list = calls();
    render(panel(bilingual));
    await waitFor(() => expect(list.some((c) => c.method === "GET")).toBe(true));
    pick("en");
    expect(screen.getByText("This decision records that you were shown the explanation in: English.")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/Accept/));
    fireEvent.click(screen.getByRole("button", { name: 'Record "accepted" for analysis v1' }));
    await waitFor(() => expect(list.find((c) => c.method === "POST")).toBeDefined());
    expect(list.find((c) => c.method === "POST")?.body).toEqual({ status: "accepted", reviewed_explanation_languages: ["en"] });
  });

  it("corrects per language, keeps drafts across a language switch, and sends no legacy field", async () => {
    const list = calls();
    render(panel(bilingual));
    fireEvent.click(screen.getByLabelText(/Correct/));
    fireEvent.change(screen.getByLabelText("Corrected explanation (中文)"), { target: { value: "人工更正：「ne … plus」表示停止。" } });
    pick("zh");
    pick("both");
    expect(screen.getByLabelText("Corrected explanation (中文)")).toHaveValue("人工更正：「ne … plus」表示停止。");
    expect(list.filter((c) => c.method !== "GET")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: 'Record "corrected" for analysis v1' }));
    await waitFor(() => expect(list.find((c) => c.method === "POST")).toBeDefined());
    expect(list.find((c) => c.method === "POST")?.body).toEqual({
      status: "corrected",
      corrected_explanation_zh: "人工更正：「ne … plus」表示停止。",
      reviewed_explanation_languages: ["en", "zh"],
    });
  });

  it("keeps the single correction field and sends no languages for a legacy analysis", async () => {
    const list = calls();
    render(panel(legacy));
    expect(screen.queryByText(/This decision records/)).toBeNull();
    fireEvent.click(screen.getByLabelText(/Correct/));
    expect(screen.queryByLabelText("Corrected explanation (English)")).toBeNull();
    fireEvent.change(screen.getByLabelText("Corrected explanation"), { target: { value: "Fixed." } });
    fireEvent.click(screen.getByRole("button", { name: 'Record "corrected" for analysis v1' }));
    await waitFor(() => expect(list.find((c) => c.method === "POST")).toBeDefined());
    expect(list.find((c) => c.method === "POST")?.body).toEqual({ status: "corrected", corrected_explanation: "Fixed." });
  });
});

describe("Concept Review with explanation languages", () => {
  it("switching the explanation language keeps the position, selection and identity draft and sends nothing", async () => {
    const { ReviewQueue } = await import("./pages/ReviewQueue");
    const unit = {
      unit_id: 9, kind: "grammar", canonical: "ne … plus", statement: EN, statements: { en: EN, zh: ZH },
      example: "Je ne fume plus.", confidence: 0.9, entry_id: 3,
      candidate_identity: { target: "ne … plus", pedagogical_intent: "grammar", scope: "", identity_features: {} }, signature: "{sig}",
    };
    const concept = { id: 40, identity_schema_version: "fr_l2_concept_identity_v1", target: "ne … plus", pedagogical_intent: "grammar",
      scope: "", identity_features: {}, signature: "s", preferred_unit_id: null, state: "active", lifecycle_state: "normal",
      support_state: "supported", created_at: "t", updated_at: "t" };
    const routes: Record<string, unknown> = {
      "/api/reviewable-units": { reviewable_units: [unit, { ...unit, unit_id: 10 }], next_cursor: null, limit: 50 },
      "/api/concepts": { concepts: [concept] },
      "/api/knowledge-units/9/concept-membership": { unit_id: 9, current_membership: null },
      "/api/knowledge-units/9/concept-resolution": { unit_id: 9, candidate_identity: unit.candidate_identity, signature: "{sig}", decision: "no_match", matches: [] },
    };
    const seen: string[] = [];
    globalThis.fetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      const path = new URL(String(url), "http://localhost").pathname;
      seen.push(`${(init?.method ?? "GET").toUpperCase()} ${path}`);
      const body = routes[path];
      return new Response(JSON.stringify(body ?? { error: "not found" }), { status: body ? 200 : 404, headers: { "Content-Type": "application/json" } });
    }) as unknown as typeof fetch;

    render(<Shell><ReviewQueue /></Shell>);
    await screen.findByText(ZH);
    await waitFor(() => expect(screen.getAllByRole("button", { name: "select this concept" }).length).toBeGreaterThan(0));
    fireEvent.click((await screen.findAllByRole("button", { name: "select this concept" }))[0]);
    fireEvent.change(screen.getByLabelText("target"), { target: { value: "ne … plus (habitude)" } });
    const before = seen.length;

    pick("zh");
    expect(screen.queryByText(EN)).toBeNull();
    pick("en");
    expect(screen.getByText(EN)).toBeInTheDocument();
    pick("both");

    expect(screen.getByText("unit 1 of 2")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "selected" })[0]).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("target")).toHaveValue("ne … plus (habitude)");
    expect(seen.slice(before).filter((c) => !c.startsWith("GET /api/knowledge-library/"))).toEqual([]);
    expect(seen.every((c) => c.startsWith("GET "))).toBe(true);
  });
});
