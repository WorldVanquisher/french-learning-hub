// Vocabulary in real Chromium (VOC): from the learning home to Vocabulary on a
// fresh database, save an approved term, reload and find it, read its meaning
// and the learner's words, open its source and come back, review it with Recall
// Practice, save two Concepts with the same spelling, search accent-blind,
// remove a term with focus moving on, at desktop and 320 px. COMBOS (JSON
// [{tag, locale, phone, url, facts}]); copy from the mounted catalogs (/i18n).
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
  const ctx = await browser.newContext({
    ...(c.phone ? { viewport: { width: 320, height: 640 }, hasTouch: true, isMobile: true } : { viewport: { width: 1280, height: 900 } }),
    reducedMotion: "reduce",
  });
  await ctx.addInitScript((loc) => window.localStorage.setItem("flh.ui-locale.v1", loc), c.locale);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const fits = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
  const active = () => page.evaluate(() => ({ tag: document.activeElement?.tagName, text: (document.activeElement?.textContent ?? "").trim().slice(0, 80), label: document.activeElement?.getAttribute("aria-label") }));
  const waitFocus = async (pred) => {
    for (let i = 0; i < 40; i++) {
      const a = await active();
      if (pred(a)) return a;
      await page.waitForTimeout(50);
    }
    return active();
  };
  const mine = page.getByRole("region", { name: T("vocabulary.region"), exact: true });
  const approved = page.getByRole("region", { name: T("notebook.kinds.region", { kind: T("notebook.mode.vocabulary") }), exact: true });
  const rows = () => page.locator("li[data-concept]").evaluateAll((lis) => lis.map((li) => li.dataset.concept));
  const openVocabulary = async () => {
    await page.goto(c.url + "/");
    await page.getByRole("button", { name: T("nav.home"), exact: true }).click();
    await page.getByRole("region", { name: T("home.heading"), exact: true }).getByRole("button", { name: T("home.vocabulary.action"), exact: true }).click();
    await mine.waitFor();
  };
  const f = c.facts;
  try {
    await openVocabulary();
    await page.getByText(T("vocabulary.emptyBook"), { exact: true }).waitFor();
    check("a fresh database opens Vocabulary with the empty book", true);
    await page.screenshot({ path: `${shots}/01-empty.png`, fullPage: true });
    // VOC-006 / VOC-090: the first save on a fresh database, immediately visible
    await approved.getByRole("button", { name: T("vocabulary.saveLabel", { term: "apporter" }), exact: true }).click();
    await page.locator(`li[data-concept="${f.concept_apporter}"]`).waitFor();
    check("the first save appears at once in My vocabulary", JSON.stringify(await rows()) === JSON.stringify([String(f.concept_apporter)]), await rows());
    const row = page.locator(`li[data-concept="${f.concept_apporter}"]`);
    const text = (await row.textContent()) ?? "";
    check("its meaning (both languages) and the learner's own words are shown", text.includes("to bring (a thing)") && text.includes("带来（东西）") && text.includes("Pouvez-vous apporter le dessert ?") && text.includes("Comment dit-on « bring »"), text.slice(0, 300));
    await page.screenshot({ path: `${shots}/02-saved.png`, fullPage: true });
    // VOC-007: a real reload of the page, then back to Vocabulary
    await page.reload();
    await openVocabulary();
    await page.locator(`li[data-concept="${f.concept_apporter}"]`).waitFor();
    check("after a reload the saved term is still listed", JSON.stringify(await rows()) === JSON.stringify([String(f.concept_apporter)]), await rows());
    // VOC-065: browser storage holds only the interface preferences, never the list, a search or learner text
    const stored = await page.evaluate(() => [localStorage, sessionStorage].flatMap((st) => Object.keys(st).map((k) => `${k}=${st.getItem(k)}`)));
    check("browser storage holds no saved term, search or learner text after a reload", !stored.some((x) => /apporter|bring|vocab|Comment dit-on/i.test(x)), stored);
    // VOC-009: open the source, come back to the same control
    await page.getByRole("button", { name: T("vocabulary.openSourceLabel", { term: "apporter" }), exact: true }).click();
    const src = page.getByRole("region", { name: T("vocabulary.sourceRegion"), exact: true });
    await src.waitFor();
    check("the source shows the learner's question and its extraction", ((await src.textContent()) ?? "").includes("Comment dit-on « bring »"));
    await page.screenshot({ path: `${shots}/03-source.png`, fullPage: false });
    await src.getByRole("button", { name: T("vocabulary.backToList"), exact: true }).click();
    const back = await waitFocus((a) => a.label === T("vocabulary.openSourceLabel", { term: "apporter" }));
    check("back from the source returns focus to its button", back.label === T("vocabulary.openSourceLabel", { term: "apporter" }), back);
    // VOC-010: start the existing Recall Practice for this term, then end it
    await page.getByRole("button", { name: T("vocabulary.reviewLabel", { term: "apporter" }), exact: true }).click();
    const practice = page.getByRole("region", { name: T("practice.region"), exact: true });
    await practice.waitFor();
    check("Review opens Recall Practice for the saved Concept", ((await practice.textContent()) ?? "").includes(T("practice.heading", { id: f.concept_apporter })));
    await page.screenshot({ path: `${shots}/04-review.png`, fullPage: false });
    await practice.getByRole("button", { name: T("vocabulary.endReview"), exact: true }).click();
    const afterReview = await waitFocus((a) => a.label === T("vocabulary.reviewLabel", { term: "apporter" }));
    check("ending the review returns to the term's Review button", afterReview.label === T("vocabulary.reviewLabel", { term: "apporter" }), afterReview);
    // VOC-014 / VOC-101: the same spelling, two Concepts (French chat, English loanword)
    const chatButtons = approved.getByRole("button", { name: T("vocabulary.saveLabel", { term: "chat" }), exact: true });
    await chatButtons.first().click();
    await page.locator(`li[data-concept="${f.concept_chat_fr}"]`).waitFor();
    await page.waitForTimeout(200);
    await approved.getByRole("button", { name: T("vocabulary.saveLabel", { term: "chat" }), exact: true }).first().click();
    await page.locator(`li[data-concept="${f.concept_chat_en}"]`).waitFor();
    check("two Concepts spelled chat are two saved terms", (await rows()).length === 3, await rows());
    // VOC-040 / VOC-104: accent-blind search over a saved phrase
    await approved.getByRole("button", { name: T("vocabulary.saveLabel", { term: "faire la grasse matinée" }), exact: true }).click();
    await page.locator(`li[data-concept="${f.concept_grasse}"]`).waitFor();
    await mine.getByRole("searchbox", { name: T("vocabulary.search"), exact: true }).fill("matinee");
    await mine.getByRole("button", { name: T("vocabulary.searchButton"), exact: true }).click();
    for (let i = 0; i < 40 && (await rows()).length !== 1; i++) await page.waitForTimeout(100);
    check("searching matinee (no accent) finds faire la grasse matinée", JSON.stringify(await rows()) === JSON.stringify([String(f.concept_grasse)]), await rows());
    await page.screenshot({ path: `${shots}/05-search.png`, fullPage: true });
    await mine.getByRole("searchbox", { name: T("vocabulary.search"), exact: true }).fill("");
    await mine.getByRole("button", { name: T("vocabulary.searchButton"), exact: true }).click();
    for (let i = 0; i < 40 && (await rows()).length !== 4; i++) await page.waitForTimeout(100);
    // VOC-026 / VOC-078: remove the first row, focus moves to the next row's heading
    const before = await rows();
    await page.getByRole("button", { name: T("vocabulary.removeLabel", { term: "apporter" }), exact: true }).click();
    for (let i = 0; i < 40 && (await rows()).includes(String(f.concept_apporter)); i++) await page.waitForTimeout(100);
    const afterRemove = await waitFocus((a) => a.tag === "H3");
    check("removing a term drops its row and moves focus to the next term", !(await rows()).includes(String(f.concept_apporter)) && afterRemove.tag === "H3", { before, after: await rows(), focus: afterRemove });
    // VOC-076: a long punctuated phrase saved; everything still wraps at 320 px
    const longTerm = "il pleut des cordes, n'est-ce pas ? — « oui » (vraiment) !";
    await approved.getByRole("button", { name: T("vocabulary.saveLabel", { term: longTerm }), exact: true }).click();
    await page.locator(`li[data-concept="${f.concept_long}"]`).waitFor();
    if (c.phone) check("phone: Vocabulary with a long phrase fits 320 px without horizontal scroll", await fits());
    await page.screenshot({ path: `${shots}/06-after-remove.png`, fullPage: true });
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
