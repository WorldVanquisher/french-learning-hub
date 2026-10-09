"""Write an FLH-032 copy of the FLH-030 browser acceptance harness.

Usage: python3 -B adapt030.py SRC_ACCEPTANCE_MJS DST_MJS

FLH-030 steps S1 and S2 asserted the pre-FLH-032 behavior (the old storage
alert text, and clicking keyed buttons that FLH-032 now disables). This replaces
only those two steps with the FLH-032 expectations; every other step is copied
unchanged. The FLH-030 source file is read, never modified.
"""
import sys

S1_S2 = r'''await step("S1 storage write fails before sending: honest alert, keyed controls disabled, explicit recheck, nothing sent", async () => {
  await goToUnit(10);
  await selectConcept("alpha");
  await page.evaluate(() => (window.__storageFail = { allow: 0 }));
  const before = posts.length;
  await decisionButton("DISTINCT").click();
  const alert = page.getByRole("alert").filter({ hasText: "Browser storage failed. Nothing was sent; reload recovery cannot be guaranteed." });
  await alert.waitFor(T);
  const alertText = await text(alert);
  const thrown = await page.evaluate(() => window.__storageFail.thrown);
  await page.evaluate(() => (window.__storageFail = null));
  const keyedDisabled = await decisionButton("BROADER").isDisabled();
  const sameUnit = await page.getByRole("button", { name: "SAME → selected" }).isEnabled();
  await page.getByRole("button", { name: "Recheck browser storage" }).click();
  await page.getByText("Browser storage works again. Keyed decisions are enabled; nothing was sent.").waitFor(T);
  const enabledAfter = await decisionButton("DISTINCT").isEnabled();
  assert(keyedDisabled && sameUnit && enabledAfter, `keyedDisabled ${keyedDisabled}, same ${sameUnit}, enabledAfter ${enabledAfter}`);
  assert(posts.length === before && (await distinctions(10)).length === 0 && (await relations(10, C.alpha, "broader")).length === 0, "something sent");
  await page.screenshot({ path: `${SHOTS}/${LABEL}-storage-failed.png`, fullPage: true });
  return `alert "${alertText.slice(0, 160)}" | setItem threw ${thrown}x | BROADER disabled, unkeyed SAME enabled | recheck after storage recovered re-enabled keyed decisions | 0 POSTs, 0 events`;
});

await step("S2 corrupt saved operations on load: honest alert, keyed controls disabled, nothing sent", async () => {
  await page.evaluate((k) => window.localStorage.setItem(k, "{not json"), KEY);
  await page.reload();
  await openReview();
  const alert = page.getByRole("alert").filter({ hasText: "Browser storage is unavailable or invalid. Unresolved identity cannot be recovered across reload; new keyed annotations are blocked." });
  await alert.waitFor(T);
  await goToUnit(10);
  await selectConcept("beta");
  const before = posts.length;
  const disabled = await decisionButton("RELATED").isDisabled();
  await sleep(500);
  const sent = posts.length - before;
  const raw = await page.evaluate((k) => window.localStorage.getItem(k), KEY);
  await page.evaluate((k) => window.localStorage.removeItem(k), KEY);
  await page.reload();
  await openReview();
  const alertsAfter = await page.getByRole("alert").filter({ hasText: "Browser storage" }).count();
  assert(disabled && sent === 0 && raw === "{not json" && alertsAfter === 0, `disabled ${disabled}, sent ${sent}, raw ${raw}, alerts ${alertsAfter}`);
  return `alert shown on load | RELATED disabled, 0 sent | corrupt value left untouched | after clearing it and reloading: no storage alert`;
});

'''


def main() -> None:
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as f:
        text = f.read()
    start = text.index('await step("S1 ')
    end = text.index('await step("S3 ')
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text[:start] + S1_S2 + text[end:])


if __name__ == "__main__":
    main()
