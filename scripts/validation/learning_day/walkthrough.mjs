// A synthetic learner's day in real Chromium (reduced motion emulated):
//   1. Mistake Notebook → Make practice: two notes, accent-rich edit with a
//      line break, keyboard between questions, Ctrl+Enter to approve, then
//      practise the edited wording;
//   2. Review Today: the approved notes and the Speaking step, each saying
//      what it is based on; arrow keys between items; hide a step for this
//      visit and show it again; This week's counts;
//   3. Resume the Speaking take: status, attribution; back to Review Today;
//   4. Open the lesson of a note: confirm the pack update, then the revision
//      studio compares revision 1 with 2 and previews a restore, closed
//      with focus returned.
// At every step: no unnamed control, no duplicate id, nothing moving, and on
// the 320 px phone no horizontal scroll. COMBOS (JSON [{tag, locale, phone,
// url, seed}]) names one seeded server per combination; copy comes from the
// mounted catalogs (/i18n).
import { chromium } from "playwright";
import fs from "node:fs";

const OUT = process.env.OUT || "/out";
const combos = JSON.parse(process.env.COMBOS);
const results = [];
const ACCENT = "Pourquoi Hélène préfère-t-elle étudier le soir ?\n« Ça dépend… » — c’est l’hôpital Saint-Éloi.";
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

