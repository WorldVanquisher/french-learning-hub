// Review Today in real Chromium: open the queue, complete a workbook item
// (it leaves without a reload), open the Speaking take, and come back to the
// queue. COMBOS (JSON [{tag, locale, phone, url}]) names one seeded server per
// combination; copy comes from the mounted catalogs (/i18n).
import { chromium } from "playwright";
import fs from "node:fs";

const OUT = process.env.OUT || "/out";
const combos = JSON.parse(process.env.COMBOS);
const results = [];
const catalog = (locale) => {
  const cat = {};
  for (const line of fs.readFileSync(`/i18n/${locale}.ts`, "utf8").split("\n")) {
    const r = line.match(/^\s*"([^"]+)":\s*("(?:[^"\\]|\\.)*"),?\s*$/);
    if (r) cat[r[1]] = JSON.parse(r[2]);
  }
  return (key, vars = {}) => {
    if (cat[key] === undefined) throw new Error(`missing ${key}`);
    return cat[key].replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? `{${k}}`));
  };
};
const browser = await chromium.launch();
for (const c of combos) {
  const T = catalog(c.locale);
  const shots = `${OUT}/shots/${c.tag}`;
  fs.mkdirSync(shots, { recursive: true });
  const check = (name, pass, detail = "") => results.push({ combo: c.tag, name, pass: !!pass, detail: typeof detail === "string" ? detail : JSON.stringify(detail) });
  const ctx = await browser.newContext(c.phone ? { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true } : { viewport: { width: 1280, height: 900 } });
  await ctx.addInitScript((loc) => window.localStorage.setItem("flh.ui-locale.v1", loc), c.locale);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const fits = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
  try {
    await page.goto(c.url + "/#/today");
    const queue = page.getByRole("list", { name: T("today.queue"), exact: true });
    await queue.waitFor();
    const rows = () => queue.locator(":scope > li").evaluateAll((lis) => lis.map((li) => `${li.dataset.source}:${li.dataset.reason}`));
    check("the queue lists one item from each source with its reason", JSON.stringify(await rows()) === JSON.stringify(["speaking:review_without_feedback", "notebook:retry_marked"]), await rows());
    if (c.phone) check("phone: the queue fits the width", await fits());
    await page.screenshot({ path: `${shots}/1-queue.png`, fullPage: true });
    await page.evaluate(() => { window.__sameDocument = true; });
    // Complete the workbook item: it leaves the queue, the page is not reloaded.
    await queue.locator('li[data-source="notebook"]').getByRole("button", { name: T("today.done") }).click();
    for (let i = 0; i < 50 && (await rows()).length !== 1; i++) await page.waitForTimeout(100);
    const same = await page.evaluate(() => window.__sameDocument === true);
    check("Done for today removes the workbook item without a reload", JSON.stringify(await rows()) === JSON.stringify(["speaking:review_without_feedback"]) && same, { rows: await rows(), same });
    await page.screenshot({ path: `${shots}/2-after-done.png`, fullPage: true });
    // Open the Speaking take, then come back to the queue.
    await queue.locator('li[data-source="speaking"]').getByRole("button", { name: T("today.openTake", { n: 1 }) }).click();
    const take = page.getByRole("heading", { name: T("speaking.take.heading", { n: 1 }), exact: true });
    await take.waitFor();
    await page.waitForTimeout(300);
    check("Open take 1 lands on take 1 (focused)", await take.evaluate((el) => el === document.activeElement));
    await page.screenshot({ path: `${shots}/3-take.png`, fullPage: false });
    await page.getByRole("button", { name: T("trail.backToToday"), exact: true }).click();
    await queue.waitFor();
    check("Back to Review Today returns to the queue, still in the same page", JSON.stringify(await rows()) === JSON.stringify(["speaking:review_without_feedback"])
      && (await page.evaluate(() => window.__sameDocument === true)), await rows());
    const hist = await page.getByText(T("today.history", { notebook: 2, takes: 1 })).count();
    check("history is counted, not queued (2 saved mistakes, 1 take)", hist === 1);
    await page.screenshot({ path: `${shots}/4-back.png`, fullPage: true });
    check("no page errors", errors.length === 0, errors);
  } catch (e) {
    check("walkthrough", false, String(e).slice(0, 600));
    await page.screenshot({ path: `${shots}/error.png`, fullPage: true }).catch(() => {});
  }
  await ctx.close();
}
await browser.close();
fs.writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 1));
const failed = results.filter((r) => !r.pass);
console.log(`${results.length - failed.length}/${results.length} PASS`);
for (const r of results) console.log(r.pass ? "PASS" : "FAIL", r.combo, r.name, r.pass ? "" : r.detail);
process.exit(failed.length ? 1 : 0);
