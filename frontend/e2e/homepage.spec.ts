import { expect, test } from "@playwright/test";

test("Amalind homepage explains the product before entering the workspace (bead 1sky)", async ({
  page,
}) => {
  await page.goto("/");

  await expect(page).toHaveTitle(/Amalind/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Engineering knowledge that can show its work",
  );

  const product = page.getByRole("region", { name: "Product capabilities" });
  await expect(product.getByRole("heading", { name: "Assistant" })).toBeVisible();
  await expect(product.getByRole("heading", { name: "Rulepacks" })).toBeVisible();
  await expect(product.getByRole("heading", { name: "Projects" })).toBeVisible();
  await expect(product.getByRole("heading", { name: "Logic engine" })).toBeVisible();

  await expect(page.getByRole("heading", { name: /Why neurosymbolic AI/ })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open assistant" }).first()).toHaveAttribute(
    "href",
    "/assistant",
  );
});
