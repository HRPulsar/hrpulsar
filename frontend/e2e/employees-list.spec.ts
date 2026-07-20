import { expect, test } from "@playwright/test";
import {
  createDictionaryItem,
  createDivision,
  createPosition,
  provisionTenantMember,
  registerUser,
  setAuthTokens,
  setDivisionManager,
} from "./helpers";

const API = "http://localhost:8100/api";

/**
 * EMP4: redesigned employees list — column layout + multi-select filters.
 */
test.describe("Employees list (EMP4)", () => {
  test("column order, no Hire date, Specialization·Grade visible", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const opts = { page, accessToken: admin.accessToken };

    const spec = await createDictionaryItem(opts, "specialization", "FE-Spec");
    const grade = await createDictionaryItem(opts, "grade", "Sr-Grade");
    const div = await createDivision(opts, "List-Div");
    const pos = await createPosition(opts, "FE Lead", {
      specialization_id: spec.id,
      grade_id: grade.id,
    });

    const member = await provisionTenantMember(opts, {
      roleCode: "employee",
      divisionId: div.id,
      positionId: pos.id,
    });
    expect(member.employeeId).not.toBeNull();

    await setAuthTokens(page, admin.accessToken, admin.refreshToken);
    await page.goto("/employees");
    await expect(page.getByTestId("employees-table")).toBeVisible({
      timeout: 15000,
    });

    const headers = page
      .getByTestId("employees-table")
      .locator("thead tr th");
    const headerTexts = (await headers.allInnerTexts()).map((s) => s.trim());
    expect(headerTexts).toContain("Name");
    expect(headerTexts).toContain("Division");
    expect(headerTexts).toContain("Position");
    expect(headerTexts).toContain("Specialization · Grade");
    expect(headerTexts).toContain("Status");
    expect(headerTexts).not.toContain("Hire date");

    // Order: Name | Division | Position | Specialization · Grade | Status
    const visibleHeaders = headerTexts.filter((t) => t.length > 0);
    expect(visibleHeaders).toEqual([
      "Name",
      "Division",
      "Position",
      "Specialization · Grade",
      "Status",
    ]);

    const specGradeCell = page.getByTestId(
      `employees-row-${member.employeeId}-spec-grade`,
    );
    await expect(specGradeCell).toContainText("FE-Spec");
    await expect(specGradeCell).toContainText("Sr-Grade");
  });

  test("multi-select Divisions: URL reflects selection and list filters", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const opts = { page, accessToken: admin.accessToken };

    const divA = await createDivision(opts, "Alpha");
    const divB = await createDivision(opts, "Beta");
    const divC = await createDivision(opts, "Gamma");
    const pos = await createPosition(opts, `Pos-${Date.now()}`);

    const inA = await provisionTenantMember(opts, {
      roleCode: "employee",
      divisionId: divA.id,
      positionId: pos.id,
    });
    const inB = await provisionTenantMember(opts, {
      roleCode: "employee",
      divisionId: divB.id,
      positionId: pos.id,
    });
    const inC = await provisionTenantMember(opts, {
      roleCode: "employee",
      divisionId: divC.id,
      positionId: pos.id,
    });

    await setAuthTokens(page, admin.accessToken, admin.refreshToken);
    await page.goto("/employees");
    await expect(page.getByTestId("employees-table")).toBeVisible({
      timeout: 15000,
    });

    await page.getByTestId("employees-multi-divisions").click();
    await page
      .getByTestId(`employees-multi-divisions-option-${divA.id}`)
      .click();
    // Wait for the first selection to land in the URL before clicking the
    // second — Playwright can fire the second click before React has
    // committed the first onChange, which lets the multi-select's
    // valueRef compose against the stale [] snapshot under CI load.
    await expect.poll(() => page.url()).toMatch(`division_id=${divA.id}`);
    await page
      .getByTestId(`employees-multi-divisions-option-${divB.id}`)
      .click();
    await expect.poll(() => page.url()).toMatch(`division_id=${divB.id}`);
    // close dropdown
    await page.keyboard.press("Escape");

    expect(page.url()).toContain(`division_id=${divA.id}`);
    expect(page.url()).toContain(`division_id=${divB.id}`);

    await expect(
      page.getByTestId(`employees-row-${inA.employeeId}`),
    ).toBeVisible();
    await expect(
      page.getByTestId(`employees-row-${inB.employeeId}`),
    ).toBeVisible();
    await expect(
      page.getByTestId(`employees-row-${inC.employeeId}`),
    ).toHaveCount(0);
  });

  test("Grade filter narrows list to employees with matching grade", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const opts = { page, accessToken: admin.accessToken };

    const spec = await createDictionaryItem(opts, "specialization", "Spec-G");
    const gradeJr = await createDictionaryItem(opts, "grade", "Junior-G");
    const gradeSr = await createDictionaryItem(opts, "grade", "Senior-G");

    const posJr = await createPosition(opts, "Pos Junior G", {
      specialization_id: spec.id,
      grade_id: gradeJr.id,
    });
    const posSr = await createPosition(opts, "Pos Senior G", {
      specialization_id: spec.id,
      grade_id: gradeSr.id,
    });

    const div = await createDivision(opts, "Grade-Div");

    const empJr = await provisionTenantMember(opts, {
      roleCode: "employee",
      divisionId: div.id,
      positionId: posJr.id,
    });
    const empSr = await provisionTenantMember(opts, {
      roleCode: "employee",
      divisionId: div.id,
      positionId: posSr.id,
    });

    await setAuthTokens(page, admin.accessToken, admin.refreshToken);
    await page.goto("/employees");
    await expect(page.getByTestId("employees-table")).toBeVisible({
      timeout: 15000,
    });

    await page.getByTestId("employees-multi-grades").click();
    await page
      .getByTestId(`employees-multi-grades-option-${gradeSr.id}`)
      .click();
    await page.keyboard.press("Escape");

    await expect.poll(() => page.url()).toContain(`grade_id=${gradeSr.id}`);
    await expect(
      page.getByTestId(`employees-row-${empSr.employeeId}`),
    ).toBeVisible();
    await expect(
      page.getByTestId(`employees-row-${empJr.employeeId}`),
    ).toHaveCount(0);
  });

  test("HRP-120: search input hits the backend (q param) and finds matches", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const opts = { page, accessToken: admin.accessToken };

    const div = await createDivision(opts, `Search-Div-${Date.now()}`);
    const pos = await createPosition(opts, `Search-Pos-${Date.now()}`);

    const needle = `Needle${Date.now()}`;
    const haystack = `Haystack${Date.now()}`;

    const matching = await provisionTenantMember(opts, {
      roleCode: "employee",
      divisionId: div.id,
      positionId: pos.id,
      firstName: needle,
      lastName: "Findable",
    });
    const other = await provisionTenantMember(opts, {
      roleCode: "employee",
      divisionId: div.id,
      positionId: pos.id,
      firstName: haystack,
      lastName: "Hidden",
    });

    await setAuthTokens(page, admin.accessToken, admin.refreshToken);

    // Make sure the search request actually leaves with a `q` parameter —
    // catches a regression of the old client-side-only filter.
    const searchRequest = page.waitForRequest(
      (req) =>
        req.url().includes("/api/employees") && req.url().includes(`q=${needle}`),
    );

    await page.goto("/employees");
    await expect(page.getByTestId("employees-table")).toBeVisible({
      timeout: 15000,
    });

    await page.getByTestId("employees-input-search").fill(needle);
    await searchRequest;

    await expect(
      page.getByTestId(`employees-row-${matching.employeeId}`),
    ).toBeVisible();
    await expect(
      page.getByTestId(`employees-row-${other.employeeId}`),
    ).toHaveCount(0);
  });

  test("Manager Divisions filter shows only their subtree", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const opts = { page, accessToken: admin.accessToken };

    const ownDiv = await createDivision(opts, "Owned");
    const otherDiv = await createDivision(opts, "Foreign");
    const pos = await createPosition(opts, `Mgr-Pos-${Date.now()}`);

    const manager = await provisionTenantMember(opts, {
      roleCode: "employee",
      divisionId: ownDiv.id,
      positionId: pos.id,
    });
    expect(manager.employeeId).not.toBeNull();
    await setDivisionManager(opts, ownDiv.id, manager.employeeId!);

    // Verify backend scope endpoint behavior directly.
    const scopeResp = await page.request.get(`${API}/divisions/scope`, {
      headers: { Authorization: `Bearer ${manager.accessToken}` },
    });
    expect(scopeResp.ok()).toBeTruthy();
    const scope = (await scopeResp.json()) as { id: string; name: string }[];
    const scopeIds = scope.map((d) => d.id);
    expect(scopeIds).toContain(ownDiv.id);
    expect(scopeIds).not.toContain(otherDiv.id);

    await setAuthTokens(page, manager.accessToken, manager.refreshToken);
    await page.goto("/employees");
    await expect(page.getByTestId("employees-multi-divisions")).toBeVisible({
      timeout: 15000,
    });

    await page.getByTestId("employees-multi-divisions").click();
    await expect(
      page.getByTestId(`employees-multi-divisions-option-${ownDiv.id}`),
    ).toBeVisible();
    await expect(
      page.getByTestId(`employees-multi-divisions-option-${otherDiv.id}`),
    ).toHaveCount(0);
  });
});
