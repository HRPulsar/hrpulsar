import { test, expect } from "./fixtures";
import {
  createAssessment,
  setAuthTokens,
  setupFullTenant,
} from "./helpers";

/**
 * HRP-36 — Single + Mass Assessment must hide the Evaluation criteria and
 * Rating scale edit affordances once the assessment leaves draft. Until this
 * fix the buttons stayed visible through `sent`/`in_progress` and the Rating
 * scale picker even let users swap the snapshot mid-flight.
 *
 * The narrower #2 case (group children always inherit) lives in
 * assessments-v160-bugs.spec.ts.
 */

const API = "http://localhost:8100/api";

async function pickDefaultScaleId(
  page: import("@playwright/test").Page,
  accessToken: string,
): Promise<string> {
  const resp = await page.request.get(`${API}/answer-scales`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  expect(resp.ok()).toBeTruthy();
  const scales = await resp.json();
  const def = scales.find((s: { is_default: boolean; id: string }) => s.is_default);
  expect(def?.id).toBeTruthy();
  return def.id;
}

async function configureAssessment(
  page: import("@playwright/test").Page,
  accessToken: string,
  assessmentId: string,
  scaleId: string,
): Promise<void> {
  const criteria = await page.request.put(
    `${API}/assessments/${assessmentId}/criteria`,
    {
      headers: { Authorization: `Bearer ${accessToken}` },
      data: { criteria_type: "current_positions", passing_score: 75 },
    },
  );
  expect(criteria.ok()).toBeTruthy();
  const scale = await page.request.put(
    `${API}/assessments/${assessmentId}/scale`,
    {
      headers: { Authorization: `Bearer ${accessToken}` },
      data: { scale_id: scaleId },
    },
  );
  expect(scale.ok()).toBeTruthy();
}

async function sendAssessment(
  page: import("@playwright/test").Page,
  accessToken: string,
  assessmentId: string,
): Promise<void> {
  const resp = await page.request.post(
    `${API}/assessments/${assessmentId}/status`,
    {
      headers: { Authorization: `Bearer ${accessToken}` },
      data: { status_code: "sent" },
    },
  );
  expect(resp.ok()).toBeTruthy();
}

test.describe("HRP-36 — criteria/scale edit locked after draft", () => {
  test("Single assessment in sent hides Evaluation criteria + Rating scale buttons", async ({
    page,
  }) => {
    const setup = await setupFullTenant(page);
    const a = await createAssessment(
      { page, accessToken: setup.accessToken },
      setup.employeeId,
      "HRP-36 single edit lock",
      "self",
    );
    const scaleId = await pickDefaultScaleId(page, setup.accessToken);
    await configureAssessment(page, setup.accessToken, a.id, scaleId);
    await sendAssessment(page, setup.accessToken, a.id);

    await setAuthTokens(page, setup.accessToken, setup.refreshToken);
    await page.goto(`/assessments/${a.id}`);

    // Cards still render — the change is only the edit affordances.
    await expect(page.getByTestId("assessment-criteria-card")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("assessment-scale-card")).toBeVisible();

    await expect(
      page.getByTestId("assessment-criteria-btn-add"),
    ).toHaveCount(0);
    await expect(
      page.getByTestId("assessment-scale-btn-change"),
    ).toHaveCount(0);
    await expect(page.getByTestId("assessment-scale-btn-add")).toHaveCount(0);
  });

  test("Mass assessment with all children sent hides group criteria + scale buttons", async ({
    page,
  }) => {
    const setup = await setupFullTenant(page);
    const scaleId = await pickDefaultScaleId(page, setup.accessToken);

    // Create a group, configure it, then push every child to sent. The group
    // page mirrors the per-child status — once nothing is in draft, edit
    // affordances must disappear.
    const groupResp = await page.request.post(`${API}/assessment-groups`, {
      headers: { Authorization: `Bearer ${setup.accessToken}` },
      data: {
        title: "HRP-36 mass edit lock",
        employee_ids: [setup.employeeId],
        type_code: "self",
      },
    });
    expect(groupResp.ok()).toBeTruthy();
    const group = (await groupResp.json()) as {
      id: string;
      assessments: { id: string }[];
    };

    const criteriaResp = await page.request.put(
      `${API}/assessment-groups/${group.id}/criteria`,
      {
        headers: { Authorization: `Bearer ${setup.accessToken}` },
        data: { criteria_type: "current_positions", passing_score: 75 },
      },
    );
    expect(criteriaResp.ok()).toBeTruthy();
    const scaleResp = await page.request.put(
      `${API}/assessment-groups/${group.id}/scale`,
      {
        headers: { Authorization: `Bearer ${setup.accessToken}` },
        data: { scale_id: scaleId },
      },
    );
    expect(scaleResp.ok()).toBeTruthy();

    for (const child of group.assessments) {
      await sendAssessment(page, setup.accessToken, child.id);
    }

    await setAuthTokens(page, setup.accessToken, setup.refreshToken);
    await page.goto(`/assessment-groups/${group.id}`);

    await expect(page.getByTestId("group-criteria-card")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("group-scale-card")).toBeVisible();

    await expect(page.getByTestId("group-criteria-btn-edit")).toHaveCount(0);
    await expect(page.getByTestId("group-scale-btn-change")).toHaveCount(0);
    await expect(page.getByTestId("group-scale-btn-add")).toHaveCount(0);
  });
});
