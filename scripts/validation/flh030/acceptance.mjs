// FLH-030 browser acceptance: keyed DISTINCT/BROADER/NARROWER/RELATED in real
// Chrome against an isolated, freshly seeded backend (units 1-12, concepts
// alpha=1 beta=2 gamma=3). "[inj]" marks a browser-level fault on one request.
// Persisted state is read directly from the backend (BACKEND), never from the UI.
import { chromium } from "playwright-core";

const [, , ORIGIN, BACKEND, SHOTS, LABEL] = process.argv;
const KEY = "flh.annotation-operations.v1";
const UUID4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const C = { alpha: 1, beta: 2, gamma: 3 };
const results = [];
const consoleErrors = [];
const posts = []; // every annotation-shaped POST the browser issued
const byRequest = new Map();
const browser = await chromium.launch({
  executablePath: process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  headless: true,
});
const context = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
// Controllable storage failure: window.__storageFail = { allow: n } lets n more
// writes of the operation key succeed, then every further write throws.
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
const page = await context.newPage();
page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
page.on("request", (r) => {
  if (r.method() !== "POST") return;
  const e = { path: new URL(r.url()).pathname, key: r.headers()["idempotency-key"] ?? null, body: r.postData(), status: null, replayed: null, respKey: null };
  posts.push(e);
  byRequest.set(r, e);
});
page.on("response", (res) => {
  const e = byRequest.get(res.request());
  if (!e) return;
  e.status = res.status();
  e.replayed = res.headers()["idempotency-replayed"] ?? null;
  e.respKey = res.headers()["idempotency-key"] ?? null;
});

const T = { timeout: 8000 };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function step(name, fn) {
  await page.evaluate(() => { if (window.__seen) window.__seen.length = 0; }).catch(() => {});
  try {
    results.push(`PASS  ${name}\n      ${(await fn()) ?? ""}`);
  } catch (e) {
    const texts = await page.evaluate(() => window.__seen?.slice(-6) ?? []).catch(() => []);
    results.push(`FAIL  ${name}\n      ${String(e.message ?? e).split("\n").slice(0, 6).join(" | ")}\n      seen: ${JSON.stringify(texts)}`);
    await page.screenshot({ path: `${SHOTS}/${LABEL}-FAIL-${name.split(" ")[0]}.png`, fullPage: true }).catch(() => {});
  }
}
const assert = (c, m) => {
  if (!c) throw new Error(m);
};
const get = async (path) => {
  const r = await fetch(`${BACKEND}${path}`);
  return { status: r.status, body: r.status === 204 ? null : await r.json().catch(() => null) };
};
const distinctions = async (unit, concept) =>
  (await get(`/knowledge-units/${unit}/concept-distinctions`)).body.distinctions.filter((d) => concept === undefined || d.concept_id === concept);
const relations = async (unit, concept, relation) =>
  (await get(`/concepts/${concept}`)).body.links.filter((l) => l.unit_id === unit && l.relation === relation);
const receipt = (key) => get(`/annotation-operations/${key}`);
const stored = async () => {
  const raw = await page.evaluate((k) => window.localStorage.getItem(k), KEY);
  return raw === null ? null : JSON.parse(raw);
};
const storedOps = async () => (await stored())?.operations ?? [];
const postsFor = (suffix) => posts.filter((p) => p.path.endsWith(suffix));
const postsWithKey = (key) => posts.filter((p) => p.key === key);
const decisionButton = (name) => page.getByRole("button", { name, exact: true });
const panel = () => page.getByRole("region", { name: "Unknown decision outcome" });
const shownUnit = async () =>
  Number(await page.locator(".panel").filter({ hasText: "Knowledge Unit (evidence)" }).locator(".field-row .value.mono").first().textContent(T));
const text = async (loc) => (await loc.textContent(T)).replace(/\s+/g, " ").trim();
const seen = () => page.evaluate(() => window.__seen.slice());
const bodyText = () => page.locator("body").innerText();

