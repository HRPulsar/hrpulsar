import { test, expect } from "@playwright/test";
import { setAuthTokens, setupFullTenant } from "./helpers";

/**
 * Regression tests for Assessment bugs reported by QA against v1.5.0
 * (Slack thread #gf-development-ai, 2026-04-30 → 2026-05-04) and fixed
 * in v1.6.0.
 *
 * Backend coverage: backend/tests/unit/test_assessment_v160_bugs.py
 *
 * This file covers the frontend-only bugs:
 *   #2  Children of a mass assessment must hide criteria/scale add/change
 *       buttons (criteria and scale are inherited from the group).
 *   #11 Non-terminal assessments expose pencil affordances for title and
 *       deadline (inline edit, parity with PDP).
 */

const API = "http://localhost:8100/api";

async function createMassAssessment(
  page: import("@playwright/test").Page,
  accessToken: string,
  employeeIds: string[],
  title: string,
): Promise<{ id: string; assessments: { id: string; employee_id: string }[] }> {
  const resp = await page.request.post(`${API}/assessment-groups`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    data: {
      title,
      employee_ids: employeeIds,
      type_code: "self",
    },
  });
  if (!resp.ok()) {
    throw new Error(
      `createMassAssessment failed (${resp.status()}): ${await resp.text()}`,
    );
  }
  return resp.json();
}

test.describe("Assessment v1.5.0 bugs to fix in v1.6.0", () => {
  let accessToken: string;
  let refreshToken: string;
  let firstChildId: string;
  let standaloneId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const setup = await setupFullTenant(page);
    accessToken = setup.accessToken;
    refreshToken = setup.refreshToken;

    // A standalone assessment for bug #11.
    const standaloneResp = await page.request.post(`${API}/assessments`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      data: {
        employee_id: setup.employeeId,
        type_code: "self",
        title: "Standalone for inline-edit",
      },
    });
    if (!standaloneResp.ok()) {
      throw new Error(
        `create standalone assessment failed: ${await standaloneResp.text()}`,
      );
    }
    standaloneId = (await standaloneResp.json()).id;

    // A mass assessment with a single employee — its child is what bug
    // #2 talks about. The own user already has an Employee row from
    // setupFullTenant().
    const group = await createMassAssessment(
      page,
      accessToken,
      [setup.employeeId],
      "Mass for child read-only check",
    );
    firstChildId = group.assessments[0].id;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  // -------------------------------------------------------------------
  // Bug #2 — child of a mass assessment must hide criteria/scale
  // edit buttons.
  // -------------------------------------------------------------------

  test("Bug #2: child of mass assessment hides criteria edit button", async ({
    page,
  }) => {
    await page.goto(`/assessments/${firstChildId}`);

    // Card renders so the assertion target exists.
    await expect(page.getByTestId("assessment-criteria-card")).toBeVisible({
      timeout: 10000,
    });
    // Edit button must NOT be present on a group child.
    await expect(
      page.getByTestId("assessment-criteria-btn-add"),
    ).toHaveCount(0);
  });

  test("Bug #2: child of mass assessment hides scale add/change buttons", async ({
    page,
  }) => {
    await page.goto(`/assessments/${firstChildId}`);

    await expect(page.getByTestId("assessment-scale-card")).toBeVisible({
      timeout: 10000,
    });
    // Neither variant of the scale button should exist on a child.
    await expect(page.getByTestId("assessment-scale-btn-add")).toHaveCount(0);
    await expect(
      page.getByTestId("assessment-scale-btn-change"),
    ).toHaveCount(0);
  });

  // -------------------------------------------------------------------
  // Bug #11 — non-terminal assessment exposes inline edit pencils for
  // title and deadline (parity with PDP).
  // -------------------------------------------------------------------

  test("Bug #11: non-terminal assessment shows pencil to edit title", async ({
    page,
  }) => {
    await page.goto(`/assessments/${standaloneId}`);

    // Inline-edit affordance the QA team expects on non-terminal
    // assessments. Convention from the PDP detail page: a button with a
    // pencil icon and a `*-btn-edit-title` testid.
    await expect(
      page.getByTestId("assessment-btn-edit-title"),
    ).toBeVisible({ timeout: 10000 });
  });

  test("Bug #11: non-terminal assessment shows pencil to edit deadline", async ({
    page,
  }) => {
    await page.goto(`/assessments/${standaloneId}`);

    await expect(
      page.getByTestId("assessment-btn-edit-deadline"),
    ).toBeVisible({ timeout: 10000 });
  });
});
