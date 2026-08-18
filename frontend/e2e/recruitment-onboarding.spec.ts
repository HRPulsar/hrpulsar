/**
 * R4d Group 5 — recruitment onboarding flow.
 *
 * Sticky onboarding banner visible across /recruitment/* until the user
 * either explicitly skips the tour or completes all five steps.
 * Requires E2E_MODE=true on the backend (helpers.registerUser uses
 * /auth/dev/auto-register).
 */
import { test, expect } from "./fixtures";
import { registerUser, loginViaUI } from "./helpers";

test.describe("Recruitment onboarding", () => {
  test("empty tenant sees welcome banner → seed demo hides the demo CTA", async ({
    page,
  }) => {
    const { email, password } = await registerUser(page);
    await loginViaUI(page, email, password);

    await page.goto("/recruitment");

    // /recruitment now redirects to /recruitment/requisitions; the sticky
    // banner is rendered by the recruitment layout so it shows up here.
    await expect(page).toHaveURL(/\/recruitment\/requisitions$/);
    await expect(page.getByTestId("recruitment-onboarding")).toBeVisible({
      timeout: 10000,
    });

    const seedButton = page.getByTestId("recruitment-onboarding-demo");
    await expect(seedButton).toBeVisible();

    await seedButton.click();

    // After seeding the demo CTA disappears (welcome step has been left).
    await expect(seedButton).toBeHidden({ timeout: 15000 });
  });

  test("skip tour permanently dismisses the banner", async ({ page }) => {
    const { email, password } = await registerUser(page);
    await loginViaUI(page, email, password);
    await page.goto("/recruitment");

    const banner = page.getByTestId("recruitment-onboarding");
    await expect(banner).toBeVisible({ timeout: 10000 });

    await page.getByTestId("recruitment-onboarding-dismiss").click();

    await expect(banner).toBeHidden({ timeout: 10000 });
  });

  test("banner stays visible across recruitment subpages", async ({ page }) => {
    const { email, password } = await registerUser(page);
    await loginViaUI(page, email, password);

    await page.goto("/recruitment/requisitions");
    await expect(page.getByTestId("recruitment-onboarding")).toBeVisible({
      timeout: 10000,
    });

    await page.goto("/recruitment/candidates");
    await expect(page.getByTestId("recruitment-onboarding")).toBeVisible({
      timeout: 10000,
    });

    await page.goto("/recruitment/reports");
    await expect(page.getByTestId("recruitment-onboarding")).toBeVisible({
      timeout: 10000,
    });
  });
});