// The accessibility and layout smoke run at every step.
const smoke = (page) =>
  page.evaluate(() => {
    const vis = (el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden";
    };
    const nameOf = (el) => {
      const l = el.getAttribute("aria-label");
      if (l && l.trim()) return l.trim();
      const lb = el.getAttribute("aria-labelledby");
      if (lb) {
        const t = lb.split(/\s+/).map((id) => document.getElementById(id)?.textContent ?? "").join(" ").trim();
        if (t) return t;
      }
      if (el.labels && el.labels.length) {
        const t = [...el.labels].map((x) => x.textContent).join(" ").trim();
        if (t) return t;
      }
      if (!["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName)) {
        const t = (el.textContent ?? "").trim();
        if (t) return t;
      }
      return (el.getAttribute("title") ?? "").trim();
    };
    const unnamed = [...document.querySelectorAll("button, a[href], input:not([type=hidden]), select, textarea, audio[controls]")]
      .filter(vis)
      .filter((el) => !nameOf(el))
      .map((el) => el.outerHTML.slice(0, 120));
    const ids = [...document.querySelectorAll("[id]")].map((e) => e.id);
    const dup = [...new Set(ids.filter((id, i) => ids.indexOf(id) !== i))];
    const moving = [...document.querySelectorAll("*")].filter((el) => {
      const cs = getComputedStyle(el);
      return cs.transitionDuration.split(",").some((d) => parseFloat(d) > 0) || (cs.animationName && cs.animationName !== "none");
    }).length;
    return { unnamed, dup, moving, fits: document.documentElement.scrollWidth <= window.innerWidth + 1, width: document.documentElement.scrollWidth };
  });

const browser = await chromium.launch();
for (const c of combos) {
  const T = catalog(c.locale);
  const shots = `${OUT}/shots/${c.tag}`;
  fs.mkdirSync(shots, { recursive: true });
  const check = (name, pass, detail = "") => results.push({ combo: c.tag, name, pass: !!pass, detail: typeof detail === "string" ? detail : JSON.stringify(detail) });
  const ctx = await browser.newContext({
    ...(c.phone ? { viewport: { width: 320, height: 640 }, hasTouch: true, isMobile: true } : { viewport: { width: 1280, height: 900 } }),
    reducedMotion: "reduce",
  });
  await ctx.addInitScript((loc) => window.localStorage.setItem("flh.ui-locale.v1", loc), c.locale);
  const page = await ctx.newPage();
  page.setDefaultTimeout(15000);
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const step = async (name) => {
    const s = await smoke(page);
    check(`${name}: every control named, ids unique, nothing moving${c.phone ? ", fits 320 px" : ""}`,
      s.unnamed.length === 0 && s.dup.length === 0 && s.moving === 0 && (!c.phone || s.fits), s);
  };
  const focusedText = () => page.evaluate(() => (document.activeElement?.textContent ?? "").trim());
  try {
    // 1. Note → practice.
    await page.goto(c.url + "/#/notebook");
    await page.getByRole("button", { name: T("notebook.mode.practice"), exact: true }).click();
    await page.getByRole("heading", { name: T("notePractice.heading"), exact: true }).waitFor();
    const boxes = page.locator("li[data-entry] input[type=checkbox]");
    check("two saved notes can be selected", (await boxes.count()) === 2, await boxes.count());
    await boxes.nth(0).check();
    await boxes.nth(1).check();
    await step("practice selection");
    await page.getByRole("button", { name: T("notePractice.previewSelected.other", { count: 2 }), exact: true }).click();
    const previewHeading = page.getByRole("heading", { name: T("notePractice.preview.heading.other", { count: 2 }), exact: true });
    await previewHeading.waitFor();
    check("the preview heading takes focus", await previewHeading.evaluate((el) => el === document.activeElement));
    const questions = page.getByLabel(T("notePractice.draft.question"), { exact: true });
    await questions.nth(0).fill(ACCENT);
    await questions.nth(0).focus();
    await page.keyboard.press("Alt+ArrowDown");
    check("Alt+↓ moves to the next draft's question", await questions.nth(1).evaluate((el) => el === document.activeElement));
    await page.screenshot({ path: `${shots}/01-practice-preview.png`, fullPage: true });
    await step("practice preview");
    await page.keyboard.press("Control+Enter");
    const approved = page.getByRole("heading", { name: T("notePractice.approved.heading"), exact: true });
    await approved.waitFor();
    check("Ctrl+Enter approves both records into Review Today", (await page.getByText(T("notePractice.approved.count.other", { count: 2 }), { exact: true }).count()) === 1);
    await page.getByRole("button", { name: T("notePractice.practiseNow"), exact: true }).click();
    const q = page.locator(".practice-question").first();
    await q.waitFor();
    check("the edited wording is practised exactly (accents, guillemets, line break)", (await q.textContent()) === ACCENT, await q.textContent());
    await page.screenshot({ path: `${shots}/02-practise-now.png`, fullPage: true });
    await step("practise now");

    // 2. Review Today.
    await page.goto(c.url + "/#/today");
    const queue = page.getByRole("list", { name: T("today.queue"), exact: true });
    await queue.waitFor();
    const reasons = () => queue.locator(":scope > li").evaluateAll((lis) => lis.map((li) => li.dataset.reason));
    check("the queue lists the Speaking step and both approved notes", JSON.stringify(await reasons()) === JSON.stringify(["review_without_feedback", "retry_marked", "retry_marked"]), await reasons());
    const based = await queue.locator("[data-based-on]").count();
    check("each item says what it is based on", based === 3, based);
    await queue.locator(":scope > li").nth(0).locator("button").first().focus();
    await page.keyboard.press("ArrowDown");
    check("↓ moves to the next item's first button", await queue.locator(":scope > li").nth(1).locator("button").first().evaluate((el) => el === document.activeElement));
    await queue.locator('li[data-source="speaking"]').getByRole("button", { name: T("today.hide"), exact: true }).click();
    for (let i = 0; i < 30 && (await reasons()).length !== 2; i++) await page.waitForTimeout(100);
    await page.waitForTimeout(100);
    check("hiding a step for this visit moves focus to the next item", (await reasons()).length === 2 && (await queue.locator(":scope > li").nth(0).locator("button").first().evaluate((el) => el === document.activeElement)), await reasons());
    await page.getByRole("button", { name: T("today.showHidden"), exact: true }).click();
    for (let i = 0; i < 30 && (await reasons()).length !== 3; i++) await page.waitForTimeout(100);
    check("the hidden step comes back", (await reasons()).length === 3);
    const week = page.getByRole("region", { name: T("week.region"), exact: true });
    await week.getByRole("table").waitFor();
    const totals = T("week.totals", { production: 3, exercises: 2, reviewed: 2, corrections: 2, feedback: 0, active: 1 });
    check("This week counts the seeded day (3 production, 2 reviewed, 2 own corrections)", (await week.getByText(totals, { exact: true }).count()) === 1, await week.locator('[data-week="totals"]').textContent());
    if (c.phone) {
      const tw = await week.getByRole("table").evaluate((el) => ({ scroll: el.scrollWidth, client: el.clientWidth }));
      check("phone: the week table shows every column without scrolling", tw.scroll <= tw.client + 1, tw);
    }
    check("a sparse week shows counts only", (await week.getByText(T("week.sparse", { min: 20 }), { exact: true }).count()) === 1);
    await page.screenshot({ path: `${shots}/03-review-today.png`, fullPage: true });
    await step("Review Today and This week");

    // 3. Resume the Speaking take, then come back.
    await queue.locator('li[data-source="speaking"]').getByRole("button", { name: T("today.openTake", { n: 2 }), exact: true }).click();
    const take = page.getByRole("heading", { name: T("speaking.take.heading", { n: 2 }), exact: true });
    await take.waitFor();
    await page.waitForTimeout(300);
    check("Resume take 2 lands on take 2 (focused)", await take.evaluate((el) => el === document.activeElement));
    const status = page.getByRole("list", { name: T("speaking.status.region", { n: 2 }), exact: true });
    check("the take says it has no audio and which transcript version it has",
      (await status.getByText(T("speaking.status.audioNone"), { exact: true }).count()) === 1 &&
        (await status.getByText(T("speaking.status.transcript", { version: 2, origin: T("speaking.origin.corrected") }), { exact: true }).count()) === 1);
    check("version 2 is attributed to the learner", (await page.getByText(T("speaking.attribution.corrected", { version: 2 }), { exact: true }).count()) === 1);
    await page.screenshot({ path: `${shots}/04-take.png`, fullPage: false });
    await step("Speaking take");
    await page.getByRole("button", { name: T("trail.backToToday"), exact: true }).click();
    await queue.waitFor();

    // 4. A note's lesson: a pack update, then the revision studio.
    await queue.locator('li[data-source="notebook"]').first().getByRole("button", { name: T("today.openLesson"), exact: true }).click();
    await page.getByRole("button", { name: T("listening.revision.review"), exact: true }).click();
    await page.getByRole("button", { name: T("listening.revision.confirm", { to: 2 }), exact: true }).click();
    await page.getByText(T("listening.revision.updated", { from: 1, to: 2 }), { exact: true }).waitFor();
    check("the confirmed update made revision 2", true);
    await page.getByRole("button", { name: T("studio.open", { n: 2 }), exact: true }).click();
    // The revision pair heads the comparison (its paragraph also holds the summary).
    const between = page.locator(".studio-compare .studio-source");
    await between.waitFor();
    check("the comparison names revision 1 → revision 2", (await between.textContent()).startsWith(T("studio.compare.between", { from: 1, to: 2 })), await between.textContent());
    const del = page.locator('.studio-compare [data-kind="changed"] del');
    check("the comparison labels the removed words of the older line", (await del.count()) >= 1 && (await del.first().textContent()).includes("Voilà"), await del.allTextContents());
    const folds = await page.locator('.studio-compare [data-kind="fold"]').count();
    check("unchanged lines are folded, the revision pair still named", folds >= 1 && (await between.textContent()).startsWith(T("studio.compare.between", { from: 1, to: 2 })), folds);
    await page.screenshot({ path: `${shots}/05-studio-compare.png`, fullPage: true });
    await step("revision comparison");
    const opener = page.getByRole("button", { name: T("studio.previewRestore", { n: 1 }), exact: true });
    await opener.click();
    await page.getByRole("heading", { name: T("studio.restore.heading", { target: 1, current: 2 }), exact: true }).waitFor();
    const impact = page.getByRole("list", { name: T("studio.restore.impact"), exact: true });
    check("the restore preview says it adds revision 3 and changes nothing else", (await impact.getByText(T("studio.restore.appends", { next: 3, target: 1 }), { exact: true }).count()) === 1);
    await page.screenshot({ path: `${shots}/06-restore-preview.png`, fullPage: true });
    await step("restore preview");
    await page.getByRole("button", { name: T("studio.restore.cancel"), exact: true }).click();
    await page.waitForTimeout(200);
    check("Not now returns focus to the button that opened the preview", (await focusedText()) === T("studio.previewRestore", { n: 1 }), await focusedText());
    check("no page errors", errors.length === 0, errors);
  } catch (e) {
    check("walkthrough", false, String(e).slice(0, 700));
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
