import { test, expect } from "@playwright/test";
import { registerUser, setAuthTokens, setupFullTenant } from "./helpers";

test.describe("Employees page", () => {
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

  test("empty state for new tenant", async ({ page }) => {
    await page.goto("/employees");
    await expect(page.getByTestId("employees-empty")).toBeVisible({
      timeout: 10000,
    });
  });

  test("search input visible", async ({ page }) => {
    await page.goto("/employees");
    await expect(page.getByTestId("employees-input-search")).toBeVisible({
      timeout: 10000,
    });
  });

  test("create employee button visible", async ({ page }) => {
    await page.goto("/employees");
    await expect(page.getByTestId("employees-btn-create")).toBeVisible({
      timeout: 10000,
    });
  });

  test("open create employee dialog", async ({ page }) => {
    await page.goto("/employees");
    await page.getByTestId("employees-btn-create").click();
    await expect(page.getByTestId("employees-modal-create")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId("employees-modal-create-select-user"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("employees-modal-create-input-position"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("employees-modal-create-input-hire-date"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("employees-modal-create-btn-submit"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("employees-modal-create-btn-cancel"),
    ).toBeVisible({ timeout: 10000 });
  });

  test("close create dialog with cancel", async ({ page }) => {
    await page.goto("/employees");
    await page.getByTestId("employees-btn-create").click();
    await expect(page.getByTestId("employees-modal-create")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("employees-modal-create-btn-cancel").click();
    await expect(page.getByTestId("employees-modal-create")).not.toBeVisible({
      timeout: 10000,
    });
  });

  // HRP-399: a 422 from the backend must surface inside the modal instead of
  // leaving it silently open.
  test("backend validation errors are shown in the create modal", async ({
    page,
  }) => {
    await page.goto("/employees");
    await page.getByTestId("employees-btn-create").click();
    await expect(page.getByTestId("employees-modal-create")).toBeVisible({
      timeout: 10000,
    });

    // Submit the empty form: user_id and hire_date fail backend validation.
    await page.getByTestId("employees-modal-create-btn-submit").click();

    await expect(
      page.getByTestId("employees-modal-create-error-user-id"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("employees-modal-create-error-hire-date"),
    ).toBeVisible({ timeout: 10000 });
    // Modal stays open and the submit button leaves its loading state.
    await expect(page.getByTestId("employees-modal-create")).toBeVisible();
    await expect(
      page.getByTestId("employees-modal-create-btn-submit"),
    ).toBeEnabled();
    await expect(
      page.getByTestId("employees-modal-create-btn-submit"),
    ).toHaveText("Create");
  });
});

test.describe("Employees CRUD", () => {
  let accessToken: string;
  let refreshToken: string;
  let employeeId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const setup = await setupFullTenant(page);
    accessToken = setup.accessToken;
    refreshToken = setup.refreshToken;
    employeeId = setup.employeeId;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("employee table visible with data", async ({ page }) => {
    await page.goto("/employees");
    await expect(page.getByTestId("employees-table")).toBeVisible({
      timeout: 10000,
    });
    const rows = page.getByTestId("employees-table").locator("tbody tr");
    await expect(rows.first()).toBeVisible({ timeout: 10000 });
    expect(await rows.count()).toBeGreaterThanOrEqual(1);
  });

  test("employee row shows name", async ({ page }) => {
    await page.goto("/employees");
    await expect(
      page.getByTestId(`employees-row-${employeeId}`),
    ).toBeVisible({ timeout: 10000 });
  });

  test("row actions dropdown opens", async ({ page }) => {
    await page.goto("/employees");
    await page.getByTestId(`employees-row-${employeeId}-actions`).click();
    await expect(
      page.getByTestId(`employees-row-${employeeId}-btn-edit`),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId(`employees-row-${employeeId}-btn-delete`),
    ).toBeVisible({ timeout: 10000 });
  });

  test("edit dialog opens from row actions", async ({ page }) => {
    await page.goto("/employees");
    await page.getByTestId(`employees-row-${employeeId}-actions`).click();
    await page.getByTestId(`employees-row-${employeeId}-btn-edit`).click();
    await expect(page.getByTestId("employees-modal-edit")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId("employees-modal-edit-input-position"),
    ).toBeVisible({ timeout: 10000 });
  });

  test("search filters employees", async ({ page }) => {
    await page.goto("/employees");
    await expect(page.getByTestId("employees-table")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("employees-input-search").fill("E2E Tester");
    // Wait for debounce
    await page.waitForTimeout(500);
    await expect(page.getByTestId("employees-table")).toBeVisible({
      timeout: 10000,
    });
    const rows = page.getByTestId("employees-table").locator("tbody tr");
    expect(await rows.count()).toBeGreaterThanOrEqual(1);
  });

  test("clear filters works", async ({ page }) => {
    await page.goto("/employees");
    await expect(page.getByTestId("employees-table")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("employees-input-search").fill("some filter text");
    await page.waitForTimeout(500);
    await page.getByTestId("employees-btn-clear-filters").click();
    await expect(page.getByTestId("employees-input-search")).toHaveValue("", {
      timeout: 10000,
    });
  });
});
