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

test.describe("HRP-146 — survey opens in a Sheet with autosave + draft rehydrate", () => {
  test("selected option survives close-and-reopen", async ({ page }) => {
    const setup = await setupFullTenant(page);
    const auth = { headers: { Authorization: `Bearer ${setup.accessToken}` } };

    // Minimum scaffolding: skill level → competence → one indicator → scale → assessment.
    const slResp = await page.request.get(`${API_BASE}/skill-levels`, auth);
    const skillLevels: { id: string }[] = await slResp.json();
    const skillLevelId = skillLevels[0].id;

    const stamp = Date.now().toString(36);
    const group = await createCompetenceGroup(
      { page, accessToken: setup.accessToken },
      `SheetGroup-${stamp}`,
    );
    const comp = await createCompetence(
      { page, accessToken: setup.accessToken },
      group.id,
      `SheetComp-${stamp}`,
    );
    const ind = await createIndicator(
      { page, accessToken: setup.accessToken },
      comp.id,
      `SheetInd-${stamp}`,
      skillLevelId,
    );

    const scaleResp = await page.request.post(`${API_BASE}/answer-scales`, {
      ...auth,
      data: {
        title: `Sheet scale ${stamp}`,
        options: [
          { title: "Low", sort_index: 0, is_neutral: false },
          { title: "Mid", sort_index: 1, is_neutral: false },
          { title: "Top", sort_index: 2, is_neutral: false },
        ],
        levels: [],
      },
    });
    const scale = await scaleResp.json();

    const a = await createAssessment(
      { page, accessToken: setup.accessToken },
      setup.employeeId,
      `Sheet flow ${stamp}`,
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

    // Pull the snapshotted option ids — frontend RadioGroup is keyed by id.
    const snapResp = await page.request.get(
      `${API_BASE}/answer-scales/${(await (await page.request.get(`${API_BASE}/assessments/${a.id}`, auth)).json()).scale_id}`,
      auth,
    );
    const snap = await snapResp.json();
    const midOption = snap.options.find(
      (o: { title: string }) => o.title === "Mid",
    );
    expect(midOption).toBeTruthy();

    await setAuthTokens(page, setup.accessToken, setup.refreshToken);
    await page.goto(`/assessments/${a.id}`);

    // Open the Sheet, pick the Mid option, close, reopen — selection persists.
    await page.getByRole("button", { name: /Take this assessment/i }).click();
    const sheet = page.getByTestId("assessment-eval-sheet");
    await expect(sheet).toBeVisible();

    const option = page.getByTestId(
      `assessment-eval-option-${ind.id}-${midOption.id}`,
    );
    await option.click();
    // Wait briefly for the autosave to land.
    await page.waitForResponse(
      (resp) =>
        resp.url().endsWith(`/assessments/${a.id}/answers`) &&
        resp.status() === 201,
    );

    // Close via Escape (one of the spec-mandated close paths).
    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();

    // Reopen and check the radio is still selected — the Sheet hydrated
    // its state from GET /assessments/:id/my-answers.
    await page.getByRole("button", { name: /Take this assessment/i }).click();
    await expect(sheet).toBeVisible();
    await expect(option).toBeChecked();
  });
});
