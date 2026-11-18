// FLH-152 phone walk (Playwright, real Chromium), driven by upgrade_walk.py on
// a database seeded by the pre-revision build:
//   u05: list -> lesson notice -> preview -> cancel -> preview -> update ->
//        reopen (list and lesson) -> the old mistake opens revision 1
//   stale: previews of two outdated lessons are opened, the server swaps to a
//        build with a changed pack, another client updates the second lesson;
//        confirming the first shows the stale-preview error and the fresh
//        preview (then confirms it), confirming the second says it is already
//        updated.
// At 390x844 (touch), in English and Simplified Chinese. The copy below is
// transcribed from web/src/i18n/en.ts and zh-CN.ts and must appear on the page
// character for character. Results in results-TAG.json, screenshots in
// shots-TAG/.
import { chromium } from "playwright";
import fs from "node:fs";

const TAG = process.env.TAG || "run";
const OUT = process.env.OUT || ".";
const CTL = process.env.CTL;
const COMBOS = (process.env.COMBOS || "phone-en").split(",");
const SHOTS = `${OUT}/shots-${TAG}`;
fs.mkdirSync(SHOTS, { recursive: true });
const results = [];
const check = (name, pass, detail = "") => results.push({ name, pass: !!pass, detail: typeof detail === "string" ? detail : JSON.stringify(detail) });
const info = (name, detail) => results.push({ name: "INFO " + name, pass: true, detail: typeof detail === "string" ? detail : JSON.stringify(detail) });
const shot = (page, name) => page.screenshot({ path: `${SHOTS}/${name}.png` });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const MAIN = "ls-wb1-u05";
const Q = 4;

// Application copy, verbatim from web/src/i18n/en.ts and zh-CN.ts.
const EN = {
  listening: "Listening",
  notebook: "Mistake Notebook",
  scripts: "Workbook listening scripts",
  open: (t) => `Open ${t}`,
  entry: (id) => `Mistake, record #${id}`,
  openSource: "Open source",
  shown: (n) => `Question ${n} is marked below.`,
  updateAvailable: "Update available",
  revision: (n) => `Revision ${n}`,
  region: "Script update",
  available: (n) => `A corrected version of this script is available. This lesson stays as it is (revision ${n}) until you review the changes and update it.`,
  review: "Review the changes",
  heading: (a, b) => `What the update changes: revision ${a} → ${b}`,
  previous: (a, b) => `Your earlier practice stays with revision ${a}: items you saved keep their wording, your answer and their Mistake Notebook link, and the update only adds revision ${b}.`,
  questionChanged: (n) => `Question ${n} changed:`,
  fieldExplanation: "explanation",
  fieldOptions: "options",
  confirm: (n) => `Update this lesson to revision ${n}`,
  cancel: "Not now",
  updated: (a, b) => `This lesson now shows revision ${b}. Items you saved from revision ${a} stay in the Mistake Notebook exactly as you saved them.`,
  already: (n) => `This lesson already shows revision ${n}, the current version, so nothing was changed again.`,
  stale: "This lesson or the script pack changed after you opened these changes, so nothing was updated. Below is what an update would change now.",
  earlierRegion: "The revision you saved from",
  earlierHeading: (n) => `Revision ${n}: the version you saved from`,
};
const ZH = {
  listening: "听力",
  notebook: "错题本",
  scripts: "练习册听力脚本",
  open: (t) => `打开 ${t}`,
  entry: (id) => `错误，记录 #${id}`,
  openSource: "打开来源",
  shown: (n) => `第 ${n} 题已在下方标出。`,
  updateAvailable: "有更新",
  revision: (n) => `第 ${n} 版`,
  region: "脚本更新",
  available: (n) => `这份脚本有更正后的版本。在你查看改动并更新之前，这节课保持原样（第 ${n} 版）。`,
  review: "查看改动",
  heading: (a, b) => `更新会改动什么：第 ${a} 版 → 第 ${b} 版`,
  previous: (a, b) => `你之前的练习留在第 ${a} 版：已保存的条目保留原来的文字、你的答案和错题本链接，更新只会新增第 ${b} 版。`,
  questionChanged: (n) => `第 ${n} 题有改动：`,
  fieldExplanation: "解释",
  fieldOptions: "选项",
  confirm: (n) => `把这节课更新到第 ${n} 版`,
  cancel: "暂不更新",
  updated: (a, b) => `这节课现在显示第 ${b} 版。你从第 ${a} 版保存的条目在错题本中按原样保留。`,
  already: (n) => `这节课已经显示当前的第 ${n} 版，所以没有再次改动。`,
  stale: "你打开这些改动之后，这节课或脚本包又有变化，所以没有更新。下面是现在更新会改动的内容。",
  earlierRegion: "你保存时的版本",
  earlierHeading: (n) => `第 ${n} 版：你保存时的版本`,
};
// English phrases that must not appear in the Chinese revision UI.
const ENGLISH_LEAKS = ["Review the changes", "Not now", "Update this lesson", "Revision ", "nothing was updated", "Script update"];

