import { expect, test } from "@playwright/test";

test("Harborfield homepage introduces PortLog before entering the workspace (bead 2cut)", async ({
  page,
}) => {
  await page.goto("/");

  await expect(page).toHaveTitle(/Harborfield/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Engineering knowledge that can show its work",
  );
  await expect(page.getByRole("link", { name: "Harborfield" }).first()).toBeVisible();
  await expect(page.getByRole("img", { name: "Harborfield sailboat" }).first()).toBeVisible();
  const account = page.getByRole("navigation", { name: "Account" });
  await expect(account.getByRole("link", { name: "Log in" })).toHaveAttribute("href", "/sign-in");
  await expect(account.getByRole("link", { name: "Sign Up" })).toHaveAttribute(
    "href",
    "/sign-in?mode=sign-up",
  );
  await expect(
    page.getByText(/process-engineering XML documents, including P&IDs, PFDs, and block diagrams/i),
  ).toBeVisible();

  const product = page.getByRole("region", { name: "Product capabilities" });
  await expect(product.getByRole("heading", { name: "PortLog" })).toBeVisible();
  await expect(product.getByRole("heading", { name: "Rulepacks" })).toBeVisible();
  await expect(product.getByRole("heading", { name: "Projects" })).toBeVisible();
  await expect(product.getByRole("heading", { name: "Logic engine" })).toBeVisible();

  await expect(page.getByRole("heading", { name: /Why neurosymbolic AI/ })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open PortLog" }).first()).toHaveAttribute(
    "href",
    "/assistant",
  );
  await expect(page.locator('link[rel~="icon"]')).toHaveAttribute("href", /icon\.svg/);
});

test("Account actions remain visible in the compact homepage header (bead 2cut)", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  const account = page.getByRole("navigation", { name: "Account" });
  await expect(account.getByRole("link", { name: "Log in" })).toBeVisible();
  await expect(account.getByRole("link", { name: "Sign Up" })).toBeVisible();
});

test("PortLog carries the Harborfield identity into the chat application (bead 2cut)", async ({
  page,
}) => {
  await page.goto("/assistant");

  await expect(page).toHaveTitle(/PortLog.*Harborfield/);
  const sidebar = page.getByRole("complementary", { name: "Sidebar navigation" });
  await expect(sidebar.getByText("PORTLOG", { exact: true })).toBeVisible();
  await expect(sidebar.getByRole("img", { name: "Harborfield sailboat" })).toBeVisible();
  await expect(sidebar.getByRole("link", { name: "PortLog" })).toHaveAttribute(
    "href",
    "/assistant",
  );
  await expect(
    page.getByRole("heading", {
      name: "How can I help you with your process document today?",
    }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Answers are grounded in the process document you upload here — nothing outside it.",
    ),
  ).toBeVisible();
  await expect(page.getByText(/your P&ID/i)).toHaveCount(0);
});

test("Sign Up opens the account form in registration mode (bead 2cut)", async ({ page }) => {
  await page.goto("/sign-in?mode=sign-up");

  await expect(page.getByRole("heading", { name: "Create an account" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create account" })).toBeVisible();
});
