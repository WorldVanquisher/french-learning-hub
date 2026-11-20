// Interactions (and wall-clock milliseconds, scripted) from Review Today to the first graded practice answer, by
// keyboard: Tab presses to reach each control, activations (Enter), typed
// answers and the submit. Runs on any build that has the practice prototype
// (the increment-4 tree has only the concept-first path; the current tree has
// both). Writes OUT/measure.json. COMBOS as in walkthrough.mjs.
import { chromium } from "playwright";
import fs from "node:fs";

const OUT = process.env.OUT || "/out";
const combos = JSON.parse(process.env.COMBOS);
const cat = {};
for (const m of fs.readFileSync("/i18n/en.ts", "utf8").matchAll(/^\s*("(?:[^"\\\n]|\\.)+"):\s*("(?:[^"\\\n]|\\.)*")/gm)) cat[JSON.parse(m[1])] = JSON.parse(m[2]);
const out = [];
const browser = await chromium.launch();
for (const c of combos) {
  for (const path of ["concept-first", "today-first"]) {
    const ctx = await browser.newContext({ ...(c.phone ? { viewport: { width: 320, height: 640 }, hasTouch: true, isMobile: true } : { viewport: { width: 1280, height: 900 } }), reducedMotion: "reduce" });
    const page = await ctx.newPage();
    page.setDefaultTimeout(10000);
    const n = { tabs: 0, activations: 0, typed: 0, submits: 0 };
    const focused = (loc) => loc.evaluate((el) => el === document.activeElement);
    const tabTo = async (loc) => {
      await loc.first().waitFor();
      for (let i = 0; i < 400; i++) {
        if (await focused(loc.first())) return;
        await page.keyboard.press("Tab");
        n.tabs++;
      }
      throw new Error("unreachable");
    };
    const activate = async (loc) => {
      await tabTo(loc);
      await page.keyboard.press("Enter");
      n.activations++;
    };
    try {
      const t0 = Date.now();
      await page.goto(c.url + "/#/today");
      await page.locator("h2").first().waitFor();
      await activate(page.getByRole("button", { name: cat["feedPractice.panel.open"], exact: true }));
      await page.getByRole("list", { name: cat["feedPractice.panel.list"], exact: true }).waitFor();
      if (path === "today-first") {
        const start = page.locator(".feed-today [data-practice]").first().getByRole("button", { name: cat["feedPractice.today.start"], exact: true });
        if ((await page.locator(".feed-today").count()) === 0) {
          out.push({ combo: c.tag, path, available: false });
          await ctx.close();
          continue;
        }
        await activate(start);
        await page.waitForTimeout(150);
      } else {
        await activate(page.getByRole("button", { name: cat["feedPractice.panel.openConcept"], exact: true }).first());
        await page.waitForTimeout(150);
        await tabTo(page.locator("textarea").first());
      }
      await page.keyboard.type("Oui, j'en reviens.");
      n.typed++;
      await page.keyboard.press("Control+Enter");
      n.submits++;
      await page.locator("[data-outcome]").first().waitFor();
      out.push({ combo: c.tag, path, available: true, ...n, total: n.tabs + n.activations + n.typed + n.submits, screens: 2, ms: Date.now() - t0 });
    } catch (e) {
      out.push({ combo: c.tag, path, available: false, error: String(e).slice(0, 200) });
    }
    await ctx.close();
  }
}
await browser.close();
fs.writeFileSync(`${OUT}/measure.json`, JSON.stringify(out, null, 1));
console.log(JSON.stringify(out));
