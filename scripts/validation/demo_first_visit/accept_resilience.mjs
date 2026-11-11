// Public demo resilience: long text, slow / failed / out-of-order reads, empty
// results, rapid switching and return navigation, against a running demo
// (normally the packaged release binary). Responses are delayed, failed or
// lengthened in the browser (Playwright routing); the server and its data are
// never changed. Each check names the failure case it guards.
//
//   node accept_resilience.mjs URL OUT_DIR
//
// Needs playwright-core (no browser download) and CHROME=/path/to/chromium.
import { chromium } from "playwright-core";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const [url, out] = process.argv.slice(2);
if (!url || !out) {
  console.error("usage: node accept_resilience.mjs URL OUT_DIR");
  process.exit(2);
}
mkdirSync(out, { recursive: true });
const checks = [];
const check = (name, ok, detail = "") => checks.push({ name, ok: Boolean(ok), detail: String(detail).slice(0, 300) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const browser = await chromium.launch({ executablePath: process.env.CHROME, args: ["--no-sandbox"] });

async function open(locale = "en", width = 1280) {
  const ctx = await browser.newContext({ viewport: { width, height: width > 500 ? 900 : 844 } });
  await ctx.addInitScript((l) => {
    try { localStorage.setItem("flh.ui-locale.v1", l); } catch {}
  }, locale);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  return { ctx, page, errors };
}
const overflow = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const searchFor = async (page, q) => {
  await page.fill("#library-query", q);
  await page.press("#library-query", "Enter");
};
const resultTitles = (page) => page.locator(".library-results .link-button").allInnerTexts();

// 1. Long text (synthetic, injected in the browser) in both languages at both widths.
const LONG_FR =
  "Dans un très long message de forum, une apprenante écrit : « Quand j'y vais avec mes collègues et qu'on en parle pendant des heures, " +
  "est-ce que « y » et « en » remplacent toujours la même chose, même dans une phrase qui continue encore et encore ? » " +
  "anticonstitutionnellementanticonstitutionnellementanticonstitutionnellement";
const LONG_ID = "fixture:flh073:fr_l2_taxonomy_v1:" + "x".repeat(120);
for (const locale of ["en", "zh-CN"]) {
  for (const width of [1280, 390]) {
    const tag = `${locale}-${width}`;
    const { ctx, page, errors } = await open(locale, width);
    await page.route(/\/knowledge-library\/concepts\/\d+$/, async (route) => {
      const r = await route.fetch();
      const d = await r.json();
      d.concept.target = `${d.concept.target} — ${"une explication très longue du concept ".repeat(6)}`;
      for (const u of [d.preferred_unit, ...d.supporting_units].filter(Boolean)) {
        u.canonical = `${u.canonical} ${"(forme longue) ".repeat(5)}`;
        u.statement = `${u.statement} ${"This statement keeps going to test wrapping. ".repeat(8)}`;
        u.example = `${u.example ?? ""} ${"Et encore une phrase d'exemple en français. ".repeat(6)}`;
      }
      await route.fulfill({ response: r, json: d });
    });
    await page.route(/\/knowledge-library\/units\/\d+\/source$/, async (route) => {
      const r = await route.fetch();
      const d = await r.json();
      d.entry.original_input = LONG_FR;
      d.entry.original_context = "Contexte : ".repeat(30);
      d.extraction.extractor = LONG_ID;
      d.source_interpretation.analysis.analyzer = LONG_ID;
      await route.fulfill({ response: r, json: d });
    });
    await page.goto(url);
    await page.click("#demo-example-y-en");
    await page.waitForSelector(".demo-question");
    check(`${tag}: long text: example has no horizontal scroll`, (await overflow(page)) <= 0, `${await overflow(page)}px`);
    check(`${tag}: long text: long French question shown whole`, (await page.locator(".demo-question").innerText()).includes("anticonstitutionnellement"));
    await page.screenshot({ path: join(out, `${tag}-long-example.png`), fullPage: true });
    await page.locator("#demo-step-concepts ~ ul button.primary").first().click();
    await page.waitForSelector(".library-concept h2");
    check(`${tag}: long text: Concept has no horizontal scroll`, (await overflow(page)) <= 0, `${await overflow(page)}px`);
    await page.screenshot({ path: join(out, `${tag}-long-concept.png`), fullPage: true });
    await page.locator(".library-section.current .library-unit .link-button").first().click();
    await page.waitForSelector("#src-entry");
    check(`${tag}: long text: evidence has no horizontal scroll`, (await overflow(page)) <= 0, `${await overflow(page)}px`);
    const nav = page.locator(".demo-return");
    if (await nav.count()) {
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      const box = await nav.boundingBox();
      check(`${tag}: long text: return actions stay in view after scrolling`, box && box.y >= -1 && box.y < 10, JSON.stringify(box));
    }
    await page.screenshot({ path: join(out, `${tag}-long-evidence.png`), fullPage: true });
    check(`${tag}: long text: no page errors`, errors.length === 0, errors.join(" | "));
    await ctx.close();
  }
}

// 2. Slow and failed reads, with recovery.
{
  const { ctx, page, errors } = await open();
  // The demo description itself fails once.
  let failInfo = true;
  await page.route(/\/knowledge-library\/demo$/, (route) =>
    failInfo ? route.fulfill({ status: 503, contentType: "application/json", body: '{"error":"unavailable"}' }) : route.continue(),
  );
  await page.goto(url);
  await page.waitForSelector(".banner.error[role=alert]");
  check("failed demo description is stated", (await page.locator(".banner.error").innerText()).includes("503"));
  const retry = page.locator(".banner.error button");
  check("failed demo description offers a retry (no reload needed)", (await retry.count()) === 1);
  await page.screenshot({ path: join(out, "failed-demo-description.png"), fullPage: true });
  failInfo = false;
  if (await retry.count()) {
    await retry.click();
    await page.waitForSelector(".demo-example-card", { timeout: 5000 }).catch(() => {});
    check("retry recovers the starting screen", (await page.locator(".demo-example-card").count()) === 3);
  } else {
    await page.reload();
    await page.waitForSelector(".demo-example-card");
  }
  await page.unroute(/\/knowledge-library\/demo$/);

  // A failed keyword search, then retry.
  let failSearch = true;
  await page.route(/\/knowledge-library\/concepts\?/, (route) =>
    failSearch ? route.fulfill({ status: 503, contentType: "application/json", body: '{"error":"unavailable"}' }) : route.continue(),
  );
  await searchFor(page, "pronouns");
  await page.waitForSelector(".banner.error[role=alert]");
  check("failed search is stated with a retry", (await page.locator(".banner.error button").count()) === 1);
  failSearch = false;
  await page.locator(".banner.error button").click();
  await page.waitForSelector(".library-results .link-button");
  check("search retry recovers the same query", (await page.inputValue("#library-query")) === "pronouns" && (await resultTitles(page)).length === 1);
  await page.unroute(/\/knowledge-library\/concepts\?/);

  // A failed source read, then retry, keeps the back actions.
  let failSource = true;
  await page.route(/\/knowledge-library\/units\/\d+\/source$/, (route) =>
    failSource ? route.fulfill({ status: 500, contentType: "application/json", body: '{"error":"x"}' }) : route.continue(),
  );
  await page.locator(".library-results .link-button").first().click();
  await page.waitForSelector(".library-concept h2");
  await page.locator(".library-section.current .library-unit .link-button").first().click();
  await page.waitForSelector(".banner.error[role=alert]");
  check("failed source read keeps both back actions", (await page.getByRole("button", { name: /← Back to/ }).count()) === 2);
  failSource = false;
  await page.locator(".banner.error button").click();
  await page.waitForSelector("#src-entry");
  check("source retry recovers", (await page.locator("#src-entry").count()) === 1);
  await page.unroute(/\/knowledge-library\/units\/\d+\/source$/);
  check("failure states raise no page errors", errors.length === 0, errors.join(" | "));
  await ctx.close();
}

// 3. Out-of-order reads: an older, slower answer must never replace a newer one.
{
  const { ctx, page } = await open();
  await page.goto(url);
  await page.waitForSelector(".demo-example-card");
  await page.route(/\/knowledge-library\/concepts\?q=pronouns/, async (route) => {
    await sleep(1500);
    await route.continue();
  });
  await searchFor(page, "pronouns");
  await searchFor(page, "train");
  await page.waitForSelector(".library-results .link-button");
  await sleep(2000);
  const titles = await resultTitles(page);
  check("out-of-order search: the later query wins", titles.length === 1 && /train/.test(titles[0]), titles.join(" | "));
  check("out-of-order search: the label names the later query", (await page.locator('section[aria-label="Library results"] [role=status]').first().innerText()).includes("train"));

  // A slow Concept, then another opened before it arrives.
  await page.route(/\/knowledge-library\/concepts\/12$/, async (route) => {
    await sleep(1500);
    await route.continue();
  });
  await searchFor(page, "y en");
  await page.waitForSelector("#library-result-12");
  await page.click("#library-result-12");
  await page.getByRole("button", { name: /← Back to/ }).first().click();
  await page.click("#library-result-14");
  await sleep(2000);
  check("out-of-order Concept: the later Concept stays on screen", /train/.test(await page.locator(".library-concept h2").innerText()));
  await ctx.close();
}

// 4. Empty results and rapid switching.
{
  const { ctx, page } = await open();
  await page.goto(url);
  await page.waitForSelector(".demo-example-card");
  await page.selectOption('select[aria-label="Concept status"]', "retired");
  await page.click('form[role=search] button[type=submit]');
  const empty = page.locator(".library .empty[role=status]", { hasText: "retired" });
  await empty.waitFor({ timeout: 5000 }).catch(() => {});
  check("empty status filter is stated", (await empty.count()) === 1);
  await page.selectOption('select[aria-label="Concept status"]', "all");
  await page.click('form[role=search] button[type=submit]');
  await page.waitForSelector(".library-results .link-button");

  // A double click on an example card must not need two Backs.
  await page.dblclick("#demo-example-y-en");
  await page.waitForSelector(".demo-question");
  await page.goBack();
  await page.waitForSelector(".demo-example-card", { timeout: 3000 }).catch(() => {});
  check("double click on an example: one Back returns to the start", await page.locator(".demo-lead").isVisible().catch(() => false));

  // Rapid example switching: the last chosen example is the one shown.
  await page.route(/\/knowledge-library\/concepts\?q=pronouns/, async (route) => {
    await sleep(1200);
    await route.continue();
  });
  if (!(await page.locator(".demo-example-card").count())) await page.goto(url);
  await page.click("#demo-example-y-en");
  await page.locator(".demo-next button").nth(1).click();
  await sleep(1800);
  check("rapid example switching shows the last example", (await page.locator(".demo-question").innerText()).includes("cuisinant"));
  await ctx.close();
}

// 5. Return navigation keeps the place: query, results and focus.
{
  const { ctx, page } = await open("en", 390);
  await page.goto(url);
  await page.waitForSelector(".demo-example-card");
  await searchFor(page, "y en");
  await page.waitForSelector("#library-result-14");
  await page.click("#library-result-14");
  await page.waitForSelector(".library-concept h2");
  await page.locator(".library-section.current .library-unit .link-button").first().click();
  await page.waitForSelector("#src-entry");
  await page.goBack();
  await page.waitForSelector(".library-concept h2");
  await page.goBack();
  await page.waitForSelector("#library-result-14");
  check("browser Back from evidence and Concept returns to the results", (await resultTitles(page)).length === 4 && (await page.inputValue("#library-query")) === "y en");
  check("focus returns to the opened result", await page.evaluate(() => document.activeElement?.id === "library-result-14"));
  const top = await page.locator("#library-result-14").boundingBox();
  check("the opened result is in view", top && top.y >= 0 && top.y < 844, JSON.stringify(top));
  await ctx.close();
}

await browser.close();
const failed = checks.filter((c) => !c.ok);
writeFileSync(join(out, "results.json"), JSON.stringify({ url, passed: checks.length - failed.length, failed: failed.length, checks }, null, 2));
for (const c of checks) console.log(`${c.ok ? "PASS" : "FAIL"} ${c.name}${c.ok || !c.detail ? "" : ` — ${c.detail}`}`);
console.log(`${checks.length - failed.length}/${checks.length} checks passed`);
process.exit(failed.length ? 1 : 0);
