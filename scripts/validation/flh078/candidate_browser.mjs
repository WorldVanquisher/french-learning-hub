// FLH-078 extended real-browser checks of a public-demo release candidate,
// complementing scripts/demo/flh076/browser/accept.mjs (run that too).
//
//   PLAYWRIGHT_CORE_DIR=... node candidate_browser.mjs --url http://127.0.0.1:PORT --out /abs/evidence/dir \
//     --chrome PATH --expect-model DEPLOYMENT_ID --expect-artifact VERSION
//
// Checks the model identity shown to the visitor; every preset in semantic and
// hybrid mode, with the UI order equal to the server's answer for the same
// preset; every status filter; concept detail and back navigation from
// semantic results; injected semantic failures (HTTP 503 and a dropped
// connection); and that every request stays GET, same-origin and on the
// public-demo allowlist. Writes results.json and screenshots. Exit 0 only if
// every check passed. It only reads.
import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const arg = (n, d) => { const i = process.argv.indexOf(n); return i > 0 ? process.argv[i + 1] : d; };
const url = arg("--url"), out = arg("--out"), chrome = arg("--chrome");
const expectModel = arg("--expect-model"), expectArtifact = arg("--expect-artifact");
if (!url || !out || !chrome || !expectModel || !expectArtifact || !process.env.PLAYWRIGHT_CORE_DIR) {
  console.error("usage: see header"); process.exit(2);
}
const { chromium } = createRequire(join(process.env.PLAYWRIGHT_CORE_DIR, "package.json"))("playwright-core");
mkdirSync(out, { recursive: true });
const checks = [], console_ = [], requests = [], presetsSeen = [];
let phase = "load";
const check = (name, ok, detail = "") => {
  checks.push({ name, status: ok ? "PASS" : "FAIL", detail: String(detail).slice(0, 400) });
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? ` — ${String(detail).slice(0, 140)}` : ""}`);
};
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

const browser = await chromium.launch({ executablePath: chrome, headless: true });
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await context.newPage();
page.on("console", (m) => console_.push({ phase, type: m.type(), text: m.text() }));
page.on("pageerror", (e) => console_.push({ phase, type: "pageerror", text: String(e) }));
page.on("request", (r) => requests.push({ phase, method: r.method(), url: r.url() }));
const shot = (name) => page.screenshot({ path: join(out, `${String(checks.length).padStart(3, "0")}-${name}.png`), fullPage: true });
const search = () => page.getByRole("button", { name: "Search", exact: true }).click();
// Server answers are read outside the page (Node fetch), so they are not page requests.
const api = async (path) => (await fetch(url + path)).json();
const titles = async (region) => (await region.getByRole("listitem").all()).length === 0 ? [] :
  Promise.all((await region.getByRole("listitem").all()).map(async (li) => (await li.getByRole("button").first().innerText()).trim()));

try {
  const info = await api("/api/knowledge-library/demo");
  await page.goto(url, { waitUntil: "networkidle" });
  const about = page.getByRole("region", { name: "About this demo" });
  await about.waitFor();
  const aboutText = await about.innerText();
  check("server reports the expected artifact and a real model", info.artifact.version === expectArtifact && info.artifact.real_model === true &&
    info.artifact.model_id === expectModel, JSON.stringify({ v: info.artifact.version, real: info.artifact.real_model, m: info.artifact.model_id }));
  check("visitor sees artifact version, model vectors and the pinned deployment",
    aboutText.includes(`Artifact ${expectArtifact} · vectors: model (${expectModel}, 768 dimensions)`), aboutText.match(/Artifact .*/)?.[0]);
  check("no mechanical-vector banner", (await page.getByText(/mechanical test fixtures/).count()) === 0);
  await shot("about");

  const presets = info.presets ?? (await api("/api/knowledge-library/demo")).presets;
  check("8 presets advertised by the server", Array.isArray(presets) && presets.length === 8, presets?.length);
  for (const mode of ["Semantic", "Hybrid"]) {
    await page.getByRole("radio", { name: mode }).check();
    await page.getByLabel("Concept status").selectOption("all");
    for (const p of presets) {
      phase = `${mode.toLowerCase()}:${p.id}`;
      await page.getByLabel("Example query").selectOption(p.id);
      await search();
      const region = page.getByRole("region", { name: `${mode} results` });
      const summary = mode === "Semantic" ? new RegExp(`by similarity to “${esc(p.text)}”`) : new RegExp(`for “${esc(p.text)}”`);
      await region.getByText(summary).first().waitFor();
      const ui = await titles(region);
      const path = `/api/knowledge-library/demo/${mode.toLowerCase()}-search?preset=${encodeURIComponent(p.id)}`;
      const srv = await api(path);
      const srvTitles = srv.results.map((r) => r.concept.target.trim());
      const text = await region.innerText();
      const evidence = mode === "Semantic" ? ui.length > 0 && /Similarity [-0-9.]+ \(cosine; not a probability/.test(text) && text.includes(`model ${expectModel}`)
        : ui.length > 0 && /Policy concept_hybrid_rrf_v1: reciprocal rank fusion with k = 60/.test(text) && /Combined score \d\.\d{4}/.test(text);
      check(`${mode} preset ${p.id}: results with evidence`, evidence, `${ui.length} results; top: ${ui[0]}`);
      check(`${mode} preset ${p.id}: UI order equals the server's`, ui.length === srvTitles.length && ui.every((t, i) => t.includes(srvTitles[i]) || srvTitles[i].includes(t)),
        `ui=${ui.slice(0, 3).join(" / ")} srv=${srvTitles.slice(0, 3).join(" / ")}`);
      presetsSeen.push({ mode, preset: p.id, text: p.text, results: ui });
      await shot(`${mode.toLowerCase()}-${p.id}`);
    }
  }

  phase = "state-filters";
  await page.getByRole("radio", { name: "Keyword" }).check();
  const counts = {};
  for (const state of ["all", "active", "orphaned", "retired"]) {
    await page.getByLabel("Search learned material").fill("");
    await page.getByLabel("Concept status").selectOption(state);
    await search();
    // A non-empty answer is a "Library results" region; an empty one is a status line outside it.
    const region = page.getByRole("region", { name: "Library results" });
    await page.getByText(state === "all" ? /^\d+ concepts?\.$/ : new RegExp(`^(\\d+ concepts?\\.|No ${state} concepts\\.)$`)).first().waitFor();
    const items = await region.getByRole("listitem").allInnerTexts();
    const srv = await api(`/api/knowledge-library/concepts${state === "all" ? "" : `?state=${state}`}`);
    counts[state] = items.length;
    const tagsOk = state === "all" || (await Promise.all((await region.getByRole("listitem").all()).map(async (li) =>
      (await li.locator(`.tag.${state}`).count()) >= 1))).every(Boolean);
    check(`status filter ${state}: count equals the server's and every result is tagged ${state}`,
      items.length === (srv.results?.length ?? -1) && tagsOk, `ui=${items.length} srv=${srv.results?.length}`);
    await shot(`state-${state}`);
  }
  check("status filters partition the catalog", counts.active + counts.orphaned + counts.retired === counts.all, JSON.stringify(counts));

  phase = "semantic-detail";
  await page.getByRole("radio", { name: "Semantic" }).check();
  await page.getByLabel("Concept status").selectOption("all");
  await page.getByLabel("Example query").selectOption("past-habits");
  await search();
  const sem = page.getByRole("region", { name: "Semantic results" });
  await sem.getByText(/by similarity to “describing past habits”/).waitFor();
  const first = (await sem.getByRole("listitem").first().getByRole("button").first().innerText()).trim();
  await sem.getByRole("listitem").first().getByRole("button").first().click();
  await page.getByRole("heading", { level: 2, name: new RegExp(esc(first)) }).waitFor();
  check("semantic result opens concept detail", true, first);
  await shot("semantic-concept");
  await page.getByRole("button", { name: /← Back to semantic results for “describing past habits”/ }).click();
  await sem.waitFor();
  check("back to semantic results restores focus", (await page.evaluate(() => document.activeElement?.textContent ?? "")).trim() === first);

  for (const [kind, handler] of [["503", (r) => r.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: "injected by the browser test" }) })],
    ["dropped", (r) => r.abort("connectionreset")]]) {
    phase = `semantic-injected-${kind}`;
    await page.route("**/knowledge-library/demo/semantic-search**", handler);
    await page.getByLabel("Example query").selectOption("although");
    await search();
    const alert = page.getByRole("alert");
    await alert.waitFor();
    const t = await alert.innerText();
    check(`semantic ${kind} failure shown explicitly with retry, no substitute results`, /Could not run the semantic search/.test(t) &&
      (await alert.getByRole("button", { name: "Try again" }).count()) === 1 && (await page.getByRole("region", { name: "Library results" }).count()) === 0, t);
    await shot(`semantic-error-${kind}`);
    await page.unroute("**/knowledge-library/demo/semantic-search**");
  }
} catch (e) {
  check("browser run completed", false, e.stack ?? e);
  await shot("crash").catch(() => {});
} finally {
  await browser.close();
}