async function watch() {
  await page.evaluate(() => {
    window.__seen = [];
    const record = () =>
      document.querySelectorAll(".banner, [role=status], [role=alert], .reconciliation").forEach((el) => {
        const t = (el.textContent ?? "").replace(/\s+/g, " ").trim();
        if (t && !window.__seen.includes(t)) window.__seen.push(t);
      });
    new MutationObserver(record).observe(document.body, { subtree: true, childList: true, characterData: true });
  });
}
async function openReview() {
  await page.getByText(/unit 1 of \d+/).waitFor(T);
  await watch();
}
async function goToUnit(n) {
  for (let i = 0; i < 30; i++) {
    const u = await shownUnit();
    if (u === n) return;
    await page.getByRole("button", { name: u < n ? "skip →" : "← previous" }).click(T);
    await page.waitForFunction((prev) => {
      const el = [...document.querySelectorAll(".panel")].find((p) => p.textContent.includes("Knowledge Unit (evidence)"));
      const v = el?.querySelector(".field-row .value.mono")?.textContent;
      return v && Number(v) !== prev;
    }, u, T);
  }
  throw new Error(`could not reach unit ${n}`);
}
async function selectConcept(name) {
  await page.getByRole("searchbox", { name: "Search existing concepts" }).fill(`concept ${name}`);
  const card = page.locator(".panel, .candidate, div").filter({ hasText: `concept ${name}` }).getByRole("button", { name: /^(select this concept|selected)$/ }).last();
  if ((await card.textContent(T)) !== "selected") await card.click(T);
  await page.getByRole("button", { name: "selected", exact: true }).first().waitFor(T);
}
async function once(glob, action) {
  let used = false;
  await page.route(glob, async (route) => {
    if (used || route.request().method() !== "POST") return route.continue();
    used = true;
    return action(route);
  });
}
const lostAfterCommit = async (route) => {
  const response = await route.fetch(); // reaches the backend and commits
  results.push(`INFO  [inj lost response] backend answered HTTP ${response.status()}; the browser sees a connection reset`);
  return route.abort("connectionreset");
};
const neverArrives = (route) => route.abort("connectionreset");
// Delay-drop: the browser sees a reset now; the identical original request
// (same URL, Origin, Idempotency-Key and body) is delivered later by deliver().
function delayDrop() {
  const held = {};
  const action = async (route) => {
    const r = route.request();
    Object.assign(held, { url: r.url(), headers: r.headers(), body: r.postData() });
    await route.abort("connectionreset");
  };
  const deliver = async () => {
    const res = await fetch(held.url, {
      method: "POST",
      headers: { "content-type": "application/json", origin: held.headers.origin ?? ORIGIN, "idempotency-key": held.headers["idempotency-key"] },
      body: held.body,
    });
    return { status: res.status, replayed: res.headers.get("idempotency-replayed"), body: await res.json() };
  };
  return { held, action, deliver };
}
// Hold: the browser request waits inside the route until release(mode).
function hold() {
  let release;
  const gate = new Promise((r) => (release = r));
  const action = async (route) => {
    const mode = await gate;
    if (mode === "continue") return route.continue();
    return route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ error: "validation error\nsynthetic rejection" }) });
  };
  return { action, release: (mode) => release(mode) };
}
const waitEnabled = (name) =>
  page.waitForFunction((n) => {
    const b = [...document.querySelectorAll("button")].find((x) => x.textContent === n);
    return b && !b.disabled;
  }, name, T);

await page.goto(`${ORIGIN}/`);
const dev = await page.evaluate(() => [...document.scripts].some((s) => s.src.includes("/src/main.tsx")));
results.push(`INFO  ${LABEL}: ${dev ? "Vite dev server, React StrictMode (effects replayed)" : "production build served by the Go server (-web-dir)"}`);
await openReview();

