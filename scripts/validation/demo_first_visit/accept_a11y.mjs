// Public demo accessibility and direct links, against a running demo (normally
// the packaged release binary):
// - the whole guided path with the keyboard only (Tab, Shift+Tab, Enter), with
//   visible focus at every stop and the focused heading never under the sticky
//   return bar; key presses are counted;
// - reduced motion: nothing animates or transitions;
// - direct links (URL fragments): each opens its screen, survives a reload,
//   and never reaches the server; malformed links open the start;
// - every button has an accessible name.
//
//   node accept_a11y.mjs URL OUT_DIR
//
// Needs playwright-core (no browser download) and CHROME=/path/to/chromium.
import { chromium } from "playwright-core";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const [url, out] = process.argv.slice(2);
if (!url || !out) {
  console.error("usage: node accept_a11y.mjs URL OUT_DIR");
  process.exit(2);
}
mkdirSync(out, { recursive: true });
const checks = [];
const metrics = {};
const check = (name, ok, detail = "") => checks.push({ name, ok: Boolean(ok), detail: String(detail).slice(0, 300) });
const browser = await chromium.launch({ executablePath: process.env.CHROME, args: ["--no-sandbox"] });
const base = url.replace(/\/?$/, "/");

async function open(locale, width, extra = {}) {
  const ctx = await browser.newContext({ viewport: { width, height: width > 500 ? 900 : 844 }, ...extra });
  await ctx.addInitScript((l) => {
    try { localStorage.setItem("flh.ui-locale.v1", l); } catch {}
  }, locale);
  const page = await ctx.newPage();
  const requests = [];
  page.on("request", (r) => requests.push(r.url()));
  return { ctx, page, requests };
}

