import { expect, test } from "@playwright/test";

// BYOK key management (bead pydexpi-datalog-1-37e2). Keys never leave the
// browser except on the turn that uses them, so the whole flow is exercised
// against localStorage with the provider probe stubbed out. Each test gets a
// fresh browser context, so storage already starts empty -- clearing it via an
// init script would re-run on every navigation and defeat the reload check.

test("a saved key becomes the active provider and is shown masked", async ({ page }) => {
  await page.goto("/account/api-keys");

  // Every provider the backend supports is offered.
  for (const provider of ["openrouter", "openai", "anthropic", "gemini"]) {
    await expect(page.getByTestId(`byok-card-${provider}`)).toBeVisible();
  }
  await expect(page.getByTestId("byok-no-active-key")).toBeVisible();

  await page.getByTestId("byok-input-openai").fill("sk-live-abcdefgh12345678");
  await page.getByTestId("byok-save-openai").click();

  await expect(page.getByTestId("byok-active-openai")).toBeVisible();
  await expect(page.getByTestId("byok-masked-openai")).toHaveText("sk-l…5678");
  await expect(page.getByTestId("byok-no-active-key")).toHaveCount(0);

  // The key survives a reload — it is persisted, not just component state.
  await page.reload();
  await expect(page.getByTestId("byok-active-openai")).toBeVisible();

  // A second key is stored without stealing the active slot until asked.
  await page.getByTestId("byok-input-anthropic").fill("sk-ant-zyxwvu87654321");
  await page.getByTestId("byok-save-anthropic").click();
  await expect(page.getByTestId("byok-active-openai")).toBeVisible();

  await page.getByTestId("byok-activate-anthropic").click();
  await expect(page.getByTestId("byok-active-anthropic")).toBeVisible();
  await expect(page.getByTestId("byok-active-openai")).toHaveCount(0);
});

test("testing a key reports the provider's verdict", async ({ page }) => {
  await page.route("**/api/byok/validate", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: false,
        provider: "openai",
        message: "Incorrect API key provided",
      }),
    }),
  );

  await page.goto("/account/api-keys");
  await page.getByTestId("byok-input-openai").fill("sk-bogus-key-value");
  await page.getByTestId("byok-card-openai").getByRole("button", { name: "Test key" }).click();

  await expect(page.getByTestId("byok-test-result-openai")).toContainText(
    "Incorrect API key provided",
  );
});

test("removing the active key promotes the remaining one", async ({ page }) => {
  await page.goto("/account/api-keys");

  await page.getByTestId("byok-input-openai").fill("sk-live-abcdefgh12345678");
  await page.getByTestId("byok-save-openai").click();
  await page.getByTestId("byok-input-gemini").fill("AIza-abcdefgh12345678");
  await page.getByTestId("byok-save-gemini").click();

  await page.getByTestId("byok-remove-openai").click();

  await expect(page.getByTestId("byok-active-gemini")).toBeVisible();
  await expect(page.getByTestId("byok-input-openai")).toBeVisible();
});

test("the active key rides along with the turn the user asks", async ({ page }) => {
  await page.goto("/account/api-keys");
  await page.getByTestId("byok-input-openrouter").fill("sk-or-abcdefgh12345678");
  await page.getByTestId("byok-save-openrouter").click();
  await expect(page.getByTestId("byok-active-openrouter")).toBeVisible();

  const turnBodies: Array<Record<string, unknown>> = [];
  await page.route("**/api/review/sessions/**/turns", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    turnBodies.push(route.request().postDataJSON() as Record<string, unknown>);
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        session_id: "s",
        turn_id: "t",
        status: "canceled",
        events: [],
      }),
    });
  });

  await page.goto("/assistant");
  const composer = page.getByRole("textbox").first();
  await composer.fill("What is downstream of P-101?");
  await composer.press("Enter");

  await expect.poll(() => turnBodies.length).toBeGreaterThan(0);
  expect(turnBodies[0].provider_settings).toEqual({
    provider: "openrouter",
    model: "anthropic/claude-sonnet-4",
    credential: "sk-or-abcdefgh12345678",
  });
});
