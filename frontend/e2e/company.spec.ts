import { test, expect } from "./fixtures";
import {
  createDivision,
  provisionTenantMember,
  registerUser,
  setAuthTokens,
} from "./helpers";

test.describe("Company page", () => {
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

  test("company info card visible", async ({ page }) => {
    await page.goto("/company");
    await expect(page.getByTestId("company-card-info")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("company-name")).toBeVisible({
      timeout: 10000,
    });
  });

  test("edit company button visible", async ({ page }) => {
    await page.goto("/company");
    await expect(page.getByTestId("company-btn-edit")).toBeVisible({
      timeout: 10000,
    });
  });

  test("edit company dialog opens", async ({ page }) => {
    await page.goto("/company");
    await page.getByTestId("company-btn-edit").click();
    await expect(page.getByTestId("company-modal-edit")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId("company-modal-edit-input-name"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("company-modal-edit-input-slug"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("company-modal-edit-btn-submit"),
    ).toBeVisible({ timeout: 10000 });
  });

  test("divisions card visible", async ({ page }) => {
    await page.goto("/company");
    await expect(page.getByTestId("company-divisions-card")).toBeVisible({
      timeout: 10000,
    });
  });

  test("add division button visible", async ({ page }) => {
    await page.goto("/company");
    await expect(page.getByTestId("company-divisions-btn-add")).toBeVisible({
      timeout: 10000,
    });
  });
});

test.describe("Division CRUD", () => {
  let accessToken: string;
  let refreshToken: string;
  let divisionId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const creds = await registerUser(page);
    accessToken = creds.accessToken;
    refreshToken = creds.refreshToken;
    const div = await createDivision(
      { page, accessToken },
      "Engineering",
    );
    divisionId = div.id;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("division tree visible", async ({ page }) => {
    await page.goto("/company");
    await expect(page.getByTestId("company-divisions-tree")).toBeVisible({
      timeout: 10000,
    });
  });

  test("division node rendered", async ({ page }) => {
    await page.goto("/company");
    await expect(
      page.getByTestId(`company-division-${divisionId}`),
    ).toBeVisible({ timeout: 10000 });
  });

  test("division actions dropdown", async ({ page }) => {
    await page.goto("/company");
    await page
      .getByTestId(`company-division-${divisionId}-actions`)
      .click();
    await expect(
      page.getByTestId(`company-division-${divisionId}-btn-edit`),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId(`company-division-${divisionId}-btn-delete`),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId(`company-division-${divisionId}-btn-add-child`),
    ).toBeVisible({ timeout: 10000 });
  });

  test("add division dialog opens", async ({ page }) => {
    await page.goto("/company");
    await page.getByTestId("company-divisions-btn-add").click();
    await expect(page.getByTestId("company-modal-division")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId("company-modal-division-input-name"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("company-modal-division-btn-submit"),
    ).toBeVisible({ timeout: 10000 });
  });

  test("edit division dialog opens from actions", async ({ page }) => {
    await page.goto("/company");
    await page
      .getByTestId(`company-division-${divisionId}-actions`)
      .click();
    await page
      .getByTestId(`company-division-${divisionId}-btn-edit`)
      .click();
    await expect(page.getByTestId("company-modal-division")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId("company-modal-division-input-name"),
    ).toHaveValue("Engineering", { timeout: 10000 });
  });

  test("delete division triggers confirm dialog", async ({ page }) => {
    await page.goto("/company");
    await page
      .getByTestId(`company-division-${divisionId}-actions`)
      .click();
    await page
      .getByTestId(`company-division-${divisionId}-btn-delete`)
      .click();
    await expect(page.getByTestId("confirm-dialog")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId("confirm-dialog-btn-confirm"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("confirm-dialog-btn-cancel"),
    ).toBeVisible({ timeout: 10000 });
  });
});

/**
 * HRP-622 — the admin-only controls on /company (tenant edit, import, the
 * per-division action menu) used to render for everyone; the form opened
 * and the save came back 403.
 */
test.describe("Company page permission gates (HRP-622)", () => {
  test("an employee sees the org chart without any action control", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const opts = { page, accessToken: admin.accessToken };
    const division = await createDivision(opts, `Gated ${Date.now()}`);
    const member = await provisionTenantMember(opts, {
      roleCode: "employee",
      divisionId: division.id,
      firstName: "Gated",
      lastName: "Employee",
    });

    await setAuthTokens(page, member.accessToken, member.refreshToken);
    await page.goto("/company");
    await expect(page.getByTestId("company-divisions-card")).toBeVisible({
      timeout: 15000,
    });

    await expect(page.getByTestId("company-btn-edit")).toHaveCount(0);
    await expect(page.getByTestId("company-btn-import")).toHaveCount(0);
    await expect(
      page.getByTestId(`company-division-${division.id}-actions`),
    ).toHaveCount(0);
    await expect(page.getByTestId("company-divisions-btn-add")).toHaveCount(0);
  });

  test("an admin keeps all of them", async ({ page }) => {
    const admin = await registerUser(page);
    const division = await createDivision(
      { page, accessToken: admin.accessToken },
      `Gated ${Date.now()}`,
    );

    await setAuthTokens(page, admin.accessToken, admin.refreshToken);
    await page.goto("/company");
    await expect(page.getByTestId("company-btn-edit")).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByTestId("company-btn-import")).toBeVisible();
    await expect(
      page.getByTestId(`company-division-${division.id}-actions`),
    ).toHaveCount(1);
  });
});
