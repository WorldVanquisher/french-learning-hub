// v1.0 release rehearsal: real-browser smoke of the packaged workbench (RC).
//
//   PLAYWRIGHT_CORE_DIR=/tmp/flh-browser-tools node browser_smoke.mjs --url http://127.0.0.1:18995 --out /abs/evidence/dir \
//     [--chrome "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
//
// Target: an EMPTY RC instance started by `rehearse.sh serve` (fake provider,
// placeholder key). The script seeds four authored records over the API
// (scripts/validation/daily_v1_rc/cases.json): record A with an explicit NEW
// CONCEPT, and records B (same use of « en »), Y (« y ») and D (stale case)
// extracted but undecided. The browser then drives the journey:
// record stage → reviewable unit → AI suggestion of the existing Concept →
// explicit Confirm SAME → both source records → return to the original view,
// plus one stale refusal, English/简体中文 and focus on return. Every request is
// logged; browsing phases must send no write. Writes results.json and
// screenshots; exit 0 only if every check passed.
import { createRequire } from "node:module";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const arg = (name, def) => {
  const i = process.argv.indexOf(name);
  return i > 0 ? process.argv[i + 1] : def;
};
const url = arg("--url");
const out = arg("--out");
const chrome = arg("--chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome");
if (!url || !out || !process.env.PLAYWRIGHT_CORE_DIR) {
  console.error("usage: PLAYWRIGHT_CORE_DIR=... node browser_smoke.mjs --url URL --out DIR [--chrome PATH]");
  process.exit(2);
}
if (!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(url)) {
  console.error("refusing: --url must be a loopback http://127.0.0.1:PORT (the rehearsal instance)");
  process.exit(2);
}
const here = dirname(fileURLToPath(import.meta.url));
const cases = JSON.parse(readFileSync(join(here, "..", "daily_v1_rc", "cases.json"), "utf8"));
const { chromium } = createRequire(join(process.env.PLAYWRIGHT_CORE_DIR, "package.json"))("playwright-core");
mkdirSync(out, { recursive: true });

const checks = [];
const requests = [];
let phase = "seed";
const check = (name, ok, detail = "") => {
  checks.push({ phase, name, status: ok ? "PASS" : "FAIL", detail: String(detail).slice(0, 300) });
  console.log(`${ok ? "PASS" : "FAIL"} [${phase}] ${name}${detail ? ` — ${String(detail).slice(0, 160)}` : ""}`);
};

// ---- API helpers (seeding and authority checks; never used for the journey itself)
async function api(method, path, body) {
  const r = await fetch(url + path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await r.text();
  return { status: r.status, body: text ? JSON.parse(text) : null };
}
const membership = async (unitId) => (await api("GET", `/knowledge-units/${unitId}/concept-membership`)).body.current_membership;

async function prepare(key) {
  const c = cases.records[key];
  const saved = await api("POST", "/captures", {
    schema_version: "learning_capture_v1", capture_id: `smoke-${key}-${Date.now()}`, source: "manual",
    original_input: c.original_input, original_context: c.original_context,
  });
  const entry = saved.body.entry_id;
  const analysis = (await api("POST", `/entries/${entry}/analysis`)).body;
  await api("POST", `/analyses/${analysis.id}/feedback`, { status: "accepted", reviewed_explanation_languages: ["en", "zh"] });
  const ex = await api("POST", `/entries/${entry}/extractions`);
  return { entry, unit: ex.body.units[0].id, input: c.original_input };
}

const browser = await chromium.launch({ executablePath: chrome, headless: true });
const context = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
const page = await context.newPage();
const consoleErrors = [];
page.on("console", (m) => m.type() === "error" && consoleErrors.push({ phase, text: m.text() }));
page.on("pageerror", (e) => consoleErrors.push({ phase, text: String(e) }));
page.on("request", (r) => requests.push({ phase, method: r.method(), url: r.url().replace(url, "") }));
const shot = async (name) => page.screenshot({ path: join(out, `${String(checks.length).padStart(2, "0")}-${name}.png`), fullPage: true });
const writesIn = (p) => requests.filter((r) => r.phase === p && r.method !== "GET" && r.method !== "HEAD");
const browsing = async (name, fn) => {
  phase = name;
  await fn();
  const w = writesIn(name);
  check("sends no write request", w.length === 0, w.map((r) => `${r.method} ${r.url}`).join(", "));
};
// Hidden workbench views stay mounted, so a text locator can also match hidden
// copies: wait until at least one match is actually rendered.
const anyVisible = async (loc, timeout = 10000) => {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await loc.evaluateAll((els) => els.some((e) => e.getClientRects().length > 0))) return true;
    await page.waitForTimeout(200);
  }
  return false;
};
const visibleText = (text) => anyVisible(page.getByText(text, { exact: false }));