// ---------------------------------------------------------------- 1, 7
await step("N1 normal DISTINCT/BROADER/NARROWER/RELATED: one keyed POST each, receipts, history and current projection", async () => {
  await goToUnit(1);
  const out = [];
  const plan = [["DISTINCT", "alpha"], ["BROADER", "beta"], ["NARROWER", "gamma"], ["RELATED", "alpha"]];
  const keys = [];
  for (const [action, concept] of plan) {
    await selectConcept(concept);
    const before = posts.length;
    await decisionButton(action).click();
    const ok = page.getByText(new RegExp(`Recorded ${action} event #\\d+ for concept #${C[concept]} \\(historical request result; current authority refreshed separately\\)`)).first();
    await ok.waitFor(T);
    await waitEnabled("INVALID");
    const sent = posts.slice(before);
    assert(sent.length === 1, `${action}: ${sent.length} POSTs`);
    const p = sent[0];
    assert(p.key && UUID4.test(p.key), `${action}: key ${p.key}`);
    assert(p.status === 201 && p.respKey === p.key && p.replayed === null, `${action}: status ${p.status} respKey ${p.respKey} replayed ${p.replayed}`);
    const rc = await receipt(p.key);
    assert(rc.status === 200 && rc.body.state === "committed" && rc.body.status === 201, `${action}: receipt ${rc.status}`);
    const evId = Number((await text(ok)).match(/event #(\d+)/)[1]);
    assert(rc.body.result.id === evId, `receipt result ${rc.body.result.id} != UI event ${evId}`);
    keys.push(p.key);
    out.push(`${action}→${concept}: key ${p.key.slice(0, 8)}… event #${evId}, receipt ${rc.body.request.action}${rc.body.request.relation ? "/" + rc.body.request.relation : ""}`);
  }
  assert(new Set(keys).size === 4, "keys reused across deliberate decisions");
  assert((await distinctions(1, C.alpha)).length === 1, "DISTINCT count");
  assert((await relations(1, C.beta, "broader")).length === 1, "BROADER count");
  assert((await relations(1, C.gamma, "narrower")).length === 1, "NARROWER count");
  assert((await relations(1, C.alpha, "related")).length === 1, "RELATED count");
  const snap = (await get("/knowledge-units/1/effective-annotation")).body.snapshot;
  assert((await storedOps()).length === 0, "operation left in storage");
  const refresh = (await seen()).filter((t) => /refresh|current/i.test(t) && !/^Recorded/.test(t)).slice(-1)[0] ?? "(none)";
  return `${out.join(" | ")} | 4 distinct keys | backend counts DISTINCT/BROADER/NARROWER/RELATED = 1/1/1/1 | effective: status ${snap.status}, distinctions [${snap.distinctions.map((d) => d.concept_id)}], relations [${snap.relations.map((r) => r.relation + ":" + r.concept_id)}] | storage empty | last refresh text: "${refresh.slice(0, 140)}"`;
});

await step("N2 history panel shows the stored relation events for the selected concept", async () => {
  await selectConcept("alpha");
  const hist = page.locator(".panel").filter({ hasText: "Resolution history" });
  if ((await hist.getByRole("button", { name: "show", exact: true }).count()) > 0) await hist.getByRole("button", { name: "show", exact: true }).click();
  await page.getByRole("button", { name: "load history for concept #1" }).click(T).catch(() => {});
  await page.waitForTimeout(800);
  const t = await bodyText();
  const m = t.match(/Events for concept #1[\s\S]{0,400}/i);
  assert(m && /related/i.test(m[0]), "RELATED event not in history panel");
  return `"${m[0].replace(/\s+/g, " ").slice(0, 220)}…"`;
});

// ---------------------------------------------------------------- 2
for (const [unit, action, concept, suffix] of [[2, "DISTINCT", "beta", "concept-distinctions"], [2, "BROADER", "gamma", "concept-links/relation"]]) {
  await step(`L-${action} committed, response lost: unknown → receipt found, not resent, storage cleared`, async () => {
    await goToUnit(unit);
    await selectConcept(concept);
    const before = posts.length;
    await once(`**/api/knowledge-units/${unit}/${suffix}`, lostAfterCommit);
    await decisionButton(action).click();
    const found = page.getByText(/Found on the server: This request committed event #\d+/).first();
    await found.waitFor(T);
    await sleep(1500);
    const sent = posts.slice(before);
    assert(sent.length === 1 && sent[0].status === null, `POSTs ${sent.length}`);
    const s = await seen();
    const unknown = s.find((x) => x.includes("so its outcome is unknown. It was not sent again."));
    assert(unknown, `no unknown-outcome text: ${JSON.stringify(s.slice(-5))}`);
    const rc = await receipt(sent[0].key);
    const count = action === "DISTINCT" ? (await distinctions(unit, C[concept])).length : (await relations(unit, C[concept], "broader")).length;
    assert(rc.status === 200 && count === 1, `receipt ${rc.status}, events ${count}`);
    assert((await storedOps()).length === 0, "storage not cleared");
    await waitEnabled("INVALID");
    if (action === "BROADER") await page.screenshot({ path: `${SHOTS}/${LABEL}-lost-response-found.png`, fullPage: true });
    return `"${unknown.slice(0, 150)}" → "${(await text(found)).slice(0, 150)}" | 1 POST, receipt 200 event #${rc.body.result.id}, backend events 1, storage empty, decisions re-enabled`;
  });
}

// ---------------------------------------------------------------- 3, 8, 6, 5
let k3;
await step("U1 RELATED never arrives: unknown, receipt 404, keyed panel, decisions blocked, no automatic resend", async () => {
  await goToUnit(3);
  await selectConcept("alpha");
  const before = posts.length;
  await once("**/api/knowledge-units/3/concept-links/relation", neverArrives);
  await decisionButton("RELATED").click();
  await panel().getByText("Receipt unknown.").waitFor(T);
  k3 = posts[before].key;
  const panelText = await text(panel());
  assert(panelText.includes(`Saved operation ${k3}.`), "saved key not shown");
  assert(await panel().getByRole("button", { name: "Check receipt" }).isEnabled(), "no Check receipt");
  assert(await panel().getByRole("button", { name: "Retry saved operation" }).isEnabled(), "no Retry");
  assert((await page.getByRole("button", { name: /Allow another decision/ }).count()) === 0, "allow-another offered for keyed op");
  const blocked = await Promise.all(["DISTINCT", "BROADER", "RELATED", "INVALID", "NEW CONCEPT"].map((n) => decisionButton(n).isDisabled()));
  assert(blocked.every(Boolean), `decisions not blocked: ${blocked}`);
  await sleep(3000);
  assert(postsWithKey(k3).length === 1, "resent automatically");
  const rc = await receipt(k3);
  const ops = await storedOps();
  assert(rc.status === 404 && (await relations(3, C.alpha, "related")).length === 0, "something stored");
  assert(ops.length === 1 && ops[0].operationId === k3 && ops[0].unitId === 3 && ops[0].conceptId === 1 && ops[0].relation === "related", `storage ${JSON.stringify(ops)}`);
  await page.screenshot({ path: `${SHOTS}/${LABEL}-never-arrived-keyed-panel.png`, fullPage: true });
  return `panel: "${panelText.slice(0, 260)}" | all decisions disabled, no Allow-another | after 3 s: 1 POST with key | receipt 404, 0 events | storage ${JSON.stringify(ops)}`;
});

await step("U2 editing the selection cannot change or reuse the saved payload; other unit gets no saved key", async () => {
  await selectConcept("gamma");
  const disabled = await Promise.all(["DISTINCT", "BROADER", "NARROWER", "RELATED"].map((n) => decisionButton(n).isDisabled()));
  assert(disabled.every(Boolean), "decisions enabled after editing selection");
  await decisionButton("BROADER").click({ force: true }).catch(() => {});
  assert(postsFor("/knowledge-units/3/concept-links/relation").length === 1, "a POST was sent");
  await goToUnit(4);
  const panelsOn4 = await panel().count();
  await goToUnit(3);
  await panel().getByText(`Saved operation ${k3}.`).waitFor(T);
  const ops = await storedOps();
  assert(panelsOn4 === 0 && ops.length === 1 && ops[0].conceptId === 1, "payload changed or panel leaked");
  return `with gamma selected all relation/DISTINCT buttons disabled, forced click sent nothing | unit 4 shows no recovery panel | back on unit 3 the panel still names ${k3.slice(0, 8)}… | storage still concept #1 related`;
});

await step("U3 reload restores the unresolved identity for unit 3 only", async () => {
  await page.reload();
  await openReview();
  const onUnit1 = await panel().count();
  await goToUnit(3);
  const p = panel();
  await p.getByText("Restored unresolved operation. Check its receipt or explicitly retry the saved payload.").waitFor(T);
  const t = await text(p);
  assert(t.includes(`Saved operation ${k3}.`) && onUnit1 === 0, "restored key differs or panel on unit 1");
  assert(await decisionButton("INVALID").isDisabled(), "decisions not blocked after reload");
  await p.getByRole("button", { name: "Check receipt" }).click();
  await p.getByText("Receipt unknown.").waitFor(T);
  assert(postsWithKey(k3).length === 1, "reload resent");
  await page.screenshot({ path: `${SHOTS}/${LABEL}-restored-after-reload.png`, fullPage: true });
  return `"${t.slice(0, 220)}" | unit 1 shows no panel | Check receipt after reload: 404 → "Receipt unknown" | no POST on reload`;
});

await step("U4 explicit retry sends the original key and payload once (beta selected), commits, clears storage", async () => {
  await selectConcept("beta");
  const before = posts.length;
  await panel().getByRole("button", { name: "Retry saved operation" }).click();
  const ok = page.getByText(/Recorded RELATED event #\d+ for concept #1 \(historical request result/).first();
  await ok.waitFor(T);
  const sent = posts.slice(before);
  assert(sent.length === 1, `${sent.length} POSTs`);
  const body = JSON.parse(sent[0].body);
  assert(sent[0].key === k3 && body.concept_id === 1 && body.relation === "related", `retry used ${sent[0].key} ${sent[0].body}`);
  assert(sent[0].status === 201 && sent[0].replayed === null, `status ${sent[0].status} replayed ${sent[0].replayed}`);
  const rc = await receipt(k3);
  assert(rc.status === 200 && (await relations(3, C.alpha, "related")).length === 1 && (await relations(3, C.beta, "related")).length === 0, "counts");
  assert((await storedOps()).length === 0, "storage not cleared");
  return `retry POST key ${k3.slice(0, 8)}… body ${sent[0].body} → 201 (first commit, not replayed) | "${(await text(ok)).slice(0, 120)}" | receipt 200 | unit 3 RELATED→alpha 1, RELATED→beta 0 | storage empty`;
});

// ---------------------------------------------------------------- 4, 11
await step("D1 receipt lookup before the delayed original commits says unknown (not canceled); after commit it is found; historical ≠ current", async () => {
  await goToUnit(4);
  await selectConcept("gamma");
  const d = delayDrop();
  const before = posts.length;
  await once("**/api/knowledge-units/4/concept-links/relation", d.action);
  await decisionButton("RELATED").click();
  await panel().getByText("Receipt unknown.").waitFor(T);
  const key = posts[before].key;
  await panel().getByRole("button", { name: "Check receipt" }).click();
  await panel().getByText("Receipt unknown.").waitFor(T);
  const preText = await text(panel());
  const pre = await receipt(key);
  assert(pre.status === 404 && (await relations(4, C.gamma, "related")).length === 0, "committed too early");
  const delivered = await d.deliver();
  assert(delivered.status === 201 && delivered.replayed === null, `original delivery ${delivered.status}`);
  // A later, unrelated human decision changes the current relation for the pair.
  const later = await fetch(`${BACKEND}/knowledge-units/4/concept-links/relation`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ concept_id: C.gamma, relation: "broader" }) });
  assert(later.status === 201, `later BROADER ${later.status}`);
  await panel().getByRole("button", { name: "Check receipt" }).click();
  const found = page.getByText(/Found on the server: This request committed event #\d+\. This historical result is separate from current authority\./).first();
  await found.waitFor(T);
  const rc = await receipt(key);
  const snap = (await get("/knowledge-units/4/effective-annotation")).body.snapshot;
  const effective = snap.relations.filter((r) => r.concept_id === C.gamma).map((r) => r.relation);
  assert(rc.body.request.relation === "related" && rc.body.result.relation === "related", "receipt not historical RELATED");
  assert(postsWithKey(key).length === 1 && (await storedOps()).length === 0, "resend or storage");
  const t = await bodyText();
  const claimsCurrentRelated = /current(ly)? RELATED/i.test(t);
  await page.screenshot({ path: `${SHOTS}/${LABEL}-delayed-commit-found.png`, fullPage: true });
  return `before commit: receipt 404, UI "${preText.slice(0, 160)}" | original delivered later → 201 | later unkeyed BROADER → current effective for gamma: [${effective}] | Check receipt → "${(await text(found)).slice(0, 150)}" | receipt still RELATED event #${rc.body.result.id} | UI claims current RELATED: ${claimsCurrentRelated} | 1 browser POST, storage empty`;
});

await step("D2 delayed original commits first, then explicit retry is replayed (no second event)", async () => {
  await goToUnit(5);
  await selectConcept("alpha");
  const d = delayDrop();
  const before = posts.length;
  await once("**/api/knowledge-units/5/concept-links/relation", d.action);
  await decisionButton("BROADER").click();
  await panel().getByText("Receipt unknown.").waitFor(T);
  const key = posts[before].key;
  const delivered = await d.deliver();
  await panel().getByRole("button", { name: "Retry saved operation" }).click();
  const ok = page.getByText(/Recorded BROADER event #\d+ for concept #1/).first();
  await ok.waitFor(T);
  const retry = posts.slice(before)[1];
  const events = await relations(5, C.alpha, "broader");
  assert(delivered.status === 201 && retry.key === key && retry.status === 201 && retry.replayed === "true", `delivery ${delivered.status}, retry ${retry.status} replayed ${retry.replayed}`);
  assert(events.length === 1 && events[0].id === delivered.body.id, `events ${events.length}`);
  assert(Number((await text(ok)).match(/event #(\d+)/)[1]) === delivered.body.id, "UI shows a different event");
  return `original → 201 event #${delivered.body.id}; retry same key → 201 Idempotency-Replayed: true, UI "${(await text(ok)).slice(0, 90)}…" | backend BROADER events: 1`;
});

await step("D3 retry commits before the delayed original; the late original is replayed (no second event)", async () => {
  await goToUnit(6);
  await selectConcept("beta");
  const d = delayDrop();
  const before = posts.length;
  await once("**/api/knowledge-units/6/concept-links/relation", d.action);
  await decisionButton("NARROWER").click();
  await panel().getByText("Receipt unknown.").waitFor(T);
  const key = posts[before].key;
  await panel().getByRole("button", { name: "Retry saved operation" }).click();
  await page.getByText(/Recorded NARROWER event #\d+ for concept #2/).first().waitFor(T);
  const late = await d.deliver();
  const events = await relations(6, C.beta, "narrower");
  assert(late.status === 201 && late.replayed === "true" && events.length === 1, `late ${late.status}/${late.replayed}, events ${events.length}`);
  assert(postsWithKey(key).length === 2, "unexpected POST count");
  return `retry 201 first; late original with key ${key.slice(0, 8)}… → 201 replayed=true event #${late.body.id} | backend NARROWER events: 1`;
});

// ---------------------------------------------------------------- 10
await step("V1 leave Concept Review while DISTINCT is in flight; it commits while away; nothing leaks into the unit shown on return", async () => {
  await goToUnit(7);
  await selectConcept("alpha");
  const h = hold();
  await once("**/api/knowledge-units/7/concept-distinctions", h.action);
  await decisionButton("DISTINCT").click();
  await page.getByText("Sending DISTINCT from concept #1 for unit #7").first().waitFor(T);
  await page.getByRole("button", { name: "Annotation Inspector" }).click();
  h.release("continue");
  await sleep(1500);
  const committed = (await distinctions(7, C.alpha)).length;
  const opsAway = await storedOps();
  await page.getByRole("button", { name: "Concept Review" }).click();
  await openReview();
  const shown = await shownUnit();
  const t = await bodyText();
  const leaked = /Recorded DISTINCT|unit #7/.test(t) || (await panel().count()) > 0;
  assert(committed === 1 && opsAway.length === 0 && !leaked, `committed ${committed}, storage ${JSON.stringify(opsAway)}, leaked ${leaked}`);
  return `commit while away: backend DISTINCT 1, storage cleared by the finished request | on return unit #${shown} shown, no outcome/panel for unit #7`;
});

await step("V2 return while still in flight: unit 7 restore is stale-safe; commit lands; unit shown is untouched", async () => {
  await goToUnit(8);
  await selectConcept("beta");
  const h = hold();
  const before = posts.length;
  await once("**/api/knowledge-units/8/concept-distinctions", h.action);
  await decisionButton("DISTINCT").click();
  await page.getByText("Sending DISTINCT from concept #2 for unit #8").first().waitFor(T);
  const key = posts[before].key;
  await page.getByRole("button", { name: "Annotation Inspector" }).click();
  await page.getByRole("button", { name: "Concept Review" }).click();
  await openReview();
  const shownBefore = await shownUnit();
  h.release("continue");
  await sleep(1500);
  const t = await bodyText();
  const leaked = /Recorded DISTINCT/.test(t);
  const committed = (await distinctions(8, C.beta)).length;
  await goToUnit(8);
  await page.waitForTimeout(300);
  const panelOn8 = (await panel().count()) ? await text(panel()) : "(no panel)";
  let resolved = "n/a";
  if ((await panel().count()) > 0) {
    await panel().getByRole("button", { name: "Check receipt" }).click();
    await page.getByText(/Found on the server: This request committed event/).first().waitFor(T);
    resolved = "Check receipt → found";
  }
  assert(committed === 1 && !leaked && postsWithKey(key).length === 1, `committed ${committed}, leaked ${leaked}`);
  return `unit #${shownBefore} shown during/after the late commit, no leaked outcome | backend DISTINCT 1 | unit 8 on revisit: "${panelOn8.slice(0, 160)}" | ${resolved} | storage ${JSON.stringify(await storedOps())}`;
});

await step("V3 [inj 422] definite rejection arrives while away: what remains on return", async () => {
  await goToUnit(9);
  await selectConcept("gamma");
  const h = hold();
  const before = posts.length;
  await once("**/api/knowledge-units/9/concept-distinctions", h.action);
  await decisionButton("DISTINCT").click();
  await page.getByText("Sending DISTINCT from concept #3 for unit #9").first().waitFor(T);
  const key = posts[before].key;
  await page.getByRole("button", { name: "Annotation Inspector" }).click();
  h.release("reject");
  await sleep(1000);
  const opsAway = await storedOps();
  await page.getByRole("button", { name: "Concept Review" }).click();
  await openReview();
  await goToUnit(9);
  await page.waitForTimeout(500);
  const panelText = (await panel().count()) ? await text(panel()) : "(no panel)";
  const blocked = await decisionButton("INVALID").isDisabled();
  const rc = await receipt(key);
  const events = (await distinctions(9)).length;
  await page.screenshot({ path: `${SHOTS}/${LABEL}-rejected-while-away.png`, fullPage: true });
  return `OBSERVED: rejected request (HTTP 422, server never saw it) → storage after unmount ${JSON.stringify(opsAway)} | on return unit 9: "${panelText.slice(0, 200)}" | decisions blocked: ${blocked} | receipt ${rc.status}, events ${events} | POSTs with key: ${postsWithKey(key).length}`;
});

// ---------------------------------------------------------------- 9
await step("S1 storage write fails before sending: honest alert, nothing sent, no event", async () => {
  await goToUnit(10);
  await selectConcept("alpha");
  await page.evaluate(() => (window.__storageFail = { allow: 0 }));
  const before = posts.length;
  await decisionButton("DISTINCT").click();
  const alert = page.getByRole("alert").filter({ hasText: "Browser storage failed. Nothing was sent; reload persistence cannot be guaranteed. Restore storage before submitting an annotation." });
  await alert.waitFor(T);
  await sleep(1000);
  const thrown = await page.evaluate(() => window.__storageFail.thrown);
  await page.evaluate(() => (window.__storageFail = null));
  // Storage works again, but the page keeps blocking keyed writes until reload.
  await decisionButton("BROADER").click();
  await sleep(1000);
  const sentAfterRestore = posts.length - before;
  const sameUnit = await page.getByRole("button", { name: "SAME → selected" }).isEnabled();
  assert(posts.length === before && (await distinctions(10)).length === 0 && (await relations(10, C.alpha, "broader")).length === 0, "something sent");
  await page.screenshot({ path: `${SHOTS}/${LABEL}-storage-failed.png`, fullPage: true });
  return `alert "${(await text(alert)).slice(0, 120)}" | setItem threw ${thrown}× | 0 POSTs, 0 events | after storage recovered, BROADER click sent ${sentAfterRestore} (blocked until reload; no extra message) | unkeyed SAME still enabled: ${sameUnit}`;
});

await step("S2 corrupt saved operations on load: honest alert, keyed writes blocked, nothing sent", async () => {
  await page.evaluate((k) => window.localStorage.setItem(k, "{not json"), KEY);
  await page.reload();
  await openReview();
  const alert = page.getByRole("alert").filter({ hasText: "Browser storage is unavailable or invalid. Unresolved identity cannot be recovered across reload; new keyed annotations are blocked." });
  await alert.waitFor(T);
  await goToUnit(10);
  await selectConcept("beta");
  const before = posts.length;
  await decisionButton("RELATED").click();
  await sleep(1000);
  const sent = posts.length - before;
  const raw = await page.evaluate((k) => window.localStorage.getItem(k), KEY);
  await page.evaluate((k) => window.localStorage.removeItem(k), KEY);
  await page.reload();
  await openReview();
  const alertsAfter = await page.getByRole("alert").filter({ hasText: "Browser storage" }).count();
  assert(sent === 0 && raw === "{not json" && alertsAfter === 0, `sent ${sent}, raw ${raw}, alerts ${alertsAfter}`);
  return `alert shown on load | RELATED click sent ${sent} | corrupt value left untouched | after clearing it and reloading: no storage alert`;
});

await step("S3 storage cleanup fails after commit: honest message; reload shows it again; receipt resolves it", async () => {
  await goToUnit(11);
  await selectConcept("gamma");
  await page.evaluate(() => (window.__storageFail = { allow: 1 }));
  const before = posts.length;
  await decisionButton("DISTINCT").click();
  const alert = page.getByRole("alert").filter({ hasText: "Request committed, but browser storage cleanup failed. Reload may show it again; check the receipt." });
  await alert.waitFor(T);
  const alertText = await text(alert);
  await page.evaluate(() => (window.__storageFail = null));
  const key = posts[before].key;
  const ops = await storedOps();
  await page.reload();
  await openReview();
  await goToUnit(11);
  await panel().getByText("Restored unresolved operation.").waitFor(T);
  await panel().getByRole("button", { name: "Check receipt" }).click();
  await page.getByText(/Found on the server: This request committed event/).first().waitFor(T);
  assert(postsWithKey(key).length === 1 && (await distinctions(11, C.gamma)).length === 1 && (await storedOps()).length === 0, "resend / count / storage");
  return `alert "${alertText.slice(0, 100)}" | stale storage ${ops.length} op(s) | after reload: restored panel → Check receipt → found, cleared | 1 POST, 1 event`;
});

// ---------------------------------------------------------------- 5xx, cross-unit new key
await step("X1 [inj 500] keyed NARROWER: treated as uncertain, then explicit retry commits once", async () => {
  await goToUnit(12);
  await selectConcept("alpha");
  const before = posts.length;
  await once("**/api/knowledge-units/12/concept-links/relation", (route) => route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: "internal error" }) }));
  await decisionButton("NARROWER").click();
  await panel().getByText("Receipt unknown.").waitFor(T);
  const key = posts[before].key;
  const s = await seen();
  const unknown = s.find((x) => x.includes("so its outcome is unknown"));
  await panel().getByRole("button", { name: "Retry saved operation" }).click();
  await page.getByText(/Recorded NARROWER event #\d+ for concept #1/).first().waitFor(T);
  assert(unknown && postsWithKey(key).length === 2 && (await relations(12, C.alpha, "narrower")).length === 1, "unexpected");
  return `"${unknown.slice(0, 140)}" | retry same key → committed | 2 POSTs with key (1 explicit retry) | 1 event`;
});

await step("X2 deliberate new decision on another unit while one is unresolved gets a new key", async () => {
  await goToUnit(12);
  await selectConcept("beta");
  const b1 = posts.length;
  await once("**/api/knowledge-units/12/concept-distinctions", neverArrives);
  await decisionButton("DISTINCT").click();
  await panel().getByText("Receipt unknown.").waitFor(T);
  const kA = posts[b1].key;
  await goToUnit(2);
  await selectConcept("alpha");
  const b2 = posts.length;
  await decisionButton("RELATED").click();
  await page.getByText(/Recorded RELATED event #\d+ for concept #1/).first().waitFor(T);
  const kB = posts[b2].key;
  const ops = await storedOps();
  assert(kA !== kB && ops.length === 1 && ops[0].operationId === kA, `keys ${kA} ${kB} storage ${JSON.stringify(ops)}`);
  // Leave unit 12 resolved for the regression checks below.
  await goToUnit(12);
  await panel().getByRole("button", { name: "Retry saved operation" }).click();
  await page.getByText(/Recorded DISTINCT event #\d+ for concept #2/).first().waitFor(T);
  return `unit 12 unresolved key ${kA.slice(0, 8)}…; unit 2 RELATED used new key ${kB.slice(0, 8)}… | storage kept only unit 12's op | then unit 12 retried and committed`;
});

await step("X3 [inj] receipt lookup itself fails: reported, not treated as committed or canceled; no write", async () => {
  await goToUnit(11);
  await selectConcept("beta");
  const before = posts.length;
  await once("**/api/knowledge-units/11/concept-distinctions", neverArrives);
  await decisionButton("DISTINCT").click();
  await panel().getByText("Receipt unknown.").waitFor(T);
  const key = posts[before].key;
  let aborted = false;
  await page.route("**/api/annotation-operations/*", (route) => {
    if (aborted) return route.continue();
    aborted = true;
    return route.abort("connectionreset");
  });
  await panel().getByRole("button", { name: "Check receipt" }).click();
  await page.waitForFunction(() => !document.querySelector(".reconciliation")?.textContent.includes("Receipt unknown."), null, T);
  await panel().waitFor(T);
  const failedText = await text(panel());
  const blocked = await decisionButton("INVALID").isDisabled();
  await page.unroute("**/api/annotation-operations/*");
  await panel().getByRole("button", { name: "Check receipt" }).click();
  await panel().getByText("Receipt unknown.").waitFor(T);
  await panel().getByRole("button", { name: "Retry saved operation" }).click();
  await page.getByText(/Recorded DISTINCT event #\d+ for concept #2/).first().waitFor(T);
  assert(postsWithKey(key).length === 2 && (await distinctions(11, C.beta)).length === 1 && blocked, "unexpected");
  return `failed lookup panel: "${failedText.slice(0, 220)}" | decisions still blocked: ${blocked} | next check 404 → retry → 1 event`;
});

// ---------------------------------------------------------------- HTTP-only contract probes
await step("H1 [HTTP] same key + different payload → 409 no write; same payload → replay; bad key → 400", async () => {
  const key = posts.find((p) => p.path.endsWith("/knowledge-units/1/concept-distinctions")).key;
  const send = (body, k) =>
    fetch(`${BACKEND}/knowledge-units/1/concept-distinctions`, { method: "POST", headers: { "content-type": "application/json", "idempotency-key": k }, body: JSON.stringify(body) });
  const n0 = (await distinctions(1)).length;
  const conflict = await send({ concept_id: C.beta }, key);
  const replay = await send({ concept_id: C.alpha }, key.toUpperCase());
  const bad = await send({ concept_id: C.alpha }, "not-a-uuid");
  const n1 = (await distinctions(1)).length;
  assert(conflict.status === 409 && replay.status === 201 && replay.headers.get("idempotency-replayed") === "true" && bad.status === 400 && n0 === n1, `${conflict.status} ${replay.status} ${bad.status} ${n0}->${n1}`);
  return `409 / 201 replayed (uppercase key normalized to ${replay.headers.get("idempotency-key")?.slice(0, 8)}…) / 400 | DISTINCT count ${n0}→${n1}`;
});

// ---------------------------------------------------------------- 12 regression
await step("R1 record → pin/resume → record-scoped review → back → inspect → back", async () => {
  await page.getByRole("button", { name: "Learning Records" }).click();
  await page.getByRole("button", { name: "Open record #4", exact: true }).click(T);
  const ext = page.getByRole("region", { name: "Knowledge extraction" });
  await ext.getByRole("button", { name: "Pin v1 as the current extraction…" }).click(T);
  await ext.getByRole("group", { name: "Pin v1 as the current extraction" }).getByRole("button", { name: "Pin v1" }).click(T);
  await page.waitForTimeout(800);
  const pinned = (await get("/entries/4/current-extraction")).body.selection_mode;
  await ext.getByRole("button", { name: "Resume automatic latest selection…" }).click(T);
  await ext.getByRole("group", { name: "Resume automatic latest selection" }).getByRole("button", { name: "Remove the pin" }).click(T);
  await page.waitForTimeout(800);
  const resumed = (await get("/entries/4/current-extraction")).body.selection_mode;
  await ext.getByRole("button", { name: "Review unit #10 in Concept Review" }).click(T);
  await page.getByRole("heading", { name: "Concept Review for record #4" }).waitFor(T);
  const focusUnit = await shownUnit();
  await page.getByRole("button", { name: "← Back to record #4" }).click();
  await ext.getByRole("button", { name: "Inspect unit #11" }).click(T);
  await page.getByText("Effective annotation").first().waitFor(T).catch(() => {});
  const inspected = (await bodyText()).match(/unit #11[\s\S]{0,120}/)?.[0]?.replace(/\s+/g, " ");
  await page.getByRole("button", { name: "← Back to record #4" }).click();
  await ext.waitFor(T);
  await page.getByRole("button", { name: "Annotation Inspector" }).click();
  await page.waitForTimeout(800);
  const insp = (await bodyText()).includes("Annotation Inspector");
  await page.getByRole("button", { name: "Experiment Dashboard" }).click();
  await page.waitForTimeout(800);
  await page.getByRole("button", { name: "Concept Review" }).click();
  await openReview();
  assert(pinned === "pinned" && resumed === "automatic" && focusUnit === 10 && insp, `pinned ${pinned} resumed ${resumed} focus ${focusUnit}`);
  return `pin → ${pinned}, resume → ${resumed} | record-scoped review opened unit #${focusUnit}, back OK | inspect: "${inspected?.slice(0, 100)}" | inspector/dashboard/review tabs OK`;
});

const final = await storedOps();
const keyed = posts.filter((p) => p.path.match(/concept-distinctions|concept-links\/relation/));
const unkeyed = keyed.filter((p) => !p.key);
results.push(`${unkeyed.length ? "FAIL" : "PASS"}  K1 every browser DISTINCT/relation POST carried an Idempotency-Key (${keyed.length} POSTs, ${new Set(keyed.map((p) => p.key)).size} keys, unkeyed ${unkeyed.length})`);
results.push(`INFO  final saved operations: ${JSON.stringify(final)}`);
const unexpected = consoleErrors.filter((t) => !/ERR_CONNECTION_RESET|status of (422|500)|Failed to load resource|Failed to fetch/.test(t));
results.push(`${unexpected.length ? "FAIL" : "PASS"}  C1 console errors: ${consoleErrors.length} total, all from injected faults${unexpected.length ? "; unexpected: " + unexpected.join(" | ") : ""}`);
console.log(`=== ${LABEL} (${ORIGIN})`);
for (const r of results) console.log(r);
await browser.close();
