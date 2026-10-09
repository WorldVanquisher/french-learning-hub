// FLH-032 real-browser probes for the three FLH-030 recovery defects, against a
// freshly seeded FLH-030 fixture database (units 1-12, concepts alpha=1 beta=2
// gamma=3). "[inj]" marks a browser-level fault on one request. Persisted state
// is read from the backend HTTP API (BACKEND), never inferred from the UI.
// Usage: node probes.mjs ORIGIN BACKEND SHOTS LABEL
import { chromium } from "playwright-core";

const [, , ORIGIN, BACKEND, SHOTS, LABEL] = process.argv;
const KEY = "flh.annotation-operations.v1";
const C = { alpha: 1, beta: 2, gamma: 3 };
const T = { timeout: 8000 };
const results = [];
const posts = []; // every POST any page issued: { path, key }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const assert = (c, m) => {
  if (!c) throw new Error(m);
};

const browser = await chromium.launch({
  executablePath: process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  headless: true,
});
const context = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
// Controllable storage failure (same as FLH-030): window.__storageFail = { allow: n }
// lets n more writes of the operation key succeed, then every further write throws.
await context.addInitScript((key) => {
  const original = Storage.prototype.setItem;
  Storage.prototype.setItem = function (k, v) {
    const f = window.__storageFail;
    if (f && k === key) {
      if (f.allow > 0) f.allow--;
      else {
        f.thrown = (f.thrown ?? 0) + 1;
        throw new DOMException("synthetic storage failure", "QuotaExceededError");
      }
    }
    return original.call(this, k, v);
  };
}, KEY);
context.on("request", (r) => r.method() === "POST" && posts.push({ path: new URL(r.url()).pathname, key: r.headers()["idempotency-key"] ?? null }));

const get = async (path) => {
  const r = await fetch(`${BACKEND}${path}`);
  return { status: r.status, body: await r.json().catch(() => null) };
};
const distinctions = async (unit) => (await get(`/knowledge-units/${unit}/concept-distinctions`)).body.distinctions;
const relations = async (unit, concept, relation) =>
  (await get(`/concepts/${concept}`)).body.links.filter((l) => l.unit_id === unit && l.relation === relation);
const receipt = (key) => get(`/annotation-operations/${key}`);
const storedOps = async (page) => {
  const raw = await page.evaluate((k) => window.localStorage.getItem(k), KEY);
  return raw === null ? [] : JSON.parse(raw).operations;
};
const postsWithKey = (key) => posts.filter((p) => p.key === key);

async function step(name, page, fn) {
  try {
    results.push(`PASS  ${name}\n      ${(await fn()) ?? ""}`);
  } catch (e) {
    const texts = await page.evaluate(() => [...document.querySelectorAll("[role=alert], [role=status], .reconciliation")].map((el) => el.textContent.replace(/\s+/g, " ").trim())).catch(() => []);
    results.push(`FAIL  ${name}\n      ${String(e.message ?? e).split("\n").slice(0, 6).join(" | ")}\n      visible: ${JSON.stringify(texts.slice(-6))}`);
    await page.screenshot({ path: `${SHOTS}/${LABEL}-032-FAIL-${name.split(" ")[0]}.png`, fullPage: true }).catch(() => {});
  }
}

