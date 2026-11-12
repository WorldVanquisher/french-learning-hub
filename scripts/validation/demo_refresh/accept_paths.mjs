// Public demo refresh: real-browser acceptance of the authored French
// examples, question -> units -> Concept -> evidence, in English and 简体中文,
// at desktop and phone widths, against a running demo (normally the
// packaged release binary). Read-only: every request must be a same-origin
// GET on the demo allowlist.
//
//   node accept_paths.mjs URL OUT_DIR [mechanical|model]
//
// Needs playwright-core (no browser download) and CHROME=/path/to/chromium.
import { chromium } from "playwright-core";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const [url, out, expectVectors = "mechanical"] = process.argv.slice(2);
if (!url || !out) {
  console.error("usage: node accept_paths.mjs URL OUT_DIR [mechanical|model]");
  process.exit(2);
}
mkdirSync(out, { recursive: true });
const checks = [];
const check = (name, ok, detail = "") => checks.push({ name, ok: Boolean(ok), detail: String(detail).slice(0, 300) });

const L = {
  en: { about: "About this demo", input: "Search learned material", search: "Search", results: "Library results",
        supporting: (n) => `Currently supporting this concept (${n})`, viewSource: /View source record #\d+/,
        source: /Original learning record #\d+/, back: /← Back to concept #\d+/, semantic: "Semantic",
        example: "Example query", semResults: "Semantic results" },
  "zh-CN": { about: "关于此演示", input: "搜索已学内容", search: "搜索", results: "知识库结果",
        supporting: (n) => `当前支持此概念（${n}）`, viewSource: /查看来源记录 #\d+/,
        source: /原始学习记录 #\d+/, back: /← 返回概念 #\d+/, semantic: "语义",
        example: "示例查询", semResults: "语义结果" },
};
// Authored French paths (fixture data: never translated).
const PATHS = [
  { query: "train", concept: "« être en train de » + infinitive: in the middle of doing", units: 1,
    unitText: "être en train de + infinitif", question: "est-ce que « je suis cuisinant » existe ?" },
  { query: "pronouns", concept: "the pronouns y and en", units: 2,
    unitText: "en remplace de + nom", question: "Dans « j'y vais » et « j'en veux »" },
  { query: "il faut", concept: "subjunctive after « il faut que »", units: 2,
    unitText: "il faut que + subjonctif de venir", question: "Pourquoi « viennes » et pas « viens » ?" },
];
const ALLOWED = /^\/(api\/)?(healthz|readyz|knowledge-library\/(concepts(\/\d+)?|units\/\d+\/source|demo(\/semantic-search|\/hybrid-search)?)|assets\/[^/]+|favicon\.[a-z]+)?$/;

