import { expect, test } from "@playwright/test";

test("API keys page loads provider and model controls on the Electron loopback origin", async ({ page }) => {
  await page.goto("/account/api-keys");

  await expect(page.getByTestId("byok-provider-search")).toBeVisible();
  await expect(page.getByText("Loading…", { exact: true })).not.toBeVisible();

  const openRouter = page.getByTestId("byok-card-openrouter");
  await expect(openRouter).toBeVisible();
  await expect(openRouter.getByRole("button", { name: "Add key" })).toBeVisible();
  await openRouter.getByRole("button", { name: "Add key" }).click();
  await expect(openRouter.getByTestId("byok-input-openrouter")).toBeVisible();
  await expect(openRouter.getByTestId("byok-model-openrouter")).toBeEnabled();
});
