// The practice prototype in real Chromium on the SEALED Extraction 2.1
// fixtures, by keyboard (Tab to reach a control, Enter or Space to use it),
// reduced motion emulated and clipboard granted. Per combination (COMBOS: JSON
// [{tag, locale, phone, url, zoom?, largeText?}]):
//   1. Review Today: open the panel; the fixtures are verified in the page;
//      today's practice lists a small set; Start the first item (focus lands
//      on its answer field).
//   2. Answer it (a known confusion), save the mistake for later, follow the
//      "next useful exercise" (recall), self-check; the source opens.
//   3. Leave a new-sentence exercise to inspect its evidence and come back
//      (the draft is kept); answer it twice (one attempt); copy the study
//      packet (no key, no answer of this visit).
//   4. A source revision while a slow check is in flight: the revision waits,
//      is applied, the late check is refused, drafts are kept; withdrawn
//      exercises are explained; the next revision restores the same IDs.
//   5. The two tutor sessions: every proposal reviewed; one candidate accepted
//      for this visit after a confirmation.
//   6. The visit log by skill and day; export without answer texts.
//   7. Reload: everything is gone.
// At every step: controls named, ids unique, nothing moving, and on narrow
// screens no horizontal scroll and 44 px touch targets. Writes
// OUT/results.json, OUT/trace-<tag>.json (every key press and where focus
// went), OUT/counts-<tag>.json (interactions to the first practice) and
// OUT/shots/<tag>/*.png. The zoom/large-text combinations run the first part
// only.
import { chromium } from "playwright";
import fs from "node:fs";