const browser = await chromium.launch({ executablePath: process.env.CHROME, args: ["--no-sandbox"] });
for (const [locale, form] of [["en", "desktop"], ["en", "mobile"], ["zh-CN", "desktop"], ["zh-CN", "mobile"]]) {
  const tag = `${locale}-${form}`;
  const t = L[locale];
  const context = await browser.newContext(form === "mobile"
    ? { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 }
    : { viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const errors = [], requests = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("request", (r) => requests.push({ method: r.method(), url: r.url() }));
  let n = 0;
  const shot = (name) => page.screenshot({ path: join(out, `${tag}-${String(++n).padStart(2, "0")}-${name}.png`), fullPage: true });
  // Under phone emulation the layout viewport (innerWidth) grows to fit wide
  // content, so comparing scrollWidth with innerWidth can never fail (it
  // passed at 421 px on a 390 px phone). Compare with the device width and
  // name the element that sticks out.
  const noOverflow = async (where) => {
    if (form !== "mobile") return;
    const device = 390;
    const r = await page.evaluate((dw) => {
      const all = [...document.querySelectorAll("body *")].filter((el) => {
        const b = el.getBoundingClientRect();
        return (b.width > 0 || b.height > 0) && b.right + window.scrollX > dw + 0.5;
      });
      const leaf = all.filter((el) => !all.some((o) => o !== el && el.contains(o)));
      return {
        scrollWidth: document.documentElement.scrollWidth,
        wide: leaf.slice(0, 2).map((el) => `${el.tagName.toLowerCase()} “${(el.textContent || "").trim().slice(0, 40)}”`).join(", "),
      };
    }, device);
    check(`${tag}: no horizontal scroll (${where})`, r.scrollWidth <= device, `${r.scrollWidth} vs device ${device}${r.wide ? `: ${r.wide}` : ""}`);
  };
  try {
    await page.goto(url, { waitUntil: "networkidle" });
    if (locale !== "en") {
      await page.getByLabel("Language").selectOption(locale);
    }
    const about = page.getByRole("region", { name: t.about });
    await about.waitFor();
    const lang = await page.getAttribute("html", "lang");
    check(`${tag}: document language`, locale === "en" ? lang === "en" : /^zh/.test(lang ?? ""), lang);
    const aboutText = await about.innerText();
    if (expectVectors === "mechanical") {
      check(`${tag}: mechanical vectors are labelled`, (await page.getByText(/mechanical|机械/).count()) >= 1);
    }
    check(`${tag}: no private section controls`, (await page.getByRole("button", { name: /Learning Records|Concept Review|Annotation Inspector|Experiment Dashboard|Writing|Reading|Listening/ }).count()) === 0);
    check(`${tag}: about text present`, aboutText.length > 40, aboutText.slice(0, 80));
    await noOverflow("home");
    await shot("home");

    for (const p of PATHS) {
      await page.getByLabel(t.input).fill(p.query);
      await page.getByRole("button", { name: t.search, exact: true }).click();
      const results = page.getByRole("region", { name: t.results });
      const hit = results.getByRole("button", { name: p.concept, exact: true });
      await hit.waitFor();
      check(`${tag}: “${p.query}” finds “${p.concept}”`, true);
      await hit.click();
      await page.getByRole("heading", { level: 2, name: p.concept }).waitFor();
      check(`${tag}: ${p.concept}: ${p.units} supporting unit(s)`, (await page.getByText(t.supporting(p.units), { exact: true }).count()) === 1);
      check(`${tag}: ${p.concept}: unit wording shown`, (await page.getByText(p.unitText).count()) >= 1, p.unitText);
      const sources = page.getByRole("button", { name: t.viewSource });
      const ids = new Set((await sources.allInnerTexts()).map((s) => s.match(/#(\d+)/)?.[1]));
      if (p.query === "il faut") check(`${tag}: ${p.concept}: evidence from two questions`, ids.size === 2, [...ids].join(","));
      await noOverflow(p.query);
      await shot(`concept-${p.query.replace(/\s+/g, "-")}`);
      // The unit card: nearest ancestor of the unit title that holds a source button.
      const card = page.getByText(p.unitText, { exact: true }).last().locator("xpath=ancestor::*[.//button][1]");
      const target = card.getByRole("button", { name: t.viewSource }).first();
      await target.click();
      await page.getByRole("heading", { level: 3, name: t.source }).waitFor();
      const body = await page.locator("main").innerText();
      check(`${tag}: ${p.concept}: source shows the original French question unchanged`, body.includes(p.question), p.question);
      await noOverflow(`${p.query} source`);
      await shot(`source-${p.query.replace(/\s+/g, "-")}`);
      await page.getByRole("button", { name: t.back }).click();
      await page.getByRole("heading", { level: 2, name: p.concept }).waitFor();
      // Back to the result list (the label quotes the query in both languages).
      await page.getByRole("button", { name: new RegExp(`^←.*${p.query}`) }).click();
      await page.getByLabel(t.input).waitFor();
    }

    await page.getByRole("radio", { name: t.semantic }).check();
    await page.getByLabel(t.example).selectOption("right-now");
    await page.getByRole("button", { name: t.search, exact: true }).click();
    const sem = page.getByRole("region", { name: t.semResults });
    await sem.getByRole("listitem").first().waitFor();
    check(`${tag}: new preset “right-now” returns results`, (await sem.getByRole("listitem").count()) > 0);
    await noOverflow("semantic");
    await shot("semantic-right-now");
  } catch (e) {
    check(`${tag}: walk completed`, false, e.stack ?? e);
    await shot("failure").catch(() => {});
  }
  const origin = new URL(url).origin;
  const off = requests.filter((r) => !r.url.startsWith(origin));
  const nonGet = requests.filter((r) => r.method !== "GET");
  const notAllowed = requests.filter((r) => r.url.startsWith(origin) && !ALLOWED.test(new URL(r.url).pathname));
  check(`${tag}: every request same-origin`, off.length === 0, off.map((r) => r.url).join(" "));
  check(`${tag}: every request is GET`, nonGet.length === 0, nonGet.map((r) => `${r.method} ${r.url}`).join(" "));
  check(`${tag}: every request on the demo allowlist`, notAllowed.length === 0, notAllowed.map((r) => r.url).join(" "));
  check(`${tag}: no console errors`, errors.length === 0, errors.join(" | "));
  await context.close();
}

// Private routes stay closed (root and /api), whatever the page shows: unknown
// paths are 404, any method other than GET/HEAD is 405 before routing.
const ctx = await browser.newContext();
for (const [method, path, want] of [["GET", "/entries", 404], ["GET", "/api/entries", 404], ["GET", "/reading/lessons", 404],
  ["GET", "/writing/tasks", 404], ["GET", "/listening/materials", 404], ["GET", "/RELEASE.json", 404],
  ["POST", "/knowledge-library/concepts", 405], ["POST", "/api/captures", 405]]) {
  const r = await ctx.request.fetch(url.replace(/\/$/, "") + path, { method, failOnStatusCode: false });
  check(`private route ${method} ${path} -> ${want}`, r.status() === want, r.status());
}
await browser.close();

const failed = checks.filter((c) => !c.ok);
writeFileSync(join(out, "results.json"), JSON.stringify({ url, expectVectors, passed: checks.length - failed.length, failed: failed.length, checks }, null, 1));
console.log(`${checks.length - failed.length}/${checks.length} checks passed`);
for (const f of failed) console.log("FAIL", f.name, f.detail);
process.exit(failed.length ? 1 : 0);