const api = async (base, method, path, body) => {
  const r = await fetch(base + "/api" + path, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  let json = null;
  try {
    json = await r.json();
  } catch {}
  return { status: r.status, json, replayed: r.headers.get("Idempotency-Replayed") };
};

async function signal(name) {
  fs.writeFileSync(`${CTL}/${name}`, "done");
}
async function waitFile(name) {
  for (let i = 0; i < 3000; i++) {
    if (fs.existsSync(`${CTL}/${name}`)) return fs.readFileSync(`${CTL}/${name}`, "utf8").trim();
    await sleep(100);
  }
  throw new Error(`no ${name}`);
}

async function noOverflow(page, where) {
  const o = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth }));
  check(`${where}: no horizontal scroll at phone width`, o.scrollWidth <= o.innerWidth, o);
}

// Is the element inside the viewport (the learner can see it without scrolling)?
const inView = (loc) =>
  loc.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { top: Math.round(r.top), bottom: Math.round(r.bottom), vh: window.innerHeight, visible: r.top >= 0 && r.bottom <= window.innerHeight };
  });
const focused = (page) => page.evaluate(() => ({ tag: document.activeElement?.tagName, text: (document.activeElement?.textContent || "").trim().slice(0, 80) }));

function watch(page) {
  const w = { writes: [], errors: [], expected409: [] };
  page.on("request", (r) => {
    if (!["GET", "HEAD"].includes(r.method()) && r.url().includes("/api/")) w.writes.push(`${r.method()} ${new URL(r.url()).pathname}`);
  });
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    // Chromium logs every non-2xx fetch; a 409 here is the stale preview under test.
    if (/status of 409/.test(m.text())) w.expected409.push(m.text());
    else w.errors.push(m.text());
  });
  page.on("pageerror", (e) => w.errors.push(String(e)));
  return w;
}

async function openLesson(page, L, title) {
  await page.getByRole("button", { name: L.listening, exact: true }).first().click();
  const scripts = page.getByRole("region", { name: L.scripts });
  await scripts.waitFor();
  const row = scripts.locator("li").filter({ hasText: title });
  await row.getByRole("button", { name: L.open(title) }).waitFor();
  const rowText = await row.innerText();
  await row.getByRole("button", { name: L.open(title) }).click();
  await page.getByRole("heading", { name: title }).waitFor();
  await sleep(300);
  return rowText;
}

const revisionOf = async (base, id) => (await api(base, "GET", `/listening/materials/${id}`)).json.script_revision;

