import { expect, test } from "@playwright/test";

test("Electron chat routes a Codex OAuth account to the authenticated local inspection bridge", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const inspectionCalls: unknown[] = [];
    Object.assign(window, {
      __portlogInspectionCalls: inspectionCalls,
      portlogDesktop: {
        loadCurrentProject: async () => ({ projectId: "desktop-session" }),
        openRouterStatus: async () => ({
          provider: "openrouter",
          model: "deepseek/deepseek-v4-flash",
          credentialSource: "environment",
          configured: false,
        }),
        checkOpenRouter: async () => ({ ok: false }),
        claudeAuthStatus: async () => ({
          provider: "anthropic",
          state: "logged_in",
          recoverable: true,
        }),
        claudeLogin: async () => ({
          provider: "anthropic",
          state: "logged_in",
          recoverable: true,
        }),
        claudeCancelLogin: async () => ({
          provider: "anthropic",
          state: "logged_in",
          recoverable: true,
        }),
        claudeLogout: async () => ({
          provider: "anthropic",
          state: "logged_out",
          recoverable: true,
        }),
        codexAuthStatus: async () => ({
          provider: "openai-codex",
          state: "logged_in",
          recoverable: true,
        }),
        codexLogin: async () => ({
          provider: "openai-codex",
          state: "logged_in",
          recoverable: true,
        }),
        codexCancelLogin: async () => ({
          provider: "openai-codex",
          state: "logged_in",
          recoverable: true,
        }),
        codexLogout: async () => ({
          provider: "openai-codex",
          state: "logged_out",
          recoverable: true,
        }),
        selectDexpiSource: async () => null,
        persistImportedProject: async () => undefined,
        runLocalAsk: async (payload: unknown) => {
          inspectionCalls.push(payload);
          if (
            payload === null ||
            typeof payload !== "object" ||
            Array.isArray(payload) ||
            !("question" in payload) ||
            !("turnId" in payload) ||
            !("provider" in payload) ||
            typeof payload.question !== "string" ||
            typeof payload.turnId !== "string" ||
            typeof payload.provider !== "string"
          )
            throw new Error("Unexpected local inspection payload");
          if (payload.provider !== "openai-codex")
            throw new Error(`Unexpected desktop provider: ${payload.provider}`);
          return {
            turnId: payload.turnId,
            posture: "inspect",
            question: payload.question,
            status: "completed",
            finalText: "Desktop inspection succeeded.",
            evidenceIds: [],
            events: [],
            model: { provider: "openai-codex", id: "gpt-5.4" },
          };
        },
        cancelLocalInspection: async () => ({ cancelled: true }),
        onInspectionEvent: () => () => undefined,
      },
    });
  });

  let webTurnRequests = 0;
  await page.route("**/api/review/sessions/**/turns", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    webTurnRequests += 1;
    await route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Desktop chat must not use the web turn API." }),
    });
  });

  await page.goto("/assistant");
  const composer = page.getByRole("textbox", { name: "Message input" });
  await composer.fill("What is downstream of P-101?");
  await page.getByRole("button", { name: "Send message" }).click();

  await expect(page.getByText("Desktop inspection succeeded.")).toBeVisible();
  await expect.poll(() => webTurnRequests).toBe(0);
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (window as Window & { __portlogInspectionCalls?: unknown[] }).__portlogInspectionCalls
            ?.length ?? 0,
      ),
    )
    .toBe(1);
});