async function openReview(page) {
  await page.getByText(/unit \d+ of \d+/).waitFor(T);
}
async function newPage() {
  const page = await context.newPage();
  await page.goto(`${ORIGIN}/`);
  await openReview(page);
  return page;
}
async function goToUnit(page, n) {
  for (let i = 0; i < 30; i++) {
    const u = Number(await page.locator(".panel").filter({ hasText: "Knowledge Unit (evidence)" }).locator(".field-row .value.mono").first().textContent());
    if (u === n) return;
    await page.getByRole("button", { name: u < n ? "skip →" : "← previous" }).click();
    await page.waitForTimeout(250);
  }
  throw new Error(`unit ${n} not reachable`);
}
async function selectConcept(page, name) {
  await page.getByRole("searchbox", { name: "Search existing concepts" }).fill(`concept ${name}`);
  const b = page.locator("div").filter({ hasText: `concept ${name}` }).getByRole("button", { name: /^(select this concept|selected)$/ }).last();
  if ((await b.textContent()) !== "selected") await b.click();
}
const decision = (page, name) => page.getByRole("button", { name, exact: true });
const panel = (page) => page.getByRole("region", { name: "Unknown decision outcome" });
const text = async (loc) => (await loc.first().innerText()).replace(/\s+/g, " ").trim();
// hold keeps the next matching request inside the browser until released with a
// definite 422 (the server never sees it) or a connection reset.
async function hold(page, pattern) {
  let release;
  const gate = new Promise((r) => (release = r));
  await page.route(pattern, async (route) => {
    const how = await gate;
    if (how === "reject") await route.fulfill({ status: 422, contentType: "application/json", body: '{"error":"validation error: synthetic rejection"}' });
    else await route.abort("connectionreset");
  }, { times: 1 });
  return release;
}
async function leaveAndReturn(page, whileAway) {
  await page.getByRole("button", { name: "Annotation Inspector" }).click();
  await whileAway();
  await page.getByRole("button", { name: "Concept Review" }).click();
  await openReview(page);
}

