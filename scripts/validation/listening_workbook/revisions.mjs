// Real-Chromium walkthrough of a workbook script revision (Playwright), driven
// by revisions.py, which swaps an OLD server (pack before a correction) for a
// NEW one on the same scratch database between the two parts of each run:
//   old UI: import ls-wb1-u05 -> answer question 4 wrongly -> reveal -> save it
//   new UI: script list -> lesson (notice only, nothing changed) -> old mistake
//           -> update preview -> update -> reopen the old mistake (revision 1)
//           -> a new mistake saved against revision 2 (and, in its answer
//           overview, a typed answer self-assessed in its row)
// at phone (390x844, touch) and desktop (1280x900), in English and Chinese.
// Every check records pass/fail + detail in results-TAG.json; screenshots in
// shots-TAG/. Nothing here uses a provider or the daily database.
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
const shot = (page, name, opts = {}) => page.screenshot({ path: `${SHOTS}/${name}.png`, ...opts });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const SCRIPT = "ls-wb1-u05";
const TITLE = "À l'accueil de la Maison des langues";
const Q = 4; // u05-l04, corrected by the 2026-11-11 evidence audit

const EN = {
  listening: "Listening",
  notebook: "Mistake Notebook",
  scripts: "Workbook listening scripts",
  open: (t) => `Open ${t}`,
  updateAvailable: "Update available",
  revision: (n) => `Revision ${n}`,
  updateRegion: "Script update",
  available: "A corrected version of this script is available.",
  review: "Review the changes",
  previewHeading: (a, b) => `What the update changes: revision ${a} → ${b}`,
  previous: (a, b) => `Your earlier practice stays with revision ${a}: items you saved keep their wording, your answer and their Mistake Notebook link, and the update only adds revision ${b}.`,
  questionChanged: (n) => `Question ${n} changed:`,
  field: "explanation",
  confirm: (n) => `Update this lesson to revision ${n}`,
  updated: (a, b) => `This lesson now shows revision ${b}. Items you saved from revision ${a} stay in the Mistake Notebook exactly as you saved them.`,
  entry: (id) => `Mistake, record #${id}`,
  show: "Show reference",
  openSource: "Open source",
  shown: (n) => `Question ${n} is marked below.`,
  earlierRegion: "The revision you saved from",
  earlierHeading: (n) => `Revision ${n}: the version you saved from`,
  choice: (n) => `Your choice for question ${n}`,
  reveal: "Reveal answers and evidence",
  reference: (n) => `Reference for question ${n}`,
  saveOpen: "Save as a learning question…",
  saveForm: (n) => `Save a missed point from question ${n}`,
  saveLabel: "What did you miss, or what do you want to ask?",
  saveConfirm: "Save learning record",
  saved: /Saved as learning record #(\d+)/,
  answer: (n) => `Your answer to question ${n}`,
  rowCheck: (n) => `Your own comparison for question ${n} (kept on this page only)`,
  questionCheck: (n) => `Self-check for question ${n} (kept on this page only)`,
  missed: "I missed it",
};
const ZH = {
  listening: "听力",
  notebook: "错题本",
  scripts: "练习册听力脚本",
  open: (t) => `打开 ${t}`,
  updateAvailable: "有更新",
  revision: (n) => `第 ${n} 版`,
  updateRegion: "脚本更新",
  available: "这份脚本有更正后的版本。",
  review: "查看改动",
  previewHeading: (a, b) => `更新会改动什么：第 ${a} 版 → 第 ${b} 版`,
  previous: (a, b) => `你之前的练习留在第 ${a} 版：已保存的条目保留原来的文字、你的答案和错题本链接，更新只会新增第 ${b} 版。`,
  questionChanged: (n) => `第 ${n} 题有改动：`,
  field: "解释",
  confirm: (n) => `把这节课更新到第 ${n} 版`,
  updated: (a, b) => `这节课现在显示第 ${b} 版。你从第 ${a} 版保存的条目在错题本中按原样保留。`,
  entry: (id) => `错误，记录 #${id}`,
  show: "显示参考",
  openSource: "打开来源",
  shown: (n) => `第 ${n} 题已在下方标出。`,
  earlierRegion: "你保存时的版本",
  earlierHeading: (n) => `第 ${n} 版：你保存时的版本`,
  choice: (n) => `你对第 ${n} 题的选择`,
  reveal: "显示答案和依据",
  reference: (n) => `第 ${n} 题的参考`,
  saveOpen: "保存为学习问题…",
  saveForm: (n) => `保存第 ${n} 题中没掌握的点`,
  saveLabel: "你没掌握什么，或想问什么？",
  saveConfirm: "保存学习记录",
  saved: /已保存为学习记录 #(\d+)/,
  answer: (n) => `你对第 ${n} 题的回答`,
  rowCheck: (n) => `第 ${n} 题你自己的对照结果（只保留在本页面）`,
  questionCheck: (n) => `第 ${n} 题的自我检查（只保留在本页面）`,
  missed: "我没答对",
};

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
async function waitUrl(name) {
  for (let i = 0; i < 3000; i++) {
    if (fs.existsSync(`${CTL}/${name}`)) return fs.readFileSync(`${CTL}/${name}`, "utf8").trim();
    await sleep(100);
  }
  throw new Error(`no ${name}`);
}

