// Public demo UX matrix: a real-browser acceptance of the first-visit
// walkthrough, navigation, keyboard use, long text and layout, at 320 px and
// 390 px phones (true phone emulation: isMobile, touch, DPR 2) and a 1280 px
// desktop, in English and 简体中文, against a running demo (normally the packaged
// release binary). Read-only: every request must be a same-origin GET on the
// demo allowlist; long text is injected in the browser, never on the server.
//
// Overflow is measured against the DEVICE width. Under phone emulation the
// layout viewport (innerWidth) grows to fit wide content, so the old check
// `scrollWidth <= innerWidth` could not fail (421 px passed on a 390 px phone).
// A built-in self-test injects the old evidence-row layout and requires this
// check to catch it; if it does not, the run fails.
//
//   node accept_matrix.mjs URL OUT_DIR [mechanical|model]
//
// Needs playwright-core (no browser download) and CHROME=/path/to/chromium.
import { chromium } from "playwright-core";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const [url, out, expectVectors = "mechanical"] = process.argv.slice(2);
if (!url || !out) {
  console.error("usage: node accept_matrix.mjs URL OUT_DIR [mechanical|model]");
  process.exit(2);
}
mkdirSync(out, { recursive: true });
const base = url.replace(/\/?$/, "/");
const origin = new URL(base).origin;
const checks = [];
const metrics = {};
const overflowTable = [];
const check = (name, ok, detail = "") => checks.push({ name, ok: Boolean(ok), detail: String(detail).slice(0, 300) });

const SIZES = [
  { size: "phone-320", width: 320, height: 640, mobile: true },
  { size: "phone-390", width: 390, height: 844, mobile: true },
  { size: "desktop", width: 1280, height: 900, mobile: false },
];
const LOCALES = ["en", "zh-CN"];
const TEXT = {
  en: { step3: "Step 3 of 4 · Concept", step4: "Step 4 of 4 · Source evidence", noMatch: "Nothing found? Try one of these", empty: "This demo build has no Concepts to show." },
  "zh-CN": { step3: "第 3 步，共 4 步 · 概念", step4: "第 4 步，共 4 步 · 来源证据", noMatch: "没有找到？试试这些", empty: "此演示构建中没有可显示的概念。" },
};
// The D1 authored examples (fixture data; shown untranslated in every locale).
const EXAMPLES = [
  { key: "y-en", question: "« j'y vais » et « j'en veux »", units: 2, concepts: 1 },
  { key: "il-faut-venir", question: "Pourquoi « viennes » et pas « viens » ?", units: 1, concepts: 1 },
  { key: "en-train-de", question: "est-ce que « je suis cuisinant » existe ?", units: 2, concepts: 2 },
];
const ALLOWED = /^\/(api\/)?(knowledge-library\/(concepts(\/\d+)?|units\/\d+\/source|demo(\/(semantic|hybrid)-search)?)|assets\/[^/]+|favicon\.[a-z]+|readyz|healthz)?$/;
// The evidence-row layout before the fix (and before this lane's demo rules).
const OLD_LAYOUT = `
  .unit-evidence div { grid-template-columns: 110px 1fr !important; }
  .unit-evidence dd, .library .hint, .demo-app .library dd { overflow-wrap: normal !important; }`;
const LONG_ID = "fixture:flh073:fr_l2_taxonomy_v1:" + "segment_without_breaks_".repeat(6);
const LONG_FR =
  "Dans un très long message, une apprenante écrit : « Quand j'y vais avec mes collègues et qu'on en parle pendant des heures, " +
  "est-ce que « y » et « en » remplacent toujours la même chose ? » anticonstitutionnellementanticonstitutionnellement";
const BILINGUAL = "Explanation in English. 中文解释：这个规则说明“y”替代地点，“en”替代由 de 引导的名词。" + "长".repeat(60) + " Et en français : y remplace à + lieu.";

