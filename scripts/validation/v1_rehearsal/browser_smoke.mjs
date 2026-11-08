// v1.0 release rehearsal: real-browser smoke of the packaged workbench (RC).
//
//   PLAYWRIGHT_CORE_DIR=DIR node browser_smoke.mjs --url http://127.0.0.1:18995 --out /abs/evidence/dir \
//     --ownership WORK/evidence/ownership.json [--chrome PATH] [--inject-failure PHASE]
//
// Usually started by browser_check.sh. Target: an EMPTY RC instance started by
// `rehearse.sh serve` (fake provider, placeholder key) whose ownership
// `rehearse.sh verify` established: ownership.json with verdict "owned", this
// URL, a rehearsal project, at most 30 minutes old. Without it nothing is seeded.
//
// The script seeds four authored records over the API
// (scripts/validation/daily_v1_rc/cases.json): record A with an explicit NEW
// CONCEPT, and records B (same use of « en »), Y (« y ») and D (stale case)
// extracted but undecided. The browser then drives the journey:
// record stage → reviewable unit → AI suggestion of the existing Concept →
// explicit Confirm SAME → both source records → return to the original view,
// plus one stale refusal, English/简体中文 and focus on return. Every request is
// logged; browsing phases must send no write. Writes results.json and
// screenshots. Exit 0 only if every check passed and every phase ran; 1 on a
// failed check; 2 on a refusal (usage, ownership); 3 if no browser started.
//
// Browser: --chrome, else $CHROME, else google-chrome, google-chrome-stable,
// chromium, chromium-browser on PATH, else the macOS Google Chrome. Headless,
// with a fresh temporary profile that Playwright deletes on close.
// --inject-failure PHASE records a deliberately failing check when PHASE starts
// (controlled-failure proof); the run then stops as on any unexpected error.
import { createRequire } from "node:module";
import { accessSync, constants, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { delimiter, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const PHASES = ["seed", "record-stage", "language", "generate", "open-suggestion", "stale", "confirm", "sources", "focus", "final"];
const arg = (name, def) => {
  const i = process.argv.indexOf(name);
  return i > 0 ? process.argv[i + 1] : def;
};
const url = arg("--url");
const out = arg("--out");
const ownershipFile = arg("--ownership");
const inject = arg("--inject-failure", "");
const refuse = (why, code = 2) => {
  console.error(`refused: ${why}`);
  if (out) {
    mkdirSync(out, { recursive: true });
    const status = code === 3 ? "browser-missing" : "refused";
    writeFileSync(join(out, "results.json"), JSON.stringify({ status, reason: why, url, checks: [] }, null, 2));
  }
  process.exit(code);
};
if (!url || !out || !ownershipFile || !process.env.PLAYWRIGHT_CORE_DIR) {
  console.error("usage: PLAYWRIGHT_CORE_DIR=... node browser_smoke.mjs --url URL --out DIR --ownership FILE [--chrome PATH] [--inject-failure PHASE]");
  process.exit(2);
}
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(url)) refuse("--url must be http://127.0.0.1:PORT (the rehearsal instance)");
if (inject && !PHASES.includes(inject)) refuse(`--inject-failure must be one of ${PHASES.join(", ")}`);

// Ownership comes from `rehearse.sh verify` (live Docker state), not from an
// empty database and a loopback URL.
let ownership;
try {
  ownership = JSON.parse(readFileSync(ownershipFile, "utf8"));
} catch (e) {
  refuse(`cannot read the ownership file ${ownershipFile}: ${e.message}`);
}
const ageSeconds = Math.floor(Date.now() / 1000) - Number(ownership.verified_at);
if (ownership.verdict !== "owned") refuse(`ownership verdict is ${ownership.verdict}, not owned`);
if (ownership.url !== url) refuse(`ownership was established for ${ownership.url}, not ${url}`);
if (!/^flh-rehearsal-\d{14}$/.test(ownership.project ?? "") || ownership.project === "french-learning-hub") {
  refuse(`not a rehearsal project: ${ownership.project}`);
}
if (!(ageSeconds >= 0 && ageSeconds <= 1800)) refuse(`ownership is ${ageSeconds}s old; run rehearse.sh verify again`);

const executable = (p) => {
  try {
    accessSync(p, constants.X_OK);
    return true;
  } catch {
    return false;
  }
};
function findChrome() {
  const explicit = arg("--chrome") ?? process.env.CHROME;
  if (explicit) return executable(explicit) ? explicit : null;
  const candidates = [];
  for (const dir of (process.env.PATH ?? "").split(delimiter).filter(Boolean)) {
    for (const name of ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]) candidates.push(join(dir, name));
  }
  candidates.push("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome");
  return candidates.find(executable) ?? null;
}
const chrome = findChrome();
if (!chrome) {
  refuse("no executable Chrome/Chromium (--chrome, $CHROME, google-chrome, google-chrome-stable, chromium, chromium-browser, macOS Google Chrome)", 3);
}
const here = dirname(fileURLToPath(import.meta.url));
const cases = JSON.parse(readFileSync(join(here, "..", "daily_v1_rc", "cases.json"), "utf8"));
const { chromium } = createRequire(join(process.env.PLAYWRIGHT_CORE_DIR, "package.json"))("playwright-core");
mkdirSync(out, { recursive: true });

