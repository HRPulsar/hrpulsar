import { test, expect } from "./fixtures";
import {
  registerUser,
  setAuthTokens,
  createDictionaryItem,
  createCompetenceGroup,
  createCompetence,
  pickFirstSkillLevel,
} from "./helpers";

const API_BASE = "http://localhost:8100/api";

/**
 * HRP-57 P6 — cold-start scenarios.
 *
 * The point of this file is to prove that *every* path from "empty
 * specialization" to "matrix configured" runs through the UI, not API
 * scaffolding:
 *  S1 — manual: Add Grades modal + Add competence + matrix save.
 *  S5 — inline salary edit in the matrix column header.
 *  S6 — drag-and-drop reorder of grades (covered via the reorder API
 *       call wired to dnd-kit; full mouse-drag has flakiness so we
 *       drive the same endpoint the UI handler does to assert the
 *       persisted order is what the page reads back).
 *
 * Existing matrix tests (specialization-matrix.spec.ts) still pre-seed
 * chains via API — they exercise cascade math, not the cold-start UX.
 */

async function ensureGradesAttached(
  page: import("@playwright/test").Page,
  accessToken: string,
  specId: string,
  gradeIds: string[] = [],
) {
  const existing = await page.request.get(
    `${API_BASE}/specializations/${specId}/grades`,
    { headers: { Authorization: `Bearer ${accessToken}` } },
  );
  if (!existing.ok()) {
    throw new Error(
      `GET /specializations/${specId}/grades failed: ${existing.status()} ${await existing.text()}`,
    );
  }
  const rows = (await existing.json()) as Array<{ grade_id: string }>;
  if (rows.length >= 2) return;
  const missing = gradeIds.filter(
    (id) => !rows.some((r) => r.grade_id === id),
  );
  if (missing.length === 0) return;
  const resp = await page.request.post(
    `${API_BASE}/specializations/${specId}/grades`,
    {
      headers: { Authorization: `Bearer ${accessToken}` },
      data: { grade_ids: missing },
    },
  );
  if (!resp.ok()) {
    throw new Error(
      `Bootstrap grades failed: ${resp.status()} ${await resp.text()}`,
    );
  }
}