const OUT = process.env.OUT || "/out";
const combos = JSON.parse(process.env.COMBOS);
const results = [];
const FORBIDDEN = JSON.parse(process.env.FORBIDDEN || "[]");
const catalog = (locale) => {
  const cat = {};
  const text = fs.readFileSync(`/i18n/${locale}.ts`, "utf8");
  for (const m of text.matchAll(/^\s*("(?:[^"\\\n]|\\.)+"):\s*("(?:[^"\\\n]|\\.)*")/gm)) cat[JSON.parse(m[1])] = JSON.parse(m[2]);
  const T = (key, vars = {}) => {
    if (cat[key] === undefined) throw new Error(`missing ${key}`);
    return cat[key].replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? `{${k}}`));
  };
  T.p = (base, count, vars = {}) => T(`${base}.${count === 1 ? "one" : "other"}`, { ...vars, count });
  return T;
};
const smoke = (page, phone) =>
  page.evaluate((phone) => {
    const vis = (el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden";
    };
    const nameOf = (el) => {
      const l = el.getAttribute("aria-label");
      if (l && l.trim()) return l.trim();
      if (el.labels && el.labels.length) {
        const t = [...el.labels].map((x) => x.textContent).join(" ").trim();
        if (t) return t;
      }
      if (!["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName)) {
        const t = (el.textContent ?? "").trim();
        if (t) return t;
      }
      return (el.getAttribute("title") ?? "").trim();
    };
    const controls = [...document.querySelectorAll("button, a[href], input:not([type=hidden]), select, textarea, summary")].filter(vis);
    const unnamed = controls.filter((el) => !nameOf(el)).map((el) => el.outerHTML.slice(0, 120));
    const ids = [...document.querySelectorAll("[id]")].map((e) => e.id);
    const dup = [...new Set(ids.filter((id, i) => ids.indexOf(id) !== i))];
    const moving = [...document.querySelectorAll("*")].filter((el) => {
      const cs = getComputedStyle(el);
      return cs.transitionDuration.split(",").some((d) => parseFloat(d) > 0) || (cs.animationName && cs.animationName !== "none");
    }).length;
    // touch targets inside the prototype (narrow screens)
    const small = phone
      ? [...document.querySelectorAll(".today-prototype button, .concept-practice button")]
          .filter(vis)
          .filter((b) => {
            const r = b.getBoundingClientRect();
            return r.height < 43.5;
          })
          .map((b) => `${(b.textContent || "").trim().slice(0, 40)} ${Math.round(b.getBoundingClientRect().height)}px`)
      : [];
    return { unnamed, dup, moving, small, fits: document.documentElement.scrollWidth <= window.innerWidth + 1, width: document.documentElement.scrollWidth };
  }, phone);

const browser = await chromium.launch();
for (const c of combos) {
  const T = catalog(c.locale);
  const shots = `${OUT}/shots/${c.tag}`;
  fs.mkdirSync(shots, { recursive: true });
  const check = (name, pass, detail = "") => results.push({ combo: c.tag, name, pass: !!pass, detail: typeof detail === "string" ? detail : JSON.stringify(detail) });
  const narrow = c.phone || c.zoom;
  const ctx = await browser.newContext({
    ...(c.phone
      ? { viewport: { width: 320, height: 640 }, hasTouch: true, isMobile: true }
      : c.zoom
        ? { viewport: { width: 640, height: 450 }, deviceScaleFactor: 2 }
        : { viewport: { width: 1280, height: 900 } }),
    reducedMotion: "reduce",
    permissions: ["clipboard-read", "clipboard-write"],
  });
  if (c.zoom)
    // this combination also checks the fallback when the browser refuses the clipboard
    await ctx.addInitScript(() => {
      Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: () => Promise.reject(new Error("denied")), readText: () => Promise.reject(new Error("denied")) } });
    });
  await ctx.addInitScript((loc) => {
    window.localStorage.setItem("flh.ui-locale.v1", loc);
    // record every scrollIntoView's options (reduced motion must not animate)
    window.__scrolls = [];
    const orig = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function (opts) {
      window.__scrolls.push(typeof opts === "object" && opts ? opts.behavior ?? "unset" : String(opts));
      return orig.call(this, opts);
    };
  }, c.locale);
  const page = await ctx.newPage();
  page.setDefaultTimeout(15000);
  if (c.largeText) {
    const cdp = await ctx.newCDPSession(page);
    await cdp.send("Page.setFontSizes", { fontSizes: { standard: 32, fixed: 26 } });
  }
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const trace = [];
  const counts = { tabs: 0, activations: 0, typed: 0 };
  const focusName = () =>
    page.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body) return "body";
      const name = el.getAttribute("aria-label") || (el.labels && el.labels[0]?.textContent) || el.textContent || "";
      return `${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""} ${name.trim().replace(/\s+/g, " ").slice(0, 60)}`;
    });
  const frames = () => page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r(null)))));
  const press = async (key, what = "") => {
    await page.keyboard.press(key);
    await frames();
    if (key === "Tab" || key === "Shift+Tab") counts.tabs++;
    else if (key === "Enter" || key === " " || key === "Space") counts.activations++;
    trace.push({ key, what, focus: await focusName() });
  };
  const isFocused = (loc) => loc.evaluate((el) => el === document.activeElement);
  // Reach a control the way a keyboard user does: Tab until it has focus.
  const tabTo = async (loc, max = 400) => {
    await loc.waitFor();
    for (let i = 0; i < max; i++) {
      if (await isFocused(loc)) return true;
      await press("Tab", "seek");
    }
    throw new Error(`Tab never reached ${await loc.evaluate((e) => e.outerHTML.slice(0, 100))}`);
  };
  const activate = async (loc, what) => {
    await tabTo(loc);
    await press("Enter", what);
  };
  const typeIn = async (text, what) => {
    await page.keyboard.type(text);
    counts.typed++;
    trace.push({ key: "type", what, focus: await focusName() });
  };
  const step = async (name) => {
    const s = await smoke(page, !!narrow);
    check(
      `${name}: every control named, ids unique, nothing moving${narrow ? ", fits the width, 44 px touch targets" : ""}`,
      s.unnamed.length === 0 && s.dup.length === 0 && s.moving === 0 && (!narrow || s.fits) && s.small.length === 0,
      s,
    );
  };
  const btn = (key, vars) => page.getByRole("button", { name: T(key, vars), exact: true });
  const cardOf = (id) => page.locator(`[data-practice="${id}"][data-kind]`);
  const field = (id) => page.locator(`#feed-${id}`);
  try {
    // 1. Review Today -> today's practice -> the first item.
    await page.goto(c.url + "/#/today");
    await page.locator("h2").first().waitFor();
    const t0 = { ...counts };
    await activate(btn("feedPractice.panel.open"), "open the prototype");
    await page.locator('[data-fixture="verified"]').waitFor();
    check("the page re-checked all 21 sealed fixture documents", (await page.locator('[data-fixture="verified"] [data-doc]').count()) === 21);
    check("html lang follows the interface language", (await page.evaluate(() => document.documentElement.lang)) === (c.locale === "zh-CN" ? "zh-CN" : "en"), await page.evaluate(() => document.documentElement.lang));
    const today = page.getByRole("list", { name: T.p("feedPractice.today.heading", 3), exact: true });
    const picks = await today.locator("[data-practice]").evaluateAll((els) => els.map((e) => `${e.dataset.practice}:${e.dataset.pickReason}`));
    check("today's practice is a small set, misses first", JSON.stringify(picks) === JSON.stringify(["p-664f7533a19d:missed_last_time", "p-e61b319d2129:missed_last_time", "p-baa71166205b:not_an_option_last_time"]), picks);
    const rows = page.locator('[data-source="practice"][data-reason="practice_outcome"]');
    check("both approved concepts are practice rows with reason practice_outcome", (await rows.count()) === 2);
    await page.screenshot({ path: `${shots}/01-review-today.png`, fullPage: true });
    await step("Review Today with the prototype");
    await activate(today.locator('[data-practice="p-664f7533a19d"]').getByRole("button", { name: T("feedPractice.today.start"), exact: true }), "start today's first item");
    await page.getByRole("heading", { name: T("feedPractice.heading", { concept: "y vs en" }), exact: true }).waitFor();
    await page.waitForTimeout(150);
    check("Start opens the concept with focus on that exercise's answer field", await isFocused(field("p-664f7533a19d")));
    await typeIn("Oui, j'y reviens.", "answer");
    await press("Control+Enter", "check");
    await cardOf("p-664f7533a19d").locator('[data-outcome="incorrect"]').waitFor();
    const reached = { tabs: counts.tabs - t0.tabs, activations: counts.activations - t0.activations, typed: counts.typed - t0.typed, submits: 1 };
    fs.writeFileSync(`${OUT}/counts-${c.tag}.json`, JSON.stringify({ path: "today-first", from: "Review Today loaded", to: "first graded answer", ...reached }, null, 1));
    check("the first practice is reached from today's set (interactions recorded)", reached.activations === 2 && reached.typed === 1, reached);
    check(
      "the state is announced as done, with the outcome in words",
      (await cardOf("p-664f7533a19d").locator('[data-announce="done"]').textContent()).includes(T("feedPractice.outcome.incorrect")),
    );
    await page.screenshot({ path: `${shots}/02-first-answer.png` });
    await step("first answer");
    if (c.zoom || c.largeText) {
      // the zoom and large-text combinations stop after the first part
      if (c.zoom) {
        const sh = page.locator('[data-packet="pk-afdb387f3af6"]');
        await activate(sh.getByRole("button", { name: T("feedPractice.packet.copy"), exact: true }), "copy (clipboard refused)");
        await sh.locator('[data-copy="selected"]').waitFor();
        const area = sh.getByLabel(T("feedPractice.packet.textLabel", { id: "pk-afdb387f3af6" }), { exact: true });
        const sel = await area.evaluate((el) => el === document.activeElement && el.selectionStart === 0 && el.selectionEnd === el.value.length && el.value.startsWith("# FLH practice packet pk-afdb387f3af6"));
        check("when the clipboard is refused, the packet text is shown, focused and fully selected", sel);
        await sh.screenshot({ path: `${shots}/03-clipboard-refused.png` });
      }
      const long = "x".repeat(400);
      await field("p-664f7533a19d").fill(long);
      await step("a 400-character unbroken answer");
      check("no page errors", errors.length === 0, errors);
      throw "done";
    }
    await activate(cardOf("p-664f7533a19d").getByRole("button", { name: T("feedPractice.convert.action"), exact: true }), "save the mistake");
    check("the mistake became practice item personal-1", (await cardOf("p-664f7533a19d").locator('[data-converted="personal-1"]').count()) === 1);

    // 2. The next useful exercise: recall the rule.
    const next = page.locator('[data-next="p-2ea892e5eaa0"]');
    check("the next useful exercise after the miss is the recall", (await next.getAttribute("data-next-why")) === "after_miss_recall_rule");
    await activate(next.getByRole("button", { name: T("feedPractice.next.start"), exact: true }), "start the next exercise");
    check("Start it moves focus to the recall field", await isFocused(field("p-2ea892e5eaa0")));
    check("the source is closed before the recall", (await page.locator('[data-source="locked"]').count()) === 1);
    // a closed source holds one control and does not trap focus
    await tabTo(btn("feedPractice.source.openAnyway"));
    await press("Tab", "past the closed source");
    const after = await page.evaluate(() => !document.activeElement.closest('[data-section="source"]'));
    check("Tab moves on past the closed source (no focus trap)", after);
    await tabTo(field("p-2ea892e5eaa0"));
    await typeIn("« y » après à (j'y vais) ; « en » après de (j'en viens).", "recall");
    await press("Control+Enter", "check the recall");
    await cardOf("p-2ea892e5eaa0").locator('[data-outcome="self_check"]').waitFor();
    await activate(cardOf("p-2ea892e5eaa0").getByRole("button", { name: T("notebook.retry.got"), exact: true }), "self-check");
    const marks = page.locator("[data-evidence] mark");
    check("the source opens after the recall with the quoted words marked", (await page.locator('[data-source="open"]').count()) === 1 && (await marks.count()) === 4, await marks.allTextContents());
    await page.locator('[data-section="source"]').screenshot({ path: `${shots}/03-source.png` });
    await step("source");

    // 3. Resume after inspecting evidence; one attempt for a repeated check; the packet.
    await tabTo(field("p-8d5cabf2ab59"));
    await typeIn("Oui, on y va", "draft");
    await activate(cardOf("p-8d5cabf2ab59").getByRole("button", { name: T("feedPractice.resume.inspect"), exact: true }), "inspect the evidence");
    check("Inspect moves focus to the source heading", await isFocused(page.getByRole("heading", { name: T("feedPractice.source.heading"), exact: true })));
    await activate(btn("feedPractice.resume.back", { id: "p-8d5cabf2ab59" }), "back to the exercise");
    check("Back to exercise returns focus to its field with the draft kept", (await isFocused(field("p-8d5cabf2ab59"))) && (await field("p-8d5cabf2ab59").inputValue()) === "Oui, on y va");
    await page.keyboard.press("End");
    await typeIn(" !", "finish");
    await press("Control+Enter", "check");
    await press("Control+Enter", "check again (same draft)");
    await cardOf("p-8d5cabf2ab59").locator('[data-outcome="correct"]').waitFor();
    const summary = page.locator('[data-practice="summary"]');
    check("a repeated check of the same answer is one attempt", (await summary.getAttribute("data-independent")) === "3", await summary.getAttribute("data-independent"));
    const share = page.locator('[data-packet="pk-afdb387f3af6"]');
    check("the packet preview names its scope and source revision before the copy", ((await share.locator('[data-share="scope"]').textContent()) || "").includes("fd55a3600f1c"));
    await activate(share.getByRole("button", { name: T("feedPractice.packet.copy"), exact: true }), "copy the packet");
    await share.locator('[data-copy="copied"]').waitFor();
    const clip = await page.evaluate(() => navigator.clipboard.readText());
    check("the clipboard holds study packet pk-afdb387f3af6", clip.startsWith("# FLH practice packet pk-afdb387f3af6") && clip.includes("study"), clip.slice(0, 80));
    const leaked = [...FORBIDDEN, "Oui, on y va !", "Oui, j'y reviens.", "« y » après à (j'y vais)"].filter((k) => clip.includes(k));
    check("the copied packet has no answer key and none of this visit's answers", leaked.length === 0 && !/"rubric"/.test(clip), leaked);
    await share.screenshot({ path: `${shots}/04-packet.png` });
    await step("packet");
    const scrolls = await page.evaluate(() => window.__scrolls);
    check("every scroll respects reduced motion (behavior auto)", scrolls.length > 0 && scrolls.every((b) => b === "auto"), scrolls);
    await activate(btn("feedPractice.exit"), "back to Review Today");
    await page.waitForTimeout(150);
    // the started item is still in today's set (the saved mistake leads it), so focus returns to its Start
    check("Back returns focus to the control that opened the concept", await isFocused(page.locator("#practice-start-p-664f7533a19d")), await focusName());

    // 4. A revision during a slow check.
    await tabTo(page.getByRole("checkbox", { name: T("feedPractice.delay.label"), exact: true }));
    await press(" ", "slow checks on");
    await activate(page.locator("#practice-open-y-en-demo"), "open y vs en");
    await page.getByRole("heading", { name: T("feedPractice.heading", { concept: "y vs en" }), exact: true }).waitFor();
    // This part races a 2-second simulated check, so its controls are focused
    // directly (the rest of the walkthrough reaches every control by Tab).
    const quick = async (loc, what) => {
      await loc.focus();
      await press("Enter", what);
    };
    await field("p-664f7533a19d").focus();
    await page.keyboard.press("Control+a");
    await typeIn("Oui, j'en reviens", "an unsent draft");
    await quick(cardOf("p-22a947cd7f5c").getByRole("button", { name: "y", exact: true }), "choose y (slow)");
    check("the check is announced as pending", (await cardOf("p-22a947cd7f5c").locator('[data-announce="pending"]').count()) === 1);
    await quick(btn("feedPractice.exit").first(), "back");
    const yRow = page.locator('[data-source-id="y-en-demo"][data-source="practice"]');
    await quick(yRow.getByRole("button", { name: T("feedPractice.rev.simulate", { revision: 2 }), exact: true }), "revision 2 arrives");
    check("the revision waits while an answer is in progress", (await yRow.locator('[data-reason-code="revision_waiting"]').count()) === 1 && (await yRow.getAttribute("data-revision")) === "1");
    await quick(yRow.getByRole("button", { name: T("feedPractice.rev.apply", { revision: 2 }), exact: true }), "apply revision 2");
    await page.waitForTimeout(2300);
    check("revision 2 withdrew the five exercises", (await yRow.getAttribute("data-revision")) === "2" && (await yRow.locator('[data-reason-code="withdrawn_source_revised"]').count()) === 1);
    const events = await page.locator(".feed-events li").evaluateAll((els) => els.map((e) => e.dataset.reasonCode));
    check("the late check was refused and the drafts were kept (reason codes)", ["revision_waiting", "revision_applied", "draft_kept_withdrawn", "late_response_withdrawn"].every((k) => events.includes(k)), events);
    await activate(page.locator("#practice-open-y-en-demo"), "open y vs en (revision 2)");
    await page.locator("[data-nothing-offered]").waitFor();
    check("revision 2 explains every withdrawn exercise with the producer's reason", (await page.locator("[data-withdrawn]").count()) === 5 && (await page.locator('[data-withdrawn] q').first().textContent()).startsWith("not offered from revision 2"));
    check("the unsent drafts are kept, not lost", (await page.locator('[data-kept="p-664f7533a19d"]').textContent()).includes("Oui, j'en reviens") && (await page.locator('[data-kept="p-22a947cd7f5c"]').count()) === 1);
    await page.screenshot({ path: `${shots}/05-withdrawn.png`, fullPage: true });
    await step("revision 2: withdrawn");
    await activate(btn("feedPractice.exit").first(), "back");
    await tabTo(page.getByRole("checkbox", { name: T("feedPractice.delay.label"), exact: true }));
    await press(" ", "slow checks off");
    await activate(yRow.getByRole("button", { name: T("feedPractice.rev.simulate", { revision: 2 }), exact: true }), "the re-approved revision 2 arrives");
    check("the re-approved revision restores the same five IDs", (await yRow.locator('[data-reason-code="restored_same_id"]').count()) === 1);
    await activate(page.locator("#practice-open-y-en-demo"), "open y vs en (restored)");
    await page.locator('.concept-practice [data-reason-code="restored_same_id"]').waitFor();
    await tabTo(cardOf("p-22a947cd7f5c").getByRole("button", { name: "y", exact: true }));
    await press("Enter", "choose y on revision 2");
    await cardOf("p-22a947cd7f5c").locator('[data-outcome="correct"]').waitFor();
    await page.screenshot({ path: `${shots}/06-restored.png`, fullPage: true });
    await step("revision 2 re-approved: restored");
    await activate(btn("feedPractice.exit").first(), "back");

    // 5. Tutor sessions.
    await activate(btn("feedPractice.tutor.show"), "show the tutor sessions");
    const s2 = page.getByRole("region", { name: T("feedPractice.tutor.session", { n: 2, agent: "claude-code" }), exact: true });
    const classes = await page.locator("[data-proposal]").evaluateAll((els) => els.map((e) => `${e.dataset.proposal}:${e.dataset.class}`));
    check(
      "every proposal is classed, with a text label (duplicates, conflict, unknown reference)",
      JSON.stringify(classes) === JSON.stringify(["c1:accepted_candidate", "c2:duplicate", "c3:accepted_candidate", "q1:conflict", "q2:accepted_candidate", "q3:duplicate", "q4:unknown_reference"]),
      classes,
    );
    const q2 = s2.locator('[data-proposal="q2"]');
    await activate(q2.getByRole("button", { name: T("feedPractice.tutor.accept", { id: "q2" }), exact: true }), "accept q2…");
    const confirm = q2.getByRole("group", { name: T("feedPractice.tutor.confirmLabel", { id: "q2" }), exact: true });
    check("the confirmation shows the exact change and the real command", ((await confirm.textContent()) || "").includes("--proposal q2") && (await q2.locator("[data-proposed]").count()) === 1);
    await activate(confirm.getByRole("button", { name: T("feedPractice.tutor.confirmAccept"), exact: true }), "confirm");
    check("q2 is accepted for this visit only", (await q2.locator('[data-accepted-visit="q2"]').count()) === 1);
    await page.locator('[data-tutors="open"]').screenshot({ path: `${shots}/07-tutors.png` });
    await step("tutor sessions");

    // 6. The log and its export.
    const log = page.locator('[data-log="visit"]');
    const origins = await log.locator("[data-entry]").evaluateAll((els) => els.map((e) => e.dataset.origin));
    check("history entries say where each outcome came from", origins.includes("exact_match") && origins.includes("learner_judgment"), origins);
    check("the week has activity", (await log.locator('[data-week="active"]').count()) === 1);
    await activate(log.getByRole("button", { name: T("feedPractice.log.export"), exact: true }), "export");
    await log.locator('[data-export="copied"]').waitFor();
    const expText = await page.evaluate(() => navigator.clipboard.readText());
    fs.writeFileSync(`${OUT}/export-${c.tag}.json`, expText);
    const exp = JSON.parse(expText);
    check(
      "the export has no answer texts by default, and every attempt names its feed revision",
      exp.answer_texts_included === false && !JSON.stringify(exp).includes("j'y reviens") && exp.attempts.every((a) => a.feed && a.revision_sha256.length === 64),
      { n: exp.attempts.length, feeds: [...new Set(exp.attempts.map((a) => a.feed))] },
    );
    await log.screenshot({ path: `${shots}/08-log.png` });
    await step("log");
    const unlabeled = await page.evaluate(() =>
      [...document.querySelectorAll("[data-outcome-tag], [data-class-tag]")].filter((e) => !(e.textContent || "").replace(/[✓✗?!👁+=≠\s]/gu, "").trim()).length,
    );
    check("every outcome and class tag carries words, not colour alone", unlabeled === 0, unlabeled);
    // a very long answer (an unbroken 400-character string, then a long French sentence) must not widen the page
    await activate(page.locator("#practice-open-savoir-connaitre-demo"), "open connaître vs savoir");
    await page.getByRole("heading", { name: T("feedPractice.heading", { concept: "connaître vs savoir" }), exact: true }).waitFor();
    await field("p-3ac3b47e483a").fill("x".repeat(400));
    await field("p-e61b319d2129").fill("Oui, je sais nager depuis que je suis tout petit, parce que mes parents m'emmenaient à la piscine municipale chaque samedi matin avant le marché. ".repeat(4));
    await tabTo(cardOf("p-e61b319d2129").getByRole("button", { name: T("feedPractice.answer.check"), exact: true }));
    await press("Enter", "check a long answer");
    await cardOf("p-e61b319d2129").locator("[data-outcome]").waitFor();
    await step("very long answers");
    await page.screenshot({ path: `${shots}/09-long-answers.png`, fullPage: false });
    await activate(btn("feedPractice.exit").first(), "back");
    fs.writeFileSync(`${OUT}/trace-${c.tag}.json`, JSON.stringify(trace, null, 1));
    const lost = trace.filter((x) => x.key !== "Tab" && x.focus === "body").map((x) => x.what);
    check("no key press leaves focus on the page body (keyboard trace)", lost.length === 0, lost);

    // 7. Reload.
    await page.reload();
    await btn("feedPractice.panel.open").waitFor();
    check("after a reload the panel is closed and nothing survives", (await page.locator('[data-log="visit"]').count()) === 0 && (await page.evaluate(() => sessionStorage.length)) === 0);
    check("no page errors", errors.length === 0, errors);
  } catch (e) {
    if (e !== "done") {
      check("walkthrough", false, String(e).slice(0, 700));
      await page.screenshot({ path: `${shots}/error.png`, fullPage: true }).catch(() => {});
    }
    fs.writeFileSync(`${OUT}/trace-${c.tag}.json`, JSON.stringify(trace, null, 1));
  }
  await ctx.close();
}
await browser.close();
fs.writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 1));
const failed = results.filter((r) => !r.pass);
console.log(`${results.length - failed.length}/${results.length} PASS`);
for (const r of results) console.log(r.pass ? "PASS" : "FAIL", r.combo, r.name, r.pass ? "" : r.detail);
process.exit(failed.length ? 1 : 0);
