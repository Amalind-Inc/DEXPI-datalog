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

// Geometry-bearing fixture (file-defined shape catalogue + as-drawn
// positions + drawn centerlines) -- renders the tier-1 schematic (ADR 0004).
export const c01DexpiFixture = path.resolve(
  "..",
  "TrainingTestCases",
  "dexpi 1.3",
  "example pids",
  "C01 DEXPI Reference P&ID",
  "C01V04-VER.EX01.xml",
);

// Otherwise geometry-bearing (passes the sanity gate) but two of its five
// PipingNetworkSegments carry no CenterLine -- exercises the per-pipe
// routed-run demotion (bead pydexpi-datalog-1-2ki.6) rather than the
// whole-scene auto-layout degradation.
export const c03DexpiFixture = path.resolve(
  "..",
  "TrainingTestCases",
  "dexpi 1.3",
  "example pids",
  "C03 Piping (Equinor)",
  "C03V04-VER.EX02.xml",
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
    datalogDetails: page.locator('[data-testid="datalog-details"]'),

    graphNode(label: string): Locator {
      return graphPanel.getByRole("button", { name: `Select ${label}` });
    },

    async open() {
      await page.goto("/");
      await expect(chat).toBeVisible();
      await expect(composer).toBeVisible();
    },

    async expectGraphNonPrimaryBeforeUpload() {
      // Graph-on-demand: the topology panel is not shown until a P&ID is
      // prepared. The chat is the primary, full-width surface on entry.
      await expect(chat).toBeVisible();
      await expect(graphPanel).toHaveCount(0);
    },

    async uploadPlantXml(filePath = e06DexpiFixture) {
      const fileChooser = page.waitForEvent("filechooser");
      await page.getByRole("button", { name: "Add Attachment" }).click();
      await (await fileChooser).setFiles(filePath);
    },

    async expectPreparedTopology(filename: string) {
      await expect(graphPanel.getByText(filename)).toBeVisible();
      // Graphics-bearing topologies render the compressed Cytoscape P&ID view
      // (a canvas, so node interactivity is not exposed as DOM buttons).
      await expect(page.getByTestId("cytoscape-pid-graph")).toBeVisible();
    },

    async expectPreparedSchematicScene(filename: string) {
      await expect(graphPanel.getByText(filename)).toBeVisible();
      // Geometry-bearing topologies render the tier-1 drawing-faithful
      // schematic instead of the auto-laid-out Cytoscape view (ADR 0004).
      await expect(page.getByTestId("schematic-panel")).toBeVisible();
      await expect(page.getByTestId("schematic-scene")).toBeVisible();
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

    async expectViewportHeightStable() {
      const heights = [];
      for (let index = 0; index < 5; index += 1) {
        await page.waitForTimeout(250);
        heights.push(
          await page.evaluate(() => ({
            body: document.body.scrollHeight,
            shell: document.querySelector(".pid-app-shell")?.getBoundingClientRect().height,
          })),
        );
      }
      expect(new Set(heights.map((height) => height.body)).size).toBe(1);
      expect(new Set(heights.map((height) => height.shell)).size).toBe(1);
    },
  };
}