test.describe("Specialization cold-start (HRP-57 P6)", () => {
  let accessToken: string;
  let refreshToken: string;
  let specId: string;
  let juniorId: string;
  let seniorId: string;
  let juniorTitle: string;
  let seniorTitle: string;
  let competenceTitle: string;
  let levelTitle: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const reg = await registerUser(page);
    accessToken = reg.accessToken;
    refreshToken = reg.refreshToken;

    const opts = { page, accessToken };
    const stamp = Date.now().toString(36);

    // Dictionary items only — NO grade-system chain, that's the whole point
    // (the UI under test is the one that creates pairs).
    const spec = await createDictionaryItem(
      opts,
      "specialization",
      `Cold-${stamp}`,
    );
    specId = spec.id;
    const junior = await createDictionaryItem(
      opts,
      "grade",
      `Junior-Cold-${stamp}`,
    );
    const senior = await createDictionaryItem(
      opts,
      "grade",
      `Senior-Cold-${stamp}`,
    );
    juniorId = junior.id;
    seniorId = senior.id;
    juniorTitle = junior.title;
    seniorTitle = senior.title;

    const group = await createCompetenceGroup(opts, `Cold-Group-${stamp}`);
    const comp = await createCompetence(opts, group.id, `Cold-Comp-${stamp}`);
    competenceTitle = comp.title;
    const level = await pickFirstSkillLevel(opts);
    levelTitle = level.title;

    await page.close();
  });

  test("S1 — manual cold-start: Add Grades → Add competence → save matrix", async ({
    page,
  }) => {
    await setAuthTokens(page, accessToken, refreshToken);
    await page.goto(`/company/specializations/${specId}`);

    // Empty state with both CTAs.
    await expect(
      page.getByTestId("specialization-grades-empty"),
    ).toBeVisible();
    await expect(
      page.getByTestId("specialization-add-grades-empty-btn"),
    ).toBeVisible();

    // Open Add Grades modal.
    await page.getByTestId("specialization-add-grades-empty-btn").click();
    const modal = page.getByTestId("add-grades-modal");
    await expect(modal).toBeVisible();

    // Filter then pick two grades.
    await modal.getByTestId("add-grades-search").fill("Cold");
    const juniorRow = modal.locator(`text="${juniorTitle}"`);
    const seniorRow = modal.locator(`text="${seniorTitle}"`);
    await juniorRow.click();
    await seniorRow.click();
    await modal.getByTestId("add-grades-save").click();

    // Modal closes, columns appear in the order ticked.
    await expect(modal).toBeHidden({ timeout: 10000 });
    await expect(
      page.getByTestId("specialization-builder"),
    ).toBeVisible();
    await expect(page.locator(`text="${juniorTitle}"`)).toBeVisible();
    await expect(page.locator(`text="${seniorTitle}"`)).toBeVisible();

    // Matrix shows the empty hint because we just added grades but no
    // competences.
    await expect(page.getByTestId("matrix-empty")).toBeVisible();

    // HRP-100: legacy inline dropdown was replaced by the Add-competences
    // modal — open it, filter to the seeded competence, tick its row, save.
    await page.getByTestId("matrix-add-competence-btn").click();
    await expect(page.getByTestId("matrix-add-competences-dialog")).toBeVisible();
    await page.getByTestId("matrix-add-competences-search").fill(competenceTitle);
    await page
      .locator('[data-testid^="matrix-add-comp-"]:not([data-testid$="-open"])')
      .first()
      .click();
    await page.getByTestId("matrix-add-competences-save").click();
    await expect(page.getByTestId("matrix-add-competences-dialog")).toBeHidden();

    // Set a level on Junior — the cascade then fills Senior.
    const matrixTable = page.getByTestId("matrix-table");
    await expect(matrixTable).toBeVisible();
    // First MatrixCell in the only competence row. matrix-cell.tsx renders
    // a <select> when no level is set; we pick the option matching our
    // seeded level title.
    const firstCellSelect = page
      .getByTestId("matrix-table")
      .locator("tbody tr")
      .first()
      .locator("select")
      .first();
    await firstCellSelect.selectOption({ label: levelTitle });

    // Save.
    await page.getByTestId("matrix-unsaved-bar-btn-save").click();
    await expect(page.getByText("Matrix saved")).toBeVisible({
      timeout: 10000,
    });

    // Smoke-check: GET pairs returns two pairs with non-empty sort_index.
    const pairsResp = await page.request.get(
      `${API_BASE}/specializations/${specId}/grades`,
      { headers: { Authorization: `Bearer ${accessToken}` } },
    );
    expect(pairsResp.ok()).toBeTruthy();
    const pairs = await pairsResp.json();
    expect(pairs).toHaveLength(2);
    expect(pairs[0].sort_index).toBeLessThan(pairs[1].sort_index);
  });

  test("S5 — inline salary edit persists via PATCH", async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);

    // Self-contained: don't depend on S1's grade bootstrap (workers may
    // be recycled between tests). The endpoint is idempotent.
    await ensureGradesAttached(page, accessToken, specId, [juniorId, seniorId]);

    await page.goto(`/company/specializations/${specId}`);

    // Junior column header.
    const builder = page.getByTestId("specialization-builder");
    await expect(builder).toBeVisible();
    const headers = page.locator('[data-testid^="matrix-th-grade-"]');
    await expect(headers).toHaveCount(2);

    // Click the salary placeholder on the first header to open inline edit.
    const firstHeader = headers.first();
    const gradeIdAttr = await firstHeader.getAttribute("data-testid");
    const firstGradeId = gradeIdAttr?.replace("matrix-th-grade-", "") ?? "";
    expect(firstGradeId.length).toBeGreaterThan(0);

    await page
      .getByTestId(`matrix-grade-salary-${firstGradeId}`)
      .click();
    await page
      .getByTestId(`matrix-grade-salary-min-${firstGradeId}`)
      .fill("100000");
    await page
      .getByTestId(`matrix-grade-salary-max-${firstGradeId}`)
      .fill("150000");
    await page
      .getByTestId(`matrix-grade-salary-save-${firstGradeId}`)
      .click();
    await expect(page.getByText("Salary updated")).toBeVisible({
      timeout: 10000,
    });

    // Reload to assert the patch persisted server-side.
    await page.reload();
    await expect(page.getByTestId("specialization-builder")).toBeVisible();
    await expect(
      page.getByTestId(`matrix-grade-salary-${firstGradeId}`),
    ).toContainText("100000");
    await expect(
      page.getByTestId(`matrix-grade-salary-${firstGradeId}`),
    ).toContainText("150000");
  });

  test("S6 — reorder persists via PATCH /grades/reorder", async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
    await ensureGradesAttached(page, accessToken, specId, [juniorId, seniorId]);

    // Read current order via API.
    const before = await page.request.get(
      `${API_BASE}/specializations/${specId}/grades`,
      { headers: { Authorization: `Bearer ${accessToken}` } },
    );
    expect(before.ok()).toBeTruthy();
    const orderBefore = (await before.json()) as Array<{
      grade_id: string;
      sort_index: number;
    }>;
    expect(orderBefore).toHaveLength(2);

    // Drive the same endpoint the dnd-kit handler does — swapping the
    // sort_index of the two columns. Mouse drag-and-drop in Playwright is
    // flaky across browsers; the wire-level assertion is what actually
    // protects the contract.
    const swap = await page.request.patch(
      `${API_BASE}/specializations/${specId}/grades/reorder`,
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: {
          orders: [
            { grade_id: orderBefore[0].grade_id, sort_index: 1 },
            { grade_id: orderBefore[1].grade_id, sort_index: 0 },
          ],
        },
      },
    );
    expect(swap.ok()).toBeTruthy();

    // Page reads the same order back from matrix-bulk.
    await page.goto(`/company/specializations/${specId}`);
    await expect(page.getByTestId("specialization-builder")).toBeVisible();
    const headers = page.locator('[data-testid^="matrix-th-grade-"]');
    const firstId = (
      await headers.first().getAttribute("data-testid")
    )?.replace("matrix-th-grade-", "");
    expect(firstId).toBe(orderBefore[1].grade_id);
  });
});
