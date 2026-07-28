import { expect, test } from "@playwright/test";
import {
  c01DexpiFixture,
  c01ShelfFixture,
  c03DexpiFixture,
  e06DexpiFixture,
  reviewWorkflow,
} from "./review-workflow";

test("preparing a geometry-bearing fixture renders the tier-1 schematic panel with selectable objects", async ({
  page,
}) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml(c01DexpiFixture);
  await workflow.expectPreparedSchematicScene("C01V04-VER.EX01.xml");

  const scene = page.getByTestId("schematic-scene");
  const symbols = scene.locator("use.schematic-symbol[role='button']");
  await expect(symbols.first()).toBeVisible();
  const symbolCount = await symbols.count();
  expect(symbolCount).toBeGreaterThan(5);

  // Clicking a schematic object selects it -- same identity as the topology
  // panel's "selected node" details, since scene ids are topology ids.
  await symbols.first().click();
  await expect(page.locator(".pid-details h3")).toBeVisible();
});

test("clicking a piped equipment symbol shows its identity and connections", async ({ page }) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml(c01DexpiFixture);
  await workflow.expectPreparedSchematicScene("C01V04-VER.EX01.xml");

  // Click every symbol until one lands on a piped equipment unit -- not every
  // drawn symbol (e.g. a bare label glyph) has piping connections.
  const symbols = page
    .getByTestId("schematic-scene")
    .locator("use.schematic-symbol[role='button']");
  const count = await symbols.count();
  for (let index = 0; index < count; index += 1) {
    // Some drawn symbols are effectively zero-size connector glyphs
    // (scale ~0.0001); dispatch the click directly rather than relying on
    // Playwright's viewport/visibility actionability checks.
    await symbols.nth(index).dispatchEvent("click");
    if (await page.getByTestId("pid-connections").isVisible()) break;
  }
  await expect(page.getByTestId("pid-connections")).toBeVisible();
  await expect(page.getByTestId("pid-connections").locator("li").first()).toBeVisible();
});

test("a pipe run missing its source centerline gets the uniform inferred cue in an otherwise as-drawn scene (bead 2ki.6)", async ({
  page,
}) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml(c03DexpiFixture);
  await workflow.expectPreparedSchematicScene("C03V04-VER.EX02.xml");

  const scene = page.getByTestId("schematic-scene");
  // Two of C03's five segments carry no CenterLine -- routed between their
  // source-stated endpoints and flagged with the one uniform inferred cue,
  // while the rest of the scene is still the drawing-faithful tier-1 render.
  const inferredPipes = scene.locator("[data-inferred='true']");
  await expect(inferredPipes.first()).toBeVisible();
  expect(await inferredPipes.count()).toBe(2);

  const drawnPipes = scene.locator(".schematic-pipe:not([data-inferred='true'])");
  expect(await drawnPipes.count()).toBeGreaterThan(0);
});

test("equipment missing its source position renders on the shelf with a leader line and a click-through disclosure (bead 2ki.7)", async ({
  page,
}) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml(c01ShelfFixture);
  await workflow.expectPreparedSchematicScene("C01-shelf.xml");

  const scene = page.getByTestId("schematic-scene");
  await expect(page.getByTestId("schematic-shelf-region")).toBeVisible();

  const shelved = scene.locator("use[data-shelved='true']");
  await expect(shelved.first()).toBeVisible();
  expect(await shelved.count()).toBe(1);

  // The rest of C01 stays exactly as drawn -- plenty of non-shelved symbols
  // remain, this is a per-item demotion, not a whole-scene degradation.
  const drawnSymbols = scene.locator("use.schematic-symbol:not([data-shelved='true'])");
  expect(await drawnSymbols.count()).toBeGreaterThan(5);

  const shelvedHit = scene.locator("circle[data-shelved='true']");
  await shelvedHit.first().dispatchEvent("click");
  await expect(page.getByTestId("shelved-disclosure")).toBeVisible();
  await expect(page.getByTestId("shelved-disclosure")).toContainText("Position not in source");
});

