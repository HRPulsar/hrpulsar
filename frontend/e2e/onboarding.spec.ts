import { test, expect } from "@playwright/test";
import { registerUser, setAuthTokens } from "./helpers";

test.describe("Onboarding wizard", () => {
  let accessToken: string;
  let refreshToken: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const creds = await registerUser(page);
    accessToken = creds.accessToken;
    refreshToken = creds.refreshToken;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("redirects to onboarding for new tenant", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/onboarding/, { timeout: 10000 });
  });

  test("step indicators visible", async ({ page }) => {
    await page.goto("/onboarding");
    await expect(page.getByTestId("onboarding-step-0")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("onboarding-step-1")).toBeVisible();
    await expect(page.getByTestId("onboarding-step-2")).toBeVisible();
    await expect(page.getByTestId("onboarding-step-3")).toBeVisible();
  });

  test("onboarding form visible", async ({ page }) => {
    await page.goto("/onboarding");
    await expect(page.getByTestId("onboarding-form")).toBeVisible({
      timeout: 10000,
    });
  });

  test("step 0 - next button advances", async ({ page }) => {
    await page.goto("/onboarding");
    await expect(page.getByTestId("onboarding-btn-next")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("onboarding-btn-next").click();
    await expect(page.getByText("First Division")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("onboarding-step-0")).toHaveClass(
      /bg-primary/,
      { timeout: 10000 },
    );
  });

  test("step 1 - back button returns", async ({ page }) => {
    await page.goto("/onboarding");
    await expect(page.getByTestId("onboarding-btn-next")).toBeVisible({
      timeout: 10000,
    });
    // Advance to step 1
    await page.getByTestId("onboarding-btn-next").click();
    await expect(page.getByText("First Division")).toBeVisible({
      timeout: 10000,
    });
    // Go back to step 0
    await page.getByTestId("onboarding-btn-back").click();
    await expect(page.getByText("Company Info")).toBeVisible({
      timeout: 10000,
    });
  });
});
