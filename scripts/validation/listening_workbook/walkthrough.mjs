// Real-Chromium study walkthrough of a workbook listening script (Playwright),
// at phone (390×844, touch) and desktop (1280×900) widths:
//   choose a script → import → attempt → reveal (answer overview) → save a
//   missed point → Mistake Notebook → reopen the saved item in its lesson,
//   then reopen it again after a page reload.
// Plus the preparation boundary through the real API with the local fake
// provider (see run.py): a script must keep its authored exercise, and a
// YouTube lesson must still prepare, reveal and link to the video.
// Every check records pass/fail + detail in results-TAG.json; one screenshot
// per step in shots-TAG/. Nothing here uses a real provider or the daily DB.
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE_URL;
const TAG = process.env.TAG || "run";
const OUT = process.env.OUT || ".";
const SHOTS = `${OUT}/shots-${TAG}`;
fs.mkdirSync(SHOTS, { recursive: true });
const results = [];
const check = (name, pass, detail = "") => results.push({ name, pass: !!pass, detail: typeof detail === "string" ? detail : JSON.stringify(detail) });
const info = (name, detail) => results.push({ name: "INFO " + name, pass: true, detail: typeof detail === "string" ? detail : JSON.stringify(detail) });
const shot = (page, name, opts = {}) => page.screenshot({ path: `${SHOTS}/${name}.png`, ...opts });

const api = async (method, path, body, headers = {}) => {
  const r = await fetch(BASE + "/api" + path, {
    method,
    headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...headers },
    body: body ? JSON.stringify(body) : undefined,
  });
  let json = null;
  try {
    json = await r.json();
  } catch {}
  return { status: r.status, json };
};

async function noOverflow(page, where) {
  const o = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth }));
  check(`${where}: no horizontal scroll`, o.scrollWidth <= o.innerWidth, o);
}
// Where an element sits relative to the viewport (after any scroll the page did).
const box = (loc) =>
  loc.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { top: Math.round(r.top), bottom: Math.round(r.bottom), vh: window.innerHeight, scrollY: Math.round(window.scrollY) };
  });
const inView = (b) => b.top >= 0 && b.top < b.vh;

