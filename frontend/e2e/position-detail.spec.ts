import { test, expect } from "@playwright/test";
import {
  registerUser,
  setAuthTokens,
  createPosition,
  setupCriteriaFixture,
} from "./helpers";

// HRP-32 redux: position detail page must expose deep-links from Overview and
// inline-edit controls for Title / Status / Headcount / Description.
test.describe("Position detail — HRP-32 deep-links + inline edits", () => {
  let accessToken: string;
  let refreshToken: string;
  let positionId: string;
  let specializationId: string;
  let gradeId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const creds = await registerUser(page);
    accessToken = creds.accessToken;
    refreshToken = creds.refreshToken;

    const fixture = await setupCriteriaFixture({ page, accessToken });
    specializationId = fixture.specializationId;
    gradeId = fixture.gradeId;

    const position = await createPosition(
      { page, accessToken },
      `HRP32-detail-${Date.now().toString(36)}`,
      {
        specialization_id: fixture.specializationId,
        grade_id: fixture.gradeId,
        headcount: 2,
      },
    );
    positionId = position.id;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("Specialization and Grade are clickable links in Overview", async ({
    page,
  }) => {
    await page.goto(`/company/positions/${positionId}`);
    await expect(page.getByTestId("position-detail-title")).toBeVisible({
      timeout: 10000,
    });

    const specLink = page.getByTestId("position-detail-specialization-link");
    await expect(specLink).toBeVisible();
    // HRP-54: link now carries from=position so the spec page can render
    // a "Back to position" breadcrumb.
    const specHref = await specLink.getAttribute("href");
    expect(specHref).toContain(`/company/specializations/${specializationId}`);
    expect(specHref).toContain(`from=position`);
    expect(specHref).toContain(`position_id=${positionId}`);

    const gradeLink = page.getByTestId("position-detail-grade-link");
    await expect(gradeLink).toBeVisible();
    const gradeHref = await gradeLink.getAttribute("href");
    expect(gradeHref).toContain(
      `/company/specializations/${specializationId}/matrix`,
    );
    expect(gradeHref).toContain(`grade_id=${gradeId}`);
    expect(gradeHref).toContain(`from=position`);
    expect(gradeHref).toContain(`position_id=${positionId}`);
  });

  test("Title can be renamed inline", async ({ page }) => {
    await page.goto(`/company/positions/${positionId}`);
    const title = page.getByTestId("position-detail-title");
    await expect(title).toBeVisible({ timeout: 10000 });

    // Pencil button is hover-revealed but always in DOM; click directly.
    await page.getByTestId("position-detail-title-edit").click({ force: true });
    const input = page.getByTestId("position-detail-title-input");
    await expect(input).toBeVisible();

    const renamed = `HRP32-renamed-${Date.now().toString(36)}`;
    await input.fill(renamed);
    await page.getByTestId("position-detail-title-save").click();

    await expect(page.getByTestId("position-detail-title")).toContainText(
      renamed,
    );
  });

  test("Status can be changed via the badge dropdown", async ({ page }) => {
    await page.goto(`/company/positions/${positionId}`);
    await expect(page.getByTestId("position-detail-status")).toBeVisible({
      timeout: 10000,
    });

    await page.getByTestId("position-detail-status-trigger").click();
    await page.getByTestId("position-detail-status-set-on_hold").click();

    await expect(page.getByTestId("position-detail-status")).toHaveAttribute(
      "data-status",
      "on_hold",
    );
  });
});

