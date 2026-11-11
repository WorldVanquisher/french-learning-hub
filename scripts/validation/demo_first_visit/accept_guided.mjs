// Public demo first visit: real-browser acceptance of the guided examples,
// their return paths and the failure states, in English and 简体中文 at desktop
// (1280×900) and phone (390×844) widths, against a running demo (normally the
// packaged release binary). Read-only: every request must be a same-origin GET
// on the demo allowlist. Complements ../demo_refresh/accept_paths.mjs (search
// paths and private-route probes), which must still pass.
//
//   node accept_guided.mjs URL OUT_DIR [mechanical|model]
//
// Needs playwright-core (no browser download) and CHROME=/path/to/chromium.
import { chromium } from "playwright-core";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const [url, out, expectVectors = "mechanical"] = process.argv.slice(2);
if (!url || !out) {
  console.error("usage: node accept_guided.mjs URL OUT_DIR [mechanical|model]");
  process.exit(2);
}
mkdirSync(out, { recursive: true });
const checks = [];
const check = (name, ok, detail = "") => checks.push({ name, ok: Boolean(ok), detail: String(detail).slice(0, 300) });

// The D1 authored examples (fixture data; shown untranslated in every locale).
const EXAMPLES = [
  { key: "y-en", question: "« j'y vais » et « j'en veux »", units: 2, concepts: 1 },
  { key: "il-faut-venir", question: "Pourquoi « viennes » et pas « viens » ?", units: 1, concepts: 1, otherEvidence: true },
  { key: "en-train-de", question: "est-ce que « je suis cuisinant » existe ?", units: 2, concepts: 2 },
];
const ALLOWED = /^\/(api\/)?(knowledge-library\/(concepts(\/\d+)?|units\/\d+\/source|demo(\/(semantic|hybrid)-search)?)|assets\/.+|readyz|healthz)?$/;
const origin = new URL(url).origin;

const browser = await chromium.launch({ executablePath: process.env.CHROME, args: ["--no-sandbox"] });
for (const locale of ["en", "zh-CN"]) {
  for (const [w, h, size] of [[1280, 900, "desktop"], [390, 844, "mobile"]]) {
    const tag = `${locale}-${size}`;
    const ctx = await browser.newContext({ viewport: { width: w, height: h } });
    await ctx.addInitScript((l) => {
      try { localStorage.setItem("flh.ui-locale.v1", l); } catch {}
    }, locale);
    const page = await ctx.newPage();
    const requests = [];
    const consoleErrors = [];
    page.on("request", (r) => requests.push({ method: r.method(), url: r.url() }));
    page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
    const shot = (n) => page.screenshot({ path: join(out, `${tag}-${n}.png`), fullPage: true });
    const noSideScroll = async (where) => {
      const o = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      check(`${tag}: ${where}: no horizontal scroll`, o <= 0, `${o}px`);
    };

    await page.goto(url);
    await page.waitForSelector(".demo-example-card");
    check(`${tag}: lead sentence visible`, await page.locator(".demo-lead").isVisible());
    check(`${tag}: three example entry points`, (await page.locator(".demo-example-card").count()) === 3);
    check(`${tag}: read-only and synthetic labels visible`, (await page.locator(".demo-labels .demo-label").count()) >= 2 && (await page.locator(".demo-labels").isVisible()));
    if (expectVectors === "mechanical") {
      check(`${tag}: mechanical warning visible on landing`, await page.locator(".demo-intro .banner.info").isVisible());
      check(`${tag}: development-build label`, await page.locator(".demo-label.warn").isVisible());
    } else {
      check(`${tag}: no mechanical warning for a model build`, (await page.locator(".demo-label.warn").count()) === 0);
    }
    check(`${tag}: direct search kept`, await page.locator("#library-query").isVisible());
    await noSideScroll("landing");
    await shot("01-landing");

    // Keyboard: the first example card is reachable with Tab and opens with Enter.
    let reached = false;
    for (let i = 0; i < 25 && !reached; i++) {
      await page.keyboard.press("Tab");
      reached = await page.evaluate(() => document.activeElement?.id === "demo-example-y-en");
    }
    check(`${tag}: first example reachable by keyboard`, reached);

    for (const [i, ex] of EXAMPLES.entries()) {
      const n = String(i + 2).padStart(2, "0");
      if (i === 0 && reached) await page.keyboard.press("Enter");
      else await page.click(`#demo-example-${ex.key}`);
      await page.waitForSelector(".demo-question");
      check(`${tag}: ${ex.key}: heading focused`, await page.evaluate(() => document.activeElement?.tagName === "H2"));
      const q = page.locator(".demo-question");
      check(`${tag}: ${ex.key}: original French question shown unchanged`, (await q.innerText()).includes(ex.question), await q.innerText());
      check(`${tag}: ${ex.key}: question marked French`, (await q.getAttribute("lang")) === "fr");
      check(`${tag}: ${ex.key}: ${ex.units} extracted units`, (await page.locator("#demo-step-extracted ~ ul .demo-unit").count()) === ex.units);
      check(`${tag}: ${ex.key}: ${ex.concepts} Concepts`, (await page.locator("#demo-step-concepts ~ ul .demo-unit").count()) === ex.concepts);
      await noSideScroll(`${ex.key} example`);
      await shot(`${n}-example-${ex.key}`);

      // Example → Concept → evidence → back to the Concept → back to the example.
      await page.locator("#demo-step-concepts ~ ul button.primary").first().click();
      await page.waitForSelector(".library-concept h2");
      await noSideScroll(`${ex.key} concept`);
      await shot(`${n}-concept-${ex.key}`);
      await page.locator(".library-section.current .library-unit .link-button").first().click();
      await page.waitForSelector("#src-entry");
      check(`${tag}: ${ex.key}: evidence shows a learner question`, (await page.locator("#src-entry ~ dl .french").innerText()).length > 0);
      await noSideScroll(`${ex.key} evidence`);
      await shot(`${n}-evidence-${ex.key}`);
      await page.locator(".actions button").first().click(); // back to the Concept
      await page.waitForSelector(".library-concept h2");
      await page.locator(".library-concept button.ghost").first().click(); // back to the example
      await page.waitForSelector(".demo-question");
      check(`${tag}: ${ex.key}: returned to the same example`, (await page.locator(".demo-question").innerText()).includes(ex.question));
      await page.locator(".demo-example > .panel button.ghost").first().click(); // back to the start
      await page.waitForSelector(".demo-example-card");
      check(`${tag}: ${ex.key}: focus back on its example card`, await page.evaluate((k) => document.activeElement?.id === `demo-example-${k}`, ex.key));
    }

    // Search state survives a guided example.
    await page.fill("#library-query", "pronouns");
    await page.press("#library-query", "Enter");
    await page.waitForSelector(".library-results .link-button");
    await page.click("#demo-example-y-en");
    await page.waitForSelector(".demo-question");
    await page.locator(".demo-example > .panel button.ghost").first().click();
    await page.waitForSelector(".demo-example-card");
    check(`${tag}: search query kept after an example`, (await page.inputValue("#library-query")) === "pronouns");
    check(`${tag}: search results kept after an example`, (await page.locator(".library-results .link-button").count()) === 1);

    const bad = requests.filter((r) => {
      const u = new URL(r.url);
      return u.origin !== origin || r.method !== "GET" || !ALLOWED.test(u.pathname);
    });
    check(`${tag}: every request a same-origin GET on the allowlist`, bad.length === 0, JSON.stringify(bad.slice(0, 3)));
    check(`${tag}: no console errors`, consoleErrors.length === 0, consoleErrors.join(" | "));
    await ctx.close();
  }
}