// One full study loop in one browser context.
async function studyLoop(browser, { label, viewport, mobile, scriptId, title, wrongItem, wrongChoice, missedText }) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: mobile ? 2 : 1, isMobile: mobile, hasTouch: mobile, locale: "en-GB" });
  const page = await ctx.newPage();
  const writes = [];
  page.on("request", (r) => {
    if (r.method() !== "GET" && r.method() !== "HEAD" && r.url().includes("/api/"))
      writes.push({ method: r.method(), path: new URL(r.url()).pathname, body: r.postData() });
  });
  const consoleErrors = [];
  page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
  page.on("pageerror", (e) => consoleErrors.push(String(e)));
  const p = `${label}`;

  // 1. Choose a script
  await page.goto(BASE + "/");
  await page.getByRole("button", { name: "Listening", exact: true }).click();
  const panel = page.getByRole("region", { name: "Workbook listening scripts" });
  await panel.waitFor();
  const importBtn = page.getByRole("button", { name: `Import ${title}` });
  await importBtn.waitFor();
  await importBtn.scrollIntoViewIfNeeded();
  await shot(page, `${p}-01-choose`);
  check(`${p}: browsing the catalogue sent nothing`, writes.length === 0, writes);

  // 2. Import
  const imported = page.waitForResponse((r) => r.url().endsWith(`/api/listening/scripts/${scriptId}`) && r.request().method() === "POST");
  await importBtn.click();
  const resp = await imported;
  check(`${p}: import answered 201 or 200`, [200, 201].includes(resp.status()), resp.status());
  const lesson = await resp.json();
  await page.getByRole("heading", { name: title }).waitFor();
  const exercise = lesson.exercises[0];
  const items = exercise.content.items;
  check(`${p}: imported lesson shows the authored exercise`, exercise.generator === "authored:flh_listening_script_pack_v1", exercise.generator);
  await shot(page, `${p}-02-lesson`);
  await noOverflow(page, `${p} lesson`);
  const secrets = [
    ...items.flatMap((i) => [i.rationale_en, ...(i.wrong_answers ?? []).map((w) => w.why_wrong_en)]),
    ...items.filter((i) => !i.choices).map((i) => i.expected_answer),
    "Reference answer:",
  ];
  const before = await page.evaluate(() => document.body.innerText);
  check(`${p}: no key before reveal`, secrets.every((s) => !before.includes(s)), secrets.filter((s) => before.includes(s)));

  // 3. Attempt: every single-choice item gets an answer; one deliberately wrong.
  for (const [i, it] of items.entries()) {
    if (it.choices) {
      const choice = i === wrongItem ? wrongChoice(it) : it.expected_answer;
      await page.getByRole("group", { name: `Your choice for question ${i + 1}` }).getByLabel(choice, { exact: true }).check();
    } else {
      await page.getByLabel(`Your answer to question ${i + 1}`).fill(i === wrongItem ? "je ne sais pas" : it.expected_answer);
    }
  }
  await shot(page, `${p}-03-attempt`);
  check(`${p}: answering sent nothing`, writes.filter((w) => !w.path.includes("/listening/scripts/")).length === 0, writes);

  // 4. Reveal. The learner should see at once which answers differ, without
  // scrolling through every reference block (checkpoint 1).
  await page.getByRole("button", { name: "Reveal answers and evidence" }).click();
  const ref = page.getByRole("group", { name: `Reference for question ${wrongItem + 1}` });
  await ref.waitFor();
  await page.waitForTimeout(300);
  await shot(page, `${p}-04a-after-reveal`);
  const overviewHeading = page.getByRole("heading", { name: "Your answers and the reference" });
  const hasOverview = (await overviewHeading.count()) === 1;
  check(`${p}: after reveal, an answer overview exists`, hasOverview);
  const exerciseBox = await box(page.getByRole("region", { name: "Listening exercise" }));
  info(`${p}: revealed exercise height (px) the learner would otherwise scan`, exerciseBox.bottom - exerciseBox.top);
  if (hasOverview) {
    check(`${p}: overview heading has focus and is on screen`, (await overviewHeading.evaluate((el) => el === document.activeElement)) && inView(await box(overviewHeading)));
    const overview = page.locator("section.listening-overview");
    const rows = overview.locator("li.listening-overview-row");
    check(`${p}: overview lists every question`, (await rows.count()) === items.length, await rows.count());
    const row = rows.nth(wrongItem);
    const rowText = await row.innerText();
    const wrongIsChoice = !!items[wrongItem].choices;
    check(
      `${p}: overview row for the missed question shows the learner's answer and the reference`,
      rowText.includes(wrongIsChoice ? "Different from the reference" : "Short answer: compare it yourself") && rowText.includes(items[wrongItem].expected_answer),
      rowText,
    );
    const others = [];
    for (let i = 0; i < items.length; i++) if (i !== wrongItem && items[i].choices) others.push((await rows.nth(i).innerText()).includes("Same as the reference"));
    check(`${p}: the other chosen answers read "Same as the reference"`, others.every(Boolean), others);
    const ovText = await overview.innerText();
    check(`${p}: overview gives no score or total`, !/\d+\s*(of|\/|sur)\s*\d+/i.test(ovText), ovText.slice(0, 200));
    await overview.screenshot({ path: `${SHOTS}/${p}-04b-overview.png` });
    await row.getByRole("button", { name: `Go to question ${wrongItem + 1}` }).click();
    await page.waitForTimeout(300);
    const qbox = await box(page.locator(`[id$="-${wrongItem + 1}"].listening-item`).first());
    check(`${p}: "Go to question" brings the question to the top of the screen`, qbox.top >= -2 && qbox.top < 120, qbox);
    check(`${p}: "Go to question" focuses that question's reference`, await ref.evaluate((el) => el === document.activeElement));
  } else {
    await ref.scrollIntoViewIfNeeded();
  }
  await shot(page, `${p}-04-reveal-item`);
  const refText = await ref.innerText();
  info(`${p}: reveal of the missed question`, refText.slice(0, 600));
  const wrongChosen = wrongChoice(items[wrongItem]);
  const yourAnswerShown = /Your answer/i.test(refText);
  info(`${p}: the reveal of the missed question names the learner's own answer`, { yourAnswerShown, chosen: wrongChosen });

  // 5. Save the missed point
  await ref.getByRole("button", { name: "Save as a learning question…" }).click();
  const form = page.getByRole("form", { name: `Save a missed point from question ${wrongItem + 1}` });
  await form.waitFor();
  await form.getByLabel("What did you miss, or what do you want to ask?").fill(missedText);
  const attemptBox = form.getByRole("checkbox");
  if (await attemptBox.count()) await attemptBox.check();
  await form.scrollIntoViewIfNeeded();
  await shot(page, `${p}-05-save-form`);
  const saved = page.waitForResponse((r) => r.url().endsWith("/api/captures") && r.request().method() === "POST");
  await form.getByRole("button", { name: "Save learning record" }).click();
  const savedResp = await saved;
  check(`${p}: save answered 201`, savedResp.status() === 201, savedResp.status());
  const capture = JSON.parse(savedResp.request().postData());
  check(`${p}: capture is manual with a listening_item source`, capture.source === "manual" && capture.source_ref?.type === "listening_item", capture.source_ref);
  check(`${p}: capture context names the script, no audio`, capture.original_context.includes("Source: authored script, no audio or video"), capture.original_context);
  const status = page.getByRole("status").filter({ hasText: /Saved as learning record #\d+/ });
  await status.waitFor();
  await shot(page, `${p}-06-saved`);
  const entryId = Number((await status.innerText()).match(/#(\d+)/)[1]);
  const back = ref.getByRole("button", { name: "Back to the answer overview" });
  if (await back.count()) {
    await back.click();
    await page.waitForTimeout(300);
    check(`${p}: "Back to the answer overview" returns to the overview`, inView(await box(page.getByRole("heading", { name: "Your answers and the reference" }))));
  }

  // 6. Reopen from the Mistake Notebook
  await page.getByRole("button", { name: "Mistake Notebook", exact: true }).first().click();
  const entry = page.getByRole("group", { name: `Mistake, record #${entryId}` });
  await entry.waitFor();
  await entry.scrollIntoViewIfNeeded();
  await shot(page, `${p}-07-notebook`);
  const entryText = await entry.innerText();
  check(`${p}: notebook item shows the learner's words`, entryText.includes(missedText), entryText.slice(0, 300));
  await entry.getByRole("button", { name: "Open source" }).click();
  await page.getByRole("heading", { name: title }).waitFor();
  const origin = page.locator(".notebook-origin");
  await origin.waitFor();
  const originText = await origin.innerText();
  check(`${p}: reopened lesson says the saved question is marked`, originText.includes(`Question ${wrongItem + 1} is marked below.`), originText);
  const target = page.locator(".notebook-target");
  await page.waitForTimeout(400); // the lesson scrolls the marked question into view
  const tbox = await box(target);
  check(`${p}: reopened question is on screen with its stem visible`, inView(tbox), tbox);
  await shot(page, `${p}-08-reopened`);
  const targetText = await target.innerText();
  info(`${p}: reopened question content`, targetText.slice(0, 600));
  info(`${p}: reopened question shows its reference without a second reveal`, /Reference answer:/.test(targetText));
  await noOverflow(page, `${p} reopened`);

  // 7. Reopen the saved mistake again after a reload (nothing kept in the page).
  await page.reload();
  await page.getByRole("button", { name: "Mistake Notebook", exact: true }).first().click();
  const entry2 = page.getByRole("group", { name: `Mistake, record #${entryId}` });
  await entry2.waitFor();
  await entry2.getByRole("button", { name: "Show reference" }).click();
  const shownRef = await entry2.innerText();
  check(`${p}: after a reload, the notebook shows the saved item's reference`, shownRef.includes(items[wrongItem].expected_answer), shownRef.slice(0, 300));
  await entry2.getByRole("button", { name: "Open source" }).click();
  await page.getByRole("heading", { name: title }).waitFor();
  await page.waitForTimeout(400);
  const t2 = page.locator(".notebook-target");
  const t2box = await box(t2);
  check(`${p}: after a reload, the reopened question is at the top of the screen`, t2box.top >= -2 && t2box.top < 160, t2box);
  check(`${p}: after a reload, the reopened lesson marks the saved question`, (await page.locator(".notebook-origin").innerText()).includes(`Question ${wrongItem + 1} is marked below.`));
  check(`${p}: after a reload, answers stay hidden until reveal`, !(await t2.innerText()).includes("Reference answer:"));
  await shot(page, `${p}-09-reopened-after-reload`);

  check(`${p}: no console errors`, consoleErrors.length === 0, consoleErrors);
  info(`${p}: writes`, writes.map((w) => `${w.method} ${w.path}`));
  await ctx.close();
  return { entryId, materialId: lesson.material.id, exerciseId: exercise.id };
}

// The preparation boundary (checkpoint 4), through the real API: the fake
// provider (run.py) answers any call with a valid generated exercise.
async function preparationBoundary(browser, scriptMaterialId, scriptTitle) {
  const before = await api("GET", `/listening/materials/${scriptMaterialId}`);
  const prep = await api("POST", `/listening/materials/${scriptMaterialId}/exercises`, null, { "Idempotency-Key": "6f1c2a4e-8b7d-4c3e-9a1f-2b3c4d5e6f70" });
  info("script: POST /listening/materials/{id}/exercises", { status: prep.status, code: prep.json?.code, generator: prep.json?.exercise?.generator ?? null });
  check("script: model preparation is refused with 409 authored_script", prep.status === 409 && prep.json?.code === "authored_script", prep);
  const after = await api("GET", `/listening/materials/${scriptMaterialId}`);
  check("script: the refused preparation stored nothing", after.json.exercises.length === before.json.exercises.length && after.json.preparations.length === before.json.preparations.length,
    { before: before.json.exercises.length, after: after.json.exercises.length });
  const shownId = after.json.current_exercise_id ?? after.json.exercises.find((e) => e.status === "completed")?.id;
  const shown = after.json.exercises.find((e) => e.id === shownId);
  check("script: the lesson still shows the authored exercise", shown?.generator === "authored:flh_listening_script_pack_v1", shown?.generator);
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: "en-GB" });
  const page = await ctx.newPage();
  await page.goto(BASE + "/");
  await page.getByRole("button", { name: "Listening", exact: true }).click();
  await page.getByRole("button", { name: scriptTitle, exact: true }).first().click();
  await page.getByRole("heading", { name: scriptTitle }).waitFor();
  const firstQuestion = await page.locator(".listening-items .listening-item p.french").first().innerText();
  check("script: in the browser, the lesson shows the authored questions after a preparation attempt", !firstQuestion.includes("Faux fournisseur"), firstQuestion);
  await shot(page, "probe-01-script-after-prepare-attempt");

  // YouTube preparation still works.
  const transcript = "[00:00] Bonjour à tous, et bienvenue dans « La minute du quartier ».\n[00:04] La nouvelle bibliothèque ouvre samedi, rue des Lilas.\n[00:10] Elle sera ouverte du mardi au dimanche.";
  const created = await api("POST", "/listening/materials", { source_url: "https://youtu.be/FLHlisten01", title: "La minute du quartier (vidéo de test)", transcript });
  check("youtube: material with a timed transcript saved", created.status === 201, created.status);
  const id = created.json.material.id;
  await page.getByRole("button", { name: "← All listening material" }).click();
  await page.getByRole("button", { name: "La minute du quartier (vidéo de test)", exact: true }).click();
  await page.getByRole("button", { name: "Prepare exercise" }).click();
  await page.getByRole("button", { name: "Reveal answers and evidence" }).waitFor();
  const yt = await api("GET", `/listening/materials/${id}`);
  const ytShown = yt.json.exercises.find((e) => e.id === (yt.json.current_exercise_id ?? yt.json.exercises[0]?.id));
  check("youtube: Prepare exercise stores and shows a generated exercise", ytShown?.generator === "openai:local-fake-model:listening_exercise_v1", ytShown?.generator);
  await page.getByRole("button", { name: "Reveal answers and evidence" }).click();
  const link = page.getByRole("link", { name: "0:00" }).first();
  await link.waitFor();
  check("youtube: the cited line links to the video at its time", (await link.getAttribute("href")) === "https://www.youtube.com/watch?v=FLHlisten01&t=0s", await link.getAttribute("href"));
  await shot(page, "probe-02-youtube-prepared-revealed", { fullPage: true });
  await ctx.close();
}

// The overview in Simplified Chinese (application text only; French unchanged).
async function chineseOverview(browser, title) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: "zh-CN" });
  await ctx.addInitScript(() => { try { localStorage.setItem("flh.ui-locale.v1", "zh-CN"); } catch {} });
  const page = await ctx.newPage();
  await page.goto(BASE + "/");
  await page.getByRole("button", { name: "听力", exact: true }).click();
  await page.getByRole("button", { name: title, exact: true }).first().click();
  await page.getByRole("heading", { name: title }).waitFor();
  await page.getByRole("button", { name: "显示答案和依据" }).click();
  const h = page.getByRole("heading", { name: "你的答案与参考答案" });
  check("zh-CN: the overview heading is translated", (await h.count()) === 1);
  await page.waitForTimeout(300);
  await shot(page, "zh-01-overview");
  await ctx.close();
}

