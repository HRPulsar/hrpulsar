import { test, expect } from "./fixtures";
import { API_BASE, provisionTenantMember, registerUser, setAuthTokens } from "./helpers";
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
 * Roles, AI settings) is admin-only. Managers and employees must not see the group,
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

  test("employee sees the talent market but not recruitment (HRP-622, HRP-765)", async ({
    page,
  }) => {
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/dashboard");
    await expect(page.getByTestId("sidebar-nav")).toBeVisible({
      timeout: 15000,
    });
    // Recruitment reads are role-gated server-side (HRP-615); the entry
    // used to be rendered for everyone and led straight into a 403.
    await expect(page.getByTestId("sidebar-link-recruitment")).toHaveCount(0);
    // The talent market is open to employees again, scoped to the cards
    // they are candidates on (HRP-765).
    await expect(page.getByTestId("sidebar-link-talent-market")).toBeVisible();
    // Everyday surfaces stay reachable.
    await expect(page.getByTestId("sidebar-link-employees")).toBeVisible();
    await expect(page.getByTestId("sidebar-link-company")).toBeVisible();
  });

  test("manager keeps recruitment and talent market (HRP-622)", async ({
    page,
  }) => {
    await setAuthTokens(page, managerAccess, managerRefresh);
    await page.goto("/dashboard");
    await expect(page.getByTestId("sidebar-nav")).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByTestId("sidebar-link-recruitment")).toBeVisible();
    await expect(page.getByTestId("sidebar-link-talent-market")).toBeVisible();
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

  // M22b: recruitment is not part of the Admin section, but it is gated the
  // same way — the whole subtree sits behind RECRUITMENT_VIEWER_ROLES on the
  // API and used to render the shell for anyone with a bookmark.
  test("employee: /recruitment direct link redirects with an error toast", async ({
    page,
  }) => {
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/recruitment");

    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 15000 });
    await expect(page.getByTestId("recruitment-onboarding")).toHaveCount(0);
    await expectPermissionToast(page);
  });

  test("admin: /settings/roles lists roles with holder counts (HRP-634)", async ({
    page,
  }) => {
    await setAuthTokens(page, adminAccess, adminRefresh);
    await page.goto("/settings/roles");

    await expect(page.getByTestId("roles-table")).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByTestId("sidebar-link-roles")).toBeVisible();
    // This tenant was registered by `adminAccess` and then handed exactly
    // one manager and one employee, so both counts are known.
    await expect(page.getByTestId("roles-count-admin")).toHaveText("1");
    await expect(page.getByTestId("roles-count-manager")).toHaveText("1");
  });

  test("manager: /settings/roles direct link redirects with an error toast", async ({
    page,
  }) => {
    await setAuthTokens(page, managerAccess, managerRefresh);
    await page.goto("/settings/roles");

    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 15000 });
    await expect(page.getByTestId("roles-table")).toHaveCount(0);
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

/**
 * HRP-762, HRP-810: the Coverage surface opens for admin and HR, and for
 * anyone who reads at least one process. An employee with none neither sees
 * the sidebar link nor gets past a direct link; a manager gets the link once
 * a process is opened to managers.
 */
test.describe("Coverage access", () => {
  let employeeAccess: string;
  let employeeRefresh: string;
  let managerAccess: string;
  let managerRefresh: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const admin = await registerUser(page);
    const opts = { page, accessToken: admin.accessToken };
    const employee = await provisionTenantMember(opts, {
      roleCode: "employee",
      firstName: "Coverage",
      lastName: "Employee",
    });
    employeeAccess = employee.accessToken;
    employeeRefresh = employee.refreshToken;
    const manager = await provisionTenantMember(opts, {
      roleCode: "manager",
      firstName: "Coverage",
      lastName: "Manager",
    });
    managerAccess = manager.accessToken;
    managerRefresh = manager.refreshToken;
    const headers = { Authorization: `Bearer ${admin.accessToken}` };
    const created = await page.request.post(`${API_BASE}/work/containers`, {
      headers,
      data: { type: "process", title: `Access review ${Date.now()}` },
    });
    if (!created.ok()) throw new Error(`container failed: ${await created.text()}`);
    const opened = await page.request.put(
      `${API_BASE}/work/containers/${(await created.json()).id}/access`,
      { headers, data: { visibility: "restricted", rules: [{ role_code: "manager" }] } },
    );
    if (!opened.ok()) throw new Error(`access failed: ${await opened.text()}`);
    await page.close();
  });

  test("employee does not see the Coverage link and is bounced from /coverage", async ({
    page,
  }) => {
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/dashboard");
    await expect(page.getByTestId("sidebar-nav")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("sidebar-link-coverage")).toHaveCount(0);

    await page.goto("/coverage");
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 15000 });
    await expectPermissionToast(page);
  });

  test("manager reads a process opened to managers and opens the list", async ({ page }) => {
    await setAuthTokens(page, managerAccess, managerRefresh);
    await page.goto("/dashboard");
    await expect(page.getByTestId("sidebar-link-coverage")).toBeVisible({ timeout: 15000 });
    await page.getByTestId("sidebar-link-coverage").click();
    await expect(page).toHaveURL(/\/coverage$/, { timeout: 10000 });
    await expect(page.getByTestId("coverage-heading")).toBeVisible({ timeout: 10000 });
  });
});