const box = (loc) =>
  loc.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { top: Math.round(r.top), bottom: Math.round(r.bottom), vh: window.innerHeight };
  });
async function noOverflow(page, where) {
  const o = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth }));
  check(`${where}: no horizontal scroll`, o.scrollWidth <= o.innerWidth, o);
}

function contextFor(browser, combo) {
  const phone = combo.startsWith("phone");
  return browser.newContext({
    viewport: phone ? { width: 390, height: 844 } : { width: 1280, height: 900 },
    deviceScaleFactor: phone ? 2 : 1,
    isMobile: phone,
    hasTouch: phone,
    locale: combo.endsWith("zh") ? "zh-CN" : "en-GB",
  });
}

function watch(page) {
  const w = { writes: [], errors: [] };
  page.on("request", (r) => {
    if (!["GET", "HEAD"].includes(r.method()) && r.url().includes("/api/")) w.writes.push(`${r.method()} ${new URL(r.url()).pathname}`);
  });
  page.on("console", (m) => m.type() === "error" && w.errors.push(m.text()));
  page.on("pageerror", (e) => w.errors.push(String(e)));
  return w;
}

// Save the missed point of question Q in the given exercise section.
async function saveMissed(page, L, section, text) {
  const ref = section.getByRole("group", { name: L.reference(Q) });
  await ref.getByRole("button", { name: L.saveOpen }).click();
  const form = page.getByRole("form", { name: L.saveForm(Q) });
  await form.getByLabel(L.saveLabel).fill(text);
  const attempt = form.getByRole("checkbox");
  if (await attempt.count()) await attempt.check();
  const resp = page.waitForResponse((r) => r.url().endsWith("/api/captures") && r.request().method() === "POST");
  await form.getByRole("button", { name: L.saveConfirm }).click();
  const r = await resp;
  const status = page.getByRole("status").filter({ hasText: L.saved });
  await status.waitFor();
  return { status: r.status(), capture: JSON.parse(r.request().postData()), entryId: Number((await status.innerText()).match(L.saved)[1]) };
}

// Old UI (English): import, answer question Q wrongly, reveal, save it.
async function oldPart(browser, combo, base) {
  const L = EN;
  const ctx = await contextFor(browser, combo.replace(/-zh$/, "-en"));
  const page = await ctx.newPage();
  await page.goto(base + "/");
  await page.getByRole("button", { name: L.listening, exact: true }).click();
  await page.getByRole("region", { name: L.scripts }).waitFor();
  const imported = page.waitForResponse((r) => r.url().endsWith(`/api/listening/scripts/${SCRIPT}`) && r.request().method() === "POST");
  await page.getByRole("button", { name: `Import ${TITLE}` }).click();
  const resp = await imported;
  const lesson = await resp.json();
  await page.getByRole("heading", { name: TITLE }).waitFor();
  const exercise = lesson.exercises[0];
  const item = exercise.content.items[Q - 1];
  const wrong = item.choices.find((c) => c !== item.expected_answer);
  await page.getByRole("group", { name: L.choice(Q) }).getByLabel(wrong, { exact: true }).check();
  await page.getByRole("button", { name: L.reveal }).click();
  const saved = await saveMissed(page, L, page, "Je n'ai pas compris pourquoi l'horaire du soir lui convient.");
  await shot(page, `${combo}-A1-old-ui-saved`);
  check(`${combo} old: import 201 and the mistake saved 201`, resp.status() === 201 && saved.status === 201, { import: resp.status(), save: saved.status });
  await ctx.close();
  return { materialId: lesson.material.id, exerciseId: exercise.id, entryId: saved.entryId, oldWhy: item.rationale_en, wrong };
}