// ------------------------------------------------------------------ F1
{
  const a = await newPage();
  const b = await newPage(); // loaded before tab A saves anything
  await step("G1 [F1] another tab's unresolved operation: per-unit conflict, accurate text, other units keyed", b, async () => {
    await goToUnit(a, 5);
    await selectConcept(a, "beta");
    await a.route("**/api/knowledge-units/5/concept-distinctions", (route) => route.abort("connectionreset"), { times: 1 });
    await decision(a, "DISTINCT").click();
    await panel(a).getByText("Receipt unknown.").waitFor(T);
    const keyA = posts.at(-1).key;

    await goToUnit(b, 5);
    await selectConcept(b, "gamma");
    const before = posts.length;
    await decision(b, "RELATED").click();
    await panel(b).getByText(/already has an unresolved DISTINCT from concept #2 saved for unit #5/).waitFor(T);
    const bPanel = await text(panel(b));
    const storageAlerts = await b.getByText(/Browser storage/).count();
    const sent = posts.length - before;
    const ops = await storedOps(b);
    const blocked = await decision(b, "INVALID").isDisabled();
    assert(sent === 0 && storageAlerts === 0 && blocked && bPanel.includes(keyA), `sent ${sent}, storage alerts ${storageAlerts}, blocked ${blocked}`);
    assert(ops.length === 1 && ops[0].operationId === keyA && ops[0].conceptId === C.beta, `storage ${JSON.stringify(ops)}`);
    await b.screenshot({ path: `${SHOTS}/${LABEL}-032-two-tabs.png`, fullPage: true });

    // Unrelated unit in tab B: keyed decision is sent and commits.
    await goToUnit(b, 6);
    await selectConcept(b, "alpha");
    const before6 = posts.length;
    await decision(b, "NARROWER").click();
    await b.getByText(/Recorded NARROWER/).first().waitFor(T);
    const narrower = await relations(6, C.alpha, "narrower");
    assert(posts.length - before6 === 1 && narrower.length === 1, `unit 6 NARROWER posts ${posts.length - before6}, events ${narrower.length}`);

    // Tab B retries the kept operation with A's key; tab A's receipt check then finds it.
    await goToUnit(b, 5);
    await panel(b).getByRole("button", { name: "Retry saved operation" }).click();
    await b.getByText(/Recorded DISTINCT event #\d+ for concept #2/).first().waitFor(T);
    await panel(a).getByRole("button", { name: "Check receipt" }).click();
    await a.getByText(/Found on the server: This request committed event/).first().waitFor(T);
    const rc = await receipt(keyA);
    const d5 = (await distinctions(5)).filter((d) => d.concept_id === C.beta);
    const rel5 = await relations(5, C.gamma, "related");
    assert(rc.status === 200 && d5.length === 1 && rel5.length === 0 && postsWithKey(keyA).length === 2 && (await storedOps(a)).length === 0,
      `receipt ${rc.status}, DISTINCT beta ${d5.length}, RELATED gamma ${rel5.length}, POSTs with A's key ${postsWithKey(keyA).length}`);
    return `tab B panel: "${bPanel.slice(0, 230)}" | 0 POSTs, no storage alert, storage kept A's op | unit 6 NARROWER sent 1, committed | B's explicit retry used A's key (2 POSTs with it: A's dropped original + B's retry), receipt 200 event #${rc.body.result.id}, unit 5 DISTINCT beta 1, RELATED gamma 0, storage empty`;
  });
  await a.close();
  await b.close();
}

const page = await newPage();

// ------------------------------------------------------------------ F2
await step("G2 [F2][inj 422] definite rejection while away: exact operation cleared, unit not unresolved", page, async () => {
  await goToUnit(page, 9);
  await selectConcept(page, "gamma");
  const release = await hold(page, "**/api/knowledge-units/9/concept-distinctions");
  const before = posts.length;
  await decision(page, "DISTINCT").click();
  await page.getByText("Sending DISTINCT from concept #3 for unit #9").first().waitFor(T);
  const key = posts[before].key;
  const during = await storedOps(page);
  let away;
  await leaveAndReturn(page, async () => {
    release("reject");
    await sleep(1000);
    away = await storedOps(page);
  });
  await goToUnit(page, 9);
  await page.waitForTimeout(500);
  const panels = await panel(page).count();
  const enabled = await decision(page, "INVALID").isEnabled();
  const rc = await receipt(key);
  const events = (await distinctions(9)).length;
  assert(during.length === 1 && away.length === 0 && panels === 0 && enabled && rc.status === 404 && events === 0 && postsWithKey(key).length === 1,
    `during ${during.length}, away ${JSON.stringify(away)}, panels ${panels}, enabled ${enabled}, receipt ${rc.status}, events ${events}`);
  return `saved while sending: ${during.length} op | after the 422 arrived while away: storage ${JSON.stringify(away)} | on return unit 9: no recovery panel, decisions enabled | receipt 404, 0 events, 1 POST`;
});

await step("G3 [F2][inj 422] a late rejection never clears a newer operation for the unit", page, async () => {
  await goToUnit(page, 10);
  await selectConcept(page, "alpha");
  const release = await hold(page, "**/api/knowledge-units/10/concept-distinctions");
  const before = posts.length;
  await decision(page, "DISTINCT").click();
  await page.getByText("Sending DISTINCT from concept #1 for unit #10").first().waitFor(T);
  const oldKey = posts[before].key;
  const newer = { kind: "relation", unitId: 10, conceptId: C.beta, relation: "broader", operationId: "0f32aaaa-bbbb-4ccc-8ddd-000000000032" };
  let away;
  await leaveAndReturn(page, async () => {
    // Stands in for another tab: the old operation was resolved there and a newer one saved.
    await page.evaluate(([k, op]) => window.localStorage.setItem(k, JSON.stringify({ version: 1, operations: [op] })), [KEY, newer]);
    release("reject");
    await sleep(1000);
    away = await storedOps(page);
  });
  assert(away.length === 1 && away[0].operationId === newer.operationId, `storage ${JSON.stringify(away)}`);
  // The newer operation is not visible to this mounted page until reload restores it.
  await page.reload();
  await openReview(page);
  await goToUnit(page, 10);
  await panel(page).getByText("Restored unresolved operation.").waitFor(T);
  const restored = await text(panel(page));
  await panel(page).getByRole("button", { name: "Retry saved operation" }).click();
  await page.getByText(/Recorded BROADER/).first().waitFor(T);
  const rel = await relations(10, C.beta, "broader");
  const rc = await receipt(newer.operationId);
  assert(rel.length === 1 && rc.status === 200 && (await receipt(oldKey)).status === 404 && (await distinctions(10)).length === 0 && (await storedOps(page)).length === 0,
    `broader ${rel.length}, receipt ${rc.status}`);
  return `old key ${oldKey.slice(0, 8)}… rejected (422) while away → storage kept only the newer ${newer.operationId.slice(0, 8)}… | after reload: "${restored.slice(0, 120)}" | explicit retry committed BROADER beta (receipt 200); old key receipt 404, 0 DISTINCT events, storage empty`;
});

await step("G4 [F2][inj reset] unknown outcome while away stays recoverable with the original key and payload", page, async () => {
  await goToUnit(page, 11);
  await selectConcept(page, "alpha");
  const release = await hold(page, "**/api/knowledge-units/11/concept-distinctions");
  const before = posts.length;
  await decision(page, "DISTINCT").click();
  await page.getByText("Sending DISTINCT from concept #1 for unit #11").first().waitFor(T);
  const key = posts[before].key;
  let away;
  await leaveAndReturn(page, async () => {
    release("reset");
    await sleep(1000);
    away = await storedOps(page);
  });
  assert(away.length === 1 && away[0].operationId === key && away[0].conceptId === C.alpha, `storage ${JSON.stringify(away)}`);
  // The mounted page lost the in-memory state; a reload restores it from storage.
  await page.reload();
  await openReview(page);
  await goToUnit(page, 11);
  await panel(page).getByText("Restored unresolved operation.").waitFor(T);
  await selectConcept(page, "gamma"); // editing the selection does not change the saved payload
  await panel(page).getByRole("button", { name: "Retry saved operation" }).click();
  await page.getByText(/Recorded DISTINCT event #\d+ for concept #1/).first().waitFor(T);
  const d = await distinctions(11);
  assert(d.length === 1 && d[0].concept_id === C.alpha && postsWithKey(key).length === 2 && (await receipt(key)).status === 200 && (await storedOps(page)).length === 0,
    `events ${JSON.stringify(d)}, posts ${postsWithKey(key).length}`);
  return `storage after the reset while away kept ${key.slice(0, 8)}… DISTINCT alpha | reload restored it | retry with gamma selected still sent alpha under the same key | 1 event (alpha), receipt 200, storage empty`;
});

// ------------------------------------------------------------------ F3
await step("G5 [F3] save-time storage failure: keyed controls disabled visibly; explicit recheck re-enables; no auto POST", page, async () => {
  await goToUnit(page, 12);
  await selectConcept(page, "beta");
  await page.evaluate(() => (window.__storageFail = { allow: 0 }));
  const before = posts.length;
  await decision(page, "DISTINCT").click();
  const alert = page.getByRole("alert").filter({ hasText: "Browser storage failed. Nothing was sent" });
  await alert.waitFor(T);
  const alertText = await text(alert);
  const keyed = {};
  for (const n of ["DISTINCT", "BROADER", "NARROWER", "RELATED", "SAME → selected", "NEW CONCEPT", "INVALID"]) keyed[n] = await decision(page, n).isDisabled();
  assert(keyed.DISTINCT && keyed.BROADER && keyed.NARROWER && keyed.RELATED && !keyed["SAME → selected"] && !keyed["NEW CONCEPT"] && !keyed.INVALID, `disabled ${JSON.stringify(keyed)}`);
  await page.getByRole("button", { name: "Recheck browser storage" }).click();
  await page.getByRole("alert").filter({ hasText: "still unavailable or unreadable" }).waitFor(T);
  await page.evaluate(() => (window.__storageFail = null));
  await sleep(1000);
  const stillDisabled = await decision(page, "DISTINCT").isDisabled();
  const sentBeforeRecheck = posts.length - before;
  await page.getByRole("button", { name: "Recheck browser storage" }).click();
  await page.getByText("Browser storage works again. Keyed decisions are enabled; nothing was sent.").waitFor(T);
  const sentByRecheck = posts.length - before;
  await selectConcept(page, "beta");
  await decision(page, "DISTINCT").click();
  await page.getByText(/Recorded DISTINCT event #\d+ for concept #2/).first().waitFor(T);
  const d = await distinctions(12);
  assert(stillDisabled && sentBeforeRecheck === 0 && sentByRecheck === 0 && posts.length - before === 1 && d.length === 1 && (await storedOps(page)).length === 0,
    `stillDisabled ${stillDisabled}, sent ${sentBeforeRecheck}/${sentByRecheck}/${posts.length - before}, events ${d.length}`);
  await page.screenshot({ path: `${SHOTS}/${LABEL}-032-storage-recheck.png`, fullPage: true });
  return `alert "${alertText.slice(0, 200)}" | keyed disabled, SAME/NEW/INVALID enabled | recheck while failing → "still unavailable" | storage restored: still disabled until recheck, 0 POSTs | recheck → enabled, 0 POSTs | explicit DISTINCT → 1 POST, 1 event, storage empty`;
});

await step("G6 [F3] cleanup failure after commit: recheck retries the exact cleanup; nothing left unresolved", page, async () => {
  await goToUnit(page, 7);
  await selectConcept(page, "gamma");
  await page.evaluate(() => (window.__storageFail = { allow: 1 }));
  const before = posts.length;
  await decision(page, "DISTINCT").click();
  await page.getByRole("alert").filter({ hasText: "Request committed, but browser storage cleanup failed" }).waitFor(T);
  const key = posts[before].key;
  const left = await storedOps(page);
  await page.evaluate(() => (window.__storageFail = null));
  await page.getByRole("button", { name: "Recheck browser storage" }).click();
  await page.getByText("Browser storage works again.").first().waitFor(T);
  const after = await storedOps(page);
  await page.reload();
  await openReview(page);
  await goToUnit(page, 7);
  await page.waitForTimeout(500);
  const panels = await panel(page).count();
  assert(left.length === 1 && left[0].operationId === key && after.length === 0 && panels === 0 && postsWithKey(key).length === 1 && (await receipt(key)).status === 200,
    `left ${JSON.stringify(left)}, after ${JSON.stringify(after)}, panels ${panels}`);
  return `commit + failed cleanup left ${key.slice(0, 8)}… saved | recheck cleared it | after reload unit 7 has no recovery panel | 1 POST, receipt 200`;
});

await step("G7 [F3] unreadable saved value on load: honest recheck text; clearing it then recheck recovers without reload", page, async () => {
  await page.evaluate((k) => window.localStorage.setItem(k, "{not json"), KEY);
  await page.reload();
  await openReview(page);
  await page.getByRole("alert").filter({ hasText: "Browser storage is unavailable or invalid." }).waitFor(T);
  await goToUnit(page, 8);
  await selectConcept(page, "alpha");
  const disabled = await decision(page, "RELATED").isDisabled();
  await page.getByRole("button", { name: "Recheck browser storage" }).click();
  await page.getByRole("alert").filter({ hasText: "Reloading does not repair an unreadable saved value." }).waitFor(T);
  const raw = await page.evaluate((k) => window.localStorage.getItem(k), KEY);
  await page.evaluate((k) => window.localStorage.removeItem(k), KEY);
  await page.getByRole("button", { name: "Recheck browser storage" }).click();
  await page.getByText("Browser storage works again.").first().waitFor(T);
  const enabled = await decision(page, "RELATED").isEnabled();
  assert(disabled && raw === "{not json" && enabled, `disabled ${disabled}, raw ${raw}, enabled ${enabled}`);
  return `RELATED disabled while unreadable | recheck left the value untouched and said reloading does not repair it | after removing the value, recheck re-enabled RELATED without reload`;
});

const unkeyed = posts.filter((p) => /concept-distinctions|concept-links\/relation/.test(p.path) && !p.key).length;
results.push(`INFO  annotation POSTs ${posts.filter((p) => /concept-distinctions|concept-links\/relation/.test(p.path)).length}, unkeyed ${unkeyed}`);
await browser.close();
console.log(`FLH-032 probes ${LABEL} ${ORIGIN}\n${results.join("\n")}`);
const failed = results.filter((r) => r.startsWith("FAIL")).length;
console.log(`${results.filter((r) => r.startsWith("PASS")).length} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
