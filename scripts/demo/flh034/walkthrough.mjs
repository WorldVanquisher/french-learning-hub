// Automated FLH-034 two-minute walkthrough in a real browser (playwright-core in a
// temporary directory; not a project dependency). It follows docs/DEMO.md against
// a freshly seeded demo, asserts what each step shows, saves screenshots, and
// fails if the browser sends any non-GET request.
// Usage: node walkthrough.mjs ORIGIN SHOTS_DIR LABEL [--multi-relation]   (CHROME=/path overrides Chrome)
//   --multi-relation  after the read-only steps, record two relations from one unit
//                     to one Concept through the API (outside the browser; this
//                     writes to the demo database) and check both render (W11).
import { chromium } from "playwright-core";

const [, , ORIGIN, SHOTS, LABEL, OPTION] = process.argv;
const T = { timeout: 8000 };
const results = [];
const writes = [];
const browser = await chromium.launch({
  executablePath: process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
page.setDefaultTimeout(T.timeout); // a failed step reports in seconds, not 30 s
const consoleErrors = [];
page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
const failedResponses = [];
page.on("response", (r) => r.status() >= 400 && failedResponses.push(`${r.status()} ${new URL(r.url()).pathname}`));
page.on("request", (r) => r.method() !== "GET" && writes.push(`${r.method()} ${new URL(r.url()).pathname}`));
const assert = (c, m) => {
  if (!c) throw new Error(m);
};
const text = async (loc) => (await loc.first().innerText()).replace(/\s+/g, " ").trim();
async function step(name, fn) {
  try {
    results.push(`PASS  ${name}\n      ${(await fn()) ?? ""}`);
  } catch (e) {
    results.push(`FAIL  ${name}\n      ${String(e.message ?? e).split("\n").slice(0, 4).join(" | ")}`);
    await page.screenshot({ path: `${SHOTS}/${LABEL}-FAIL-${name.split(" ")[0]}.png`, fullPage: true }).catch(() => {});
  }
}
const region = (name) => page.getByRole("region", { name });
async function search(q) {
  const back = page.getByRole("button", { name: /^← Back to (results for|all concepts)/ });
  if (await back.count()) await back.last().click();
  await page.getByLabel("Search learned material").fill(q);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.getByText(new RegExp(`concepts? matching “${q}”|No concepts match`)).first().waitFor(T);
}
async function openConcept(target) {
  await page.getByRole("button", { name: target, exact: true }).click();
  await page.getByRole("heading", { name: new RegExp(target.replace(/[«»()]/g, ".")) }).first().waitFor(T);
  await page.waitForTimeout(150);
}

await page.goto(`${ORIGIN}/`);

await step("W1 open the Knowledge Library tab: browse all concepts", async () => {
  await page.getByRole("button", { name: "Knowledge Library" }).click();
  await page.getByText("7 concepts.").waitFor(T);
  const order = await page.locator(".library-result .link-button").allInnerTexts();
  return `7 concepts; order ${JSON.stringify(order)}`;
});

await step("W2 search “subjunctive”: active before orphaned, identity matches; “subjonctif” finds the same", async () => {
  await search("subjonctif");
  const french = (await page.locator(".library-result .link-button").allInnerTexts()).join(" | ");
  await search("subjunctive");
  const rows = await page.locator(".library-result").allInnerTexts();
  const flat = rows.map((r) => r.replace(/\s+/g, " "));
  assert(flat.length === 4 && /active/.test(flat[0]) && /active/.test(flat[1]) && /orphaned/.test(flat[3]), JSON.stringify(flat));
  assert(flat.every((r) => r.includes("Found in") && r.includes("filed here")), "match explanation missing");
  const english = (await page.locator(".library-result .link-button").allInnerTexts()).join(" | ");
  assert(french === english, `subjonctif: ${french} / subjunctive: ${english}`);
  await page.screenshot({ path: `${SHOTS}/${LABEL}-1-search.png`, fullPage: true });
  return flat.map((r) => r.slice(0, 90)).join(" || ");
});

let historicalUnitRecord = "";
await step("W3 open “il faut que”: best explanation, current support, filed-but-not-supporting member, link", async () => {
  await openConcept("subjunctive after « il faut que »");
  const heading = page.getByRole("heading", { level: 2 }).first();
  assert(await heading.evaluate((el) => el === document.activeElement), "heading not focused");
  const status = await text(page.locator("dl.unit-evidence"));
  assert(status.includes("Active: at least one unit currently supports"), status);
  const explainer = await text(page.getByText(/A unit is filed under a concept when/));
  const preferred = await text(region("Best explanation (preferred unit)"));
  assert(preferred.includes("expresses necessity") && preferred.includes("current extraction"), preferred);
  assert(preferred.includes("French example: Il faut que tu viennes demain."), preferred);
  const frenchLang = await region("Best explanation (preferred unit)").locator("[lang=fr]").first().innerText();
  const support = await text(region("Currently supporting this concept (1)"));
  const members = await text(region("Filed here but not supporting (1)"));
  assert(members.includes("older extraction v1") && members.includes("which is no longer that record's current extraction"), members);
  assert(members.includes("Il faut que je fasse mes devoirs."), members);
  const relations = await text(region("Linked units (1)"));
  assert(relations.includes("RELATED link from unit"), relations);
  historicalUnitRecord = `${explainer.slice(0, 80)} | lang=fr "${frenchLang}"`;
  await page.screenshot({ path: `${SHOTS}/${LABEL}-2-concept.png`, fullPage: true });
  return `support: "${support.slice(0, 110)}" | member: "${members.slice(0, 160)}" | relation: "${relations.slice(0, 120)}" | ${historicalUnitRecord}`;
});

await step("W4 follow the historical member to its source record and interpretation", async () => {
  await region("Filed here but not supporting (1)").getByRole("button", { name: "View source record #1" }).click();
  await page.getByRole("heading", { name: /Where unit #\d+ came from: learning record #1/ }).waitFor(T);
  const entry = await text(region("Original learning record #1"));
  assert(entry.includes("il faut que je fasse"), entry);
  const extraction = await text(region("Extraction v1"));
  assert(extraction.includes("Historical: this is not the record's current extraction"), extraction);
  const interp = await text(region("Interpretation this extraction used: analysis v1"));
  assert(interp.includes("newer analysis (v2)") && interp.includes("rule-based"), interp);
  await page.screenshot({ path: `${SHOTS}/${LABEL}-3-source.png`, fullPage: true });
  return `record: "${entry.slice(0, 110)}" | extraction: "${extraction.slice(0, 120)}" | interpretation: "${interp.slice(-110)}"`;
});

await step("W5 back to concept, then back to results: query and focus preserved", async () => {
  await page.getByRole("button", { name: "← Back to concept #1" }).click();
  await region("Currently supporting this concept (1)").waitFor(T);
  await page.getByRole("button", { name: "← Back to results for “subjunctive”" }).click();
  await page.getByText("4 concepts matching “subjunctive”.").waitFor(T);
  await page.waitForTimeout(150);
  const focused = await page.evaluate(() => document.activeElement?.textContent);
  const value = await page.getByLabel("Search learned material").inputValue();
  assert(focused === "subjunctive after « il faut que »" && value === "subjunctive", `${focused} / ${value}`);
  return `query "${value}", focus on "${focused}"`;
});

await step("W6 search “fasse”: found in the French examples of filed units, not support; orphaned concept is honest", async () => {
  await search("fasse");
  const rows = (await page.locator(".library-result").allInnerTexts()).map((r) => r.replace(/\s+/g, " "));
  const label = "not in the concept's title. Being filed here does not mean the unit supports the concept";
  assert(rows.length === 2 && rows.every((r) => r.includes(label)), JSON.stringify(rows));
  await openConcept("subjunctive forms of faire");
  const status = await text(page.locator("dl.unit-evidence"));
  assert(status.includes("Orphaned: no unit currently supports this concept"), status);
  assert((await text(region("Currently supporting this concept (0)"))).includes("No unit currently supports"), "support");
  const members = await text(region("Filed here but not supporting (1)"));
  assert(members.includes("que je fasse") && members.includes("Il faut que nous fassions attention."), members);
  await page.screenshot({ path: `${SHOTS}/${LABEL}-4-orphaned.png`, fullPage: true });
  await page.getByRole("button", { name: "← Back to results for “fasse”" }).click();
  return `results ${rows.length}, both via unit wording | orphaned: "${members.slice(0, 140)}"`;
});

await step("W7 history: a moved unit and an INVALID unit are never current", async () => {
  await search("être");
  await openConcept("passé composé with être");
  const history = await text(region("History: no longer current (1)"));
  assert(history.includes("This unit was moved: it is now filed under concept #6."), history);
  await region("History: no longer current (1)").getByRole("button", { name: "concept #6" }).click();
  await region("Currently supporting this concept (1)").waitFor(T);
  const accord = await page.getByRole("heading", { level: 2 }).first().evaluate((el) => el.textContent);
  await search("manques");
  await openConcept("tu me manques: saying you miss someone");
  const invalid = await text(region("History: no longer current (1)"));
  assert(invalid.includes("This unit was later marked INVALID"), invalid);
  assert((await text(region("Currently supporting this concept (1)"))).includes("Tu me manques beaucoup."), "support");
  await page.screenshot({ path: `${SHOTS}/${LABEL}-5-history.png`, fullPage: true });
  return `passé composé history: "${history.slice(0, 150)}" → opened "${accord}" | tu me manques history: "${invalid.slice(0, 150)}"`;
});

await step("W8 source of a record whose analysis was corrected before extraction", async () => {
  await search("bien que");
  await openConcept("subjunctive after « bien que »");
  const members = await text(region("Filed here but not supporting (1)"));
  assert(members.includes("The learner hid it (admission suppressed)."), members);
  await region("Best explanation (preferred unit)").getByRole("button", { name: "View source record #2" }).click();
  const interp = await text(region("Interpretation this extraction used: analysis v1"));
  assert(interp.includes("corrected by a person (feedback #") && interp.includes("Concession") && interp.includes("Before correction"), interp);
  return `suppressed member: "${members.slice(0, 120)}" | interpretation: "${interp.slice(0, 200)}"`;
});

await step("W9 switching views keeps the library where the reader left it", async () => {
  await page.getByRole("button", { name: "Concept Review" }).click();
  await page.getByRole("heading", { name: "Concept Review" }).waitFor(T);
  await page.getByRole("button", { name: "Knowledge Library" }).click();
  const heading = await page.getByRole("heading", { level: 2 }).first().evaluate((el) => el.textContent);
  assert(heading.startsWith("Where unit"), heading);
  return `returned to "${heading}"`;
});

await step("W10 read-only: no non-GET request; no failed API request", async () => {
  assert(writes.length === 0, `writes: ${writes.join(", ")}`);
  // The workbench has no favicon, so the browser's automatic /favicon.ico request 404s.
  const unexpected = failedResponses.filter((r) => !r.endsWith("/favicon.ico"));
  assert(unexpected.length === 0, `failed responses: ${unexpected.join(", ")} | console: ${consoleErrors.join(" | ")}`);
  return `0 non-GET requests | failed responses: ${JSON.stringify(failedResponses)} | console errors: ${JSON.stringify(consoleErrors)}`;
});

if (OPTION === "--multi-relation") {
  await step("W11 two relations from one unit to one concept both render (written via API, outside the browser)", async () => {
    // FLH-035 B3 reproduction on a fresh seed: unit 9 → concept 3, RELATED and BROADER.
    // `/api` works for both the production server and the Vite proxy.
    const detail = async () => (await (await fetch(`${ORIGIN}/api/knowledge-library/concepts/3`)).json()).current_relations;
    const have = new Set((await detail()).filter((r) => r.unit.unit_id === 9).map((r) => r.relation));
    for (const relation of ["related", "broader"].filter((r) => !have.has(r))) {
      const res = await fetch(`${ORIGIN}/api/knowledge-units/9/concept-links/relation`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ concept_id: 3, relation }),
      });
      assert(res.status === 201, `POST ${relation}: ${res.status}`);
    }
    const before = consoleErrors.length;
    await search("bien que");
    await openConcept("subjunctive after « bien que »");
    const rows = await page.locator("section[aria-labelledby=lib-relations] .library-unit").allInnerTexts();
    const flat = rows.map((r) => r.replace(/\s+/g, " "));
    const fromUnit9 = flat.filter((r) => r.includes("link from unit #9 "));
    assert(fromUnit9.some((r) => r.includes("RELATED")) && fromUnit9.some((r) => r.includes("BROADER")), JSON.stringify(flat));
    const keyWarnings = consoleErrors.slice(before).filter((m) => m.includes("same key"));
    assert(keyWarnings.length === 0, keyWarnings.join(" | "));
    await page.screenshot({ path: `${SHOTS}/${LABEL}-6-relations.png`, fullPage: true });
    return `${flat.length} relation rows; unit #9 rows: ${fromUnit9.map((r) => r.match(/(RELATED|BROADER|NARROWER)/)?.[0]).join(", ")} | duplicate-key warnings: 0`;
  });
}

await browser.close();
console.log(`FLH-034 walkthrough ${LABEL} ${ORIGIN}\n${results.join("\n")}`);
const failed = results.filter((r) => r.startsWith("FAIL")).length;
console.log(`${results.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
