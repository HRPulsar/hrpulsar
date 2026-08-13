import { test, expect } from "@playwright/test";
import {
  registerUser,
  setAuthTokens,
  standAvailableLocales,
} from "./helpers";

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
    await expect(page.getByTestId("onboarding-step-4")).toBeVisible();
  });

  test("onboarding form visible", async ({ page }) => {
    await page.goto("/onboarding");
    await expect(page.getByTestId("onboarding-form")).toBeVisible({
      timeout: 10000,
    });
  });

  test("step 0 - language step shows AI content language select", async ({
    page,
  }) => {
    await page.goto("/onboarding");
    // Always present regardless of AVAILABLE_LOCALES; the interface-language
    // select (onboarding-select-ui-language) appears only on multi-locale
    // deployments.
    await expect(
      page.getByTestId("onboarding-select-content-language"),
    ).toBeVisible({ timeout: 10000 });
    // F7 (HRP-481): CI runs multi-locale (AVAILABLE_LOCALES=de,en), so
    // the interface-language select is present on the language step; on a
    // single-locale stack it is hidden by design. Gated on what the stand
    // actually serves (HRP-511 e) — the env flag alone lied when the
    // frontend was started without NEXT_PUBLIC_AVAILABLE_LOCALES.
    if ((await standAvailableLocales(page)).length > 1) {
      await expect(
        page.getByTestId("onboarding-select-ui-language"),
      ).toBeVisible({ timeout: 10000 });
    }
  });

  test("step 0 - next button advances", async ({ page }) => {
    await page.goto("/onboarding");
    await expect(page.getByTestId("onboarding-btn-next")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("onboarding-btn-next").click();
    // F2: STEPS[] titles now resolve through t() — these assertions match the
    // default-locale (en) values of onboarding.stepCompanyInfo /
    // onboarding.stepFirstDivision. F7 runs CI multi-locale but keeps
    // DEFAULT_LOCALE=en, so en text matchers stay valid as-is.
    await expect(page.getByText("Company Info")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("onboarding-step-0")).toHaveClass(
      /bg-primary/,
      { timeout: 10000 },
    );
  });

  test("walks language and company steps to divisions", async ({ page }) => {
    await page.goto("/onboarding");
    await expect(page.getByTestId("onboarding-btn-next")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("onboarding-btn-next").click();
    await expect(page.getByText("Company Info")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("onboarding-btn-next").click();
    await expect(page.getByText("First Division")).toBeVisible({
      timeout: 10000,
    });
  });

  test("step 1 - back button returns to language step", async ({ page }) => {
    await page.goto("/onboarding");
    await expect(page.getByTestId("onboarding-btn-next")).toBeVisible({
      timeout: 10000,
    });
    // Advance to step 1 (Company Info)
    await page.getByTestId("onboarding-btn-next").click();
    await expect(page.getByText("Company Info")).toBeVisible({
      timeout: 10000,
    });
    // Go back to step 0 (Language)
    await page.getByTestId("onboarding-btn-back").click();
    await expect(
      page.getByTestId("onboarding-select-content-language"),
    ).toBeVisible({ timeout: 10000 });
  });
});