test("an evidence-bearing answer auto-opens the tier-1 schematic panel and highlights the full witness run on chip click (bead 2ki.9)", async ({
  page,
}) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml(c01DexpiFixture);
  await workflow.expectPreparedSchematicScene("C01V04-VER.EX01.xml");

  // Close the topology panel that auto-opened on upload, so the assertion
  // below is unambiguously about the answer's evidence triggering the
  // reopen -- not it having stayed open the whole time.
  // The panel stays mounted (collapsed, animated shut) rather than
  // unmounting -- "reopen-graph" only renders when the graph is genuinely
  // closed, so it's a reliable signal instead of the collapsed panel's own
  // visibility (Playwright's toBeVisible() doesn't account for a
  // zero-width, overflow-clipped ancestor).
  await page.getByTestId("close-graph").click();
  await expect(page.getByTestId("reopen-graph")).toBeVisible();

  // A directed piping question resolves to multiple evidence paths -- the
  // witness for each is the full connected structural path, not just its
  // two endpoints.
  await workflow.sendPrompt("What is downstream of the segment?");
  await page.getByTestId("grounded-qa-answer").waitFor({ state: "visible" });

  // The answer carries evidence -- the panel reopens on its own, no click
  // on "open graph" required.
  const scene = page.getByTestId("schematic-scene");
  await expect(scene).toBeVisible();

  const highlightAll = page.getByTestId("qa-evidence-highlight-all");
  await expect(highlightAll).toBeVisible();

  await highlightAll.click();
  await expect(scene).toHaveAttribute("data-highlight-active", "true", { timeout: 3000 });
  // A structural path witness highlights as a connected run, not just its
  // two endpoints -- more than one drawn object should pick up the class.
  const highlightedCount = await scene.locator(".highlighted").count();
  expect(highlightedCount).toBeGreaterThan(1);

  // Manual close is respected afterward: closing now must not be undone by
  // this same already-rendered answer.
  await page.getByTestId("close-graph").click();
  await expect(page.getByTestId("reopen-graph")).toBeVisible();
});

test("geometry health card describes a healthy as-drawn fixture (bead 2ki.8)", async ({ page }) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml(c01DexpiFixture);
  await workflow.expectPreparedSchematicScene("C01V04-VER.EX01.xml");

  const summary = page.getByTestId("geometry-health-summary");
  await expect(summary).toContainText("As drawn");
  await expect(page.getByTestId("schematic-tier-badge")).toHaveAttribute("data-tier", "as-drawn");

  await summary.click();
  const stats = page.getByTestId("geometry-health-stat");
  await expect(stats.filter({ hasText: "Passed the geometry sanity gate" })).toBeVisible();
  await expect(stats.filter({ hasText: "on the shelf" })).toHaveCount(0);
});

test("geometry health card describes a partially-inferred fixture (bead 2ki.8)", async ({
  page,
}) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml(c01ShelfFixture);
  await workflow.expectPreparedSchematicScene("C01-shelf.xml");

  const summary = page.getByTestId("geometry-health-summary");
  await expect(summary).toContainText("Partially inferred");
  await expect(page.getByTestId("schematic-tier-badge")).toHaveAttribute(
    "data-tier",
    "partially-inferred",
  );

  await summary.click();
  await expect(
    page.getByTestId("geometry-health-stat").filter({ hasText: "1 item on the shelf" }),
  ).toBeVisible();
});

test("geometry health card describes an auto-layout demoted fixture (bead 2ki.8)", async ({
  page,
}) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml(e06DexpiFixture);
  await workflow.expectPreparedTopology("E06V01-VER.EX01.xml");

  const summary = page.getByTestId("geometry-health-summary");
  await expect(summary).toContainText("Auto-layout");
  // Tier-2 keeps its existing dedicated badge; no schematic-tier-badge here.
  await expect(page.getByTestId("schematic-tier-badge")).toHaveCount(0);

  await summary.click();
  // E06 carries no drawable positions, so its extent is degenerate -- the
  // gate reasons are a real typed diagnostic list, not a fixed message.
  await expect(
    page
      .getByTestId("geometry-health-stat")
      .filter({ hasText: "Did not pass the geometry sanity gate" }),
  ).toContainText("the drawing extent is degenerate");
});