// New UI in the combination's language.
async function newPart(browser, combo, base, old) {
  const L = combo.endsWith("zh") ? ZH : EN;
  const ctx = await contextFor(browser, combo);
  if (combo.endsWith("zh")) await ctx.addInitScript(() => window.localStorage.setItem("flh.ui-locale.v1", "zh-CN"));
  const page = await ctx.newPage();
  const w = watch(page);
  const p = combo;

  // 1. The script list says an update is available; nothing changed.
  await page.goto(base + "/");
  await page.getByRole("button", { name: L.listening, exact: true }).click();
  const scripts = page.getByRole("region", { name: L.scripts });
  await scripts.waitFor();
  const row = scripts.locator("li").filter({ hasText: TITLE });
  await row.getByRole("button", { name: L.open(TITLE) }).waitFor();
  await row.getByText(L.updateAvailable).waitFor({ timeout: 3000 }).catch(() => {});
  const rowText = await row.innerText();
  check(`${p}: the list tags the imported script "${L.updateAvailable}" and "${L.revision(1)}"`, rowText.includes(L.updateAvailable) && rowText.includes(L.revision(1)), rowText);
  await row.scrollIntoViewIfNeeded();
  await shot(page, `${p}-B01-list`);

  // 2. The lesson: a notice, no update button, the old wording kept.
  await row.getByRole("button", { name: L.open(TITLE) }).click();
  await page.getByRole("heading", { name: TITLE }).waitFor();
  const notice = page.getByRole("region", { name: L.updateRegion });
  await notice.waitFor({ timeout: 5000 }).catch(() => {});
  const hasNotice = (await notice.count()) === 1;
  check(`${p}: the lesson announces the corrected version`, hasNotice && (await notice.innerText()).includes(L.available), hasNotice ? await notice.innerText() : "no notice");
  check(`${p}: no update button on load`, (await page.getByRole("button", { name: L.confirm(2) }).count()) === 0);
  const before = await api(base, "GET", `/listening/materials/${old.materialId}`);
  const cur = before.json.exercises.find((e) => e.id === before.json.current_exercise_id);
  check(`${p}: before the update the lesson still shows revision 1 with its wording`,
    before.json.current_exercise_id === old.exerciseId && before.json.script_revision?.pack_status === "update_available" && cur.content.items[Q - 1].rationale_en === old.oldWhy,
    { current: before.json.current_exercise_id, state: before.json.script_revision });
  await shot(page, `${p}-B02-lesson-notice`);
  await noOverflow(page, `${p} lesson`);

  // 3. The old mistake, before any update: the same question, marked.
  await page.getByRole("button", { name: L.notebook, exact: true }).first().click();
  let entry = page.getByRole("group", { name: L.entry(old.entryId) });
  await entry.waitFor();
  await entry.getByRole("button", { name: L.openSource }).click();
  await page.getByRole("heading", { name: TITLE }).waitFor();
  await sleep(400);
  check(`${p}: the old mistake opens its question, marked`, (await page.locator(".notebook-origin").innerText()).includes(L.shown(Q)));
  await shot(page, `${p}-B03-old-mistake-before-update`);

  if (!hasNotice) {
    // A server without the update path: record what the learner sees, and stop.
    await page.getByRole("button", { name: L.reveal }).click();
    const ref = page.getByRole("group", { name: L.reference(Q) });
    await ref.scrollIntoViewIfNeeded();
    info(`${p}: question ${Q} after reveal, without an update path`, (await ref.innerText()).slice(0, 400));
    await shot(page, `${p}-B03b-old-wording-after-reveal`);
    const reimport = await api(base, "POST", `/listening/scripts/${SCRIPT}`);
    info(`${p}: re-import without an update path`, { status: reimport.status, code: reimport.json?.code });
    check(`${p}: an explicit update path exists`, false, "no notice, no preview route");
    await ctx.close();
    return;
  }

  // 4. The preview: what changes, what happens to earlier practice; key hidden.
  check(`${p}: reading the lesson and the notebook wrote nothing`, w.writes.length === 0, w.writes);
  const notice2 = page.getByRole("region", { name: L.updateRegion });
  await notice2.getByRole("button", { name: L.review }).click();
  const heading = notice2.getByRole("heading", { name: L.previewHeading(1, 2) });
  await heading.waitFor();
  await sleep(200);
  check(`${p}: the preview heading takes focus`, await heading.evaluate((el) => el === document.activeElement));
  const preview = await notice2.innerText();
  check(`${p}: the preview explains previous practice in one sentence`, preview.includes(L.previous(1, 2)), preview.slice(0, 400));
  check(`${p}: the preview names question ${Q} and what changed`, preview.includes(L.questionChanged(Q)) && preview.includes(L.field), preview.slice(0, 600));
  check(`${p}: the exact before/after stays closed`, !(await notice2.locator("details").evaluate((d) => d.open)));
  check(`${p}: the preview does not show the reference answer`, !(await notice2.locator("ul.listening-revision-changes").innerText()).includes("17 h 30"));
  check(`${p}: previewing wrote nothing`, w.writes.length === 0, w.writes);
  await heading.scrollIntoViewIfNeeded();
  await shot(page, `${p}-B04-preview`);
  await noOverflow(page, `${p} preview`);
  await notice2.locator("details summary").click();
  await notice2.locator("details").scrollIntoViewIfNeeded();
  await shot(page, `${p}-B04b-preview-details`);

  // 5. Confirm: revision 2.
  const posted = page.waitForResponse((r) => r.url().endsWith(`/api/listening/materials/${old.materialId}/script-update`) && r.request().method() === "POST");
  await notice2.getByRole("button", { name: L.confirm(2) }).click();
  const up = await posted;
  check(`${p}: the confirmation answered 201`, up.status() === 201, up.status());
  await page.getByText(L.updated(1, 2)).waitFor();
  await sleep(300);
  check(`${p}: the notice is gone and the lesson says "${L.revision(2)}"`,
    (await page.getByRole("region", { name: L.updateRegion }).count()) === 0 && (await page.locator(".tag", { hasText: L.revision(2) }).count()) > 0);
  await shot(page, `${p}-B05-updated`);
  const body = JSON.parse(up.request().postData());
  const resend = await api(base, "POST", `/listening/materials/${old.materialId}/script-update`, body);
  check(`${p}: resending the same confirmation (lost response) replays: 200, revision 2`, resend.status === 200 && resend.replayed === "true" && resend.json.revision === 2, { status: resend.status, rev: resend.json?.revision });
  const reimport = await api(base, "POST", `/listening/scripts/${SCRIPT}`);
  check(`${p}: re-import now replays (200)`, reimport.status === 200, reimport.status);
  const after = await api(base, "GET", `/listening/materials/${old.materialId}`);
  const newEx = after.json.exercises.find((e) => e.id === after.json.current_exercise_id);
  check(`${p}: the lesson now shows revision 2 with the corrected explanation`,
    after.json.transcript.version === 2 && newEx.id !== old.exerciseId && newEx.content.items[Q - 1].rationale_en !== old.oldWhy, { version: after.json.transcript.version, current: newEx.id });

  // 6. Reopen the old mistake: revision 1, its wording, marked at the top.
  await page.getByRole("button", { name: L.notebook, exact: true }).first().click();
  entry = page.getByRole("group", { name: L.entry(old.entryId) });
  await entry.waitFor();
  await entry.getByRole("button", { name: L.show }).click();
  await sleep(200);
  const shownRef = await entry.innerText();
  check(`${p}: the old notebook item keeps the explanation it was saved with`, shownRef.includes(old.oldWhy), shownRef.slice(0, 500));
  info(`${p}: old notebook item after the update`, shownRef.slice(0, 500));
  await shot(page, `${p}-B06a-notebook-old-item`);
  await entry.getByRole("button", { name: L.openSource }).click();
  const earlier = page.getByRole("region", { name: L.earlierRegion });
  await earlier.waitFor();
  await sleep(500);
  check(`${p}: the old mistake opens revision 1`, (await earlier.getByRole("heading", { name: L.earlierHeading(1) }).count()) === 1);
  const target = earlier.locator(".notebook-target");
  const tb = await box(target);
  check(`${p}: the saved question is marked and at the top of the screen`, tb.top >= -2 && tb.top < 160, tb);
  check(`${p}: the banner says the question is shown`, (await page.locator(".notebook-origin").innerText()).includes(L.shown(Q)));
  await shot(page, `${p}-B06-reopened-old-revision`);
  await noOverflow(page, `${p} reopened`);

  // 7. A new mistake on the current revision (2) is a separate record.
  const current = page.locator("section.listening-exercise").filter({ hasNot: page.locator(".notebook-target") }).last();
  const item = newEx.content.items[Q - 1];
  const wrong = item.choices.find((c) => c !== item.expected_answer);
  const typed = newEx.content.items.findIndex((it) => !it.choices) + 1;
  await current.getByRole("group", { name: L.choice(Q) }).getByLabel(wrong, { exact: true }).check();
  await current.getByLabel(L.answer(typed)).fill("je ne sais plus");
  await current.getByRole("button", { name: L.reveal }).click();
  // CP6: a typed answer is self-assessed in its overview row, in place.
  const rowCheck = current.locator("section.listening-overview").getByRole("group", { name: L.rowCheck(typed) });
  await rowCheck.getByRole("button", { name: L.missed }).click();
  check(`${p}: a typed answer is self-assessed in its overview row and the question agrees`,
    (await rowCheck.getByRole("button", { name: L.missed }).getAttribute("aria-pressed")) === "true" &&
      (await current.getByRole("group", { name: L.questionCheck(typed) }).getByRole("button", { name: L.missed }).getAttribute("aria-pressed")) === "true");
  await rowCheck.scrollIntoViewIfNeeded();
  await shot(page, `${p}-B07a-overview-self-check`);
  const saved = await saveMissed(page, L, current, "Toujours pas sûr du lien entre 17 h 30 et le cours du soir.");
  check(`${p}: a new mistake saves against revision 2's exercise`, saved.status === 201 && saved.capture.source_ref?.record_id === newEx.id, { status: saved.status, ref: saved.capture.source_ref });
  await shot(page, `${p}-B07-new-mistake-revision-2`);
  const nb = await api(base, "GET", "/mistake-notebook/items");
  const oldItem = nb.json.items.find((i) => i.entry_id === old.entryId);
  const newItem = nb.json.items.find((i) => i.entry_id === saved.entryId);
  check(`${p}: notebook keeps both: revision 1 (latest_version 2) and revision 2`,
    oldItem?.link?.listening_transcript_version === 1 && oldItem?.latest_version === 2 && newItem?.link?.listening_transcript_version === 2 && oldItem?.explanation_en === old.oldWhy,
    { old: oldItem?.link, oldLatest: oldItem?.latest_version, new: newItem?.link });

  check(`${p}: writes were only the update and the new capture`, JSON.stringify(w.writes) === JSON.stringify([`POST /api/listening/materials/${old.materialId}/script-update`, "POST /api/captures"]), w.writes);
  check(`${p}: no console errors`, w.errors.length === 0, w.errors);
  await ctx.close();
}

