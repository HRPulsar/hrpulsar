import { test, expect } from "./fixtures";
import {
  API_BASE,
  completeOnboarding,
  provisionTenantMember,
  registerUser,
  setAuthTokens,
} from "./helpers";
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
 * Roles, AI settings) was admin-only; since HRP-831 the tenant's matrix
 * decides, and by default only Invitations opens below the admin role - to
 * `hr` and `manager`, on their scope. Whoever a section is closed to must
 * not see its entry, and a direct link must be denied with a toast +
 * redirect to /dashboard rather than rendering an empty page.
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

  test("manager sees Invitations of the Admin section and nothing else (HRP-831)", async ({ page }) => {
    await setAuthTokens(page, managerAccess, managerRefresh);
    await page.goto("/dashboard");
    await expect(page.getByTestId("sidebar-nav")).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByTestId("sidebar-link-invitations")).toBeVisible();
    for (const id of ["dictionaries", "import", "roles", "ai-settings"]) {
      await expect(page.getByTestId(`sidebar-link-${id}`)).toHaveCount(0);
    }
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

  test("manager: /settings/invitations opens on their own subtree (HRP-831)", async ({
    page,
    request,
  }) => {
    await setAuthTokens(page, managerAccess, managerRefresh);
    await page.goto("/settings/invitations");

    await expect(page.getByTestId("invitations-btn-invite")).toBeVisible({ timeout: 15000 });
    await expect(page).toHaveURL(/\/settings\/invitations$/);
    // The registry is the manager's subtree: their own invitation into the
    // division they head is there, the employee's (no division) is not.
    const listed = await request.get(`${API_BASE}/invitations`, {
      headers: { Authorization: `Bearer ${managerAccess}` },
    });
    expect(listed.status()).toBe(200);
    const items = (await listed.json()).items as { division_id: string | null }[];
    expect(items.length).toBeGreaterThan(0);
    expect(items.every((i) => i.division_id !== null)).toBe(true);
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

  test("the admin block follows the matrix: view opens the page, manage sends, none closes it (HRP-831)", async ({
    page,
    request,
  }) => {
    const employeeAuth = { Authorization: `Bearer ${employeeAccess}` };
    const saved = page
      .locator("[data-sonner-toast]")
      .filter({ hasText: /section access saved/i })
      .first();
    await completeOnboarding({ page, accessToken: adminAccess });
    const setEmployeeLevel = async (section: string, level: string) => {
      await setAuthTokens(page, adminAccess, adminRefresh);
      await page.goto("/company/profile/section-access");
      await expect(page.getByTestId("section-access-table")).toBeVisible({ timeout: 15000 });
      const select = page.getByTestId(`section-access-select-${section}-employee`);
      await select.selectOption(level);
      await expect(select).toHaveValue(level);
      await page.getByTestId("section-access-btn-save").click();
      await expect(saved).toBeVisible();
    };
    const invite = () =>
      request.post(`${API_BASE}/invitations`, {
        headers: employeeAuth,
        data: { email: `matrix-${Date.now()}@example.com`, name: "From the matrix", role_code: "employee" },
      });

    // `view`: the page opens on the registry, nothing sends.
    await setEmployeeLevel("invitations", "view");
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/settings/invitations");
    await expect(page.getByTestId("invitations-hint-title")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("invitations-btn-invite")).toHaveCount(0);
    expect((await invite()).status()).toBe(403);

    // `manage`: the API takes only a division the caller heads, and this
    // employee heads none - the fence, not the gate; the page hides the
    // button for the same reason (nowhere to send).
    await setEmployeeLevel("invitations", "manage");
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/settings/invitations");
    await expect(page.getByTestId("invitations-hint-title")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("invitations-btn-invite")).toHaveCount(0);
    const fenced = await invite();
    expect(fenced.status()).toBe(403);
    expect((await fenced.json()).code).toBe("outside_division_scope");

    // The other three open the same way: `view` reads, the default closes.
    await setEmployeeLevel("import", "view");
    expect((await request.get(`${API_BASE}/import/jobs`, { headers: employeeAuth })).status()).toBe(200);
    await setEmployeeLevel("import", "none");
    expect((await request.get(`${API_BASE}/import/jobs`, { headers: employeeAuth })).status()).toBe(403);

    // `none` (the default): the page bounces and so does the API.
    await setEmployeeLevel("invitations", "none");
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/settings/invitations");
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 15000 });
    await expectPermissionToast(page);
    expect((await request.get(`${API_BASE}/invitations`, { headers: employeeAuth })).status()).toBe(403);
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

/**
 * HRP-820: the admin hides a section for everyone on
 * /company/profile/section-access - the entry leaves every sidebar, a
 * direct link bounces, and the API answers 403.
 */
test.describe("Section access matrix (HRP-820)", () => {
  let adminAccess: string;
  let adminRefresh: string;
  let employeeAccess: string;
  let employeeRefresh: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const admin = await registerUser(page);
    adminAccess = admin.accessToken;
    adminRefresh = admin.refreshToken;
    const employee = await provisionTenantMember(
      { page, accessToken: adminAccess },
      { roleCode: "employee", firstName: "Matrix", lastName: "Employee" },
    );
    employeeAccess = employee.accessToken;
    employeeRefresh = employee.refreshToken;
    await page.close();
  });

  test("no role is offered a level below the Employee column (HRP-998)", async ({ page }) => {
    // Everyone holds the employee baseline and a level is the strongest
    // role's, so a level under the Employee column would change nothing.
    // Nothing is saved here - the other tests share this tenant.
    await setAuthTokens(page, adminAccess, adminRefresh);
    await page.goto("/company/profile/section-access");
    await expect(page.getByTestId("section-access-table")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("section-access-employee-floor")).toBeVisible();

    const managerNone = page
      .getByTestId("section-access-select-employees-manager")
      .locator('option[value="none"]');
    // Employees defaults to view for the Employee column.
    await expect(managerNone).toBeDisabled();
    await page.getByTestId("section-access-select-employees-employee").selectOption("none");
    await expect(managerNone).toBeEnabled();
  });

  test("hiding a section removes it for everyone", async ({ page, request }) => {
    await setAuthTokens(page, adminAccess, adminRefresh);
    await page.goto("/company/profile");
    await page.getByTestId("company-profile-link-section-access").click();
    await expect(page.getByTestId("section-access-table")).toBeVisible({ timeout: 15000 });
    // "company" is admin_locked (the admin row never drops below manage)
    // and "employees" is never_hidden — both controls stay disabled.
    await expect(page.getByTestId("section-access-select-company-admin")).toBeDisabled();
    await expect(page.getByTestId("section-access-hidden-employees")).toBeDisabled();

    await page.getByTestId("section-access-hidden-exams").click();
    await page.getByTestId("section-access-btn-save").click();
    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: /section access saved/i }).first(),
    ).toBeVisible();

    // No-reload refresh: save() calls refresh() on the auth context, so the
    // admin's own sidebar drops the hidden section right here, on the
    // matrix page itself (same layout), before any navigation.
    await expect(page.getByTestId("sidebar-link-exams")).toHaveCount(0);

    await page.goto("/dashboard");
    await expect(page.getByTestId("sidebar-nav")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("sidebar-link-exams")).toHaveCount(0);
    await expect(page.getByTestId("sidebar-link-employees")).toBeVisible();

    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/dashboard");
    await expect(page.getByTestId("sidebar-nav")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("sidebar-link-exams")).toHaveCount(0);
    // Proves the count-0 above isn't just an empty sidebar.
    await expect(page.getByTestId("sidebar-link-employees")).toBeVisible();

    // HRP-823: the mass exams are the section, so they are what a hidden
    // section closes - the page and the API alike.
    await page.goto("/exams/00000000-0000-0000-0000-000000000000");
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 15000 });
    await expectPermissionToast(page);

    const deniedEmployee = await request.get(`${API_BASE}/mass-exams`, {
      headers: { Authorization: `Bearer ${employeeAccess}` },
    });
    expect(deniedEmployee.status()).toBe(403);

    // "For everyone" includes the admin who hid it — the matrix closes the
    // section tenant-wide, not just for the roles that lack a manage level.
    const deniedAdmin = await request.get(`${API_BASE}/mass-exams`, {
      headers: { Authorization: `Bearer ${adminAccess}` },
    });
    expect(deniedAdmin.status()).toBe(403);

    // ... and an exam already assigned is still the taker's: their own
    // list keeps answering, and the page behind the assignment e-mail
    // keeps opening, on the taker's half of the entry.
    const ownExams = await request.get(`${API_BASE}/exams`, {
      headers: { Authorization: `Bearer ${employeeAccess}` },
    });
    expect(ownExams.status()).toBe(200);

    await page.goto("/exams");
    await expect(page.getByTestId("exams-heading")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("exams-btn-create")).toHaveCount(0);
  });

  test("the talent market follows the matrix: manage opens the board, none closes it (HRP-824)", async ({
    page,
    request,
  }) => {
    const employeeAuth = { Authorization: `Bearer ${employeeAccess}` };
    const saved = page
      .locator("[data-sonner-toast]")
      .filter({ hasText: /section access saved/i })
      .first();
    // A tenant with no employees sends the dashboard on to /onboarding, so
    // the bounce below would only pass through /dashboard; settle it first.
    await completeOnboarding({ page, accessToken: adminAccess });

    // The default: `view` - the candidate's half. The entry and the page
    // are there, the create button is not, and the API refuses a card.
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/talent-market");
    await expect(page.getByTestId("talent-market-heading")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("talent-market-btn-create")).toHaveCount(0);
    const refused = await request.post(`${API_BASE}/talent-market`, {
      headers: employeeAuth,
      data: { title: "From the matrix", card_type: "talent" },
    });
    expect(refused.status()).toBe(403);

    // Hand the section to the employee role: the button appears and the
    // same call goes through - no role change anywhere.
    await setAuthTokens(page, adminAccess, adminRefresh);
    await page.goto("/company/profile/section-access");
    await expect(page.getByTestId("section-access-table")).toBeVisible({ timeout: 15000 });
    await page.getByTestId("section-access-select-talent-market-employee").selectOption("manage");
    await page.getByTestId("section-access-btn-save").click();
    await expect(saved).toBeVisible();

    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/talent-market");
    await expect(page.getByTestId("talent-market-btn-create")).toBeVisible({ timeout: 15000 });
    const created = await request.post(`${API_BASE}/talent-market`, {
      headers: employeeAuth,
      data: { title: "From the matrix", card_type: "talent" },
    });
    expect(created.status()).toBe(201);

    // Take it away: the page bounces and the candidate's half closes too -
    // nothing of this section lives outside the matrix.
    await setAuthTokens(page, adminAccess, adminRefresh);
    await page.goto("/company/profile/section-access");
    await expect(page.getByTestId("section-access-table")).toBeVisible({ timeout: 15000 });
    await page.getByTestId("section-access-select-talent-market-employee").selectOption("none");
    await page.getByTestId("section-access-btn-save").click();
    await expect(saved).toBeVisible();

    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/talent-market");
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 15000 });
    await expectPermissionToast(page);
    const closed = await request.post(`${API_BASE}/talent-market/search`, {
      headers: employeeAuth,
      data: {},
    });
    expect(closed.status()).toBe(403);
  });

  test("development plans follow the matrix: manage opens authoring, none closes one's own plans (HRP-825)", async ({
    page,
    request,
  }) => {
    const employeeAuth = { Authorization: `Bearer ${employeeAccess}` };
    const saved = page
      .locator("[data-sonner-toast]")
      .filter({ hasText: /section access saved/i })
      .first();
    await completeOnboarding({ page, accessToken: adminAccess });
    const setEmployeeLevel = async (level: string) => {
      await setAuthTokens(page, adminAccess, adminRefresh);
      await page.goto("/company/profile/section-access");
      await expect(page.getByTestId("section-access-table")).toBeVisible({ timeout: 15000 });
      const select = page.getByTestId("section-access-select-development-employee");
      await select.selectOption(level);
      await expect(select).toHaveValue(level);
      await page.getByTestId("section-access-btn-save").click();
      await expect(saved).toBeVisible();
    };

    // The default: `view` - the plan owner's half. The page is there and
    // Create plan is greyed out with its reason.
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/development");
    await expect(page.getByTestId("development-heading")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("development-btn-create")).toBeDisabled();

    // Hand authoring to the employee role - no role change anywhere.
    await setEmployeeLevel("manage");
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/development");
    await expect(page.getByTestId("development-btn-create")).toBeEnabled({ timeout: 15000 });

    // Take it away: the page bounces and one's own plans close with it.
    await setEmployeeLevel("none");
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/development");
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 15000 });
    await expectPermissionToast(page);
    const closed = await request.get(`${API_BASE}/pdp`, { headers: employeeAuth });
    expect(closed.status()).toBe(403);
  });

  test("assessments follow the matrix: manage opens running them, none closes the section (HRP-826)", async ({
    page,
    request,
  }) => {
    const employeeAuth = { Authorization: `Bearer ${employeeAccess}` };
    const saved = page
      .locator("[data-sonner-toast]")
      .filter({ hasText: /section access saved/i })
      .first();
    await completeOnboarding({ page, accessToken: adminAccess });
    const setEmployeeLevel = async (level: string) => {
      await setAuthTokens(page, adminAccess, adminRefresh);
      await page.goto("/company/profile/section-access");
      await expect(page.getByTestId("section-access-table")).toBeVisible({ timeout: 15000 });
      const select = page.getByTestId("section-access-select-assessments-employee");
      await select.selectOption(level);
      await expect(select).toHaveValue(level);
      await page.getByTestId("section-access-btn-save").click();
      await expect(saved).toBeVisible();
    };

    // The default: `view` - the respondent's half. The list is there,
    // Create is not.
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/assessments");
    await expect(page.getByTestId("assessments-heading")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("assessments-btn-create")).toHaveCount(0);

    // Hand the section to the employee role - no role change anywhere.
    await setEmployeeLevel("manage");
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/assessments");
    await expect(page.getByTestId("assessments-btn-create")).toBeVisible({ timeout: 15000 });

    // Take it away: the page bounces and the API closes with it.
    await setEmployeeLevel("none");
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/assessments");
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 15000 });
    await expectPermissionToast(page);
    const closed = await request.get(`${API_BASE}/assessments`, { headers: employeeAuth });
    expect(closed.status()).toBe(403);
  });

  test("the competence catalogue follows the matrix: manage opens authoring, the pickers outlive none (HRP-827)", async ({
    page,
    request,
  }) => {
    const employeeAuth = { Authorization: `Bearer ${employeeAccess}` };
    const saved = page
      .locator("[data-sonner-toast]")
      .filter({ hasText: /section access saved/i })
      .first();
    await completeOnboarding({ page, accessToken: adminAccess });
    const setEmployeeLevel = async (level: string) => {
      await setAuthTokens(page, adminAccess, adminRefresh);
      await page.goto("/company/profile/section-access");
      await expect(page.getByTestId("section-access-table")).toBeVisible({ timeout: 15000 });
      const select = page.getByTestId("section-access-select-competences-employee");
      await select.selectOption(level);
      await expect(select).toHaveValue(level);
      await page.getByTestId("section-access-btn-save").click();
      await expect(saved).toBeVisible();
    };

    // The default: `view` - the tree reads, nothing writes.
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/competences");
    await expect(page.getByTestId("competences-tree")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("competences-btn-add-group")).toHaveCount(0);

    // Hand the section to the employee role: authoring opens, the AI
    // generation stays the admin role's.
    await setEmployeeLevel("manage");
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/competences");
    await expect(page.getByTestId("competences-btn-add-group")).toBeVisible({ timeout: 15000 });
    await expect(page.locator('[data-testid^="compgen-btn-"]')).toHaveCount(0);

    // Take it away: the page bounces, the tree every picker reads does not.
    await setEmployeeLevel("none");
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/competences");
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 15000 });
    await expectPermissionToast(page);
    const tree = await request.get(`${API_BASE}/competence-tree`, { headers: employeeAuth });
    expect(tree.status()).toBe(200);
    const write = await request.post(`${API_BASE}/competence-groups`, {
      headers: employeeAuth,
      data: { title: "From the matrix" },
    });
    expect(write.status()).toBe(403);
  });

  test("the org chart follows the matrix: manage opens authoring, the pickers outlive none (HRP-828)", async ({
    page,
    request,
  }) => {
    const employeeAuth = { Authorization: `Bearer ${employeeAccess}` };
    const saved = page
      .locator("[data-sonner-toast]")
      .filter({ hasText: /section access saved/i })
      .first();
    await completeOnboarding({ page, accessToken: adminAccess });
    const setEmployeeLevel = async (level: string) => {
      await setAuthTokens(page, adminAccess, adminRefresh);
      await page.goto("/company/profile/section-access");
      await expect(page.getByTestId("section-access-table")).toBeVisible({ timeout: 15000 });
      const select = page.getByTestId("section-access-select-company-employee");
      await select.selectOption(level);
      await expect(select).toHaveValue(level);
      await page.getByTestId("section-access-btn-save").click();
      await expect(saved).toBeVisible();
    };

    // The default: `view` - HRP-622: a plain employee keeps the overview
    // only, the positions tab bounces.
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/company/positions");
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 15000 });
    await expectPermissionToast(page);

    // Hand the section to the employee role: authoring opens.
    await setEmployeeLevel("manage");
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/company/positions");
    await expect(page.getByTestId("positions-btn-create")).toBeVisible({ timeout: 15000 });

    // Take it away: the pages bounce, the pickers every section reads and
    // the dashboard's own reads do not.
    await setEmployeeLevel("none");
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/company/positions");
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 15000 });
    await expectPermissionToast(page);
    for (const path of ["/divisions", "/positions", "/company", "/onboarding/status"]) {
      const read = await request.get(`${API_BASE}${path}`, { headers: employeeAuth });
      expect(read.status(), path).toBe(200);
    }
    const write = await request.post(`${API_BASE}/divisions`, {
      headers: employeeAuth,
      data: { name: "From the matrix" },
    });
    expect(write.status()).toBe(403);
  });

  test("the employee records follow the matrix: manage opens the HR record, the pickers outlive none (HRP-829)", async ({
    page,
    request,
  }) => {
    const employeeAuth = { Authorization: `Bearer ${employeeAccess}` };
    const saved = page
      .locator("[data-sonner-toast]")
      .filter({ hasText: /section access saved/i })
      .first();
    await completeOnboarding({ page, accessToken: adminAccess });
    const setEmployeeLevel = async (level: string) => {
      await setAuthTokens(page, adminAccess, adminRefresh);
      await page.goto("/company/profile/section-access");
      await expect(page.getByTestId("section-access-table")).toBeVisible({ timeout: 15000 });
      const select = page.getByTestId("section-access-select-employees-employee");
      await select.selectOption(level);
      await expect(select).toHaveValue(level);
      await page.getByTestId("section-access-btn-save").click();
      await expect(saved).toBeVisible();
    };

    // The member was invited with no division, so no card yet: file one.
    const member = await (await request.get(`${API_BASE}/auth/me`, { headers: employeeAuth })).json();
    const card = await request.post(`${API_BASE}/employees`, {
      headers: { Authorization: `Bearer ${adminAccess}` },
      data: { user_id: member.id, hire_date: "2025-01-01" },
    });
    expect(card.status()).toBe(201);
    const ownId = (await card.json()).id as string;

    // The default: `view` - the directory reads, nothing writes.
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/employees");
    await expect(page.getByTestId("employees-table")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("employees-multi-issues")).toHaveCount(0);
    await expect(page.getByTestId("employees-btn-create")).toHaveCount(0);

    // Hand the section to the employee role: the HR record opens. Heading
    // no division, the member has nowhere to file anyone, so no Add.
    await setEmployeeLevel("manage");
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/employees");
    await expect(page.getByTestId("employees-multi-issues")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("employees-btn-create")).toHaveCount(0);

    // Take it away: the pages bounce, the section's own reads close, the
    // people pickers every other section reads do not.
    await setEmployeeLevel("none");
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/employees");
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 15000 });
    await expectPermissionToast(page);
    for (const path of ["/employees", `/employees/${ownId}`, "/employees/me"]) {
      const read = await request.get(`${API_BASE}${path}`, { headers: employeeAuth });
      expect(read.status(), path).toBe(200);
    }
    const history = await request.get(`${API_BASE}/employees/${ownId}/education`, {
      headers: employeeAuth,
    });
    expect(history.status()).toBe(403);
  });

  test("recruitment follows the matrix: view reads, manage runs hiring, none closes it and its /v1 routes (HRP-830)", async ({
    page,
    request,
  }) => {
    const employeeAuth = { Authorization: `Bearer ${employeeAccess}` };
    const saved = page
      .locator("[data-sonner-toast]")
      .filter({ hasText: /section access saved/i })
      .first();
    await completeOnboarding({ page, accessToken: adminAccess });
    const setEmployeeLevel = async (level: string) => {
      await setAuthTokens(page, adminAccess, adminRefresh);
      await page.goto("/company/profile/section-access");
      await expect(page.getByTestId("section-access-table")).toBeVisible({ timeout: 15000 });
      const select = page.getByTestId("section-access-select-recruitment-employee");
      await select.selectOption(level);
      await expect(select).toHaveValue(level);
      await page.getByTestId("section-access-btn-save").click();
      await expect(saved).toBeVisible();
    };
    const createVacancy = () =>
      request.post(`${API_BASE}/recruitment/vacancies`, {
        headers: employeeAuth,
        data: { title: "From the matrix" },
      });

    // `view`: the section opens on the caller's own vacancies - none yet -
    // and nothing writes.
    await setEmployeeLevel("view");
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/recruitment/requisitions");
    await expect(page.getByTestId("recruitment-vacancy-count")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("recruitment-btn-create-vacancy")).toHaveCount(0);
    expect((await createVacancy()).status()).toBe(403);

    // `manage`: the same call goes through, and the button is there.
    await setEmployeeLevel("manage");
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/recruitment/requisitions");
    await expect(page.getByTestId("recruitment-btn-create-vacancy")).toBeVisible({ timeout: 15000 });
    const created = await createVacancy();
    expect(created.status()).toBe(201);
    const vacancyId = (await created.json()).id as string;

    // `none` (the default): the page bounces, and so do the hiring rounds
    // under /v1, which the gate did not see before this ticket.
    await setEmployeeLevel("none");
    await setAuthTokens(page, employeeAccess, employeeRefresh);
    await page.goto("/recruitment/requisitions");
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 15000 });
    await expectPermissionToast(page);
    for (const path of [`/recruitment/vacancies/${vacancyId}`, "/v1/tenants/me/assessment-scales"]) {
      const read = await request.get(`${API_BASE}${path}`, { headers: employeeAuth });
      expect(read.status(), path).toBe(403);
    }
  });
});
