import { test, expect } from "@playwright/test";

import {
  createAssessment,
  setAuthTokens,
  setupCriteriaFixture,
  setupFullTenant,
} from "./helpers";
import type { CriteriaFixture } from "./helpers";

const API_BASE = "http://localhost:8100/api";

// Each test below gets a freshly registered tenant so we don't fight existing
// criteria fixtures from sibling specs (e.g. criteria.spec.ts).
test.describe("Passing score & grade recommendation — frontend", () => {
  test("criteria sheet shows passing score field with default 75 (HRP-183)", async ({
    page,
  }) => {
    const setup = await setupFullTenant(page);
    const a = await createAssessment(
      { page, accessToken: setup.accessToken },
      setup.employeeId,
      "Passing score smoke",
      "self",
    );
    await setAuthTokens(page, setup.accessToken, setup.refreshToken);

    await page.goto(`/assessments/${a.id}`);
    await page.getByTestId("assessment-criteria-btn-add").click();
    await expect(page.getByTestId("criteria-sheet")).toBeVisible({ timeout: 10000 });
    await page.getByTestId("criteria-radio-current").click();

    const input = page.getByTestId("assessment-criteria-passing-score-input");
    await expect(input).toBeVisible();
    await expect(input).toHaveValue("75");

    // HRP-183: tooltip + formula toggle were intentionally removed for
    // Target / Current positions; only the input + new "Passing score for
    // recommended grade" label remain. Round-trip below still verifies
    // the override is stored.

    await input.fill("70");
    await page.getByTestId("criteria-save").click();
    await expect(page.getByTestId("criteria-sheet")).toBeHidden({ timeout: 10000 });

    // Round-trip — backend stored the override.
    const fresh = await page.request.get(`${API_BASE}/assessments/${a.id}`, {
      headers: { Authorization: `Bearer ${setup.accessToken}` },
    });
    expect(fresh.ok()).toBeTruthy();
    expect((await fresh.json()).passing_score).toBe(70);
  });

  test("passing score becomes read-only after assessment leaves draft", async ({
    page,
  }) => {
    const setup = await setupFullTenant(page);
    const a = await createAssessment(
      { page, accessToken: setup.accessToken },
      setup.employeeId,
      "Passing score lock",
      "self",
    );
    // Configure criteria + scale so the assessment can be sent. The
    // change_status(draft → sent) guard requires both — if we leave either
    // unset, the transition silently fails and the assessment stays in
    // draft, which would let the criteria PUT below succeed (200) and mask
    // the read-only invariant we're actually testing.
    const criteriaResp = await page.request.put(
      `${API_BASE}/assessments/${a.id}/criteria`,
      {
        headers: { Authorization: `Bearer ${setup.accessToken}` },
        data: { criteria_type: "current_positions", passing_score: 80 },
      },
    );
    expect(criteriaResp.ok()).toBeTruthy();

    const scalesResp = await page.request.get(`${API_BASE}/answer-scales`, {
      headers: { Authorization: `Bearer ${setup.accessToken}` },
    });
    expect(scalesResp.ok()).toBeTruthy();
    const scales = await scalesResp.json();
    const defaultScale = scales.find(
      (s: { is_default: boolean; id: string }) => s.is_default,
    );
    expect(defaultScale?.id).toBeTruthy();
    const scaleResp = await page.request.put(
      `${API_BASE}/assessments/${a.id}/scale`,
      {
        headers: { Authorization: `Bearer ${setup.accessToken}` },
        data: { scale_id: defaultScale.id },
      },
    );
    expect(scaleResp.ok()).toBeTruthy();

    const statusResp = await page.request.post(
      `${API_BASE}/assessments/${a.id}/status`,
      {
        headers: { Authorization: `Bearer ${setup.accessToken}` },
        data: { status_code: "sent" },
      },
    );
    expect(statusResp.ok()).toBeTruthy();

    await setAuthTokens(page, setup.accessToken, setup.refreshToken);
    await page.goto(`/assessments/${a.id}`);
    // The card no longer shows "Edit" once we're past draft, so the sheet
    // is unreachable. Either way, the read-only invariant is satisfied — the
    // backend rejects criteria updates with a 400.
    const editBtn = page.getByTestId("assessment-criteria-btn-add");
    if (await editBtn.isVisible({ timeout: 1000 }).catch(() => false)) {
      await editBtn.click();
      await expect(page.getByTestId("criteria-sheet")).toBeVisible({ timeout: 5000 });
      await expect(
        page.getByTestId("assessment-criteria-passing-score-input"),
      ).toBeDisabled();
    }

    // Backend guard — direct PUT must fail.
    const resp = await page.request.put(`${API_BASE}/assessments/${a.id}/criteria`, {
      headers: { Authorization: `Bearer ${setup.accessToken}` },
      data: { criteria_type: "current_positions", passing_score: 50 },
    });
    expect(resp.status()).toBe(400);
  });
});

