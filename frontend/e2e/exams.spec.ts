import { test, expect } from "@playwright/test";
import { registerUser, setAuthTokens, createExam } from "./helpers";

test.describe("Exams page", () => {
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

  test("exams page renders", async ({ page }) => {
    await page.goto("/exams");
    await expect(page.getByTestId("exams-heading")).toBeVisible({
      timeout: 10000,
    });
  });

  test("empty state", async ({ page }) => {
    await page.goto("/exams");
    await expect(page.getByTestId("exams-empty")).toBeVisible({
      timeout: 10000,
    });
  });

  test("create button visible", async ({ page }) => {
    await page.goto("/exams");
    await expect(page.getByTestId("exams-btn-create")).toBeVisible({
      timeout: 10000,
    });
  });

  test("create exam dialog", async ({ page }) => {
    await page.goto("/exams");
    await page.getByTestId("exams-btn-create").click();
    await expect(page.getByTestId("exams-modal-create")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId("exams-modal-create-input-title"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("exams-modal-create-input-description"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("exams-modal-create-input-end-date"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("exams-modal-create-btn-submit"),
    ).toBeVisible({ timeout: 10000 });
  });
});

test.describe("Exams with data", () => {
  let accessToken: string;
  let refreshToken: string;
  let examId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const creds = await registerUser(page);
    accessToken = creds.accessToken;
    refreshToken = creds.refreshToken;
    const exam = await createExam(
      { page, accessToken },
      "TypeScript Fundamentals",
    );
    examId = exam.id;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("exam table visible", async ({ page }) => {
    await page.goto("/exams");
    await expect(page.getByTestId("exams-table")).toBeVisible({
      timeout: 10000,
    });
  });

  test("exam row rendered", async ({ page }) => {
    await page.goto("/exams");
    await expect(page.getByTestId(`exams-row-${examId}`)).toBeVisible({
      timeout: 10000,
    });
  });

  test("exam row status badge", async ({ page }) => {
    await page.goto("/exams");
    await expect(
      page.getByTestId(`exams-row-${examId}-status`),
    ).toBeVisible({ timeout: 10000 });
  });

  // HRP-226 redo: pass mark add → edit (pencil + Edit dialog) → delete.
  test("pass mark add, edit and delete", async ({ page }) => {
    await page.goto(`/exams/${examId}`);
    await page.getByTestId("exam-passmark-add").click({ timeout: 10000 });
    await expect(page.getByTestId("exam-passmark-modal")).toBeVisible({
      timeout: 10000,
    });
    await page.getByPlaceholder("e.g. 60").fill("60");
    await page.getByTestId("exam-passmark-modal-btn-submit").click();
    await expect(page.getByTestId("exam-passmark-row")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("exam-passmark-row")).toContainText("60%");

    await page.getByTestId("exam-passmark-edit").click();
    await expect(page.getByTestId("exam-passmark-modal")).toBeVisible({
      timeout: 10000,
    });
    await page.getByPlaceholder("e.g. 60").fill("75");
    await page.getByTestId("exam-passmark-modal-btn-submit").click();
    await expect(page.getByTestId("exam-passmark-row")).toContainText("75%", {
      timeout: 10000,
    });

    await page.getByTestId("exam-passmark-delete").click();
    await expect(page.getByTestId("exam-passmark-add")).toBeVisible({
      timeout: 10000,
    });
  });

  // HRP-225: assign-employees dialog carries division/position/specialization
  // filters and a filter-aware select-all, mirroring Mass assessment.
  test("assign employees dialog has filters and select-all", async ({
    page,
  }) => {
    await page.goto(`/exams/${examId}`);
    await page
      .getByRole("button", { name: "Assign employees" })
      .click({ timeout: 10000 });
    await expect(page.getByTestId("exam-assign-select-division")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("exam-assign-select-position")).toBeVisible();
    await expect(
      page.getByTestId("exam-assign-select-specialization"),
    ).toBeVisible();
    await expect(
      page.getByTestId("exam-assign-checkbox-select-all"),
    ).toBeVisible();
  });
});
