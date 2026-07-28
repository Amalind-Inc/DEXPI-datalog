import { chromium } from "playwright";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const FIXTURE = path.resolve(
  __dirname, "..", "TrainingTestCases", "dexpi 1.3", "example pids",
  "E06 Pump, HeatExchanger, Nozzles Connected With PNS", "E06V01-VER.EX01.xml",
);

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });

  await page.goto("http://127.0.0.1:3000");
  await page.waitForLoadState("networkidle");

  const fileChooserPromise = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Add Attachment" }).click();
  const fileChooser = await fileChooserPromise;
  await fileChooser.setFiles(FIXTURE);
  await page.waitForSelector('[aria-label="P&ID topology graph"]', { timeout: 30000 });
  console.log("Topology loaded");

  await page.getByRole("textbox", { name: "Message input" }).fill(
    "What downstream process objects are reachable from the pump?"
  );
  await page.getByRole("button", { name: "Send message" }).click();

  await page.waitForSelector('[data-testid="datalog-confirmation-card"]', { timeout: 60000 });
  console.log("Confirmation card appeared");
  await page.screenshot({ path: path.join(__dirname, "03-confirmation.png") });

  await page.locator('[data-testid="datalog-confirmation-card"]').last()
    .getByRole("button", { name: "Run" }).click();

  await page.waitForSelector('[data-testid="grounded-logic-answer"]', { timeout: 60000 });
  await page.screenshot({ path: path.join(__dirname, "04-after-run.png") });
  console.log("Grounded answer appeared");

  const summaryText = await page.locator('[data-testid="evidence-summary"]').textContent();
  console.log("\nevidence-summary:", JSON.stringify(summaryText));

  await browser.close();
}

main().catch((err) => { console.error(err); process.exit(1); });
