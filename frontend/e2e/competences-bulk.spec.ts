import { test, expect } from "@playwright/test";
import {
  createCompetenceGroup,
  registerUser,
  seedOriginGroup,
  setAuthTokens,
} from "./helpers";

// HRP-138 — bulk-add competences flow. Backend pieces (POST
// /competence-groups/{id}/competences/bulk + billing coverage) were shipped
// in HRP-108; these specs lock the Playwright path that exercises the new
// inline button and multi-row dialog end-to-end on a freshly registered
// tenant.

test.describe("HRP-138 — bulk-add competences", () => {
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

  test("cold start — bulk-add button opens the dialog", async ({ page }) => {
    const stamp = Date.now();
    const group = await createCompetenceGroup(
      { page, accessToken },
      `BulkOpen ${stamp}`,
    );

    await page.goto("/competences");
    await expect(
      page.getByTestId(`competences-group-${group.id}`),
    ).toBeVisible({ timeout: 10000 });

    // The button is hidden until hover/focus; click via testid bypasses that.
    await page
      .getByTestId(`competences-group-${group.id}-btn-bulk-add`)
      .click({ force: true });
    await expect(page.getByTestId("competences-modal-bulk")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId("competences-modal-bulk-row-0"),
    ).toBeVisible();
  });

  test("happy path — three rows create three competences", async ({ page }) => {
    const stamp = Date.now();
    const group = await createCompetenceGroup(
      { page, accessToken },
      `BulkHappy ${stamp}`,
    );

    await page.goto("/competences");
    await page
      .getByTestId(`competences-group-${group.id}-btn-bulk-add`)
      .click({ force: true });
    await expect(page.getByTestId("competences-modal-bulk")).toBeVisible();

    await page
      .getByTestId("competences-modal-bulk-row-0-title")
      .fill(`Bulk A ${stamp}`);
    await page
      .getByTestId("competences-modal-bulk-row-0-description")
      .fill("Alpha");

    await page.getByTestId("competences-modal-bulk-btn-add-row").click();
    await page
      .getByTestId("competences-modal-bulk-row-1-title")
      .fill(`Bulk B ${stamp}`);

    await page.getByTestId("competences-modal-bulk-btn-add-row").click();
    await page
      .getByTestId("competences-modal-bulk-row-2-title")
      .fill(`Bulk C ${stamp}`);

    await page.getByTestId("competences-modal-bulk-btn-submit").click();
    await expect(page.getByTestId("competences-modal-bulk")).toBeHidden({
      timeout: 10000,
    });

    const count = page.getByTestId(`competences-group-${group.id}-count`);
    await expect(count).toContainText("3", { timeout: 10000 });
    for (const name of [
      `Bulk A ${stamp}`,
      `Bulk B ${stamp}`,
      `Bulk C ${stamp}`,
    ]) {
      await expect(page.getByText(name).first()).toBeVisible();
    }
  });

  test("edge — empty rows are filtered, removed row is skipped", async ({
    page,
  }) => {
    const stamp = Date.now();
    const group = await createCompetenceGroup(
      { page, accessToken },
      `BulkEdge ${stamp}`,
    );

    await page.goto("/competences");
    await page
      .getByTestId(`competences-group-${group.id}-btn-bulk-add`)
      .click({ force: true });
    await expect(page.getByTestId("competences-modal-bulk")).toBeVisible();

    // Start with 1 row → add 2 more, ending at three rows: 0 (kept), 1 (blank),
    // 2 (filled then removed). saveBulk filters out empty titles, so only the
    // "kept" row reaches the backend.
    await page.getByTestId("competences-modal-bulk-btn-add-row").click();
    await page.getByTestId("competences-modal-bulk-btn-add-row").click();
    await page
      .getByTestId("competences-modal-bulk-row-0-title")
      .fill(`Kept ${stamp}`);
    await page
      .getByTestId("competences-modal-bulk-row-2-title")
      .fill(`Dropped ${stamp}`);
    await page.getByTestId("competences-modal-bulk-row-2-remove").click();

    await page.getByTestId("competences-modal-bulk-btn-submit").click();
    await expect(page.getByTestId("competences-modal-bulk")).toBeHidden({
      timeout: 10000,
    });

    const count = page.getByTestId(`competences-group-${group.id}-count`);
    await expect(count).toContainText("1", { timeout: 10000 });
    await expect(page.getByText(`Kept ${stamp}`).first()).toBeVisible();
    await expect(page.getByText(`Dropped ${stamp}`)).toHaveCount(0);
  });

  test("origin group — bulk-add button is not rendered", async ({ page }) => {
    const stamp = Date.now();
    const origin = await seedOriginGroup(
      { page, accessToken },
      `Origin ${stamp}`,
    );

    await page.goto("/competences");
    await expect(
      page.getByTestId(`competences-group-${origin.id}`),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId(`competences-group-${origin.id}-btn-bulk-add`),
    ).toHaveCount(0);
  });
});
