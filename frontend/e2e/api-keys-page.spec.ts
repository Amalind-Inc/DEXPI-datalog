import { expect, type Page, test } from "@playwright/test";

// BYOK key management (beads 37e2 / hvso). Keys never leave the browser except
// on the turn that uses them, so the whole flow is exercised against
// localStorage with the provider probe stubbed out. Each test gets a fresh
// browser context, so storage already starts empty -- clearing it via an init
// script would re-run on every navigation and defeat the reload check.

/** Open a provider's "Add key" panel and wait for its models to load. */
async function addKey(page: Page, provider: string, credential: string) {
  await page.getByTestId(`byok-add-${provider}`).click();
  await expect(page.getByTestId(`byok-model-${provider}`)).toBeEnabled();
  if (credential) await page.getByTestId(`byok-input-${provider}`).fill(credential);
  await page.getByTestId(`byok-save-${provider}`).click();
}

test("providers come from the catalogue and are searchable", async ({ page }) => {
  await page.goto("/account/api-keys");

  // The majors lead the list...
  for (const provider of ["openrouter", "anthropic", "openai", "google"]) {
    await expect(page.getByTestId(`byok-card-${provider}`)).toBeVisible();
  }
  // ...and the long tail is reachable by search rather than scrolling.
  await expect(page.getByTestId("byok-card-cerebras")).toHaveCount(1);
  await page.getByTestId("byok-provider-search").fill("cereb");
  await expect(page.getByTestId("byok-card-cerebras")).toBeVisible();
  await expect(page.getByTestId("byok-card-openai")).toHaveCount(0);

  await page.getByTestId("byok-provider-search").fill("nothing-matches-this");
  await expect(page.getByText(/No providers match/)).toBeVisible();
});

test("a saved key becomes the active provider and is shown masked", async ({ page }) => {
  await page.goto("/account/api-keys");
  await addKey(page, "openai", "sk-live-abcdefgh12345678");

  await expect(page.getByTestId("byok-active-openai")).toBeVisible();
  await expect(page.getByTestId("byok-masked-openai")).toHaveText("sk-l…5678");

  // The key survives a reload — it is persisted, not just component state.
  await page.reload();
  await expect(page.getByTestId("byok-active-openai")).toBeVisible();

  // A second key is stored without stealing the active slot until asked.
  await addKey(page, "anthropic", "sk-ant-zyxwvu87654321");
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
  await page.getByTestId("byok-add-openai").click();
  await page.getByTestId("byok-input-openai").fill("sk-bogus-key-value");
  await page.getByTestId("byok-card-openai").getByRole("button", { name: "Test key" }).click();

  await expect(page.getByTestId("byok-test-result-openai")).toContainText(
    "Incorrect API key provided",
  );
});

test("removing the active key promotes the remaining one", async ({ page }) => {
  await page.goto("/account/api-keys");
  await addKey(page, "openai", "sk-live-abcdefgh12345678");
  await addKey(page, "google", "AIza-abcdefgh12345678");

  await page.getByTestId("byok-remove-openai").click();

  await expect(page.getByTestId("byok-active-google")).toBeVisible();
  await expect(page.getByTestId("byok-add-openai")).toBeVisible();
});

test("a local server is configured by model name with no credential", async ({ page }) => {
  await page.goto("/account/api-keys");
  await page.getByTestId("byok-provider-search").fill("ollama");
  await page.getByTestId("byok-add-ollama").click();

  // No API-key field: a local server authenticates by endpoint.
  await expect(page.getByTestId("byok-input-ollama")).toHaveCount(0);
  await page.getByTestId("byok-model-ollama").fill("ornith:35b");
  await page.getByTestId("byok-save-ollama").click();

  await expect(page.getByTestId("byok-active-ollama")).toBeVisible();
  await expect(page.getByTestId("byok-masked-ollama")).toHaveText("local");
});

test("the active key rides along with the turn the user asks", async ({ page }) => {
  await page.goto("/account/api-keys");
  await addKey(page, "openrouter", "sk-or-abcdefgh12345678");
  await expect(page.getByTestId("byok-active-openrouter")).toBeVisible();

  const selectedModel = await page.getByTestId("byok-model-openrouter").inputValue();

  const turnBodies: Array<Record<string, unknown>> = [];
  await page.route("**/api/review/sessions/**/turns", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    turnBodies.push(route.request().postDataJSON() as Record<string, unknown>);
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ session_id: "s", turn_id: "t", status: "canceled", events: [] }),
    });
  });

  await page.goto("/assistant");
  const composer = page.getByRole("textbox").first();
  await composer.fill("What is downstream of P-101?");
  await composer.press("Enter");

  await expect.poll(() => turnBodies.length).toBeGreaterThan(0);
  expect(turnBodies[0].provider_settings).toEqual({
    provider: "openrouter",
    model: selectedModel,
    credential: "sk-or-abcdefgh12345678",
  });
});