const browser = await chromium.launch();
info("browser", `Chromium ${browser.version()}`);
try {
  for (const combo of COMBOS) {
    const oldBase = await waitUrl(`${combo}.old`);
    let old = null;
    try {
      old = await oldPart(browser, combo, oldBase);
    } catch (e) {
      check(`${combo} old part ran`, false, String(e).slice(0, 400));
    }
    await signal(`${combo}.old-done`);
    const newBase = await waitUrl(`${combo}.new`);
    try {
      if (old) await newPart(browser, combo, newBase, old);
    } catch (e) {
      check(`${combo} new part ran`, false, String(e).slice(0, 400));
    }
    await signal(`${combo}.new-done`);
  }
} finally {
  await browser.close();
  fs.writeFileSync(`${OUT}/results-${TAG}.json`, JSON.stringify(results, null, 1));
}
const failed = results.filter((r) => !r.pass);
for (const r of results) console.log(`${r.pass ? "PASS" : "FAIL"} ${r.name}${r.pass && !r.name.startsWith("INFO") ? "" : " :: " + r.detail.slice(0, 300)}`);
console.log(`${results.filter((r) => r.pass && !r.name.startsWith("INFO")).length}/${results.filter((r) => !r.name.startsWith("INFO")).length} checks passed`);
process.exit(failed.length ? 1 : 0);
