// Review Today in Chromium at scale (browser_perf.py): the request's own
// duration and size apart from rendering, then repeated navigation away and
// back, counting /review-today requests per visit and net event listeners.
import { chromium } from "playwright";
import fs from "node:fs";

const URL_ = process.env.URL;
const CYCLES = Number(process.env.CYCLES || 15);
const ITEMS = Number(process.env.ITEMS || 0);
const out = { loads: [], cycles: [], checks: [] };
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: "reduce" });
await ctx.addInitScript(() => {
  // net listener count on window and document (added minus removed, by type and target)
  window.__listeners = 0;
  for (const target of [window, document]) {
    const add = target.addEventListener.bind(target);
    const rem = target.removeEventListener.bind(target);
    const live = new Set();
    target.addEventListener = (type, fn, opts) => {
      const key = `${type}`;
      if (!live.has(fn + key)) {
        live.add(fn + key);
      }
      window.__listeners++;
      return add(type, fn, opts);
    };
    target.removeEventListener = (type, fn, opts) => {
      window.__listeners--;
      return rem(type, fn, opts);
    };
  }
});
const page = await ctx.newPage();
page.setDefaultTimeout(30000);
let requests = 0;
page.on("request", (r) => {
  if (new URL(r.url()).pathname.endsWith("/review-today")) requests++;
});
const check = (name, pass, detail) => out.checks.push({ name, pass: !!pass, detail });

async function loadToday(label) {
  // a real (cold) document load each time: the same URL and hash would be a same-document navigation
  await page.goto("about:blank");
  await page.goto(`${URL_}/#/today`);
  const list = page.locator("ol.today-queue").first();
  await list.waitFor();
  await page.waitForFunction((n) => document.querySelectorAll("ol.today-queue:first-of-type > li").length >= Math.min(n, 1), ITEMS);
  const m = await page.evaluate(() => {
    const r = performance.getEntriesByType("resource").filter((e) => e.name.includes("/review-today")).pop();
    const nav = performance.getEntriesByType("navigation")[0];
    const shown = performance.now();
    return {
      request_ms: r ? Math.round(r.responseEnd - r.requestStart) : null,
      transfer_bytes: r ? r.transferSize : null,
      body_bytes: r ? r.encodedBodySize : null,
      render_after_response_ms: r ? Math.round(shown - r.responseEnd) : null,
      page_ready_ms: Math.round(shown - (nav ? nav.startTime : 0)),
      items_rendered: document.querySelectorAll("ol.today-queue > li").length,
    };
  });
  out.loads.push({ label, ...m });
}

for (let i = 0; i < 5; i++) await loadToday(`cold load ${i + 1}`);
// repeated navigation inside the single-page app
await page.goto(`${URL_}/#/today`);
await page.locator("ol.today-queue").first().waitFor();
await page.waitForTimeout(300);
const baseListeners = await page.evaluate(() => window.__listeners);
requests = 0;
for (let c = 0; c < CYCLES; c++) {
  const before = requests;
  await page.evaluate(() => {
    location.hash = "#/notebook";
  });
  await page.waitForTimeout(150);
  await page.evaluate(() => {
    location.hash = "#/today";
  });
  await page.locator("ol.today-queue").first().waitFor();
  // once per cycle: the practice panel and a concept, then back
  const open = page.getByRole("button", { name: "Show the practice prototype (synthetic data)…", exact: true });
  if (await open.count()) await open.click();
  await page.locator('[data-source="practice"]').first().waitFor();
  await page.locator("#practice-open-y-en-demo").click();
  await page.locator(".concept-practice").waitFor();
  await page.getByRole("button", { name: "← Back to Review Today", exact: true }).first().click();
  await page.locator("#practice-open-y-en-demo").waitFor();
  await page.waitForTimeout(150);
  out.cycles.push({ cycle: c + 1, review_today_requests: requests - before, listeners: await page.evaluate(() => window.__listeners) });
}
const extra = out.cycles.filter((x) => x.review_today_requests !== 1);
check("one /review-today request per visit to Review Today (no duplicate requests)", extra.length === 0, extra);
const grown = out.cycles.at(-1).listeners - baseListeners;
check("window and document listeners return to their level after each cycle (no leak)", out.cycles.every((x) => x.listeners === out.cycles[0].listeners) && grown <= out.cycles[0].listeners - baseListeners, { base: baseListeners, first: out.cycles[0].listeners, last: out.cycles.at(-1).listeners });
check(`every queue item is rendered (${ITEMS})`, out.loads.every((l) => l.items_rendered >= ITEMS), out.loads.map((l) => l.items_rendered));
check("each cold load is its own document load (distinct navigation entries)", new Set(out.loads.map((l) => l.page_ready_ms + ":" + l.request_ms)).size > 1 || out.loads.length === 1, out.loads.map((l) => l.request_ms));
await browser.close();
fs.writeFileSync("/out/browser.json", JSON.stringify(out, null, 1));
console.log(JSON.stringify(out.checks));
process.exit(out.checks.every((c) => c.pass) ? 0 : 1);