const browser = await chromium.launch();
try {
  const phone = await studyLoop(browser, {
    label: "phone",
    viewport: { width: 390, height: 844 },
    mobile: true,
    scriptId: "ls-wb1-u05",
    title: "À l'accueil de la Maison des langues",
    wrongItem: 4,
    wrongChoice: (it) => it.choices.find((c) => c !== it.expected_answer),
    missedText: "Pourquoi « 90 euros » n'est pas le prix du trimestre ?",
  });
  info("phone loop ids", phone);
  const desktop = await studyLoop(browser, {
    label: "desktop",
    viewport: { width: 1280, height: 900 },
    mobile: false,
    scriptId: "ls-wb1-u02",
    title: (await api("GET", "/listening/scripts")).json.scripts.find((s) => s.id === "ls-wb1-u02").title,
    wrongItem: 2,
    wrongChoice: (it) => (it.choices ? it.choices.find((c) => c !== it.expected_answer) : "x"),
    missedText: "Je n'ai pas compris cette réplique.",
  });
  info("desktop loop ids", desktop);
  await preparationBoundary(browser, phone.materialId, "À l'accueil de la Maison des langues");
  await chineseOverview(browser, "À l'accueil de la Maison des langues");
} catch (e) {
  check("walkthrough completed without an exception", false, String(e && e.stack ? e.stack : e));
} finally {
  await browser.close();
  fs.writeFileSync(`${OUT}/results-${TAG}.json`, JSON.stringify(results, null, 1));
  const failed = results.filter((r) => !r.pass);
  for (const r of results) console.log(`${r.pass ? "PASS" : "FAIL"} ${r.name}${r.pass && !r.name.startsWith("INFO") ? "" : " :: " + r.detail.slice(0, 400)}`);
  console.log(`${results.length - failed.length}/${results.length} pass`);
  process.exitCode = failed.length ? 1 : 0;
}
