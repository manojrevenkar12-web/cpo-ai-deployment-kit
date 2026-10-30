import { expect, test } from "@playwright/test";

test("reads on a phone without sideways scrolling of the page", async ({ page }) => {
  await page.goto("./#/rollout");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  if (process.env.SCREENSHOTS) await page.screenshot({ path: "../docs/screenshots/05-phone.png", fullPage: true });
});
