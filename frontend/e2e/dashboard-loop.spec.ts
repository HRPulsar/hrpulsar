import { test, expect } from "./fixtures";

import {
  createAssessment,
  createCompetence,
  createCompetenceGroup,
  createIndicator,
  setAuthTokens,
  setupFullTenant,
} from "./helpers";

const API_BASE = "http://localhost:8100/api";

/**
 * Dashboard development loop (HRP dashboard rework): a below-the-bar
 * assessment result with no development plan must surface as an
 * action-queue row with a CTA, and the loop hero must reflect the gap.
 */
test.describe("Dashboard — development loop", () => {
  test("below-bar result surfaces a gaps_without_plan action", async ({
    page,
  }) => {
    const setup = await setupFullTenant(page);
    const auth = { headers: { Authorization: `Bearer ${setup.accessToken}` } };
    const opts = { page, accessToken: setup.accessToken };

    // Competence + indicator so the assessment produces a result.
    const slResp = await page.request.get(`${API_BASE}/skill-levels`, auth);
    const skillLevels: { id: string }[] = await slResp.json();
    const skillLevelId = skillLevels[0].id;

    const stamp = Date.now().toString(36);
    const group = await createCompetenceGroup(opts, `LoopGroup-${stamp}`);
    const comp = await createCompetence(opts, group.id, `LoopComp-${stamp}`);
    await createIndicator(opts, comp.id, `LoopInd-${stamp}`, skillLevelId);

    // Scale with 3 scoring options — answering with the lowest one lands
    // the competence percent well below the default 75% bar.
    const scaleResp = await page.request.post(`${API_BASE}/answer-scales`, {
      ...auth,
      data: {
        title: `Loop scale ${stamp}`,
        options: [
          { title: "Low", sort_index: 0, is_neutral: false },
          { title: "Mid", sort_index: 1, is_neutral: false },
          { title: "Top", sort_index: 2, is_neutral: false },
        ],
        levels: [
          { percent_from: 0, percent_to: 50, system_title: "Growth area", sort_index: 0 },
          { percent_from: 51, percent_to: 100, system_title: "On target", sort_index: 1 },
        ],
      },
    });
    expect(scaleResp.ok()).toBeTruthy();
    const scale = await scaleResp.json();

    const a = await createAssessment(
      opts,
      setup.employeeId,
      `Loop review ${stamp}`,
      "self",
    );
    await page.request.put(`${API_BASE}/assessments/${a.id}/scale`, {
      ...auth,
      data: { scale_id: scale.id },
    });
    await page.request.put(`${API_BASE}/assessments/${a.id}/criteria`, {
      ...auth,
      data: {
        criteria_type: "competences",
        competences: [{ competence_id: comp.id, skill_level_id: skillLevelId }],
      },
    });
    await page.request.post(`${API_BASE}/assessments/${a.id}/status`, {
      ...auth,
      data: { status_code: "sent" },
    });

    const detail = await (
      await page.request.get(`${API_BASE}/assessments/${a.id}`, auth)
    ).json();
    const participant = detail.participants.find(
      (p: { role: string }) => p.role === "self",
    );
    expect(participant).toBeTruthy();

    const snap = await (
      await page.request.get(`${API_BASE}/answer-scales/${detail.scale_id}`, auth)
    ).json();
    const lowest = [...snap.options]
      .filter((o: { is_neutral: boolean }) => !o.is_neutral)
      .sort(
        (a: { weight: number }, b: { weight: number }) => a.weight - b.weight,
      )[0];

    const compDetail = await (
      await page.request.get(`${API_BASE}/competences/${comp.id}`, auth)
    ).json();
    const indicatorId = compDetail.indicators[0].id;

    await page.request.post(`${API_BASE}/assessments/${a.id}/status`, {
      ...auth,
      data: { status_code: "in_progress" },
    });
    const ansResp = await page.request.post(
      `${API_BASE}/assessments/${a.id}/answers`,
      {
        ...auth,
        data: {
          participant_id: participant.id,
          indicator_id: indicatorId,
          answer_option_id: lowest.id,
          score: lowest.weight,
        },
      },
    );
    expect(ansResp.ok()).toBeTruthy();
    await page.request.post(`${API_BASE}/assessments/${a.id}/status`, {
      ...auth,
      data: { status_code: "done" },
    });

    // Dashboard: the loop hero renders and the action queue names the gap.
    await setAuthTokens(page, setup.accessToken, setup.refreshToken);
    await page.goto("/dashboard");

    await expect(page.getByTestId("dashboard-loop-stage-gaps")).toBeVisible({
      timeout: 10000,
    });
    const gapRow = page.getByTestId("dashboard-action-gaps_without_plan");
    await expect(gapRow).toBeVisible({ timeout: 10000 });
    await expect(gapRow).toContainText("E2E", { timeout: 10000 });

    // AI summary is on-demand only: the button renders, no auto-call.
    await expect(page.getByTestId("dashboard-ai-summary-btn")).toBeVisible();

    // The CTA deep-links into the development module.
    await gapRow.getByTestId("dashboard-action-cta").click();
    await expect(page).toHaveURL(/\/development/, { timeout: 10000 });
  });
});
