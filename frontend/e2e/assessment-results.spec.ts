import { test, expect } from "@playwright/test";

import {
  createAssessment,
  createCompetence,
  createCompetenceGroup,
  createIndicator,
  setAuthTokens,
  setupFullTenant,
} from "./helpers";

const API_BASE = "http://localhost:8100/api";

test.describe("Assessment Results — percent + level columns", () => {
  test("done assessment renders percent value and level badge", async ({ page }) => {
    const setup = await setupFullTenant(page);
    const auth = { headers: { Authorization: `Bearer ${setup.accessToken}` } };

    // Pick the first available skill level (system-wide seed).
    const slResp = await page.request.get(`${API_BASE}/skill-levels`, auth);
    const skillLevels: { id: string }[] = await slResp.json();
    const skillLevelId = skillLevels[0].id;

    // Competence + one indicator so the assessment has a measurable result.
    const stamp = Date.now().toString(36);
    const group = await createCompetenceGroup(
      { page, accessToken: setup.accessToken },
      `ResultsGroup-${stamp}`,
    );
    const comp = await createCompetence(
      { page, accessToken: setup.accessToken },
      group.id,
      `ResultsComp-${stamp}`,
    );
    await createIndicator(
      { page, accessToken: setup.accessToken },
      comp.id,
      `ResultsInd-${stamp}`,
      skillLevelId,
    );

    // Custom scale with 3 scoring options + 2 levels covering [0..100].
    const scaleResp = await page.request.post(`${API_BASE}/answer-scales`, {
      ...auth,
      data: {
        title: `Results scale ${stamp}`,
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

    // Assessment of type 'self' — participant auto-created.
    const a = await createAssessment(
      { page, accessToken: setup.accessToken },
      setup.employeeId,
      `Results flow ${stamp}`,
      "self",
    );

    // Wire scale + competence-based criteria.
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

    // draft → sent (this snapshots the scale)
    await page.request.post(`${API_BASE}/assessments/${a.id}/status`, {
      ...auth,
      data: { status_code: "sent" },
    });

    // Pull the snapshotted scale + the auto-created self participant.
    const detailResp = await page.request.get(
      `${API_BASE}/assessments/${a.id}`,
      auth,
    );
    const detail = await detailResp.json();
    const participant = detail.participants.find(
      (p: { role: string }) => p.role === "self",
    );
    expect(participant).toBeTruthy();

    const snapResp = await page.request.get(
      `${API_BASE}/answer-scales/${detail.scale_id}`,
      auth,
    );
    const snap = await snapResp.json();
    const top = [...snap.options]
      .filter((o: { is_neutral: boolean }) => !o.is_neutral)
      .sort(
        (a: { weight: number }, b: { weight: number }) => b.weight - a.weight,
      )[0];

    // Indicator id from competence detail.
    const compDetailResp = await page.request.get(
      `${API_BASE}/competences/${comp.id}`,
      auth,
    );
    const compDetail = await compDetailResp.json();
    const indicatorId = compDetail.indicators[0].id;

    // sent → in_progress, record top answer, → done.
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
          answer_option_id: top.id,
          score: top.weight,
        },
      },
    );
    expect(ansResp.ok()).toBeTruthy();
    await page.request.post(`${API_BASE}/assessments/${a.id}/status`, {
      ...auth,
      data: { status_code: "done" },
    });

    // Frontend assertion — Results table shows percent + level badge.
    await setAuthTokens(page, setup.accessToken, setup.refreshToken);
    await page.goto(`/assessments/${a.id}`);

    const percentCell = page.getByTestId(
      `assessment-results-row-${comp.id}-percent`,
    );
    const levelCell = page.getByTestId(
      `assessment-results-row-${comp.id}-level`,
    );
    await expect(percentCell).toBeVisible({ timeout: 15000 });
    await expect(percentCell).toHaveText("100%");
    await expect(levelCell).toBeVisible();
    await expect(levelCell).toContainText("On target");
  });

  test("scale without levels renders empty level cell", async ({ page }) => {
    const setup = await setupFullTenant(page);
    const auth = { headers: { Authorization: `Bearer ${setup.accessToken}` } };

    const slResp = await page.request.get(`${API_BASE}/skill-levels`, auth);
    const skillLevels: { id: string }[] = await slResp.json();
    const skillLevelId = skillLevels[0].id;

    const stamp = Date.now().toString(36);
    const group = await createCompetenceGroup(
      { page, accessToken: setup.accessToken },
      `LegacyGroup-${stamp}`,
    );
    const comp = await createCompetence(
      { page, accessToken: setup.accessToken },
      group.id,
      `LegacyComp-${stamp}`,
    );
    await createIndicator(
      { page, accessToken: setup.accessToken },
      comp.id,
      `LegacyInd-${stamp}`,
      skillLevelId,
    );

    // Scale without levels at all.
    const scaleResp = await page.request.post(`${API_BASE}/answer-scales`, {
      ...auth,
      data: {
        title: `Legacy scale ${stamp}`,
        options: [
          { title: "A", sort_index: 0, is_neutral: false },
          { title: "B", sort_index: 1, is_neutral: false },
        ],
        levels: [],
      },
    });
    const scale = await scaleResp.json();

    const a = await createAssessment(
      { page, accessToken: setup.accessToken },
      setup.employeeId,
      `Legacy flow ${stamp}`,
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

    // sent → answer → (auto on_review when participant completes) → done.
    await page.request.post(`${API_BASE}/assessments/${a.id}/status`, {
      ...auth,
      data: { status_code: "sent" },
    });
    const detailResp = await page.request.get(
      `${API_BASE}/assessments/${a.id}`,
      auth,
    );
    const detail = await detailResp.json();
    const participantId = detail.participants.find(
      (p: { role: string }) => p.role === "self",
    ).id;
    const compDetailResp = await page.request.get(
      `${API_BASE}/competences/${comp.id}`,
      auth,
    );
    const compDetail = await compDetailResp.json();
    const indicatorId = compDetail.indicators[0].id;
    const scaleDetailResp = await page.request.get(
      `${API_BASE}/answer-scales/${scale.id}`,
      auth,
    );
    const scaleDetail = await scaleDetailResp.json();
    const top = scaleDetail.options[scaleDetail.options.length - 1];
    await page.request.post(`${API_BASE}/assessments/${a.id}/answers`, {
      ...auth,
      data: {
        participant_id: participantId,
        indicator_id: indicatorId,
        answer_option_id: top.id,
        score: top.weight,
      },
    });
    await page.request.post(`${API_BASE}/assessments/${a.id}/status`, {
      ...auth,
      data: { status_code: "done" },
    });

    await setAuthTokens(page, setup.accessToken, setup.refreshToken);
    await page.goto(`/assessments/${a.id}`);

    const percentCell = page.getByTestId(
      `assessment-results-row-${comp.id}-percent`,
    );
    const levelCell = page.getByTestId(
      `assessment-results-row-${comp.id}-level`,
    );
    // Scale carries no levels, so the level cell renders blank even when
    // the percent has been computed normally (HRP-27 + HRP-62: results
    // are populated on the on_review hop the assessment auto-takes when
    // the only participant finishes).
    await expect(percentCell).toBeVisible({ timeout: 15000 });
    await expect(levelCell).toBeVisible();
    await expect(levelCell).toHaveText("");
  });
});
