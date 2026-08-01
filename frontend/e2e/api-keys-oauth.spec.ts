import { expect, test } from "@playwright/test";

test("API keys page exposes desktop OAuth account controls without hydration errors", async ({
  page,
}) => {
  const hydrationErrors: string[] = [];
  page.on("console", (message) => {
    if (/(Hydration failed|Encountered a script tag)/i.test(message.text()))
      hydrationErrors.push(message.text());
  });
  page.on("pageerror", (error) => {
    if (/(Hydration failed|Encountered a script tag)/i.test(error.message))
      hydrationErrors.push(error.message);
  });
  await page.addInitScript(() => {
    let claudeLoggedIn = false;
    let codexLoggedIn = false;
    let selectedProvider: "anthropic" | "openai-codex" | null = null;

    Object.assign(window, {
      __portlogSelectedProvider: () => selectedProvider,
      portlogDesktop: {
        getSelectedChatProvider: async () => selectedProvider,
        setSelectedChatProvider: async (provider: "anthropic" | "openai-codex" | null) => {
          selectedProvider = provider;
          return provider;
        },
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
  await page.getByRole("button", { name: "Connect OpenAI Codex" }).click();
  await expect(page.getByTestId("desktop-oauth-status-openai-codex")).toContainText("Connected");
  await expect(page.getByTestId("desktop-oauth-select-openai-codex")).toHaveText(
    "Selected for local chat",
  );
  await expect
    .poll(() =>
      page.evaluate(() =>
        (
          window as Window & { __portlogSelectedProvider?: () => string | null }
        ).__portlogSelectedProvider?.(),
      ),
    )
    .toBe("openai-codex");
  expect(hydrationErrors).toEqual([]);
});