// HRP-54 redo: positions list + detail page must expose CTAs for missing
// spec/grade and route the operator into the right corner of the matrix.
test.describe("Position pages — HRP-54 spec/grade CTAs + matrix breadcrumbs", () => {
  let accessToken: string;
  let refreshToken: string;
  let coldPositionId: string;
  let specOnlyPositionId: string;
  let configuredPositionId: string;
  let specializationId: string;
  let gradeId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const creds = await registerUser(page);
    accessToken = creds.accessToken;
    refreshToken = creds.refreshToken;

    const fixture = await setupCriteriaFixture({ page, accessToken });
    specializationId = fixture.specializationId;
    gradeId = fixture.gradeId;

    // Cold-start: position with neither spec nor grade.
    const cold = await createPosition(
      { page, accessToken },
      `HRP54-cold-${Date.now().toString(36)}`,
      { headcount: 1 },
    );
    coldPositionId = cold.id;

    // Spec only, no grade.
    const specOnly = await createPosition(
      { page, accessToken },
      `HRP54-specOnly-${Date.now().toString(36)}`,
      { specialization_id: fixture.specializationId, headcount: 1 },
    );
    specOnlyPositionId = specOnly.id;

    // Spec + grade (fully wired) for the breadcrumb assertion.
    const wired = await createPosition(
      { page, accessToken },
      `HRP54-wired-${Date.now().toString(36)}`,
      {
        specialization_id: fixture.specializationId,
        grade_id: fixture.gradeId,
        headcount: 1,
      },
    );
    configuredPositionId = wired.id;

    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("list page shows Set CTAs when spec/grade are missing", async ({
    page,
  }) => {
    await page.goto("/company/positions");
    await expect(
      page.getByTestId(`positions-row-${coldPositionId}-btn-set-specialization`),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId(`positions-row-${coldPositionId}-btn-set-grade`),
    ).toBeVisible();
    // Wired row exposes link, not CTA.
    await expect(
      page.getByTestId(`positions-row-${configuredPositionId}-specialization-link`),
    ).toBeVisible();
  });

  test("Overview edit button on detail page opens the edit dialog", async ({
    page,
  }) => {
    await page.goto(`/company/positions/${coldPositionId}`);
    const editBtn = page.getByTestId("position-detail-overview-btn-edit");
    await expect(editBtn).toBeVisible({ timeout: 10000 });
    await editBtn.click();
    // PositionEditDialog renders the title input; reuse its existing testid.
    await expect(page.getByRole("dialog")).toBeVisible({ timeout: 10000 });
  });

  test("matrix-empty surfaces the right CTA for each state", async ({
    page,
  }) => {
    // Cold position → "no spec" state.
    await page.goto(`/company/positions/${coldPositionId}`);
    await expect(
      page.getByTestId("position-detail-matrix-empty-no-spec"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("position-detail-matrix-empty-btn-pick-spec"),
    ).toBeVisible();

    // Spec-only position → "no grade" state with Pick grade + Open spec.
    await page.goto(`/company/positions/${specOnlyPositionId}`);
    await expect(
      page.getByTestId("position-detail-matrix-empty-no-grade"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("position-detail-matrix-empty-btn-pick-grade"),
    ).toBeVisible();
    const specLink = page.getByTestId("position-detail-matrix-empty-spec-link");
    await expect(specLink).toBeVisible();
    const href = await specLink.getAttribute("href");
    expect(href).toContain(`/company/specializations/${specializationId}`);
    expect(href).toContain(`from=position`);
  });

  test("matrix page rendered from position shows Back to position", async ({
    page,
  }) => {
    await page.goto(
      `/company/specializations/${specializationId}/matrix?grade_id=${gradeId}&from=position&position_id=${configuredPositionId}`,
    );
    const back = page.getByTestId("matrix-page-back-to-position");
    await expect(back).toBeVisible({ timeout: 10000 });
    await expect(back).toHaveAttribute(
      "href",
      `/company/positions/${configuredPositionId}`,
    );
  });

  test("spec page rendered from position shows Back to position", async ({
    page,
  }) => {
    await page.goto(
      `/company/specializations/${specializationId}?from=position&position_id=${configuredPositionId}`,
    );
    const back = page.getByTestId("specialization-detail-back-to-position");
    await expect(back).toBeVisible({ timeout: 10000 });
    await expect(back).toHaveAttribute(
      "href",
      `/company/positions/${configuredPositionId}`,
    );
  });
});
