import { test, expect } from "./fixtures";
import { registerUser, setAuthTokens, createDivision } from "./helpers";

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