const browser = await chromium.launch({ executablePath: process.env.CHROME, args: ["--no-sandbox"] });

async function open(sz, locale, extra = {}) {
  const ctx = await browser.newContext({
    viewport: { width: sz.width, height: sz.height },
    ...(sz.mobile ? { isMobile: true, hasTouch: true, deviceScaleFactor: 2 } : {}),
    ...extra,
  });
  await ctx.addInitScript((l) => {
    try { localStorage.setItem("flh.ui-locale.v1", l); } catch {}
  }, locale);
  const page = await ctx.newPage();
  const requests = [];
  const errors = [];
  page.on("request", (r) => requests.push({ method: r.method(), url: r.url() }));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(String(e)));
  return { ctx, page, requests, errors };
}

// Root width against the device width, with the leaf-most elements that stick out.
const measure = (page, device) =>
  page.evaluate((dw) => {
    const all = [...document.querySelectorAll("body *")].filter((el) => {
      const b = el.getBoundingClientRect();
      return (b.width > 0 || b.height > 0) && b.right + window.scrollX > dw + 0.5;
    });
    const leaf = all.filter((el) => !all.some((o) => o !== el && el.contains(o)));
    return {
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
      clientWidth: document.documentElement.clientWidth,
      wide: leaf.slice(0, 3).map((el) => `${el.tagName.toLowerCase()}${el.className ? "." + String(el.className).trim().split(/\s+/).join(".") : ""} “${(el.textContent || "").trim().slice(0, 40)}”`),
    };
  }, device);
