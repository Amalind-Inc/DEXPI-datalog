import { expect, test } from "@playwright/test";

test("API keys page exposes desktop OAuth account controls", async ({ page }) => {
  await page.addInitScript(() => {
    let claudeLoggedIn = false;
    let codexLoggedIn = false;

    Object.assign(window, {
      portlogDesktop: {
        claudeAuthStatus: async () => ({
          provider: "anthropic",
          state: claudeLoggedIn ? "logged_in" : "logged_out",
          recoverable: true,
        }),
        claudeLogin: async () => {
          claudeLoggedIn = true;
          return { provider: "anthropic", state: "logged_in", recoverable: true };
        },
        claudeLogout: async () => {
          claudeLoggedIn = false;
          return { provider: "anthropic", state: "logged_out", recoverable: true };
        },
        codexAuthStatus: async () => ({
          provider: "openai-codex",
          state: codexLoggedIn ? "logged_in" : "logged_out",
          recoverable: true,
        }),
        codexLogin: async () => {
          codexLoggedIn = true;
          return { provider: "openai-codex", state: "logged_in", recoverable: true };
        },
        codexLogout: async () => {
          codexLoggedIn = false;
          return { provider: "openai-codex", state: "logged_out", recoverable: true };
        },
      },
    });
  });

  await page.goto("/account/api-keys");

  await expect(page.getByTestId("desktop-oauth-panel")).toBeVisible();
  await expect(page.getByTestId("desktop-oauth-status-anthropic")).toContainText("Not connected");
  await expect(page.getByRole("button", { name: "Connect Claude" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Use device code" })).toBeVisible();

  await page.getByRole("button", { name: "Connect Claude" }).click();
  await expect(page.getByTestId("desktop-oauth-status-anthropic")).toContainText("Connected");
  await expect(page.getByRole("button", { name: "Disconnect" }).first()).toBeVisible();
  await expect(page.getByTestId("desktop-oauth-select-anthropic")).toHaveText(
    "Selected for local chat",
  );
});
