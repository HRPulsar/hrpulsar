import { test, expect } from "@playwright/test";
import { registerUser, setAuthTokens, completeOnboarding } from "./helpers";

test.describe("Sidebar navigation", () => {
  let accessToken: string;
  let refreshToken: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const creds = await registerUser(page);
    accessToken = creds.accessToken;
    refreshToken = creds.refreshToken;
    await completeOnboarding({ page, accessToken });
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("sidebar renders navigation links", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByTestId("sidebar-nav")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("sidebar-link-dashboard")).toBeVisible();
    await expect(page.getByTestId("sidebar-link-employees")).toBeVisible();
    await expect(page.getByTestId("sidebar-link-company")).toBeVisible();
    await expect(page.getByTestId("sidebar-link-assessments")).toBeVisible();
    await expect(page.getByTestId("sidebar-link-development")).toBeVisible();
    await expect(page.getByTestId("sidebar-link-exams")).toBeVisible();
    await expect(page.getByTestId("sidebar-link-competences")).toBeVisible();
  });

  test("navigate via sidebar links", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByTestId("sidebar-nav")).toBeVisible({
      timeout: 10000,
    });

    await page.getByTestId("sidebar-link-employees").click();
    await expect(page).toHaveURL(/\/employees/);

    await page.getByTestId("sidebar-link-assessments").click();
    await expect(page).toHaveURL(/\/assessments/);

    await page.getByTestId("sidebar-link-exams").click();
    await expect(page).toHaveURL(/\/exams/);

    await page.getByTestId("sidebar-link-company").click();
    await expect(page).toHaveURL(/\/company/);
  });

  test("dashboard KPI strip renders", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByTestId("dashboard-title")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("dashboard-kpi-headcount")).toBeVisible();
    await expect(page.getByTestId("dashboard-kpi-active-reviews")).toBeVisible();
    await expect(page.getByTestId("dashboard-kpi-divisions")).toBeVisible();
    await expect(page.getByTestId("dashboard-kpi-open-pdps")).toBeVisible();
  });
});

test.describe("Header", () => {
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

  test("user menu opens", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByTestId("header-btn-user-menu")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("header-btn-user-menu").click();
    await expect(page.getByTestId("header-menu-settings")).toBeVisible({
      timeout: 3000,
    });
    await expect(page.getByTestId("header-menu-signout")).toBeVisible();
  });

  test("settings link from user menu", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByTestId("header-btn-user-menu")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("header-btn-user-menu").click();
    await expect(page.getByTestId("header-menu-settings")).toBeVisible({
      timeout: 3000,
    });
    await page.getByTestId("header-menu-settings").click();
    await expect(page).toHaveURL(/\/settings\/profile/);
  });

  test("sign out redirects to login", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByTestId("header-btn-user-menu")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("header-btn-user-menu").click();
    await expect(page.getByTestId("header-menu-signout")).toBeVisible({
      timeout: 3000,
    });
    await page.getByTestId("header-menu-signout").click();
    await expect(page).toHaveURL(/\/login/, { timeout: 10000 });
  });

  test("theme toggle works", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByTestId("header-btn-theme")).toBeVisible({
      timeout: 10000,
    });

    const htmlBefore = await page.locator("html").getAttribute("class");
    await page.getByTestId("header-btn-theme").click();
    await page.waitForTimeout(500);
    const htmlAfter = await page.locator("html").getAttribute("class");

    expect(htmlAfter).not.toBe(htmlBefore);
  });
});
