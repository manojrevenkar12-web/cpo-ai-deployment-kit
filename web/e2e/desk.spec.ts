import { expect, test } from "@playwright/test";

const shot = async (page: import("@playwright/test").Page, name: string) => {
  if (process.env.SCREENSHOTS) await page.screenshot({ path: `../docs/screenshots/${name}.png`, fullPage: true });
};

test("the portfolio ranks the use cases and shows the gate", async ({ page }) => {
  await page.goto("./");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("under ten person-days");
  await expect(page.getByRole("row")).toHaveCount(5);
  await expect(page.getByRole("heading", { name: /Release gate: passed/ })).toBeVisible();
  await shot(page, "01-use-cases");
});

test("the rollout grid fills and the three measurements are explained", async ({ page }) => {
  await page.goto("./#/rollout");
  await expect(page.getByRole("table", { name: /driver refund tickets/ })).toBeVisible();
  await expect(page.getByRole("rowheader")).toHaveCount(11);
  await expect(page.getByText("What a usage dashboard would show")).toBeVisible();
  await page.waitForTimeout(1200);
  await shot(page, "02-rollout-and-impact");
});

test("a use case shows its gate, adoption and handover pack", async ({ page }) => {
  await page.goto("./");
  await page.getByRole("button", { name: /Driver refund tickets/ }).click();
  await expect(page.getByRole("heading", { name: "Go-live gate" })).toBeVisible();
  await expect(page.getByText(/Handover pack for/)).toBeVisible();
  await shot(page, "03-use-case");
});

test("a proposal shows its evidence and who must approve", async ({ page }) => {
  await page.goto("./#/proposals");
  const first = page.getByRole("button", { name: /credit/ }).first();
  await first.click();
  await expect(page.getByRole("heading", { name: "Evidence" })).toBeVisible();
  await expect(page.getByText(/needs finance approver in Teams/).first()).toBeVisible();
  await shot(page, "04-proposal");
});

test("a missing data file shows an error with a retry, not a blank page", async ({ page }) => {
  await page.route("**/data/rollout.json", (r) => r.fulfill({ status: 404, body: "" }));
  await page.goto("./#/rollout");
  await expect(page.getByRole("alert")).toContainText("did not load");
  await expect(page.getByRole("button", { name: "Load again" })).toBeVisible();
});