const origin = new URL(url).origin;
const allowed = /^\/(|assets\/.+|api\/knowledge-library\/(concepts(\/\d+)?|units\/\d+\/source|demo(\/(semantic|hybrid)-search)?))$/;
check("every request is same-origin", requests.every((r) => r.url.startsWith(origin)), requests.filter((r) => !r.url.startsWith(origin)).map((r) => r.url).join(" "));
check("every request is GET", requests.every((r) => r.method === "GET"));
check("every request is on the demo allowlist", requests.every((r) => allowed.test(new URL(r.url).pathname)),
  requests.filter((r) => !allowed.test(new URL(r.url).pathname)).map((r) => r.url).join(" "));
check("semantic/hybrid requests carry preset ids only", requests.filter((r) => /demo\/(semantic|hybrid)-search/.test(r.url))
  .every((r) => { const q = new URL(r.url).searchParams; return q.has("preset") && !q.has("q"); }));
const unexpected = console_.filter((m) => (m.type === "error" || m.type === "pageerror") &&
  !(m.phase === "semantic-injected-503" && /status of 503/.test(m.text)) && !(m.phase === "semantic-injected-dropped" && /ERR_CONNECTION_RESET|Failed to load/.test(m.text)));
check("no console errors except the deliberate injected failures", unexpected.length === 0, unexpected.map((m) => `${m.phase}: ${m.text}`).join(" | "));
const summary = { url, chrome: browser.version?.() ?? null, expect_model: expectModel, expect_artifact: expectArtifact,
  pass: checks.filter((c) => c.status === "PASS").length, fail: checks.filter((c) => c.status === "FAIL").length, requests: requests.length };
writeFileSync(join(out, "results.json"), JSON.stringify({ summary, checks, presets: presetsSeen, console: console_, requests }, null, 2) + "\n");
console.log(JSON.stringify(summary));
process.exit(summary.fail === 0 ? 0 : 1);
