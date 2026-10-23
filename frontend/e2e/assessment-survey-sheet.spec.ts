import { test, expect } from "./fixtures";

import {
  API_BASE,
  createAssessment,
  createCompetence,
  createCompetenceGroup,
  createIndicator,
  setAuthTokens,
  setupFullTenant,
} from "./helpers";

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

test.describe("HRP-317 — Submit with skipped questions takes you to the first one", () => {
  test("a long sheet scrolls to and focuses the first unanswered indicator", async ({ page }) => {
    const setup = await setupFullTenant(page);
    const opts = { page, accessToken: setup.accessToken };
    const auth = { headers: { Authorization: `Bearer ${setup.accessToken}` } };
    const skillLevels: { id: string }[] = await (
      await page.request.get(`${API_BASE}/skill-levels`, auth)
    ).json();
    const skillLevelId = skillLevels[0].id;

    // Dozens of indicators: 3 competences x 10.
    const stamp = Date.now().toString(36);
    const group = await createCompetenceGroup(opts, `SkipGroup-${stamp}`);
    const competenceIds: string[] = [];
    const indicatorIds: string[] = [];
    for (let c = 0; c < 3; c++) {
      const comp = await createCompetence(opts, group.id, `SkipComp-${c}-${stamp}`);
      competenceIds.push(comp.id);
      for (let i = 0; i < 10; i++) {
        const ind = await createIndicator(opts, comp.id, `SkipInd-${c}-${i}-${stamp}`, skillLevelId);
        indicatorIds.push(ind.id);
      }
    }
    const scale = await (
      await page.request.post(`${API_BASE}/answer-scales`, {
        ...auth,
        data: {
          title: `Skip scale ${stamp}`,
          options: [
            { title: "Low", sort_index: 0, is_neutral: false },
            { title: "Top", sort_index: 1, is_neutral: false },
          ],
          levels: [],
        },
      })
    ).json();
    const a = await createAssessment(opts, setup.employeeId, `Skip flow ${stamp}`, "self");
    await page.request.put(`${API_BASE}/assessments/${a.id}/scale`, {
      ...auth,
      data: { scale_id: scale.id },
    });
    await page.request.put(`${API_BASE}/assessments/${a.id}/criteria`, {
      ...auth,
      data: {
        criteria_type: "competences",
        competences: competenceIds.map((id) => ({ competence_id: id, skill_level_id: skillLevelId })),
      },
    });
    await page.request.post(`${API_BASE}/assessments/${a.id}/status`, {
      ...auth,
      data: { status_code: "sent" },
    });

    // Answer everything but two indicators deep in the sheet.
    const detail = await (await page.request.get(`${API_BASE}/assessments/${a.id}`, auth)).json();
    const participant = detail.participants.find((p: { role: string }) => p.role === "self");
    const snapshot = await (
      await page.request.get(`${API_BASE}/answer-scales/${detail.scale_id}`, auth)
    ).json();
    const skipped = new Set([indicatorIds[17], indicatorIds[25]]);
    for (const indicatorId of indicatorIds) {
      if (skipped.has(indicatorId)) continue;
      const resp = await page.request.post(`${API_BASE}/assessments/${a.id}/answers`, {
        ...auth,
        data: {
          participant_id: participant.id,
          indicator_id: indicatorId,
          answer_option_id: snapshot.options[0].id,
        },
      });
      expect(resp.ok()).toBeTruthy();
    }

    await setAuthTokens(page, setup.accessToken, setup.refreshToken);
    await page.goto(`/assessments/${a.id}`);
    await page.getByRole("button", { name: /Take this assessment/i }).click();
    const sheet = page.getByTestId("assessment-eval-sheet");
    await expect(sheet).toBeVisible();
    const cards = sheet.locator('[data-testid^="assessment-eval-indicator-"]');
    await expect(cards).toHaveCount(30);

    // "First" is the order the sheet shows, whatever order the ids came in.
    const shown = await cards.evaluateAll((els) =>
      els.map((el) => el.getAttribute("data-testid")!.replace("assessment-eval-indicator-", "")),
    );
    const firstSkipped = shown.find((id) => skipped.has(id))!;
    const target = page.getByTestId(`assessment-eval-indicator-${firstSkipped}`);
    await expect(target).not.toBeInViewport();

    await sheet.getByRole("button", { name: /Submit answers/i }).click();
    await expect(target).toBeFocused();
    await expect(target).toBeInViewport();
    for (const id of skipped) {
      await expect(page.getByTestId(`assessment-eval-indicator-${id}`)).toHaveAttribute("aria-invalid", "true");
    }
  });
});
