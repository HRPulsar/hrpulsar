import { test, expect } from "./fixtures";
import { provisionTenantMember, registerUser, setAuthTokens } from "./helpers";
import type { Page } from "@playwright/test";

/**
 * Assert the guard's own toast, not just any toast — the dashboard raises its
 * own after the redirect, and sonner auto-dismisses in a few seconds.
 * sonner renders into [data-sonner-toast].
 */
async function expectPermissionToast(page: Page) {
  await expect(
    page
      .locator("[data-sonner-toast]")
      .filter({ hasText: /don't have permission/i })
      .first(),
  ).toBeVisible();
}

/**
 * HRP-436: the Admin sidebar section (Dictionaries, Invitations, Import,
 * AI settings) is admin-only. Managers and employees must not see the group,
 * and a direct link must be denied with a toast + redirect to /dashboard
 * rather than rendering an empty page.
 */
test.describe("Admin section access", () => {
  let adminAccess: string;
  let adminRefresh: string;
  let managerAccess: string;
  let managerRefresh: string;
  let employeeAccess: string;
  let employeeRefresh: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();

    const admin = await registerUser(page);
    adminAccess = admin.accessToken;
    adminRefresh = admin.refreshToken;

    const manager = await provisionTenantMember(
      { page, accessToken: adminAccess },
      { roleCode: "manager", firstName: "Access", lastName: "Manager" },
    );
    managerAccess = manager.accessToken;
    managerRefresh = manager.refreshToken;

    const employee = await provisionTenantMember(
      { page, accessToken: adminAccess },
      { roleCode: "employee", firstName: "Access", lastName: "Employee" },
    );
    employeeAccess = employee.accessToken;
    employeeRefresh = employee.refreshToken;

    await page.close();
  });

  test("admin sees the Admin section links", async ({ page }) => {
    await setAuthTokens(page, adminAccess, adminRefresh);
    await page.goto("/dashboard");
    await expect(page.getByTestId("sidebar-nav")).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByTestId("sidebar-link-dictionaries")).toBeVisible();
    await expect(page.getByTestId("sidebar-link-invitations")).toBeVisible();
  });

  test("manager does not see the Admin section links", async ({ page }) => {
    await setAuthTokens(page, managerAccess, managerRefresh);
    await page.goto("/dashboard");
    await expect(page.getByTestId("sidebar-nav")).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByTestId("sidebar-link-dictionaries")).toHaveCount(0);
    await expect(page.getByTestId("sidebar-link-invitations")).toHaveCount(0);
  });

  test("employee does not see the Admin section links", async ({ page }) => {
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/dashboard");
    await expect(page.getByTestId("sidebar-nav")).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByTestId("sidebar-link-dictionaries")).toHaveCount(0);
    await expect(page.getByTestId("sidebar-link-invitations")).toHaveCount(0);
  });

  test("manager: /dictionaries direct link redirects with an error toast", async ({
    page,
  }) => {
    await setAuthTokens(page, managerAccess, managerRefresh);
    await page.goto("/dictionaries");

    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 15000 });
    await expectPermissionToast(page);
  });

  test("manager: /settings/invitations direct link redirects with an error toast", async ({
    page,
  }) => {
    await setAuthTokens(page, managerAccess, managerRefresh);
    await page.goto("/settings/invitations");

    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 15000 });
    await expect(page.getByTestId("invitations-table")).toHaveCount(0);
    await expectPermissionToast(page);
  });

  test("manager: /settings/ai direct link redirects with an error toast", async ({
    page,
  }) => {
    await setAuthTokens(page, managerAccess, managerRefresh);
    await page.goto("/settings/ai");

    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 15000 });
    await expectPermissionToast(page);
  });

  test("employee: /settings/invitations direct link redirects with an error toast", async ({
    page,
  }) => {
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/settings/invitations");

    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 15000 });
    await expect(page.getByTestId("invitations-table")).toHaveCount(0);
    await expectPermissionToast(page);
  });

  test("employee: /dictionaries direct link redirects with an error toast", async ({
    page,
  }) => {
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/dictionaries");

    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 15000 });
    await expectPermissionToast(page);
  });
});