try {
  // ---- Seed an empty instance.
  const empty = (await api("GET", "/entries?limit=1")).body.entries.length === 0;
  check("target instance is empty", empty);
  if (!empty) throw new Error("refusing to seed a non-empty instance");
  check("suggestions enabled (fake provider)", (await api("GET", "/concept-suggestion-runs")).body.enabled === true);
  const A = await prepare("en_first");
  const created = await api("POST", "/concepts", { identity: cases.en_concept_identity, seed_unit_id: A.unit, link_seed_as_same: true });
  const C = created.body.concept.id;
  const Bq = await prepare("en_second");
  const Y = await prepare("y_related");
  const D = await prepare("en_stale");
  check("seeded A (NEW CONCEPT), B, Y, D", created.status === 201, `concept #${C}; records ${A.entry}, ${Bq.entry}, ${Y.entry}, ${D.entry}`);

  // ---- Record stage → reviewable unit (read-only).
  await page.goto(url, { waitUntil: "networkidle" });
  await browsing("record-stage", async () => {
    await page.getByRole("button", { name: "Learning Records", exact: true }).click();
    await page.getByRole("button", { name: `Open record #${Bq.entry}`, exact: true }).click();
    const stage = page.getByRole("region", { name: `Stage of record #${Bq.entry}` });
    await stage.waitFor();
    check("stage shows the unit awaiting a decision", await anyVisible(stage.getByText("1 of 1 units await a decision in Concept Review.")));
    check("stage offers the review link", await stage.getByRole("button", { name: `Open unit #${Bq.unit} in Concept Review` }).isVisible());
    check("analysis vs extraction wording", (await visibleText("An analysis describes and classifies your question")) && (await visibleText("Extraction produces the knowledge statements")));
    await shot("record-stage");
  });

  // ---- Language switch on the record (read-only).
  await browsing("language", async () => {
    await page.getByLabel("Language").selectOption("zh-CN");
    check("Chinese stage title", await page.getByRole("heading", { name: "这条记录进行到哪一步" }).isVisible());
    check("learner text not translated", await anyVisible(page.getByText(Bq.input, { exact: true })));
    await shot("record-zh");
    await page.getByLabel("语言").selectOption("en");
    check("back to English", await page.getByRole("heading", { name: "Where this record stands" }).isVisible());
  });

  // ---- Suggestions: select and generate (exactly one write: the generation).
  phase = "generate";
  await page.getByRole("button", { name: "Concept Review", exact: true }).click();
  await page.getByRole("button", { name: "AI suggestions", exact: true }).click();
  await page.getByRole("checkbox", { name: new RegExp(`unit #${Bq.unit} · record`) }).check();
  await page.getByRole("checkbox", { name: new RegExp(`unit #${D.unit} · record`) }).check();
  await page.getByRole("button", { name: "Generate suggestions" }).click();
  await page.getByRole("heading", { name: /^Suggestion run #\d+$/ }).waitFor({ timeout: 30000 });
  const gen = writesIn("generate");
  check("generation is the only write", gen.length === 1 && gen[0].method === "POST" && gen[0].url === "/concept-suggestion-runs", gen.map((r) => `${r.method} ${r.url}`).join(", "));
  check("run states it is advisory", await visibleText("These suggestions are advisory. Generating them recorded nothing"));
  check("generation changed no membership", (await membership(Bq.unit)) === null && (await membership(D.unit)) === null);
  await shot("suggestions");

  // ---- Opening a suggestion's record and coming back is read-only.
  await browsing("open-suggestion", async () => {
    const itemB = page.getByRole("article", { name: `Suggestion for unit ${Bq.unit}` });
    check("B is suggested for the existing Concept", await itemB.getByRole("button", { name: `Confirm SAME to Concept #${C}` }).isVisible());
    await itemB.getByRole("button", { name: `Open record #${Bq.entry}`, exact: true }).click();
    await page.getByRole("heading", { name: `Record #${Bq.entry}` }).waitFor();
    await page.getByRole("button", { name: "← Back to AI suggestions" }).click();
    check("run still open after return", await page.getByRole("heading", { name: /^Suggestion run #\d+$/ }).isVisible());
  });

  // ---- Stale confirmation refused (the record is re-extracted elsewhere, over the API).
  phase = "stale";
  const reex = await api("POST", `/entries/${D.entry}/extractions`);
  check("D re-extracted outside the browser (v2)", reex.status === 201 && reex.body.version === 2);
  const itemD = page.getByRole("article", { name: `Suggestion for unit ${D.unit}` });
  await itemD.getByRole("button", { name: `Confirm SAME to Concept #${C}` }).click();
  check("stale confirmation refused", await anyVisible(itemD.getByText("Not recorded: the state changed since the suggestion was made.")));
  check("stale refusal changed no membership", (await membership(D.unit)) === null && (await membership(reex.body.units[0].id)) === null);
  await shot("stale");

  // ---- Explicit SAME.
  phase = "confirm";
  const itemB = page.getByRole("article", { name: `Suggestion for unit ${Bq.unit}` });
  await itemB.getByRole("button", { name: `Confirm SAME to Concept #${C}` }).click();
  check("confirmation recorded", await anyVisible(itemB.getByText(/^Recorded as human SAME event #\d+\.$/)));
  const confirmWrites = writesIn("confirm");
  check("exactly one confirm write", confirmWrites.length === 1 && /^\/concept-suggestion-items\/\d+\/confirm$/.test(confirmWrites[0].url), confirmWrites.map((r) => r.url).join(", "));
  check("CURRENT SAME of B is the existing Concept", (await membership(Bq.unit))?.concept_id === C);
  check("Y unit untouched", (await membership(Y.unit)) === null);

  // ---- Both distinct sources, then back (read-only).
  await browsing("sources", async () => {
    await itemB.getByRole("button", { name: `Open Concept #${C} in Knowledge Library` }).click();
    await page.getByRole("heading", { name: /^en\b/ }).waitFor();
    for (const r of [A, Bq]) {
      await page.getByRole("button", { name: `View source record #${r.entry}`, exact: true }).first().click();
      check(`source of record #${r.entry} shows its own question`, await anyVisible(page.getByText(r.input, { exact: true })));
      await page.getByRole("button", { name: `← Back to concept #${C}` }).click();
    }
    await shot("concept");
    await page.getByRole("button", { name: `View source record #${Bq.entry}`, exact: true }).first().click();
    await page.getByRole("button", { name: `Open record #${Bq.entry} in Learning Records` }).click();
    const stage = page.getByRole("region", { name: `Stage of record #${Bq.entry}` });
    check("record stage now complete", await anyVisible(stage.getByText(/^Nothing is left to decide for this record/)));
    await page.getByRole("button", { name: "← Back to Knowledge Library" }).click();
    check("library source screen restored", await page.getByRole("heading", { name: `Where unit #${Bq.unit} came from: learning record #${Bq.entry}` }).isVisible());
  });

  // ---- Focus on return to the record (read-only).
  await browsing("focus", async () => {
    await page.getByRole("button", { name: "Learning Records", exact: true }).click();
    await page.getByRole("button", { name: `Open Concept #${C} in Knowledge Library` }).first().click();
    await page.getByRole("button", { name: `← Back to record #${Bq.entry}` }).click();
    await page.waitForTimeout(500);
    const active = await page.evaluate(() => document.activeElement?.id ?? "");
    check("focus returns to the filed unit", active === `extracted-unit-${Bq.unit}`, active);
    await shot("return-focus");
  });

  phase = "final";
  check("no console or page errors", consoleErrors.length === 0, JSON.stringify(consoleErrors).slice(0, 300));
} catch (e) {
  check("unexpected error", false, e?.stack ?? String(e));
  await shot("error").catch(() => {});
} finally {
  writeFileSync(join(out, "results.json"), JSON.stringify({ chrome: browser.version(), url, checks, requests, consoleErrors }, null, 2));
  await browser.close();
}
const failed = checks.filter((c) => c.status !== "PASS").length;
console.log(`${checks.length - failed} passed, ${failed} failed; evidence in ${out}`);
process.exit(failed ? 1 : 0);
