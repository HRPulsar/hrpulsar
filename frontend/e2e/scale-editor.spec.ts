import { test, expect, type Page } from "./fixtures";

import {
  createAssessment,
  setAuthTokens,
  setupFullTenant,
} from "./helpers";

async function openScalePicker(page: Page, assessmentId: string) {
  await page.goto(`/assessments/${assessmentId}`);
  // Wait for the rating-scale card to render (whichever button it shows).
  const trigger = page
    .getByTestId("assessment-scale-btn-add")
    .or(page.getByTestId("assessment-scale-btn-change"));
  await expect(trigger).toBeVisible({ timeout: 15000 });
  await trigger.click();
  await expect(page.getByTestId("assessment-scale-modal")).toBeVisible({
    timeout: 10000,
  });
}

test.describe("Rating scale editor — CRUD UI", () => {
  let accessToken: string;
  let refreshToken: string;
  let assessmentId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const setup = await setupFullTenant(page);
    accessToken = setup.accessToken;
    refreshToken = setup.refreshToken;
    const a = await createAssessment(
      { page, accessToken },
      setup.employeeId,
      "Scale editor flow",
      "self",
    );
    assessmentId = a.id;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("creates a custom scale and selects it", async ({ page }) => {
    await openScalePicker(page, assessmentId);
    await page.getByTestId("assessment-scale-modal-btn-create").click();
    await expect(page.getByTestId("scale-editor-sheet")).toBeVisible({
      timeout: 10000,
    });

    const title = `Test scale ${Date.now()}`;
    await page.getByTestId("scale-editor-input-title").fill(title);

    // Default 2 options — fill them.
    await page
      .getByTestId("scale-editor-option-row-0-input-title")
      .fill("Doesn't fit");
    await page
      .getByTestId("scale-editor-option-row-1-input-title")
      .fill("Fits");

    // Add a third option.
    await page.getByTestId("scale-editor-options-btn-add").click();
    await page
      .getByTestId("scale-editor-option-row-2-input-title")
      .fill("Exceeds");

    // Add two levels covering 0..50, 51..100.
    await page.getByTestId("scale-editor-levels-btn-add").click();
    await page.getByTestId("scale-editor-level-row-0-input-from").fill("0");
    await page.getByTestId("scale-editor-level-row-0-input-to").fill("50");
    await page
      .getByTestId("scale-editor-level-row-0-input-title")
      .fill("Growth area");

    await page.getByTestId("scale-editor-levels-btn-add").click();
    await page.getByTestId("scale-editor-level-row-1-input-from").fill("51");
    await page.getByTestId("scale-editor-level-row-1-input-to").fill("100");
    await page
      .getByTestId("scale-editor-level-row-1-input-title")
      .fill("On target");

    await expect(page.getByTestId("scale-editor-btn-save")).toBeEnabled();
    await page.getByTestId("scale-editor-btn-save").click();
    await expect(page.getByTestId("scale-editor-sheet")).toBeHidden({
      timeout: 10000,
    });
    await expect(page.getByTestId("assessment-scale-modal")).toContainText(
      title,
    );
  });

  test("preview shows the default scale read-only", async ({ page }) => {
    await openScalePicker(page, assessmentId);
    const defaultRow = page
      .locator('[data-testid^="assessment-scale-modal-item-"]')
      .filter({ hasText: "Default answer scale" })
      .first();
    const menu = defaultRow.locator(
      '[data-testid$="-menu"]:not([data-testid$="-preview"]):not([data-testid$="-edit"]):not([data-testid$="-delete"])',
    );
    await menu.click();
    await page.getByRole("menuitem", { name: "Preview" }).first().click();
    await expect(
      page.getByTestId("assessment-scale-preview-modal"),
    ).toBeVisible({ timeout: 10000 });
  });

  test("default scale exposes preview only, no delete option", async ({
    page,
  }) => {
    await openScalePicker(page, assessmentId);
    const defaultRow = page
      .locator('[data-testid^="assessment-scale-modal-item-"]')
      .filter({ hasText: "Default answer scale" })
      .first();
    const menu = defaultRow.locator(
      '[data-testid$="-menu"]:not([data-testid$="-preview"]):not([data-testid$="-edit"]):not([data-testid$="-delete"])',
    );
    await menu.click();
    await expect(
      page.getByRole("menuitem", { name: "Delete" }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("menuitem", { name: "Edit" }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("menuitem", { name: "Preview" }),
    ).toHaveCount(1);
  });

  test("save button is disabled when title is empty", async ({ page }) => {
    await openScalePicker(page, assessmentId);
    await page.getByTestId("assessment-scale-modal-btn-create").click();
    await expect(page.getByTestId("scale-editor-sheet")).toBeVisible({
      timeout: 10000,
    });
    // Empty title + empty option titles → save disabled.
    await expect(page.getByTestId("scale-editor-btn-save")).toBeDisabled();
  });

  test("edit and delete a custom scale via row menu", async ({ page }) => {
    // Create one through the API to keep the test focused.
    const title = `Editable scale ${Date.now()}`;
    const created = await page.request.post(
      "http://localhost:8100/api/answer-scales",
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: {
          title,
          options: [
            { title: "A", description: null, sort_index: 0, is_neutral: false },
            { title: "B", description: null, sort_index: 1, is_neutral: false },
          ],
          levels: [],
        },
      },
    );
    const scale = await created.json();

    await openScalePicker(page, assessmentId);
    const editTrigger = page.getByTestId(
      `assessment-scale-modal-item-${scale.id}-menu`,
    );
    await editTrigger.click();
    await page
      .getByTestId(`assessment-scale-modal-item-${scale.id}-menu-edit`)
      .click();
    await expect(page.getByTestId("scale-editor-sheet")).toBeVisible({
      timeout: 10000,
    });

    const newTitle = `${title} (edited)`;
    await page.getByTestId("scale-editor-input-title").fill(newTitle);
    await page.getByTestId("scale-editor-btn-save").click();
    // Edit-mode — confirm dialog appears.
    await expect(page.getByTestId("scale-confirm-save")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("scale-confirm-save-confirm").click();
    await expect(page.getByTestId("scale-editor-sheet")).toBeHidden({
      timeout: 10000,
    });
    await expect(page.getByTestId("assessment-scale-modal")).toContainText(
      newTitle,
    );

    // Delete via menu.
    await page
      .getByTestId(`assessment-scale-modal-item-${scale.id}-menu`)
      .click();
    await page
      .getByTestId(`assessment-scale-modal-item-${scale.id}-menu-delete`)
      .click();
    await expect(page.getByTestId("scale-confirm-delete")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("scale-confirm-delete-confirm").click();
    await expect(
      page.getByTestId(`assessment-scale-modal-item-${scale.id}`),
    ).toHaveCount(0);
  });
});
