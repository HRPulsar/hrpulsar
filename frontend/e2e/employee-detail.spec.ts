import { test, expect } from "@playwright/test";
import { setupFullTenant, setAuthTokens, createDivision } from "./helpers";

test.describe("Employee detail", () => {
  let accessToken: string;
  let refreshToken: string;
  let employeeId: string;
  let divisionId: string;
  let secondDivisionId: string;
  const secondDivisionName = "Marketing";

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const setup = await setupFullTenant(page);
    accessToken = setup.accessToken;
    refreshToken = setup.refreshToken;
    employeeId = setup.employeeId;
    divisionId = setup.divisionId;
    const div2 = await createDivision(
      { page, accessToken: setup.accessToken },
      secondDivisionName,
    );
    secondDivisionId = div2.id;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("detail page shows employee name", async ({ page }) => {
    await page.goto(`/employees/${employeeId}`);
    await expect(page.getByTestId("employee-name")).toBeVisible({
      timeout: 10000,
    });
  });

  test("back button visible", async ({ page }) => {
    await page.goto(`/employees/${employeeId}`);
    await expect(page.getByTestId("employee-btn-back")).toBeVisible({
      timeout: 10000,
    });
  });

  test("edit button visible", async ({ page }) => {
    await page.goto(`/employees/${employeeId}`);
    await expect(page.getByTestId("employee-btn-edit")).toBeVisible({
      timeout: 10000,
    });
  });

  test("profile info card visible", async ({ page }) => {
    await page.goto(`/employees/${employeeId}`);
    await expect(page.getByTestId("employee-card-info")).toBeVisible({
      timeout: 10000,
    });
  });

  test("all tabs visible", async ({ page }) => {
    await page.goto(`/employees/${employeeId}`);
    await expect(page.getByTestId("employee-tab-events")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("employee-tab-experience")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("employee-tab-education")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("employee-tab-compensation")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("employee-tab-assessments")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("employee-tab-development")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("employee-tab-competences")).toBeVisible({
      timeout: 10000,
    });
  });

  test("back button navigates to list", async ({ page }) => {
    await page.goto(`/employees/${employeeId}`);
    await page.getByTestId("employee-btn-back").click();
    // Pagination state survives the back navigation, so the URL may
    // carry `?page=…` from the list — `$/` would only pass on a virgin
    // visit. Accept any query suffix.
    await expect(page).toHaveURL(/\/employees(\?.*)?$/, { timeout: 10000 });
  });

  test("events tab - add event button", async ({ page }) => {
    await page.goto(`/employees/${employeeId}`);
    await page.getByTestId("employee-tab-events").click();
    await expect(page.getByTestId("employee-events-btn-add")).toBeVisible({
      timeout: 10000,
    });
  });

  test("events tab - events list visible", async ({ page }) => {
    await page.goto(`/employees/${employeeId}`);
    await page.getByTestId("employee-tab-events").click();
    await expect(page.getByTestId("employee-events-list")).toBeVisible({
      timeout: 10000,
    });
  });

  test("experience tab - list and add button", async ({ page }) => {
    await page.goto(`/employees/${employeeId}`);
    await page.getByTestId("employee-tab-experience").click();
    await expect(page.getByTestId("employee-experience-list")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("employee-experience-btn-add")).toBeVisible({
      timeout: 10000,
    });
  });

  test("HRP-151: current employment division picker shows name, not uuid", async ({
    page,
  }) => {
    await page.goto(`/employees/${employeeId}`);
    await page.getByTestId("employee-tab-experience").click();
    await page.getByTestId("employee-experience-btn-add").click();
    const divisionTrigger = page.getByTestId("employee-experience-division");
    await expect(divisionTrigger).toBeVisible({ timeout: 10000 });
    // Default pulls the employee's current division ("Engineering"). The
    // trigger must render the division name, never its raw uuid.
    await expect(divisionTrigger).toContainText("Engineering");
    await expect(divisionTrigger).not.toContainText(divisionId);
    // Switching to another division must also render its name, not the uuid.
    await divisionTrigger.click();
    await page.getByRole("option", { name: secondDivisionName }).click();
    await expect(divisionTrigger).toContainText(secondDivisionName);
    await expect(divisionTrigger).not.toContainText(secondDivisionId);
  });

  test("education tab - list and add button", async ({ page }) => {
    await page.goto(`/employees/${employeeId}`);
    await page.getByTestId("employee-tab-education").click();
    await expect(page.getByTestId("employee-education-list")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("employee-education-btn-add")).toBeVisible({
      timeout: 10000,
    });
  });

  test("education tab - courses list", async ({ page }) => {
    await page.goto(`/employees/${employeeId}`);
    await page.getByTestId("employee-tab-education").click();
    await expect(page.getByTestId("employee-courses-list")).toBeVisible({
      timeout: 10000,
    });
  });

  test("compensation tab - list and add button", async ({ page }) => {
    await page.goto(`/employees/${employeeId}`);
    await page.getByTestId("employee-tab-compensation").click();
    await expect(page.getByTestId("employee-compensation-list")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId("employee-compensation-btn-add"),
    ).toBeVisible({
      timeout: 10000,
    });
  });

  test("HRP-121: Edit profile dialog edits Name and Last name", async ({
    page,
  }) => {
    await page.goto(`/employees/${employeeId}`);
    await expect(page.getByTestId("employee-name")).toBeVisible({
      timeout: 10000,
    });

    await page.getByTestId("employee-btn-edit").click();
    await expect(page.getByTestId("employee-modal-edit")).toBeVisible({
      timeout: 10000,
    });

    const firstNameInput = page.getByTestId(
      "employee-modal-edit-input-first-name",
    );
    const lastNameInput = page.getByTestId(
      "employee-modal-edit-input-last-name",
    );

    await expect(firstNameInput).toBeVisible();
    await expect(lastNameInput).toBeVisible();

    const stamp = Date.now();
    const nextFirst = `Renamed${stamp}`;
    const nextLast = `Last${stamp}`;

    await firstNameInput.fill(nextFirst);
    await lastNameInput.fill(nextLast);
    await page.getByTestId("employee-modal-edit-btn-submit").click();

    await expect(page.getByTestId("employee-modal-edit")).toBeHidden({
      timeout: 10000,
    });
    await expect(page.getByTestId("employee-name")).toHaveText(
      `${nextFirst} ${nextLast}`,
      { timeout: 10000 },
    );
  });
});