// Failure and edge states (English desktop): slow load, failed read with retry,
// no keyword match.
{
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(url);
  await page.waitForSelector(".demo-example-card");
  let release;
  const gate = new Promise((r) => (release = r));
  await page.route(/\/knowledge-library\/units\/\d+\/source$/, async (route) => {
    await gate;
    await route.continue();
  });
  await page.click("#demo-example-y-en");
  await page.waitForSelector(".empty[role=status]");
  check("en-desktop: example shows a loading state", (await page.locator(".empty[role=status]").innerText()).length > 0);
  release();
  await page.waitForSelector(".demo-question");
  await page.unroute(/\/knowledge-library\/units\/\d+\/source$/);
  await page.locator(".demo-example > .panel button.ghost").first().click();
  await page.waitForSelector(".demo-example-card");

  await page.route(/\/knowledge-library\/concepts\/\d+$/, (route) => route.fulfill({ status: 503, contentType: "application/json", body: '{"error":"unavailable"}' }));
  await page.click("#demo-example-en-train-de");
  await page.waitForSelector(".banner.error[role=alert]");
  check("en-desktop: failed example read is stated with a retry", (await page.locator(".banner.error button").count()) === 1);
  await page.screenshot({ path: join(out, "en-desktop-90-example-failed.png"), fullPage: true });
  await page.unroute(/\/knowledge-library\/concepts\/\d+$/);
  await page.locator(".banner.error button").click();
  await page.waitForSelector(".demo-question");
  check("en-desktop: retry recovers the example", (await page.locator(".demo-question").innerText()).includes("cuisinant"));
  await page.locator(".demo-example > .panel button.ghost").first().click();
  await page.waitForSelector(".demo-example-card");

  await page.fill("#library-query", "zzzzqx");
  await page.press("#library-query", "Enter");
  const noMatch = page.locator(".library .empty[role=status]", { hasText: "zzzzqx" });
  await noMatch.waitFor({ timeout: 5000 }).catch(() => {});
  check("en-desktop: no keyword match is stated", (await noMatch.count()) === 1);
  await page.screenshot({ path: join(out, "en-desktop-91-no-match.png"), fullPage: true });
  await ctx.close();
}
await browser.close();

const failed = checks.filter((c) => !c.ok);
writeFileSync(join(out, "results.json"), JSON.stringify({ url, expectVectors, passed: checks.length - failed.length, failed: failed.length, checks }, null, 2));
for (const c of checks) console.log(`${c.ok ? "PASS" : "FAIL"} ${c.name}${c.ok || !c.detail ? "" : ` — ${c.detail}`}`);
console.log(`${checks.length - failed.length}/${checks.length} checks passed`);
process.exit(failed.length ? 1 : 0);
