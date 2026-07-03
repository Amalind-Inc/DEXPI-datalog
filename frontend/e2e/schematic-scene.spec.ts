import { expect, test } from "@playwright/test";
import { c01DexpiFixture, c03DexpiFixture, reviewWorkflow } from "./review-workflow";

test("preparing a geometry-bearing fixture renders the tier-1 schematic panel with selectable objects", async ({
  page,
}) => {
  const workflow = reviewWorkflow(page);

  await workflow.open();
  await workflow.uploadPlantXml(c01DexpiFixture);
  await workflow.expectPreparedSchematicScene("C01V04-VER.EX01.xml");

  const scene = page.getByTestId("schematic-scene");
  const symbols = scene.locator(".schematic-symbol[role='button']");
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
  const symbols = page.getByTestId("schematic-scene").locator(".schematic-symbol[role='button']");
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