async function walk(browser, combo, base) {
  const L = combo.endsWith("zh") ? ZH : EN;
  const p = combo;
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: combo.endsWith("zh") ? "zh-CN" : "en-GB" });
  if (combo.endsWith("zh")) await ctx.addInitScript(() => window.localStorage.setItem("flh.ui-locale.v1", "zh-CN"));
  const page = await ctx.newPage();
  const w = watch(page);

  const list = (await api(base, "GET", "/listening/scripts")).json.scripts;
  const byId = Object.fromEntries(list.map((s) => [s.id, s]));
  const outdated = list.filter((s) => s.id !== MAIN && s.pack_status === "update_available").map((s) => s.id).sort();
  const [B, D] = outdated;
  const main = byId[MAIN];
  const mid = main.imported_material_id;
  const lesson0 = (await api(base, "GET", `/listening/materials/${mid}`)).json;
  const ex1 = lesson0.current_exercise_id;
  const nb0 = (await api(base, "GET", "/mistake-notebook/items")).json.items;
  const oldEntry = nb0.find((i) => i.source.record_id === ex1 && i.source.item === Q);
  info(`${p}: setup`, { mid, ex1, oldEntry: oldEntry?.entry_id, B, D, revision: lesson0.script_revision });

  // A1. The list tags the imported script.
  await page.goto(base + "/");
  const rowText = await openLesson(page, L, main.title);
  check(`${p}: list row shows "${L.revision(1)}" and "${L.updateAvailable}"`, rowText.includes(L.revision(1)) && rowText.includes(L.updateAvailable), rowText);

  // A2. Lesson load: the notice only, no update button, nothing written.
  const region = page.getByRole("region", { name: L.region });
  await region.waitFor();
  const noticeText = await region.innerText();
  check(`${p}: notice copy is exact`, noticeText.includes(L.available(1)), noticeText);
  check(`${p}: no update button on lesson load`, (await page.getByRole("button", { name: L.confirm(2) }).count()) === 0);
  await region.scrollIntoViewIfNeeded();
  await shot(page, `${p}-A2-notice`);
  await noOverflow(page, `${p} lesson`);

  // A3. Preview.
  await region.getByRole("button", { name: L.review }).click();
  const heading = region.getByRole("heading", { name: L.heading(1, 2) });
  await heading.waitFor();
  await sleep(200);
  const prev = await region.innerText();
  check(`${p}: preview heading, earlier-practice sentence and question ${Q} change are exact`,
    prev.includes(L.previous(1, 2)) && prev.includes(L.questionChanged(Q)) && prev.includes(L.fieldExplanation), prev.slice(0, 500));
  check(`${p}: preview heading has focus`, await heading.evaluate((el) => el === document.activeElement));
  check(`${p}: preview buttons "${L.confirm(2)}" and "${L.cancel}"`,
    (await region.getByRole("button", { name: L.confirm(2) }).count()) === 1 && (await region.getByRole("button", { name: L.cancel }).count()) === 1);
  await shot(page, `${p}-A3-preview`);
  await noOverflow(page, `${p} preview`);

  // A4. Cancel: back to the notice, nothing written, still revision 1.
  await region.getByRole("button", { name: L.cancel }).click();
  await sleep(200);
  const afterCancel = await revisionOf(base, mid);
  check(`${p}: cancel closes the preview and shows the notice again`,
    (await region.getByRole("heading", { name: L.heading(1, 2) }).count()) === 0 && (await region.getByRole("button", { name: L.review }).count()) === 1 && (await page.getByRole("button", { name: L.confirm(2) }).count()) === 0);
  const fc = await focused(page);
  check(`${p}: after cancel, keyboard focus returns to "${L.review}"`, fc.tag === "BUTTON" && fc.text === L.review, fc);
  check(`${p}: after cancel nothing was written and the lesson is still revision 1`,
    w.writes.length === 0 && afterCancel.revision === 1 && afterCancel.pack_status === "update_available", { writes: w.writes, afterCancel });
  await shot(page, `${p}-A4-cancelled`);

  // A5. Update.
  await region.getByRole("button", { name: L.review }).click();
  await region.getByRole("heading", { name: L.heading(1, 2) }).waitFor();
  const posted = page.waitForResponse((r) => r.url().endsWith(`/api/listening/materials/${mid}/script-update`) && r.request().method() === "POST");
  await region.getByRole("button", { name: L.confirm(2) }).click();
  const up = await posted;
  await page.getByText(L.updated(1, 2)).waitFor();
  await sleep(300);
  check(`${p}: update answered 201 and the success copy is exact`, up.status() === 201, up.status());
  check(`${p}: after the update the success message is on screen`, (await inView(page.getByRole("status").filter({ hasText: L.updated(1, 2) }))).visible,
    await inView(page.getByRole("status").filter({ hasText: L.updated(1, 2) })));
  check(`${p}: notice gone, "${L.revision(2)}" shown`, (await page.getByRole("region", { name: L.region }).count()) === 0 && (await page.locator(".tag", { hasText: L.revision(2) }).count()) > 0);
  await shot(page, `${p}-A5-updated`);

  // A6. Reopen: a fresh page load, the list, the lesson.
  await page.reload();
  const rowText2 = await openLesson(page, L, main.title);
  const rev2 = await revisionOf(base, mid);
  check(`${p}: after reopening, the list says "${L.revision(2)}" without "${L.updateAvailable}"`, rowText2.includes(L.revision(2)) && !rowText2.includes(L.updateAvailable), rowText2);
  check(`${p}: after reopening, the lesson has no notice and is revision 2, up to date`,
    (await page.getByRole("region", { name: L.region }).count()) === 0 && rev2.revision === 2 && rev2.pack_status === "up_to_date", rev2);
  await shot(page, `${p}-A6-reopened`);
  await noOverflow(page, `${p} reopened lesson`);

  // A7. The old mistake opens revision 1.
  await page.getByRole("button", { name: L.notebook, exact: true }).first().click();
  const entry = page.getByRole("group", { name: L.entry(oldEntry.entry_id) });
  await entry.waitFor();
  await entry.getByRole("button", { name: L.openSource }).click();
  const earlier = page.getByRole("region", { name: L.earlierRegion });
  await earlier.waitFor();
  await sleep(400);
  check(`${p}: the old mistake opens "${L.earlierHeading(1)}" with question ${Q} marked`,
    (await earlier.getByRole("heading", { name: L.earlierHeading(1) }).count()) === 1 && (await page.locator(".notebook-origin").innerText()).includes(L.shown(Q)));
  await shot(page, `${p}-A7-old-mistake-revision-1`);
  await noOverflow(page, `${p} old mistake`);
  check(`${p}: writes so far: the one update`, JSON.stringify(w.writes) === JSON.stringify([`POST /api/listening/materials/${mid}/script-update`]), w.writes);

  // S1. Two previews opened on the current pack.
  await page.goto(base + "/");
  await openLesson(page, L, byId[B].title);
  const rB = page.getByRole("region", { name: L.region });
  await rB.getByRole("button", { name: L.review }).click();
  await rB.getByRole("heading", { name: L.heading(1, 2) }).waitFor();
  const page2 = await ctx.newPage();
  const w2 = watch(page2);
  await page2.goto(base + "/");
  await openLesson(page2, L, byId[D].title);
  const rD = page2.getByRole("region", { name: L.region });
  await rD.getByRole("button", { name: L.review }).click();
  await rD.getByRole("heading", { name: L.heading(1, 2) }).waitFor();
  const previewB0 = await rB.innerText();

  // S2. The pack changes (server swap); another client updates D on it.
  await signal(`${combo}.swap`);
  await waitFile(`${combo}.swapped`);
  const pd = (await api(base, "GET", `/listening/materials/${byId[D].imported_material_id}/script-update`)).json;
  const other = await api(base, "POST", `/listening/materials/${byId[D].imported_material_id}/script-update`, { from_revision: pd.current_revision, pack_fingerprint: pd.pack_fingerprint });
  info(`${p}: after the swap another client updated ${D}`, { status: other.status, revision: other.json?.revision });

  // S3. Confirming B's old preview: the stale-preview error and a fresh preview.
  const stale = page.waitForResponse((r) => r.url().endsWith(`/api/listening/materials/${byId[B].imported_material_id}/script-update`) && r.request().method() === "POST");
  await rB.getByRole("button", { name: L.confirm(2) }).click();
  const sr = await stale;
  await rB.getByText(L.stale).waitFor();
  await sleep(300);
  const staleText = await rB.innerText();
  const bAfter = await revisionOf(base, byId[B].imported_material_id);
  check(`${p}: stale confirmation answered 409 stale_preview`, sr.status() === 409 && (await sr.json()).code === "stale_preview", sr.status());
  check(`${p}: stale-preview error copy is exact and announced (role alert)`,
    staleText.includes(L.stale) && (await rB.getByRole("alert").filter({ hasText: L.stale }).count()) === 1, staleText.slice(0, 400));
  const sent = JSON.parse(sr.request().postData());
  const fresh = (await sr.json()).preview;
  check(`${p}: the fresh preview is for the new pack, lists its change ("${L.fieldOptions}"), and nothing was updated`,
    fresh.pack_fingerprint !== sent.pack_fingerprint && staleText !== previewB0 && staleText.includes(L.fieldOptions) && bAfter.revision === 1 && bAfter.pack_status === "update_available",
    { sent: sent.pack_fingerprint, fresh: fresh.pack_fingerprint, bAfter });
  await rB.getByRole("alert").filter({ hasText: L.stale }).scrollIntoViewIfNeeded();
  await shot(page, `${p}-S3-stale-preview`);
  await noOverflow(page, `${p} stale preview`);

  // S4. Confirming the fresh preview updates B.
  const ok = page.waitForResponse((r) => r.url().endsWith(`/api/listening/materials/${byId[B].imported_material_id}/script-update`) && r.request().method() === "POST");
  await rB.getByRole("button", { name: L.confirm(2) }).click();
  const okr = await ok;
  await page.getByText(L.updated(1, 2)).waitFor();
  const bFinal = await revisionOf(base, byId[B].imported_material_id);
  check(`${p}: after confirming the fresh preview the success message is on screen`, (await inView(page.getByRole("status").filter({ hasText: L.updated(1, 2) }))).visible,
    await inView(page.getByRole("status").filter({ hasText: L.updated(1, 2) })));
  check(`${p}: confirming the fresh preview: 201, revision 2 on the new pack`, okr.status() === 201 && bFinal.revision === 2 && bFinal.pack_status === "up_to_date", { status: okr.status(), bFinal });
  await shot(page, `${p}-S4-fresh-preview-confirmed`);

  // S5. D's old preview after another client updated it: "already".
  const dPost = page2.waitForResponse((r) => r.url().endsWith(`/api/listening/materials/${byId[D].imported_material_id}/script-update`) && r.request().method() === "POST");
  await rD.getByRole("button", { name: L.confirm(2) }).click();
  const dr = await dPost;
  await page2.getByText(L.already(2)).waitFor();
  await sleep(300);
  const dFinal = await revisionOf(base, byId[D].imported_material_id);
  check(`${p}: the "already" message is on screen`, (await inView(page2.getByRole("status").filter({ hasText: L.already(2) }))).visible,
    await inView(page2.getByRole("status").filter({ hasText: L.already(2) })));
  check(`${p}: a preview already applied elsewhere: 409, then the "already" copy, still revision 2`,
    other.status === 201 && dr.status() === 409 && dFinal.revision === 2 && dFinal.pack_status === "up_to_date", { other: other.status, status: dr.status(), dFinal });
  await shot(page2, `${p}-S5-already-updated`);
  await noOverflow(page2, `${p} already updated`);

  if (combo.endsWith("zh")) {
    const texts = [noticeText, prev, staleText, await page2.locator("body").innerText()].join("\n");
    const leaks = ENGLISH_LEAKS.filter((e) => texts.includes(e));
    check(`${p}: no English revision copy in the Chinese UI`, leaks.length === 0, leaks);
  }
  const bId = byId[B].imported_material_id;
  check(`${p}: writes: u05 once, ${B} twice (stale, then fresh), ${D} once from this tab`,
    JSON.stringify(w.writes) === JSON.stringify([`POST /api/listening/materials/${mid}/script-update`, `POST /api/listening/materials/${bId}/script-update`, `POST /api/listening/materials/${bId}/script-update`]) &&
      JSON.stringify(w2.writes) === JSON.stringify([`POST /api/listening/materials/${byId[D].imported_material_id}/script-update`]), { w: w.writes, w2: w2.writes });
  check(`${p}: no console errors other than the two expected 409s`, w.errors.length === 0 && w2.errors.length === 0 && w.expected409.length + w2.expected409.length === 2,
    { errors: [...w.errors, ...w2.errors], expected409: [...w.expected409, ...w2.expected409] });
  await ctx.close();
}

const browser = await chromium.launch();
info("browser", `Chromium ${browser.version()}`);
try {
  for (const combo of COMBOS) {
    const base = await waitFile(`${combo}.url`);
    try {
      await walk(browser, combo, base);
    } catch (e) {
      check(`${combo} walk ran`, false, String(e).slice(0, 500));
      if (!fs.existsSync(`${CTL}/${combo}.swap`)) await signal(`${combo}.swap`);
    }
    await signal(`${combo}.done`);
  }
} finally {
  await browser.close();
  fs.writeFileSync(`${OUT}/results-${TAG}.json`, JSON.stringify(results, null, 1));
}
const failed = results.filter((r) => !r.pass);
for (const r of results) console.log(`${r.pass ? "PASS" : "FAIL"} ${r.name}${r.pass && !r.name.startsWith("INFO") ? "" : " :: " + r.detail.slice(0, 300)}`);
console.log(`${results.filter((r) => r.pass && !r.name.startsWith("INFO")).length}/${results.filter((r) => !r.name.startsWith("INFO")).length} checks passed`);
process.exit(failed.length ? 1 : 0);
