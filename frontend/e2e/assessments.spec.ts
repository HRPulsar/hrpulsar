import { test, expect } from "./fixtures";
import {
  registerUser,
  setAuthTokens,
  setupFullTenant,
  createAssessment,
} from "./helpers";

test.describe("Assessments page", () => {
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

  test("assessments page renders", async ({ page }) => {
    await page.goto("/assessments");
    await expect(page.getByTestId("assessments-heading")).toBeVisible({
      timeout: 10000,
    });
  });

  test("empty state for new tenant", async ({ page }) => {
    await page.goto("/assessments");
    await expect(page.getByTestId("assessments-empty")).toBeVisible({
      timeout: 10000,
    });
  });

  test("create button visible", async ({ page }) => {
    await page.goto("/assessments");
    await expect(page.getByTestId("assessments-btn-create")).toBeVisible({
      timeout: 10000,
    });
  });

  test("search input visible", async ({ page }) => {
    await page.goto("/assessments");
    await expect(page.getByTestId("assessments-input-search")).toBeVisible({
      timeout: 10000,
    });
  });

  test("type and status filters visible", async ({ page }) => {
    await page.goto("/assessments");
    await expect(page.getByTestId("assessments-multi-types")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("assessments-multi-statuses")).toBeVisible({
      timeout: 10000,
    });
  });

  test("HRP-86: type filter is multi-select", async ({ page }) => {
    await page.goto("/assessments");
    await page.getByTestId("assessments-multi-types").click();
    // Opens the dropdown; checkbox options carry the multi suffix per
    // TEST_IDS conventions. MultiSelectFilter keeps the menu open via
    // closeOnClick={false}, so successive clicks register on the same panel.
    await page.getByTestId("assessments-multi-types-option-self").click();
    await page.getByTestId("assessments-multi-types-option-180").click();
    // Canonical label format: "{placeholder} (n)" — matches employees page.
    await expect(page.getByTestId("assessments-multi-types")).toContainText("All types (2)");
  });

  test("mode selection dialog opens on create", async ({ page }) => {
    await page.goto("/assessments");
    await page.getByTestId("assessments-btn-create").click();
    await expect(page.getByTestId("assessments-modal-mode")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId("assessments-modal-mode-btn-single"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("assessments-modal-mode-btn-mass"),
    ).toBeVisible({ timeout: 10000 });
  });
});

test.describe("Assessments with data", () => {
  let accessToken: string;
  let refreshToken: string;
  let employeeId: string;
  let assessmentId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const setup = await setupFullTenant(page);
    accessToken = setup.accessToken;
    refreshToken = setup.refreshToken;
    employeeId = setup.employeeId;
    const assessment = await createAssessment(
      { page, accessToken },
      employeeId,
      "Q1 Performance Review",
      "self",
    );
    assessmentId = assessment.id;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("assessment table visible", async ({ page }) => {
    await page.goto("/assessments");
    await expect(page.getByTestId("assessments-table")).toBeVisible({
      timeout: 10000,
    });
  });

  test("assessment row rendered", async ({ page }) => {
    await page.goto("/assessments");
    await expect(
      page.getByTestId(`assessments-row-${assessmentId}`),
    ).toBeVisible({ timeout: 10000 });
  });

  test("status badge in row", async ({ page }) => {
    await page.goto("/assessments");
    await expect(
      page.getByTestId(`assessments-row-${assessmentId}-status`),
    ).toBeVisible({ timeout: 10000 });
  });

  test("actions dropdown opens", async ({ page }) => {
    await page.goto("/assessments");
    await page
      .getByTestId(`assessments-row-${assessmentId}-actions`)
      .click();
    await expect(
      page.getByTestId(`assessments-row-${assessmentId}-actions-content`),
    ).toBeVisible({ timeout: 10000 });
  });

  test("single create form opens", async ({ page }) => {
    await page.goto("/assessments");
    await page.getByTestId("assessments-btn-create").click();
    await expect(page.getByTestId("assessments-modal-mode")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("assessments-modal-mode-btn-single").click();
    await expect(page.getByTestId("assessments-modal-create")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId("assessments-modal-create-input-title"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("assessments-modal-create-select-employee"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("assessments-modal-create-select-type"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("assessments-modal-create-btn-submit"),
    ).toBeVisible({ timeout: 10000 });
  });

  test("search filters assessments", async ({ page }) => {
    await page.goto("/assessments");
    await expect(page.getByTestId("assessments-table")).toBeVisible({
      timeout: 10000,
    });
    await page
      .getByTestId("assessments-input-search")
      .fill("Q1 Performance Review");
    await page.waitForTimeout(500);
    await expect(page.getByTestId("assessments-table")).toBeVisible({
      timeout: 10000,
    });
    const rows = page.getByTestId("assessments-table").locator("tbody tr");
    expect(await rows.count()).toBeGreaterThanOrEqual(1);
  });
});