const fits = async (page, sz, tag, where) => {
  const device = sz.mobile ? sz.width : (await page.evaluate(() => document.documentElement.clientWidth));
  const m = await measure(page, device);
  overflowTable.push({ tag, where, device, ...m });
  check(`${tag}: ${where}: no horizontal scroll (device ${device})`, m.scrollWidth <= device, `${m.scrollWidth}px ${m.wide.join(", ")}`);
  return m;
};
const focusVisible = (page) =>
  page.evaluate(() => {
    const el = document.activeElement;
    if (!el || el === document.body) return false;
    const s = getComputedStyle(el);
    return (s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== "none" || /^H[23]$/.test(el.tagName);
  });
const notUnderBar = (page) =>
  page.evaluate(() => {
    const el = document.activeElement;
    const bar = document.querySelector(".demo-return");
    if (!el || !bar || bar.contains(el)) return true;
    const a = el.getBoundingClientRect();
    const b = bar.getBoundingClientRect();
    return a.top >= b.bottom - 1 || a.bottom <= b.top;
  });
const visibleH2 = (page) => page.evaluate(() => [...document.querySelectorAll("h2")].find((h) => h.offsetParent !== null)?.textContent?.trim() ?? "");
const screenKind = (page) =>
  page.evaluate(() => {
    const shown = (s) => { const e = document.querySelector(s); return Boolean(e && e.offsetParent !== null); };
    return shown("#src-entry") ? "source" : shown(".library-concept") ? "concept" : shown(".demo-example") ? "example" : shown(".demo-example-card") ? "start" : "other";
  });
const waitKind = async (page, kind) => {
  await page.waitForFunction((k) => {
    const shown = (s) => { const e = document.querySelector(s); return Boolean(e && e.offsetParent !== null); };
    const now = shown("#src-entry") ? "source" : shown(".library-concept") ? "concept" : shown(".demo-example") ? "example" : shown(".demo-example-card") ? "start" : "other";
    return now === k;
  }, kind, { timeout: 8000 }).catch(() => {});
  return screenKind(page);
};
const settle = async (page, sel) => page.waitForSelector(sel, { timeout: 8000 }).catch(() => {});
async function keyTo(page, matcher, { back = false, max = 80 } = {}) {
  for (let i = 1; i <= max; i++) {
    await page.keyboard.press(back ? "Shift+Tab" : "Tab");
    if (await page.evaluate(matcher)) return i;
  }
  return -1;
}
const requestChecks = (tag, requests, errors) => {
  const bad = requests.filter((r) => {
    const u = new URL(r.url);
    return u.origin !== origin || r.method !== "GET" || !ALLOWED.test(u.pathname);
  });
  check(`${tag}: every request a same-origin GET on the demo allowlist`, bad.length === 0, JSON.stringify(bad.slice(0, 3)));
  check(`${tag}: no console or page errors`, errors.length === 0, errors.join(" | "));
};

for (const sz of SIZES) {
  for (const locale of LOCALES) {
    const tag = `${sz.size}-${locale}`;
    const T = TEXT[locale];
    let n = 0;
    const { ctx, page, requests, errors } = await open(sz, locale);
    const shot = (name, fullPage = true, p = page) => p.screenshot({ path: join(out, `${tag}-${String(++n).padStart(2, "0")}-${name}.png`), fullPage });

    // 1. Start.
    const t0 = Date.now();
    await page.goto(base);
    await settle(page, ".demo-example-card");
    check(`${tag}: start: three examples`, (await page.locator(".demo-example-card").count()) === 3);
    check(`${tag}: start: read-only and synthetic labels`, (await page.locator(".demo-labels .demo-label").count()) >= 2);
    check(`${tag}: start: development-build label matches the vectors`, (await page.locator(".demo-label.warn").count()) === (expectVectors === "mechanical" ? 1 : 0));
    // The first example is whole on the first screen from 390 px up; on a 320 px
    // phone its title line is (a mechanical build's warning takes the room).
    const card = await page.locator("#demo-example-y-en").boundingBox();
    const need = sz.width >= 390 ? card?.height ?? 0 : 64;
    check(`${tag}: start: first example on the first screen`, card && card.y >= 0 && card.y + need <= sz.height, JSON.stringify(card));
    metrics[`${tag}: first example card top (px)`] = Math.round(card?.y ?? -1);
    await fits(page, sz, tag, "start");
    await shot("start");

    // 2. Each example: question → units → Concept → evidence, then back.
    for (const ex of EXAMPLES) {
      await page.click(`#demo-example-${ex.key}`);
      await settle(page, ".demo-question");
      if (ex.key === "y-en") metrics[`${tag}: ms from load to the first question`] = Date.now() - t0;
      check(`${tag}: ${ex.key}: question shown unchanged`, (await page.locator(".demo-question").innerText()).includes(ex.question));
      check(`${tag}: ${ex.key}: four steps on the example`, (await page.locator("#demo-step-question, #demo-step-extracted, #demo-step-concepts, #demo-step-evidence").count()) === 4);
      check(`${tag}: ${ex.key}: ${ex.units} units and ${ex.concepts} Concept(s)`,
        (await page.locator("#demo-step-extracted ~ ul .demo-unit").count()) === ex.units && (await page.locator("#demo-step-concepts ~ ul .demo-unit").count()) === ex.concepts);
      await fits(page, sz, tag, `${ex.key} example`);
      await shot(`example-${ex.key}`);
      await page.locator("#demo-step-concepts ~ ul button.primary").first().click();
      await settle(page, ".library-concept h2");
      check(`${tag}: ${ex.key}: Concept names step 3`, (await page.locator(".library-concept .demo-eyebrow").textContent()) === T.step3);
      await fits(page, sz, tag, `${ex.key} Concept`);
      await shot(`concept-${ex.key}`);
      await page.locator(".library-section.current .library-unit .link-button").first().click();
      await settle(page, "#src-entry");
      check(`${tag}: ${ex.key}: evidence names step 4`, (await page.locator(".demo-eyebrow", { hasText: T.step4 }).count()) === 1);
      check(`${tag}: ${ex.key}: evidence shows a learner question`, (await page.locator("#src-entry ~ .demo-question").innerText()).length > 0);
      await fits(page, sz, tag, `${ex.key} evidence`);
      await shot(`evidence-${ex.key}`);
      // In-page back, then the browser's Back: one move further back each time.
      const lengthBefore = await page.evaluate(() => history.length);
      await page.locator(".demo-return .actions button").first().click();
      check(`${tag}: ${ex.key}: in-page back to the Concept`, (await waitKind(page, "concept")) === "concept");
      check(`${tag}: ${ex.key}: in-page back adds no history entry`, (await page.evaluate(() => history.length)) === lengthBefore);
      await page.goBack();
      check(`${tag}: ${ex.key}: browser Back then goes to the example, not to the evidence just left`, (await waitKind(page, "example")) === "example");
      await page.goForward();
      check(`${tag}: ${ex.key}: browser Forward returns to the Concept`, (await waitKind(page, "concept")) === "concept");
      await page.goForward();
      check(`${tag}: ${ex.key}: …and to the evidence`, (await waitKind(page, "source")) === "source");
      await page.reload();
      check(`${tag}: ${ex.key}: reload stays on the evidence`, (await waitKind(page, "source")) === "source");
      await page.locator(".demo-return .actions button").nth(1).click(); // back to the example
      check(`${tag}: ${ex.key}: evidence → back to the example`, (await waitKind(page, "example")) === "example");
      await page.locator(".demo-example > .panel button.ghost").first().click();
      await waitKind(page, "start");
      await page.waitForFunction((k) => document.activeElement?.id === `demo-example-${k}`, ex.key, { timeout: 3000 }).catch(() => {});
      check(`${tag}: ${ex.key}: back at the start, focus on its card`, await page.evaluate((k) => document.activeElement?.id === `demo-example-${k}`, ex.key));
    }

    // 3. A search: an entry of its own, kept by a reload and by the way back.
    await page.fill("#library-query", "il faut");
    await page.press("#library-query", "Enter");
    await settle(page, ".library-results .link-button");
    check(`${tag}: search: the address names it`, new URL(page.url()).hash === "#q=il+faut", page.url());
    await page.locator(".library-results .link-button").first().click();
    await settle(page, ".library-concept h2");
    const title = await visibleH2(page);
    await page.reload();
    await settle(page, ".library-concept h2");
    check(`${tag}: search: reload keeps the Concept`, (await visibleH2(page)) === title, title);
    check(`${tag}: search: …and the way back to the search`, (await page.locator(".demo-return button").first().innerText()).includes("il faut"));
    await page.locator(".demo-return button").first().click();
    await settle(page, ".library-results .link-button");
    check(`${tag}: search: back to its results with the query`, (await page.inputValue("#library-query")) === "il faut");
    await page.waitForFunction(() => document.activeElement?.id?.startsWith("library-result-"), null, { timeout: 3000 }).catch(() => {});
    check(`${tag}: search: focus back on the Concept opened`, await page.evaluate(() => document.activeElement?.id?.startsWith("library-result-")));
    await page.goBack();
    await page.waitForFunction(() => document.querySelector("#library-query")?.value === "", null, { timeout: 3000 }).catch(() => {});
    check(`${tag}: search: browser Back undoes the search`, (await page.inputValue("#library-query")) === "" && new URL(page.url()).hash === "");
    await fits(page, sz, tag, "start after search");

    // 4. Keyboard only: start → example → Concept → evidence, focus visible.
    await page.goto(base);
    await settle(page, ".demo-example-card");
    let keys = 0;
    const stop = async (name, presses) => {
      check(`${tag}: keyboard: ${name}`, presses > 0, presses);
      if (presses > 0) keys += presses;
      check(`${tag}: keyboard: ${name}: focus visible`, await focusVisible(page));
      check(`${tag}: keyboard: ${name}: not under the return bar`, await notUnderBar(page));
    };
    const enter = async (sel) => { await page.keyboard.press("Enter"); keys += 1; await settle(page, sel); };
    await stop("first example card", await keyTo(page, () => document.activeElement?.id === "demo-example-y-en"));
    await enter(".demo-question");
    await stop("“Open the Concept”", await keyTo(page, () => document.activeElement?.matches("#demo-step-concepts ~ ul button.primary") ?? false));
    await enter(".library-concept h2");
    check(`${tag}: keyboard: Concept heading focused`, await page.evaluate(() => document.activeElement?.tagName === "H2"));
    await stop("a source link", await keyTo(page, () => document.activeElement?.matches(".library-section.current .library-unit .link-button") ?? false));
    await enter("#src-entry");
    check(`${tag}: keyboard: evidence heading focused`, await page.evaluate(() => document.activeElement?.tagName === "H2"));
    await shot("keyboard-evidence", false);
    await stop("“Back to the example” (Shift+Tab)", await keyTo(page, () => document.activeElement?.closest(".demo-return") !== null && !/#\d/.test(document.activeElement?.textContent ?? ""), { back: true }));
    await enter(".demo-question");
    await stop("“Back to examples and search”", await keyTo(page, () => document.activeElement?.matches(".demo-example > .panel button.ghost") ?? false));
    await page.keyboard.press("Enter");
    keys += 1;
    await page.waitForFunction(() => document.activeElement?.id === "demo-example-y-en", null, { timeout: 3000 }).catch(() => {});
    check(`${tag}: keyboard: focus restored to the first card`, await page.evaluate(() => document.activeElement?.id === "demo-example-y-en"));
    metrics[`${tag}: key presses, start → evidence → start`] = keys;

    // 5. Every Concept and every supporting unit's evidence, by direct link.
    const concepts = await page.evaluate(async () => (await (await fetch("/knowledge-library/concepts?state=all")).json()).results.map((r) => r.concept.id));
    let screens = 0;
    for (const c of concepts) {
      await page.goto(`${base}#concept=${c}`);
      await page.reload();
      await settle(page, ".library-concept h2");
      await fits(page, sz, tag, `Concept ${c}`);
      screens++;
      const units = await page.evaluate(async (id) => (await (await fetch(`/knowledge-library/concepts/${id}`)).json()).supporting_units.map((u) => u.unit_id), c);
      for (const u of units) {
        await page.goto(`${base}#concept=${c}&unit=${u}`);
        await page.reload();
        await settle(page, "#src-entry");
        await fits(page, sz, tag, `evidence of unit ${u}`);
        screens++;
      }
    }
    metrics[`${tag}: Concept and evidence screens measured`] = screens;

    // 6. Semantic preset results (the preset list is the widest control).
    await page.goto(base);
    await settle(page, ".demo-example-card");
    await page.check('input[name="library-mode"][value="semantic"]');
    await page.click('form[role=search] button[type=submit]');
    await settle(page, ".library-results .link-button");
    if (expectVectors === "mechanical") check(`${tag}: semantic: mechanical notice beside the scores`, await page.locator(".demo-mechanical-results").isVisible());
    await fits(page, sz, tag, "semantic results");
    await shot("semantic", false);
    requestChecks(tag, requests, errors);
    await ctx.close();

    // 7. Long and bilingual text (injected in the browser) through the walk.
    {
      const { ctx, page, requests, errors } = await open(sz, locale);
      await page.route(/\/knowledge-library\/concepts\/\d+$/, async (route) => {
        const r = await route.fetch();
        const d = await r.json();
        d.concept.target = `${d.concept.target} — ${"une explication très longue du concept ".repeat(4)}${"x".repeat(80)}`;
        d.concept.scope = LONG_ID;
        d.concept.identity_features = { ...d.concept.identity_features, very_long_feature_name_without_spaces: LONG_ID };
        for (const u of [d.preferred_unit, ...d.supporting_units].filter(Boolean)) {
          u.canonical = `${u.canonical} ${"y".repeat(70)}`;
          u.statement = `${u.statement} ${BILINGUAL}`;
          u.example = `${u.example ?? ""} ${"Et encore une phrase d'exemple en français. ".repeat(4)}`;
        }
        await route.fulfill({ response: r, json: d });
      });
      await page.route(/\/knowledge-library\/units\/\d+\/source$/, async (route) => {
        const r = await route.fetch();
        const d = await r.json();
        d.entry.original_input = LONG_FR;
        d.entry.original_context = `${BILINGUAL} ${"Contexte : ".repeat(20)}`;
        d.entry.created_at = "2026-11-12T02:28:09.131184273Z";
        d.extraction.extractor = LONG_ID;
        d.source_interpretation.analysis.analyzer = LONG_ID;
        if (d.source_interpretation.effective.effective) d.source_interpretation.effective.effective.explanation = BILINGUAL;
        await route.fulfill({ response: r, json: d });
      });
      await page.goto(base);
      await settle(page, ".demo-example-card");
      await page.click("#demo-example-y-en");
      await settle(page, ".demo-question");
      check(`${tag}: long text: whole long question shown`, (await page.locator(".demo-question").innerText()).includes("anticonstitutionnellement"));
      await fits(page, sz, tag, "long text example");
      await page.locator("#demo-step-concepts ~ ul button.primary").first().click();
      await settle(page, ".library-concept h2");
      await page.locator(".library-concept .demo-details summary").click();
      await fits(page, sz, tag, "long text Concept (details open)");
      await shot("long-concept", true, page);
      await page.locator(".library-section.current .library-unit .link-button").first().click();
      await settle(page, "#src-entry");
      await fits(page, sz, tag, "long text evidence");
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      const bar = await page.locator(".demo-return").boundingBox();
      check(`${tag}: long text: return bar stays in view after scrolling`, bar && bar.y >= -1 && bar.y < 10, JSON.stringify(bar));
      await shot("long-evidence", true, page);
      requestChecks(`${tag} long text`, requests, errors);
      await ctx.close();
    }

    // 8. Loading, empty, no-match and unavailable states.
    {
      const { ctx, page } = await open(sz, locale);
      let failInfo = true;
      await page.route(/\/knowledge-library\/demo$/, (route) =>
        failInfo ? route.fulfill({ status: 503, contentType: "application/json", body: '{"error":"unavailable"}' }) : route.continue());
      await page.goto(base);
      await settle(page, ".banner.error[role=alert]");
      check(`${tag}: unavailable: stated with its status and a retry`, (await page.locator(".banner.error").innerText()).includes("503") && (await page.locator(".banner.error button").count()) === 1);
      await fits(page, sz, tag, "unavailable");
      await shot("state-unavailable", false, page);
      failInfo = false;
      await page.locator(".banner.error button").click();
      await settle(page, ".demo-example-card");
      check(`${tag}: unavailable: retry recovers without a reload`, (await page.locator(".demo-example-card").count()) === 3);

      let release;
      const gate = new Promise((r) => (release = r));
      await page.route(/\/knowledge-library\/units\/\d+\/source$/, async (route) => { await gate; await route.continue(); });
      await page.click("#demo-example-y-en");
      await settle(page, ".demo-example .empty[role=status]");
      check(`${tag}: loading: example states it is loading`, (await page.locator(".demo-example .empty[role=status]").count()) === 1);
      await shot("state-loading", false, page);
      release();
      await settle(page, ".demo-question");
      await page.unroute(/\/knowledge-library\/units\/\d+\/source$/);
      await page.locator(".demo-example > .panel button.ghost").first().click();
      await settle(page, ".demo-example-card");

      await page.fill("#library-query", "subjonctiff");
      await page.press("#library-query", "Enter");
      await settle(page, ".demo-no-match-help");
      check(`${tag}: no match: stated, with how matching works`, (await page.locator(".demo-no-match .empty[role=status]").count()) === 1 && (await page.locator(".demo-no-match-help h3").innerText()) === T.noMatch);
      await fits(page, sz, tag, "no match");
      await shot("state-no-match", false, page);
      await page.locator(".demo-no-match-help button").first().click();
      await settle(page, ".library-results .link-button");
      check(`${tag}: no match: a suggestion finds Concepts`, (await page.locator(".library-results .link-button").count()) >= 1);

      await page.route(/\/knowledge-library\/concepts(\?.*)?$/, (route) =>
        route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ schema_version: "knowledge_library_search_v1", query: "", tokens: [], state: "all", limit: 20, total_matches: 0, truncated: false, results: [] }) }));
      await page.goto(base);
      await page.reload();
      await settle(page, ".library .empty[role=status]");
      check(`${tag}: empty: an empty catalog is the demo build's`, (await page.locator(".library .empty[role=status]").innerText()) === T.empty && (await page.locator(".demo-no-match-help").count()) === 0);
      await ctx.close();
    }
  }
}