// Focus is visible when the focused element draws an outline (the demo's
// :focus-visible rule) or a box shadow.
const focusVisible = (page) =>
  page.evaluate(() => {
    const el = document.activeElement;
    if (!el || el === document.body) return false;
    const s = getComputedStyle(el);
    return (s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== "none" || el.tagName === "H2";
  });
// The focused element is not covered by the sticky return bar.
const notUnderBar = (page) =>
  page.evaluate(() => {
    const el = document.activeElement;
    const bar = document.querySelector(".demo-return");
    if (!el || !bar) return true;
    const a = el.getBoundingClientRect();
    const b = bar.getBoundingClientRect();
    if (bar.contains(el)) return true;
    return a.top >= b.bottom - 1 || a.bottom <= b.top;
  });

async function keyTo(page, matcher, { back = false, max = 60 } = {}) {
  for (let i = 1; i <= max; i++) {
    await page.keyboard.press(back ? "Shift+Tab" : "Tab");
    if (await page.evaluate(matcher)) return i;
  }
  return -1;
}

// 1. Keyboard only, the whole guided path, in English (desktop) and 简体中文 (phone).
for (const [locale, width] of [["en", 1280], ["zh-CN", 390]]) {
  const tag = `${locale}-${width}`;
  const { ctx, page } = await open(locale, width);
  await page.goto(base);
  await page.waitForSelector(".demo-example-card");
  let keys = 0;
  const step = async (name, n) => {
    check(`${tag}: keyboard: ${name}`, n > 0, n);
    if (n > 0) keys += n;
    check(`${tag}: keyboard: ${name}: focus visible`, await focusVisible(page));
  };
  const enter = async (waitFor) => {
    await page.keyboard.press("Enter");
    keys += 1;
    await page.waitForSelector(waitFor);
  };
  const headingFocused = async (name) => {
    await page.waitForFunction(() => document.activeElement?.tagName === "H2", null, { timeout: 5000 }).catch(() => {});
    check(`${tag}: keyboard: ${name}: heading focused`, await page.evaluate(() => document.activeElement?.tagName === "H2"));
    check(`${tag}: keyboard: ${name}: focused heading not under the return bar`, await notUnderBar(page));
  };

  await step("reach the first example", await keyTo(page, () => document.activeElement?.id === "demo-example-y-en"));
  await enter(".demo-question");
  await headingFocused("example opened");
  await step("reach “Open the Concept”", await keyTo(page, () => document.activeElement?.matches("#demo-step-concepts ~ ul button.primary") ?? false));
  await enter(".library-concept h2");
  await headingFocused("Concept opened");
  await step("reach a source link", await keyTo(page, () => document.activeElement?.matches(".library-section.current .library-unit .link-button") ?? false));
  await enter("#src-entry");
  await headingFocused("evidence opened");
  await page.screenshot({ path: join(out, `${tag}-keyboard-evidence.png`), fullPage: false });
  await step("reach “Back to concept” (Shift+Tab)", await keyTo(page, () => /#\d+/.test(document.activeElement?.textContent ?? "") && document.activeElement?.closest(".demo-return") !== null, { back: true }));
  await enter(".library-concept h2");
  await headingFocused("back on the Concept");
  await step("reach “Back to the example” (Shift+Tab)", await keyTo(page, () => document.activeElement?.closest(".demo-return") !== null, { back: true }));
  await enter(".demo-question");
  await headingFocused("back on the example");
  await step("reach “Back to examples and search”", await keyTo(page, () => document.activeElement?.matches(".demo-example > .panel button.ghost") ?? false));
  await page.keyboard.press("Enter");
  keys += 1;
  await page.waitForSelector(".demo-example-card");
  check(`${tag}: keyboard: focus restored to the example card`, await page.evaluate(() => document.activeElement?.id === "demo-example-y-en"));
  metrics[`${tag}: keyboard key presses for the whole guided path`] = keys;
  await ctx.close();
}

// 2. Reduced motion: nothing animates or transitions on any guided screen.
{
  const { ctx, page } = await open("en", 390, { reducedMotion: "reduce" });
  const still = async (where) => {
    const moving = await page.evaluate(() => {
      const anims = document.getAnimations().length;
      const transitions = [...document.querySelectorAll("*")].filter((el) => {
        const d = getComputedStyle(el).transitionDuration.split(",").map(parseFloat);
        return d.some((x) => x > 0);
      }).length;
      return { anims, transitions, smooth: getComputedStyle(document.documentElement).scrollBehavior };
    });
    check(`reduced motion: ${where}: no animation or transition`, moving.anims === 0 && moving.transitions === 0 && moving.smooth !== "smooth", JSON.stringify(moving));
  };
  await page.goto(base);
  await page.waitForSelector(".demo-example-card");
  await still("start");
  await page.click("#demo-example-y-en");
  await page.waitForSelector(".demo-question");
  await still("example");
  await page.locator("#demo-step-concepts ~ ul button.primary").first().click();
  await page.waitForSelector(".library-concept h2");
  await still("Concept");
  await page.locator(".library-section.current .library-unit .link-button").first().click();
  await page.waitForSelector("#src-entry");
  await still("evidence");
  await ctx.close();
}

// 3. Direct links (fragments) in both languages.
for (const locale of ["en", "zh-CN"]) {
  const { ctx, page, requests } = await open(locale, 390);
  const go = async (hash, waitFor) => {
    await page.goto(`${base}${hash}`);
    await page.waitForSelector(waitFor, { timeout: 8000 }).catch(() => {});
  };
  await go("#example=y-en", ".demo-question");
  check(`${locale}: link to an example opens it`, (await page.locator(".demo-question").count()) === 1);
  await page.reload();
  await page.waitForSelector(".demo-question", { timeout: 8000 }).catch(() => {});
  check(`${locale}: an example survives a reload`, (await page.locator(".demo-question").count()) === 1);
  await page.locator("#demo-step-concepts ~ ul button.primary").first().click();
  await page.waitForSelector(".library-concept h2");
  const conceptHash = new URL(page.url()).hash;
  check(`${locale}: the address names the Concept and its example`, /example=y-en/.test(conceptHash) && /concept=\d+/.test(conceptHash), conceptHash);
  await page.locator(".library-section.current .library-unit .link-button").first().click();
  await page.waitForSelector("#src-entry");
  const sourceHash = new URL(page.url()).hash;
  check(`${locale}: the address names the evidence`, /concept=\d+&unit=\d+/.test(sourceHash), sourceHash);

  await go(sourceHash, "#src-entry");
  check(`${locale}: a link to evidence opens it`, (await page.locator("#src-entry").count()) === 1);
  check(`${locale}: evidence opened from a link keeps “back to the example”`, (await page.locator(".demo-return button").count()) === 2);
  await page.locator(".demo-return button").nth(1).click();
  await page.waitForSelector(".demo-question");
  check(`${locale}: …and it returns to the example`, (await page.locator(".demo-question").count()) === 1);

  await go("#concept=12", ".library-concept h2");
  check(`${locale}: link to a Concept opens it`, (await page.locator(".library-concept h2").count()) === 1);
  await page.locator(".demo-return button").first().click();
  await page.waitForSelector(".demo-example-card");
  check(`${locale}: a Concept opened from a link returns to the start`, new URL(page.url()).hash === "");

  for (const bad of ["#concept=abc", "#example=nope", "#concept=0", "#unit=5", "#concept=12&unit=-1"]) {
    await go(bad, ".demo-example-card");
    check(`${locale}: malformed link ${bad} opens the start`, (await page.locator(".demo-lead").count()) === 1);
  }
  await go("#concept=999999", ".banner.error");
  check(`${locale}: a link to a Concept that does not exist states the failed read`, (await page.locator(".banner.error").count()) === 1);
  check(`${locale}: …and still offers the way back`, (await page.locator(".demo-return button").count()) === 1);
  check(`${locale}: fragments never reach the server`, requests.every((u) => !u.includes("#") && !/[?&](example|concept|unit)=/.test(u)), requests.filter((u) => u.includes("#")).join(" "));
  await ctx.close();
}

// 4. Every button has an accessible name; the page has its landmarks.
{
  const { ctx, page } = await open("en", 1280);
  const names = async (where) => {
    const unnamed = await page.evaluate(() =>
      [...document.querySelectorAll("button")].filter((b) => !(b.getAttribute("aria-label") || b.textContent || "").trim()).length,
    );
    check(`accessible names: ${where}: every button named`, unnamed === 0, unnamed);
  };
  await page.goto(base);
  await page.waitForSelector(".demo-example-card");
  await names("start");
  check("landmarks: banner and main", (await page.locator("header").count()) === 1 && (await page.locator("main").count()) === 1);
  await page.click("#demo-example-en-train-de");
  await page.waitForSelector(".demo-question");
  await names("example");
  await page.locator("#demo-step-concepts ~ ul button.primary").first().click();
  await page.waitForSelector(".library-concept h2");
  await names("Concept");
  check("landmarks: return navigation on detail screens", (await page.locator("nav.demo-return").count()) === 1);
  await ctx.close();
}

await browser.close();
const failed = checks.filter((c) => !c.ok);
writeFileSync(join(out, "results.json"), JSON.stringify({ url, passed: checks.length - failed.length, failed: failed.length, metrics, checks }, null, 2));
for (const c of checks) console.log(`${c.ok ? "PASS" : "FAIL"} ${c.name}${c.ok || c.detail === "" ? "" : ` — ${c.detail}`}`);
for (const [k, v] of Object.entries(metrics)) console.log(`METRIC ${k}: ${v}`);
console.log(`${checks.length - failed.length}/${checks.length} checks passed`);
process.exit(failed.length ? 1 : 0);
