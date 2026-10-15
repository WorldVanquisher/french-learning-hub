// FLH-076 real-browser acceptance of the read-only public demo.
//
//   PLAYWRIGHT_CORE_DIR=/tmp/flh076-browser-tools node accept.mjs --url http://127.0.0.1:PORT --out /abs/evidence/dir \
//     [--chrome "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"] [--expect-vectors mechanical|model]
//
// Drives an installed Chrome (headless, fresh temporary profile) through the
// demo build served by a running demo server. Records every console message,
// page error and network request, takes screenshots, and writes results.json.
// Exit 0 only if every check passed. It only reads: GET requests to the demo.
import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const arg = (name, def) => {
  const i = process.argv.indexOf(name);
  return i > 0 ? process.argv[i + 1] : def;
};
const url = arg("--url");
const out = arg("--out");
const chrome = arg("--chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome");
const expectVectors = arg("--expect-vectors", "mechanical");
if (!url || !out || !process.env.PLAYWRIGHT_CORE_DIR) {
  console.error("usage: PLAYWRIGHT_CORE_DIR=... node accept.mjs --url URL --out DIR");
  process.exit(2);
}
const { chromium } = createRequire(join(process.env.PLAYWRIGHT_CORE_DIR, "package.json"))("playwright-core");
mkdirSync(out, { recursive: true });

