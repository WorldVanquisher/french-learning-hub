// FLH-030 probes: (P1) historical receipt vs a unit made INVALID after commit;
// (P2) two tabs, second tab decides on a unit the first tab left unresolved.
import { chromium } from "playwright-core";
const [, , ORIGIN, BACKEND, P1UNIT, P2UNIT] = process.argv;
const KEY = "flh.annotation-operations.v1";
const T = { timeout: 8000 };
const browser = await chromium.launch({ executablePath: process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
const context = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
const posts = [];
context.on("request", (r) => r.method() === "POST" && posts.push({ path: new URL(r.url()).pathname, key: r.headers()["idempotency-key"] }));
const get = async (p) => { const r = await fetch(BACKEND + p); return { status: r.status, body: await r.json().catch(() => null) }; };
async function open() {
  const page = await context.newPage();
  await page.goto(`${ORIGIN}/`);
  await page.getByText(/unit 1 of \d+/).waitFor(T);
  await page.evaluate(() => {
    window.__seen = [];
    new MutationObserver(() => document.querySelectorAll(".banner, [role=status], [role=alert], .reconciliation").forEach((el) => {
      const t = (el.textContent ?? "").replace(/\s+/g, " ").trim();
      if (t && !window.__seen.includes(t)) window.__seen.push(t);
    })).observe(document.body, { subtree: true, childList: true, characterData: true });
  });
  return page;
}
async function goTo(page, n) {
  for (let i = 0; i < 30; i++) {
    const u = Number(await page.locator(".panel").filter({ hasText: "Knowledge Unit (evidence)" }).locator(".field-row .value.mono").first().textContent());
    if (u === n) return;
    await page.getByRole("button", { name: u < n ? "skip →" : "← previous" }).click();
    await page.waitForTimeout(250);
  }
}
async function select(page, name) {
  await page.getByRole("searchbox", { name: "Search existing concepts" }).fill(`concept ${name}`);
  const b = page.locator("div").filter({ hasText: `concept ${name}` }).getByRole("button", { name: /^(select this concept|selected)$/ }).last();
  if ((await b.textContent()) !== "selected") await b.click();
}
const panel = (page) => page.getByRole("region", { name: "Unknown decision outcome" });

// P1
{
  const unit = Number(P1UNIT);
  const page = await open();
  await goTo(page, unit);
  await select(page, "gamma");
  const held = {};
  await page.route(`**/api/knowledge-units/${unit}/concept-links/relation`, async (route) => {
    const r = route.request();
    Object.assign(held, { url: r.url(), headers: r.headers(), body: r.postData() });
    await route.abort("connectionreset");
  }, { times: 1 });
  await page.getByRole("button", { name: "RELATED", exact: true }).click();
  await panel(page).getByText("Receipt unknown.").waitFor(T);
  const orig = await fetch(held.url, { method: "POST", headers: { "content-type": "application/json", origin: held.headers.origin, "idempotency-key": held.headers["idempotency-key"] }, body: held.body });
  const inv = await fetch(`${BACKEND}/knowledge-units/${unit}/invalid`, { method: "POST", headers: { "content-type": "application/json" }, body: "{}" });
  await page.evaluate(() => (window.__seen.length = 0));
  await panel(page).getByRole("button", { name: "Check receipt" }).click();
  await page.getByText(/Found on the server: This request committed event/).first().waitFor(T);
  await page.waitForTimeout(1000);
  const texts = await page.evaluate(() => window.__seen.slice());
  const rc = await get(`/annotation-operations/${held.headers["idempotency-key"]}`);
  const snap = (await get(`/knowledge-units/${unit}/effective-annotation`)).body.snapshot;
  const reviewable = (await get("/reviewable-units")).body.reviewable_units.some((u) => u.unit_id === unit);
  const membershipText = (await page.locator(".panel").filter({ hasText: "Current membership" }).first().innerText()).replace(/\s+/g, " ");
  console.log(`P1 unit ${unit}: original delivered → ${orig.status}; later INVALID → ${inv.status}`);
  console.log(`   receipt ${rc.status}: ${rc.body.request.action}/${rc.body.request.relation} result #${rc.body.result.id}`);
  console.log(`   current: status=${snap.status}, latest_unit_judgment=${JSON.stringify(snap.latest_unit_judgment)?.slice(0, 80)}, relations=${JSON.stringify(snap.relations.map((r) => r.relation + ":" + r.concept_id))}, reviewable=${reviewable}`);
  console.log(`   UI texts after Check receipt: ${JSON.stringify(texts)}`);
  console.log(`   UI membership panel: "${membershipText.slice(0, 200)}"`);
  await page.screenshot({ path: `${process.env.SHOTS}/${process.env.LABEL}-historical-vs-invalid.png`, fullPage: true });
  await page.close();
}

// P2
{
  const unit = Number(P2UNIT);
  const a = await open();
  const b = await open(); // loaded before tab A saves anything
  await goTo(a, unit);
  await select(a, "beta");
  await a.route(`**/api/knowledge-units/${unit}/concept-distinctions`, (route) => route.abort("connectionreset"), { times: 1 });
  await a.getByRole("button", { name: "DISTINCT", exact: true }).click();
  await panel(a).getByText("Receipt unknown.").waitFor(T);
  const keyA = posts.at(-1).key;
  const before = posts.length;
  await goTo(b, unit);
  await select(b, "gamma");
  const bPanels = await panel(b).count();
  await b.getByRole("button", { name: "RELATED", exact: true }).click();
  await b.waitForTimeout(1500);
  const bTexts = await b.evaluate(() => window.__seen.slice());
  const sent = posts.length - before;
  const stored = JSON.parse(await b.evaluate((k) => localStorage.getItem(k), KEY));
  // Can tab B still send a keyed decision for a different unit?
  await goTo(b, unit === 1 ? 2 : 1);
  await select(b, "alpha");
  const before2 = posts.length;
  await b.getByRole("button", { name: "NARROWER", exact: true }).click();
  await b.waitForTimeout(1500);
  const sentOther = posts.length - before2;
  console.log(`P2 unit ${unit}: tab A unresolved key ${keyA}; tab B showed recovery panel before acting: ${bPanels > 0}`);
  console.log(`   tab B RELATED on same unit → POSTs ${sent}; texts ${JSON.stringify(bTexts)}`);
  console.log(`   storage ops: ${JSON.stringify(stored.operations)}`);
  console.log(`   tab B NARROWER on another unit afterwards → POSTs ${sentOther}`);
  await b.screenshot({ path: `${process.env.SHOTS}/${process.env.LABEL}-two-tabs.png`, fullPage: true });
  // Leave no unresolved operation behind: tab A retries its own saved payload.
  await panel(a).getByRole("button", { name: "Retry saved operation" }).click();
  await a.getByText(/Recorded DISTINCT event #\d+ for concept #2/).first().waitFor(T);
  console.log(`   cleanup: tab A retry committed; storage now ${await a.evaluate((k) => localStorage.getItem(k), KEY)}`);
}
await browser.close();
