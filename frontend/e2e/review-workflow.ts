import { expect, type Locator, type Page } from "@playwright/test";
import path from "node:path";

export const e06DexpiFixture = path.resolve(
  "..",
  "TrainingTestCases",
  "dexpi 1.3",
  "example pids",
  "E06 Pump, HeatExchanger, Nozzles Connected With PNS",
  "E06V01-VER.EX01.xml",
);

export function reviewWorkflow(page: Page) {
  const chat = page.getByRole("region", { name: "Chat" });
  const graphPanel = page.getByRole("complementary", {
    name: "P&ID graph panel",
  });
  const composer = page.getByRole("textbox", { name: "Message input" });

  return {
    chat,
    graphPanel,
    composer,
    confirmationCards: page.locator('[data-testid="datalog-confirmation-card"]'),
    evidenceSummaries: page.locator('[data-testid="evidence-summary"]'),
    rawEvidenceDetails: page.locator('[data-testid="raw-evidence-details"]'),

    graphNode(label: string): Locator {
      return graphPanel.getByRole("button", { name: `Select ${label}` });
    },

    async open() {
      await page.goto("/");
      await expect(chat).toBeVisible();
      await expect(composer).toBeVisible();
    },

    async expectGraphNonPrimaryBeforeUpload() {
      await expect(graphPanel).toBeVisible();
      await expect(graphPanel.getByText("sample graph")).toBeVisible();
      await expect(chat).toBeVisible();
    },

    async uploadPlantXml(filePath = e06DexpiFixture) {
      const fileChooser = page.waitForEvent("filechooser");
      await page.getByRole("button", { name: "Add Attachment" }).click();
      await (await fileChooser).setFiles(filePath);
    },

    async expectPreparedTopology(filename: string) {
      await expect(graphPanel.getByText(filename)).toBeVisible();
      await expect(graphPanel.getByRole("img", { name: "P&ID topology graph" })).toBeVisible();
      await expect(graphPanel.getByRole("button").first()).toBeVisible();
    },

    async sendPrompt(prompt: string) {
      await composer.fill(prompt);
      await page.getByRole("button", { name: "Send message" }).click();
    },

    async expectAssistantReply(text: string | RegExp) {
      await expect(page.locator('[data-role="assistant"]').last()).toContainText(text);
    },

    async expectLatestAssistantReplyNotToContain(text: string | RegExp) {
      await expect(page.locator('[data-role="assistant"]').last()).not.toContainText(text);
    },

    async expandCollapsedSection(name: string | RegExp) {
      await page.getByRole("button", { name }).click();
    },
  };
}