test.describe("Passing score — specialization dictionary", () => {
  let fixture: CriteriaFixture;
  let accessToken: string;
  let refreshToken: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const setup = await setupFullTenant(page);
    accessToken = setup.accessToken;
    refreshToken = setup.refreshToken;
    fixture = await setupCriteriaFixture({ page, accessToken });
    await page.close();
  });

  test("HR can edit passing_score per grade in specialization detail page", async ({
    page,
  }) => {
    await setAuthTokens(page, accessToken, refreshToken);
    await page.goto(`/dictionaries/specializations/${fixture.specializationId}`);

    const input = page.getByTestId(
      `grade-spec-passing-score-input-${fixture.gradeId}`,
    );
    await expect(input).toBeVisible({ timeout: 10000 });
    await expect(input).toHaveValue("75");

    await input.fill("85");
    await page
      .getByTestId(`grade-spec-passing-score-save-${fixture.gradeId}`)
      .click();

    // Reload — the new value persists.
    await page.reload();
    await expect(
      page.getByTestId(`grade-spec-passing-score-input-${fixture.gradeId}`),
    ).toHaveValue("85", { timeout: 10000 });

    // Backend mirror.
    const resp = await page.request.get(
      `${API_BASE}/grade-system/specializations/${fixture.specializationId}`,
      { headers: { Authorization: `Bearer ${accessToken}` } },
    );
    const chains = await resp.json();
    const chain = chains.find(
      (c: { grade_id: string; passing_score: number | null }) =>
        c.grade_id === fixture.gradeId,
    );
    expect(chain?.passing_score).toBe(85);
  });

  test("criteria sheet hydrates passing_score from grade_specializations default", async ({
    page,
  }) => {
    // Set a non-default value on the chain so we can detect the hydration.
    await page.request.put(`${API_BASE}/grade-system/chains/${fixture.chainId}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      data: { passing_score: 60 },
    });

    // Fresh assessment so criteria can still be edited.
    const empResp = await page.request.get(`${API_BASE}/employees?limit=1`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    const empId = (await empResp.json()).items[0].id;
    const aResp = await page.request.post(`${API_BASE}/assessments`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      data: {
        employee_id: empId,
        type_code: "self",
        title: "Hydrate threshold",
      },
    });
    const aid = (await aResp.json()).id;

    await setAuthTokens(page, accessToken, refreshToken);
    await page.goto(`/assessments/${aid}`);
    await page.getByTestId("assessment-criteria-btn-add").click();
    await expect(page.getByTestId("criteria-sheet")).toBeVisible({ timeout: 10000 });

    await page.getByTestId("criteria-radio-target").click();
    await page.getByTestId("criteria-spec-select").click();
    await page.getByRole("option", { name: fixture.specializationTitle }).click();
    await page.getByTestId("criteria-grade-select").click();
    await page.getByRole("option", { name: fixture.gradeTitle }).click();

    await expect(
      page.getByTestId("assessment-criteria-passing-score-input"),
    ).toHaveValue("60", { timeout: 5000 });
  });
});
