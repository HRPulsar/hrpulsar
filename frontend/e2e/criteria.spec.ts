import { test, expect } from "@playwright/test";

import {
  createAssessment,
  setAuthTokens,
  setupCriteriaFixture,
  setupFullTenant,
} from "./helpers";
import type { CriteriaFixture } from "./helpers";

test.describe("Evaluation criteria sheet", () => {
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
      "Criteria flow",
      "self",
    );
    assessmentId = a.id;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("opens criteria sheet with three radio options", async ({ page }) => {
    await page.goto(`/assessments/${assessmentId}`);
    await page.getByTestId("assessment-criteria-btn-add").click();
    await expect(page.getByTestId("criteria-sheet")).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId("criteria-radio-current")).toBeVisible();
    await expect(page.getByTestId("criteria-radio-target")).toBeVisible();
    await expect(page.getByTestId("criteria-radio-competences")).toBeVisible();
  });

  test("save is disabled until type is chosen", async ({ page }) => {
    await page.goto(`/assessments/${assessmentId}`);
    await page.getByTestId("assessment-criteria-btn-add").click();
    await expect(page.getByTestId("criteria-sheet")).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId("criteria-save")).toBeDisabled();
  });

  test("current_positions enables save without extra config", async ({ page }) => {
    await page.goto(`/assessments/${assessmentId}`);
    await page.getByTestId("assessment-criteria-btn-add").click();
    await expect(page.getByTestId("criteria-sheet")).toBeVisible({ timeout: 10000 });
    await page.getByTestId("criteria-radio-current").click();
    await expect(page.getByTestId("criteria-save")).toBeEnabled();
  });

  test("target_position needs both selects to enable save", async ({ page }) => {
    await page.goto(`/assessments/${assessmentId}`);
    await page.getByTestId("assessment-criteria-btn-add").click();
    await expect(page.getByTestId("criteria-sheet")).toBeVisible({ timeout: 10000 });
    await page.getByTestId("criteria-radio-target").click();
    await expect(page.getByTestId("criteria-spec-select")).toBeVisible();
    await expect(page.getByTestId("criteria-save")).toBeDisabled();
  });
});

test.describe("Evaluation criteria — round-trip persistence", () => {
  let accessToken: string;
  let refreshToken: string;
  let fixture: CriteriaFixture;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const setup = await setupFullTenant(page);
    accessToken = setup.accessToken;
    refreshToken = setup.refreshToken;
    fixture = await setupCriteriaFixture({ page, accessToken });
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("target_position saves and shows specialization + grade titles", async ({
    page,
  }) => {
    // Fresh assessment per test to avoid cross-test contamination
    const browserPage = await page.context().newPage();
    await setAuthTokens(browserPage, accessToken, refreshToken);
    const setupResp = await browserPage.request.get(
      "http://localhost:8100/api/employees?limit=1",
      { headers: { Authorization: `Bearer ${accessToken}` } },
    );
    const empId = (await setupResp.json()).items[0].id;
    const aResp = await browserPage.request.post(
      "http://localhost:8100/api/assessments",
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: { employee_id: empId, type_code: "self", title: "Target round-trip" },
      },
    );
    const assessmentId = (await aResp.json()).id;
    await browserPage.close();

    await page.goto(`/assessments/${assessmentId}`);
    await page.getByTestId("assessment-criteria-btn-add").click();
    await expect(page.getByTestId("criteria-sheet")).toBeVisible({ timeout: 10000 });

    await page.getByTestId("criteria-radio-target").click();

    // base-ui Select uses native click on the trigger; pick by visible text.
    await page.getByTestId("criteria-spec-select").click();
    await page.getByRole("option", { name: fixture.specializationTitle }).click();

    await page.getByTestId("criteria-grade-select").click();
    await page.getByRole("option", { name: fixture.gradeTitle }).click();

    await expect(page.getByTestId("criteria-save")).toBeEnabled();
    await page.getByTestId("criteria-save").click();

    // Sheet closes; summary card shows resolved titles.
    await expect(page.getByTestId("criteria-sheet")).toBeHidden({ timeout: 10000 });
    await expect(
      page
        .getByTestId("assessment-criteria-card")
        .getByText(fixture.specializationTitle),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("assessment-criteria-card").getByText(fixture.gradeTitle),
    ).toBeVisible();

    // Reload — value persists from backend.
    await page.reload();
    await expect(
      page
        .getByTestId("assessment-criteria-card")
        .getByText(fixture.specializationTitle),
    ).toBeVisible({ timeout: 10000 });
  });

  test("competences mode saves selected competence as a badge", async ({ page }) => {
    const browserPage = await page.context().newPage();
    await setAuthTokens(browserPage, accessToken, refreshToken);
    const setupResp = await browserPage.request.get(
      "http://localhost:8100/api/employees?limit=1",
      { headers: { Authorization: `Bearer ${accessToken}` } },
    );
    const empId = (await setupResp.json()).items[0].id;
    const aResp = await browserPage.request.post(
      "http://localhost:8100/api/assessments",
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: {
          employee_id: empId,
          type_code: "self",
          title: "Competences round-trip",
        },
      },
    );
    const assessmentId = (await aResp.json()).id;
    await browserPage.close();

    await page.goto(`/assessments/${assessmentId}`);
    await page.getByTestId("assessment-criteria-btn-add").click();
    await expect(page.getByTestId("criteria-sheet")).toBeVisible({ timeout: 10000 });

    await page.getByTestId("criteria-radio-competences").click();
    await page.getByTestId("criteria-pick-competences").click();

    // Tree groups start collapsed; typing into the search both filters and
    // auto-expands matching groups.
    await page
      .getByTestId("competence-tree-search")
      .fill(fixture.competenceTitle);

    const treeRow = page.getByText(fixture.competenceTitle, { exact: true });
    await expect(treeRow).toBeVisible({ timeout: 10000 });
    await treeRow.click();

    await page.getByTestId("competence-tree-save").click();

    // Back in the criteria sheet — the picked competence appears as a row.
    await expect(
      page.getByTestId(`criteria-comp-${fixture.competenceId}`),
    ).toBeVisible({ timeout: 10000 });

    await page.getByTestId("criteria-save").click();
    await expect(page.getByTestId("criteria-sheet")).toBeHidden({ timeout: 10000 });

    await expect(
      page
        .getByTestId("assessment-criteria-card")
        .getByText(fixture.competenceTitle),
    ).toBeVisible({ timeout: 10000 });

    await page.reload();
    await expect(
      page
        .getByTestId("assessment-criteria-card")
        .getByText(fixture.competenceTitle),
    ).toBeVisible({ timeout: 10000 });
  });
});