const checks = [];
const requests = [];
let phase = "seed";
const started = new Set(["seed"]);
const check = (name, ok, detail = "") => {
  checks.push({ phase, name, status: ok ? "PASS" : "FAIL", detail: String(detail).slice(0, 300) });
  console.log(`${ok ? "PASS" : "FAIL"} [${phase}] ${name}${detail ? ` — ${String(detail).slice(0, 160)}` : ""}`);
};
const enter = (p) => {
  phase = p;
  started.add(p);
  if (inject === p) {
    check(`injected failure at the start of phase ${p} (--inject-failure)`, false, "controlled failure");
    throw new Error(`injected failure in phase ${p}`);
  }
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

let browser;
try {
  browser = await chromium.launch({ executablePath: chrome, headless: true });
} catch (e) {
  refuse(`browser ${chrome} did not start: ${String(e?.message ?? e).split("\n")[0]}`, 3);
}
const context = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
const page = await context.newPage();
const consoleErrors = [];
page.on("console", (m) => m.type() === "error" && consoleErrors.push({ phase, text: m.text() }));
page.on("pageerror", (e) => consoleErrors.push({ phase, text: String(e) }));
// The packaged workbench calls the API under /api; record the route without it.
page.on("request", (r) => requests.push({ phase, method: r.method(), url: r.url().replace(url, "").replace(/^\/api(?=\/)/, "") }));
const shot = async (name) => page.screenshot({ path: join(out, `${String(checks.length).padStart(2, "0")}-${name}.png`), fullPage: true });
const writesIn = (p) => requests.filter((r) => r.phase === p && r.method !== "GET" && r.method !== "HEAD");
const browsing = async (name, fn) => {
  enter(name);
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
  // ---- Seed an empty instance (ownership was checked above).
  if (inject === "seed") enter("seed");
  check(`ownership verified by rehearse.sh verify (${ownership.project}, ${ageSeconds}s ago)`, true);
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
    // The <label> wraps the <select>, so its accessible name also contains the
    // option names; pick the visible UI-locale control by its zh-CN option.
    const localeSelect = () => page.locator("select:visible").filter({ has: page.locator('option[value="zh-CN"]') }).first();
    check("language control labelled Language", (await localeSelect().locator("xpath=ancestor::label").innerText()).startsWith("Language"));
    await localeSelect().selectOption("zh-CN");
    check("Chinese stage title", await page.getByRole("heading", { name: "这条记录进行到哪一步" }).isVisible());
    check("learner text not translated", await anyVisible(page.getByText(Bq.input, { exact: true })));
    await shot("record-zh");
    check("language control labelled 语言", (await localeSelect().locator("xpath=ancestor::label").innerText()).startsWith("语言"));
    await localeSelect().selectOption("en");
    check("back to English", await page.getByRole("heading", { name: "Where this record stands" }).isVisible());
  });

  // ---- Suggestions: select and generate (exactly one write: the generation).
  enter("generate");
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
    // Returning re-reads the open run and the queue asynchronously; wait for
    // both, or a later re-extraction could land mid-click.
    const reread = (re) => page.waitForResponse((r) => r.request().method() === "GET" && re.test(new URL(r.url()).pathname), { timeout: 15000 });
    const rereads = Promise.all([reread(/\/concept-suggestion-runs\/\d+$/), reread(/\/reviewable-units$/)]);
    await page.getByRole("button", { name: "← Back to AI suggestions" }).click();
    await rereads;
    check("run still open after return", await page.getByRole("heading", { name: /^Suggestion run #\d+$/ }).isVisible());
  });

  // ---- Stale confirmation refused (the record is re-extracted elsewhere, over the API).
  enter("stale");
  const reex = await api("POST", `/entries/${D.entry}/extractions`);
  check("D re-extracted outside the browser (v2)", reex.status === 201 && reex.body.version === 2);
  const itemD = page.getByRole("article", { name: `Suggestion for unit ${D.unit}` });
  await itemD.getByRole("button", { name: `Confirm SAME to Concept #${C}` }).click();
  check("stale confirmation refused", await anyVisible(itemD.getByText("Not recorded: the state changed since the suggestion was made.")));
  check("stale refusal changed no membership", (await membership(D.unit)) === null && (await membership(reex.body.units[0].id)) === null);
  await shot("stale");

  // ---- Explicit SAME.
  enter("confirm");
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
    // The text follows a bold "Next:" in the same element, so it is not anchored.
    const complete = await anyVisible(stage.getByText(/Nothing is left to decide for this record/));
    check("record stage now complete", complete, complete ? "" : (await stage.innerText().catch(() => "")).slice(0, 300));
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

  enter("final");
  // The one expected entry: Chrome logs the refused stale confirmation (409).
  const expected = (e) => e.phase === "stale" && /status of 409 \(Conflict\)/.test(e.text);
  const unexpected = consoleErrors.filter((e) => !expected(e));
  check("stale refusal logged by the browser as one 409", consoleErrors.filter(expected).length === 1);
  check("no other console or page errors", unexpected.length === 0, JSON.stringify(unexpected).slice(0, 300));
} catch (e) {
  if (!checks.some((c) => c.status === "FAIL" && /injected failure/.test(c.name))) check("unexpected error", false, e?.stack ?? String(e));
  await shot("error").catch(() => {});
} finally {
  const failedChecks = checks.filter((c) => c.status !== "PASS").length;
  const phasesRun = PHASES.filter((p) => started.has(p));
  writeFileSync(join(out, "results.json"), JSON.stringify({
    status: failedChecks === 0 && phasesRun.length === PHASES.length ? "passed" : "failed",
    chrome: browser.version(), chromePath: chrome, url, project: ownership.project, injectedFailure: inject || null,
    phases: PHASES, phasesRun, passed: checks.length - failedChecks, failed: failedChecks,
    checks, requests, consoleErrors,
  }, null, 2));
  await browser.close();
}
const failed = checks.filter((c) => c.status !== "PASS").length;
const notRun = PHASES.filter((p) => !started.has(p));
console.log(`${checks.length - failed} passed, ${failed} failed${notRun.length ? `; phases not run: ${notRun.join(", ")}` : ""}; evidence in ${out}`);
process.exit(failed || notRun.length ? 1 : 0);
