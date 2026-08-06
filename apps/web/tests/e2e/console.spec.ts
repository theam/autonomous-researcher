import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

async function expectNoSeriousAccessibilityViolations(page: Page) {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();

  expect(
    result.violations.filter(({ impact }) => impact === "critical" || impact === "serious"),
  ).toEqual([]);
}

test.describe("Limina Console", () => {
  test("loads without a framework overlay or browser error", async ({ page }) => {
    const browserErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") browserErrors.push(message.text());
    });
    page.on("pageerror", (error) => browserErrors.push(error.message));

    await page.goto("/");
    await page.waitForTimeout(500);
    await expect(page.locator("body")).not.toHaveText("");
    await expect(
      page.locator("[data-nextjs-dialog], .vite-error-overlay, #webpack-dev-server-client-overlay"),
    ).toHaveCount(0);
    expect(browserErrors).toEqual([]);
  });

  for (const path of ["/", "/projects", "/new", "/settings/health"] as const) {
    test(`${path} renders meaningful, accessible content`, async ({ page }) => {
      await page.goto(path);
      await expect(page.locator("main")).toBeVisible();
      await expect(page.locator("body")).not.toContainText("Application error");
      await expectNoSeriousAccessibilityViolations(page);
    });
  }

  test("keyboard users can bypass the shell navigation", async ({ page }) => {
    await page.goto("/");
    await page.keyboard.press("Tab");
    const skipLink = page.getByRole("link", { name: "Skip to main content" });
    await expect(skipLink).toBeFocused();
    await skipLink.press("Enter");
    await expect(page.locator("main")).toBeFocused();
  });

  test("creates a safe draft, configures write-only input, and attaches live", async ({
    page,
  }, testInfo) => {
    const suffix = `${testInfo.project.name}-${Date.now()}`
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-");
    const slug = `console-e2e-${suffix}`;
    const secretValue = `never-render-${suffix}`;

    await page.goto("/new");
    await page.getByLabel("Project name").fill("Console acceptance");
    await page.getByLabel("Stable slug").fill(slug);
    await page
      .getByRole("textbox", { name: "Mission", exact: true })
      .fill("Validate the Console control plane.");
    await page
      .getByLabel("Success criteria")
      .fill("Draft, secret, and live attachment remain safe and operable.");
    await page.getByRole("button", { name: "Create draft" }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${slug}$`));
    await expect(page.getByRole("heading", { name: "Console acceptance" })).toBeVisible();

    await page.getByRole("link", { name: "Settings" }).click();
    await page.getByLabel("Secret name").fill("E2E_SECRET");
    await page.getByLabel("Secret value").fill(secretValue);
    await page.getByRole("button", { name: "Set write-only secret" }).click();
    await expect(page.getByText("E2E_SECRET")).toBeVisible();
    await expect(page.getByText("Configured · value hidden")).toBeVisible();
    await expect(page.locator("body")).not.toContainText(secretValue);

    await page.getByRole("link", { name: "Live" }).click();
    await expect(page.getByRole("heading", { name: "Live project activity" })).toBeVisible();
    await expect(page.getByRole("status")).toHaveText("live", { timeout: 10_000 });
    await expectNoSeriousAccessibilityViolations(page);
  });
});