// 9. Self-test: the overflow check must catch the old evidence-row layout.
for (const locale of LOCALES) {
  for (const sz of SIZES.filter((s) => s.mobile)) {
    const tag = `regression ${sz.size}-${locale}`;
    const { ctx, page } = await open(sz, locale);
    await page.goto(`${base}#concept=10&unit=11`);
    await settle(page, "#src-entry");
    const now = await measure(page, sz.width);
    check(`${tag}: current layout fits`, now.scrollWidth <= sz.width, `${now.scrollWidth}px`);
    await page.addStyleTag({ content: OLD_LAYOUT });
    await page.waitForTimeout(100);
    const old = await measure(page, sz.width);
    const caught = old.scrollWidth > sz.width && old.wide.some((w) => w.startsWith("dd"));
    check(`${tag}: the overflow check catches the old layout`, caught, `${old.scrollWidth}px ${old.wide.join(", ")}`);
    metrics[`${tag}: old layout width / innerWidth / old check would pass`] = `${old.scrollWidth} / ${old.innerWidth} / ${old.scrollWidth <= old.innerWidth + 1}`;
    await page.screenshot({ path: join(out, `regression-${sz.size}-${locale}-old-layout.png`) });
    await ctx.close();
  }
}

// 10. The read-only boundary: private routes stay closed whatever the page shows.
{
  const ctx = await browser.newContext();
  for (const [method, path, want] of [["GET", "/entries", 404], ["GET", "/api/entries", 404], ["GET", "/listening/materials", 404],
    ["GET", "/reading/lessons", 404], ["GET", "/mistake-notebook/items", 404], ["GET", "/RELEASE.json", 404],
    ["POST", "/knowledge-library/concepts", 405], ["POST", "/api/captures", 405], ["PUT", "/api/knowledge-library/concepts/1", 405]]) {
    const r = await ctx.request.fetch(`${origin}${path}`, { method, failOnStatusCode: false });
    check(`boundary: ${method} ${path} -> ${want}`, r.status() === want, r.status());
  }
  await ctx.close();
}
await browser.close();

const failed = checks.filter((c) => !c.ok);
writeFileSync(join(out, "results.json"), JSON.stringify({ url, expectVectors, passed: checks.length - failed.length, failed: failed.length, metrics, checks }, null, 1));
writeFileSync(join(out, "overflow.json"), JSON.stringify(overflowTable, null, 1));
for (const f of failed) console.log(`FAIL ${f.name} — ${f.detail}`);
for (const [k, v] of Object.entries(metrics)) console.log(`METRIC ${k}: ${v}`);
console.log(`${checks.length - failed.length}/${checks.length} checks passed; ${overflowTable.length} screens measured for overflow`);
process.exit(failed.length ? 1 : 0);
