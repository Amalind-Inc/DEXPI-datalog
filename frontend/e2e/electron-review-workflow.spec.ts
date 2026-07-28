import { _electron as electron, expect, test } from "@playwright/test";
import { reviewWorkflow } from "./review-workflow";

const desktopUiUrl = `http://127.0.0.1:${process.env.PLAYWRIGHT_FRONTEND_PORT ?? "3000"}`;

test("Electron renders a prepared PortLog DEXPI review through the local backend", async () => {
  const desktop = await electron.launch({
    args: ["desktop/electron-main.cjs"],
    env: {
      ...process.env,
      PORTLOG_DESKTOP_UI_URL: desktopUiUrl,
    },
  });

  try {
    const page = await desktop.firstWindow();
    const workflow = reviewWorkflow(page);
    await page.goto(`${desktopUiUrl}/assistant`);
    await workflow.uploadPlantXml();
    await workflow.expectPreparedTopology("E06V01-VER.EX01.xml");

    await expect(page.getByTestId("auto-layout-schematic")).toBeVisible();
    await expect(page.getByText("Process document ready")).toBeVisible();
  } finally {
    await desktop.close();
  }
});
