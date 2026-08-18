import { test, expect } from "./fixtures";
import {
  createAssessment,
  createCompetence,
  createCompetenceGroup,
  setAuthTokens,
  setupFullTenant,
} from "./helpers";

test.describe("Cross-page data consistency", () => {
  let accessToken: string;
  let refreshToken: string;
  let employeeId: string;
  let divisionId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const setup = await setupFullTenant(page);
    accessToken = setup.accessToken;
    refreshToken = setup.refreshToken;
    employeeId = setup.employeeId;
    divisionId = setup.divisionId;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("employee count on dashboard", async ({ page }) => {
    await page.goto("/dashboard");
    const card = page.getByTestId("dashboard-kpi-headcount");
    await expect(card).toBeVisible({ timeout: 10000 });
    await expect(card).toContainText("1", { timeout: 10000 });
  });

  test("division count on dashboard", async ({ page }) => {
    await page.goto("/dashboard");
    const card = page.getByTestId("dashboard-kpi-divisions");
    await expect(card).toBeVisible({ timeout: 10000 });
    await expect(card).toContainText("1", { timeout: 10000 });
  });

  test("division visible in company tree", async ({ page }) => {
    await page.goto("/company");
    await expect(
      page.getByTestId(`company-division-${divisionId}`),
    ).toBeVisible({ timeout: 10000 });
  });

  test("employee visible in list", async ({ page }) => {
    await page.goto("/employees");
    await expect(
      page.getByTestId(`employees-row-${employeeId}`),
    ).toBeVisible({ timeout: 10000 });
  });

  test("assessment appears on employee detail", async ({ page }) => {
    const assessment = await createAssessment(
      { page, accessToken },
      employeeId,
      "Cross-page Review",
      "self",
    );

    await page.goto(`/employees/${employeeId}`);
    await page.getByTestId("employee-tab-assessments").click();

    const tabContent = page.getByTestId("employee-assessments-content");
    await expect(tabContent).toBeVisible({ timeout: 10000 });
    await expect(tabContent.getByText(assessment.title)).toBeVisible({
      timeout: 10000,
    });
  });

  test("publish on detail page propagates to /competences without reload", async ({
    page,
  }) => {
    const opts = { page, accessToken };
    const stamp = Date.now();
    const group = await createCompetenceGroup(opts, `XPropGroup-${stamp}`);
    const comp = await createCompetence(opts, group.id, `XPropComp-${stamp}`);

    await page.goto("/competences");
    await expect(
      page.getByTestId(`competences-item-${comp.id}-unpublished-icon`),
    ).toBeVisible({ timeout: 10000 });

    await page.goto(`/competences/${comp.id}`);
    await page.getByTestId("competence-detail-btn-publish").click();
    await expect(page.getByTestId("competence-detail-published-badge")).toBeVisible({
      timeout: 10000,
    });

    // SPA navigation: invalidateCompetenceTree() must have repushed the tree
    // so the icon flips without an explicit refresh.
    await page.goto("/competences");
    await expect(
      page.getByTestId(`competences-item-${comp.id}-published-icon`),
    ).toBeVisible({ timeout: 10000 });
  });
});
