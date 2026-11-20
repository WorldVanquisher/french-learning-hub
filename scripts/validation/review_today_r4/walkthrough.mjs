// Review Today R4 in real Chromium on the synthetic R4 profile. COMBOS (JSON
// [{tag, locale, phone, url, facts}]) names one seeded server per combination;
// copy comes from the mounted catalogs (/i18n). MODE=baseline only records
// what the page does (screenshots and observations) for the before/after.
import { chromium } from "playwright";
import fs from "node:fs";

const OUT = process.env.OUT || "/out";
const MODE = process.env.MODE || "r4";
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
  const check = (name, pass, detail = "") => results.push({ combo: c.tag, name, pass: MODE === "baseline" ? true : !!pass, observed: detail === "" ? undefined : detail });
  const ctx = await browser.newContext({
    ...(c.phone ? { viewport: { width: 320, height: 640 }, hasTouch: true, isMobile: true } : { viewport: { width: 1280, height: 900 } }),
    reducedMotion: "reduce",
  });
  await ctx.addInitScript((loc) => window.localStorage.setItem("flh.ui-locale.v1", loc), c.locale);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const fits = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
  const active = () =>
    page.evaluate(() => {
      const a = document.activeElement;
      return { tag: a?.tagName ?? null, text: (a?.textContent ?? "").trim().slice(0, 60), key: a?.closest("li[data-key]")?.getAttribute("data-key") ?? null };
    });
  const queue = page.getByRole("list", { name: T("today.queue"), exact: true });
  const keys = () => queue.locator(":scope > li").evaluateAll((lis) => lis.map((li) => li.dataset.key));
  const row = (key) => queue.locator(`:scope > li[data-key="${key}"]`);
  const waitKeys = async (pred) => {
    for (let i = 0; i < 60; i++) {
      if (pred(await keys())) return true;
      await page.waitForTimeout(100);
    }
    return false;
  };
  // Focus moves asynchronously by design (after a hide, a completion or a return): wait for it to
  // settle before the next keyboard step, so a late move never redirects a key press.
  const waitFocus = async (pred) => {
    for (let i = 0; i < 40; i++) {
      const a = await active();
      if (pred(a)) return a;
      await page.waitForTimeout(50);
    }
    return active();
  };
  const expected = c.facts.queue.map((q) => q.key);
  const grouped = `notebook:entry:${c.facts.grouped.lead}`;
  try {
    const t0 = Date.now();
    await page.goto(c.url + "/#/today");
    await queue.waitFor();
    const firstPaintMs = Date.now() - t0;
    check("the queue shows the profile's items in the backend's order", JSON.stringify(await keys()) === JSON.stringify(expected), { got: await keys(), expected, firstPaintMs });
    await page.screenshot({ path: `${shots}/01-queue.png`, fullPage: true });
    if (c.phone) check("phone: the queue fits 320 px without horizontal scroll", await fits());
    // reload: the same order (R4-WB-007)
    await page.reload();
    await queue.waitFor();
    check("a reload keeps the same order", JSON.stringify(await keys()) === JSON.stringify(expected), await keys());
    // one row per workbook question (R4-WB-008)
    const groupRows = await queue.locator(":scope > li").evaluateAll((lis, title) => lis.filter((li) => (li.textContent ?? "").includes(title)).length, c.facts.title);
    check("question 2 saved from two revisions is one row", (await row(grouped).locator("[data-also]").count()) === 1, { rowsForTheLesson: groupRows });
    // every row: a reason sentence and a primary action (R4-WB-006)
    const anatomy = await queue.locator(":scope > li").evaluateAll((lis) =>
      lis.map((li) => ({ key: li.dataset.key, reason: li.dataset.reason, primary: !!li.querySelector("button.primary"), raw: (li.querySelector("p:nth-of-type(2)")?.textContent ?? "").includes(li.dataset.reason) })),
    );
    check("every row has a primary action and a reason sentence (no raw code)", anatomy.every((a) => a.primary && !a.raw), anatomy);
    // the next review (R4-WB-011, R4-WB-014)
    const sched = row(grouped).locator("[data-schedule]");
    if ((await sched.count()) === 1) {
      await sched.locator("summary").click();
      check("the next review explains a completed and a missed attempt", (await sched.locator('[data-if="completed"]').isVisible()) && (await sched.locator('[data-if="missed"]').isVisible()));
      await page.screenshot({ path: `${shots}/02-next-review.png`, fullPage: false });
    } else check("the next review explains a completed and a missed attempt", false, "no schedule");
    // keyboard: arrows move between rows (R4-WB-061)
    await queue.locator(":scope > li button").first().focus();
    await page.keyboard.press("ArrowDown");
    check("ArrowDown moves to the next item's first button", (await active()).key === expected[1], await active());
    // hide a Speaking step, open a lesson, come back (R4-WB-005, R4-WB-009)
    const sp = expected.find((k) => k.startsWith("speaking:"));
    await row(sp).getByRole("button", { name: T("today.hide"), exact: true }).click();
    await waitKeys((k) => !k.includes(sp));
    await waitFocus((a) => a.key !== null && a.key !== sp);
    const target = `notebook:entry:${c.facts.queue.find((q) => q.key.startsWith("notebook:")).key.split(":")[2]}`;
    // keyboard only (R4-WB-061): open the lesson, then Back, with Enter
    await row(target).getByRole("button", { name: T("today.openLesson"), exact: true }).focus();
    await page.keyboard.press("Enter");
    const back = page.getByRole("button", { name: T("trail.backToToday"), exact: true });
    await back.waitFor();
    await page.screenshot({ path: `${shots}/03-lesson.png`, fullPage: false });
    await back.focus();
    await page.keyboard.press("Enter");
    await queue.waitFor();
    const after = await waitFocus((a) => a.key === target);
    check("Back to Review Today returns focus to the item that was opened", after.key === target && after.text === T("today.openLesson"), after);
    check("a step hidden for this visit stays hidden after the lesson", !(await keys()).includes(sp), await keys());
    await page.screenshot({ path: `${shots}/04-back.png`, fullPage: true });
    // a failed save keeps the row and its focus, then succeeds (R4-WB-010, R4-WB-062)
    let failed = 0;
    await page.route("**/mistake-notebook/items/*/retry", async (route, req) => {
      if (req.method() === "PUT" && failed === 0) {
        failed++;
        return route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: "could not record the retry decision" }) });
      }
      return route.continue();
    });
    const doneBtn = () => row(target).getByRole("button", { name: T("today.done"), exact: true });
    await doneBtn().focus();
    await page.keyboard.press("Enter");
    await page.getByRole("alert").first().waitFor();
    const kept = await waitFocus((a) => a.key === target && a.text === T("today.done"));
    check("a failed save keeps the row and gives focus back to its button", (await keys()).includes(target) && kept.key === target && kept.text === T("today.done"), kept);
    await page.screenshot({ path: `${shots}/05-failed-save.png`, fullPage: false });
    await page.keyboard.press("Enter");
    const left = await waitKeys((k) => !k.includes(target));
    const live = (await page.locator('.review-today [aria-live="polite"]').textContent()) ?? "";
    const [pre, post] = T("today.doneAnnounce", { title: "\u0000" }).split("\u0000");
    check("the same button then succeeds; the item leaves and is announced once", left && live.startsWith(pre) && live.endsWith(post) && live.split(pre).length === 2, { live, keys: await keys() });
    const moved = await waitFocus((a) => a.key !== null && a.key !== target);
    check("focus moves to the item that took its place", moved.key !== null && moved.key !== target, moved);
    await page.unroute("**/mistake-notebook/items/*/retry");
    // the grouped row clears both records
    await row(grouped).getByRole("button", { name: T("today.done"), exact: true }).click();
    const groupedLeft = await waitKeys((k) => !k.includes(grouped));
    check("Done for today on the grouped row clears both records", groupedLeft, await keys());
    // empty: finish every notebook item, hide the other step (R4-WB-062)
    for (const k of await keys()) {
      if (k.startsWith("notebook:")) {
        await row(k).getByRole("button", { name: T("today.done"), exact: true }).click();
        await waitKeys((ks) => !ks.includes(k));
      } else {
        await row(k).getByRole("button", { name: T("today.hide"), exact: true }).click();
        await waitKeys((ks) => !ks.includes(k));
      }
    }
    await page.waitForTimeout(300);
    const empty = await active();
    check("an emptied queue puts focus on the heading", empty.tag === "H2", empty);
    await page.screenshot({ path: `${shots}/06-empty.png`, fullPage: true });
    // the notebook keeps every record; the long French text fits the phone (R4-WB-019, R4-WB-064)
    await page.goto(c.url + "/#/notebook");
    await page.waitForTimeout(800);
    const longShown = await page.getByText(/Je pensais que la responsable de l'inscription/).count();
    check("the Mistake Notebook still lists the records after Done for today", longShown >= 1, { longShown });
    if (c.phone) check("phone: the notebook with long French text fits 320 px", await fits());
    await page.screenshot({ path: `${shots}/07-notebook.png`, fullPage: false });
    check("no page errors", errors.length === 0, errors);
  } catch (e) {
    results.push({ combo: c.tag, name: "walkthrough", pass: false, observed: String(e).slice(0, 600) });
    await page.screenshot({ path: `${shots}/error.png`, fullPage: true }).catch(() => {});
  }
  await ctx.close();
}
await browser.close();
fs.writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 1));
const failed = results.filter((r) => !r.pass);
console.log(`${results.length - failed.length}/${results.length} PASS (${MODE})`);
for (const r of results) console.log(r.pass ? "PASS" : "FAIL", r.combo, r.name, r.pass && MODE !== "baseline" ? "" : JSON.stringify(r.observed ?? ""));
process.exit(failed.length ? 1 : 0);