const checks = [];
const console_ = [];
const requests = [];
const check = (name, ok, detail = "") => {
  checks.push({ name, status: ok ? "PASS" : "FAIL", detail: String(detail).slice(0, 300) });
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? ` — ${String(detail).slice(0, 120)}` : ""}`);
};
let phase = "load";

const browser = await chromium.launch({ executablePath: chrome, headless: true });
const chromeVersion = browser.version();
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await context.newPage();
page.on("console", (m) => console_.push({ phase, type: m.type(), text: m.text() }));
page.on("pageerror", (e) => console_.push({ phase, type: "pageerror", text: String(e) }));
page.on("request", (r) => requests.push({ phase, method: r.method(), url: r.url() }));
page.on("requestfailed", (r) => console_.push({ phase, type: "requestfailed", text: `${r.method()} ${r.url()} ${r.failure()?.errorText}` }));
const shot = async (name) => page.screenshot({ path: join(out, `${String(checks.length).padStart(2, "0")}-${name}.png`), fullPage: true });
const search = async () => page.getByRole("button", { name: "Search", exact: true }).click();

try {
  await page.goto(url, { waitUntil: "networkidle" });
  const about = page.getByRole("region", { name: "About this demo" });
  await about.waitFor();
  check("demo title", (await page.title()) === "Knowledge Library — read-only public demo", await page.title());
  check("html lang en", (await page.getAttribute("html", "lang")) === "en");
  const aboutText = await about.innerText();
  check("synthetic + read-only + no-AI notice", /synthetic/.test(aboutText) && /read-only/.test(aboutText) && /calls no AI service/.test(aboutText));
  check("free-text semantic disabled notice", /Free-text semantic search is disabled/.test(aboutText));
  const banner = await page.getByText("Development build: the vectors are mechanical test fixtures").count();
  if (expectVectors === "mechanical") check("mechanical-vector banner shown", banner === 1);
  else check("no mechanical banner for a model artifact", banner === 0);
  check("artifact identity line", /Artifact [0-9a-f]{16} · vectors: /.test(aboutText), aboutText.match(/Artifact .*/)?.[0]);
  for (const name of ["Learning Records", "Concept Review", "Annotation Inspector", "Experiment Dashboard"]) {
    check(`no "${name}" control`, (await page.getByRole("button", { name }).count()) === 0);
  }
  check("no editing/import/review controls", (await page.getByRole("button", { name: /import|analy[sz]e|extract|accept|reject|retire|save|delete|edit/i }).count()) === 0);
  check("no text inputs other than the query", (await page.locator("textarea, input:not([type=search]):not([type=radio])").count()) === 0);
  await page.getByText(/^\d+ concepts\.$/).waitFor();
  await shot("browse");

  phase = "keyword";
  await page.getByLabel("Search learned material").fill("subj");
  await search();
  const kwResults = page.getByRole("region", { name: "Library results" });
  await kwResults.getByText(/matching “subj”/).waitFor();
  const kwItems = await kwResults.getByRole("listitem").allInnerTexts();
  check("keyword free text returns matches with evidence", kwItems.length >= 2 && kwItems.every((t) => /Found in /.test(t)), kwItems.length);
  check("keyword identity match evidence", kwItems.some((t) => /subjunctive/.test(t) && /Found in identity details, title/.test(t)));
  check("keyword unit-wording match labelled as such", kwItems.some((t) => /not in the concept's title/.test(t)));
  await shot("keyword");

  phase = "keyword-empty";
  await page.getByLabel("Search learned material").fill("zzzzzz");
  await search();
  await page.getByText("No concepts match “zzzzzz”.").waitFor();
  check("keyword empty result message", true);

  phase = "keyword-server-error";
  await page.getByLabel("Search learned material").fill("a".repeat(201));
  await search();
  const alert = page.getByRole("alert");
  await alert.waitFor();
  check("server 400 shown as an explicit error with retry", /Could not search the knowledge library: \(400\)/.test(await alert.innerText()) &&
    (await alert.getByRole("button", { name: "Try again" }).count()) === 1, await alert.innerText());
  await shot("keyword-error");

  phase = "semantic";
  await page.getByRole("radio", { name: "Semantic" }).check();
  check("free-text box hidden for semantic", (await page.getByLabel("Search learned material").count()) === 0);
  const preset = page.getByLabel("Example query");
  const options = await preset.locator("option").allInnerTexts();
  check("8 presets shown with exact text", options.length === 8 && options.every((o) => /: “.+”$/.test(o)), options.join(" | "));
  check("preset restriction note", /limited to a fixed list of example queries/.test(await page.getByRole("note").innerText()));
  check("demo semantic description (no embedding service claim)", (await page.getByText(/It needs that index and an embedding service/).count()) === 0 &&
    (await page.getByText(/using vectors stored with this demo/).count()) === 1);
  await preset.selectOption("no-longer");
  await search();
  const sem = page.getByRole("region", { name: "Semantic results" });
  await sem.getByText(/by similarity to “no longer doing something”/).waitFor();
  const semItems = await sem.getByRole("listitem").allInnerTexts();
  check("semantic preset results with similarity evidence", semItems.length > 0 && semItems.every((t) => /Similarity [-0-9.]+ \(cosine; not a probability/.test(t)), semItems.length);
  await shot("semantic");

  phase = "hybrid";
  await page.getByRole("radio", { name: "Hybrid" }).check();
  await page.getByLabel("Example query").selectOption("subjunctive");
  await page.getByLabel("Concept status").selectOption("active");
  await search();
  const hyb = page.getByRole("region", { name: "Hybrid results" });
  await hyb.getByText(/merged concepts? for “subjunctive” with status active/).waitFor();
  const hybText = await hyb.innerText();
  check("hybrid policy summary", /Policy concept_hybrid_rrf_v1: reciprocal rank fusion with k = 60/.test(hybText));
  const hybItems = await hyb.getByRole("listitem").allInnerTexts();
  check("hybrid per-result evidence", hybItems.length > 0 && hybItems.every((t) => /(Keyword #\d+ \([^)]*\)|Not found by keyword) · (Semantic #\d+ \(similarity -?\d\.\d\d\)|Not among the semantic candidates) · Combined score \d\.\d{4}/.test(t)), hybItems[0]);
  check("hybrid shows keyword-and-semantic evidence", hybItems.some((t) => /Keyword #\d+ .*Semantic #\d+/.test(t)));
  await shot("hybrid");

  phase = "detail";
  const firstTitle = await hyb.getByRole("listitem").first().getByRole("button").innerText();
  await hyb.getByRole("listitem").first().getByRole("button").click();
  const conceptRegion = page.getByRole("region", { name: "Concept", exact: true }).first();
  await page.getByRole("heading", { level: 2, name: new RegExp(firstTitle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")) }).waitFor();
  check("concept detail opens", true, firstTitle);
  const sourceButton = page.getByRole("button", { name: /View source record #\d+/ }).first();
  await sourceButton.waitFor();
  check("concept lists units with a source link", (await page.getByText(/Currently supporting this concept \(\d+\)/).count()) === 1);
  await shot("concept");
  await sourceButton.click();
  await page.getByRole("heading", { level: 3, name: /Original learning record #\d+/ }).waitFor();
  const sourceText = await page.locator("main").innerText();
  check("source shows the original question and interpretation", /Original learning record #\d+/.test(sourceText) && /\?/.test(sourceText) && /Interpretation this extraction used/.test(sourceText));
  await shot("source");
  await page.getByRole("button", { name: /← Back to concept #\d+/ }).click();
  await page.getByRole("heading", { level: 2, name: new RegExp(firstTitle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")) }).waitFor();
  check("back to concept", await conceptRegion.isVisible());
  await page.getByRole("button", { name: /← Back to hybrid results for “subjunctive”/ }).click();
  await hyb.waitFor();
  const focused = await page.evaluate(() => document.activeElement?.textContent ?? "");
  check("back to results restores focus on the opened result", focused === firstTitle, focused);

  phase = "hybrid-injected-failure";
  // Client-side fault injection: the server is fine; this checks the page's error state only.
  await page.route("**/knowledge-library/demo/hybrid-search**", (route) =>
    route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: "injected by the browser test" }) }));
  await page.getByLabel("Example query").selectOption("although");
  await search();
  const herr = page.getByRole("alert");
  await herr.waitFor();
  check("hybrid failure shown explicitly, no keyword substitute", /Could not run the hybrid search: \(503\) injected by the browser test/.test(await herr.innerText()) &&
    (await page.getByRole("region", { name: "Library results" }).count()) === 0, await herr.innerText());
  await page.unroute("**/knowledge-library/demo/hybrid-search**");
  await shot("hybrid-error");
} catch (e) {
  check("browser run completed", false, e.stack ?? e);
  await shot("crash").catch(() => {});
} finally {
  await browser.close();
}

const origin = new URL(url).origin;
const allowed = /^\/(|assets\/.+|api\/knowledge-library\/(concepts(\/\d+)?|units\/\d+\/source|demo(\/(semantic|hybrid)-search)?))$/;
const offOrigin = requests.filter((r) => !r.url.startsWith(origin));
const nonGet = requests.filter((r) => r.method !== "GET");
const notAllowed = requests.filter((r) => r.url.startsWith(origin) && !allowed.test(new URL(r.url).pathname));
const freeText = requests.filter((r) => /\/knowledge-library\/(semantic|hybrid)-search/.test(r.url));
check("every request is same-origin", offOrigin.length === 0, offOrigin.map((r) => r.url).join(" "));
check("every request is GET", nonGet.length === 0, nonGet.map((r) => r.method + " " + r.url).join(" "));
check("every request is on the demo allowlist", notAllowed.length === 0, notAllowed.map((r) => r.url).join(" "));
check("no free-text semantic/hybrid request", freeText.length === 0);
check("preset requests use preset ids", requests.some((r) => /demo\/semantic-search\?preset=no-longer$/.test(r.url)) &&
  requests.some((r) => /demo\/hybrid-search\?preset=subjunctive&state=active$/.test(r.url)));
const errors = console_.filter((m) => m.type === "error" || m.type === "pageerror");
// Every console message is checked: the only allowed errors are the two deliberate HTTP failures.
const unexpected = errors.filter((m) => !(m.phase === "keyword-server-error" && /status of 400/.test(m.text)) &&
  !(m.phase === "hybrid-injected-failure" && /status of 503/.test(m.text)));
check("no console errors except the two deliberate HTTP errors", unexpected.length === 0, unexpected.map((m) => m.text).join(" | "));

const summary = { url, chrome: chromeVersion, expect_vectors: expectVectors, pass: checks.filter((c) => c.status === "PASS").length,
  fail: checks.filter((c) => c.status === "FAIL").length, requests: requests.length, console_messages: console_.length };
writeFileSync(join(out, "results.json"), JSON.stringify({ summary, checks, console: console_, requests }, null, 2) + "\n");
console.log(JSON.stringify(summary));
process.exit(summary.fail === 0 ? 0 : 1);
