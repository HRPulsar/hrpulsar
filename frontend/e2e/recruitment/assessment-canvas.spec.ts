/**
 * HRP-546 — e2e coverage for the fullscreen assessment canvas (HRP-510).
 *
 * The canvas is a read-only grid: competences from the vacancy profile are
 * the rows, attached candidates the columns, and every cell carries the
 * manager score next to the AI one. The spec drives it end to end —
 * entry link, scored/unscored cells, the Points↔Percent switch, both
 * filters, the candidate panel and the divergence deep link.
 *
 * Everything is seeded over the API: the AI half of the grid needs Celery
 * plus a model, so the fixture scores the manager half only and asserts the
 * AI half renders its "no data" text. That keeps the run deterministic
 * without weakening what the canvas itself is being tested for.
 */
import { expect, test, type Page } from "@playwright/test";

import { API_BASE, registerUser, setAuthTokens } from "../helpers";

// The profile save normalizes competence ids, so a slug would come back
// rewritten as a uuid5 and no longer match the cell testids built below.
// Literal UUIDs survive the round-trip untouched.
const COMPETENCE_ALPHA = "11111111-1111-4111-8111-111111111111";
const COMPETENCE_BETA = "22222222-2222-4222-8222-222222222222";

interface CanvasFixture {
  accessToken: string;
  refreshToken: string;
  vacancyId: string;
  /** Candidate carrying manager scores on both competences. */
  scoredCvId: string;
  /** Candidate attached but never assessed. */
  unscoredCvId: string;
}

async function seedCanvas(page: Page): Promise<CanvasFixture> {
  const reg = await registerUser(page);
  const auth = { headers: { Authorization: `Bearer ${reg.accessToken}` } };
  const stamp = Date.now().toString(36);

  async function post<T>(path: string, data: unknown): Promise<T> {
    const resp = await page.request.post(`${API_BASE}${path}`, {
      ...auth,
      data: data as Record<string, unknown>,
    });
    if (!resp.ok()) {
      throw new Error(`POST ${path} failed (${resp.status()}): ${await resp.text()}`);
    }
    return resp.json() as Promise<T>;
  }

  const vacancy = await post<{ id: string }>("/recruitment/vacancies", {
    title: `Canvas E2E ${stamp}`,
  });

  // Profile competences are the only source of matrix rows.
  const profileResp = await page.request.put(
    `${API_BASE}/recruitment/vacancies/${vacancy.id}/profile`,
    {
      ...auth,
      data: {
        profile_data: {
          competences: [
            {
              id: COMPETENCE_ALPHA,
              name: `Communication ${stamp}`,
              group: "Soft",
              criticality: "critical",
              indicators: [],
            },
            {
              id: COMPETENCE_BETA,
              name: `Ownership ${stamp}`,
              group: "Soft",
              criticality: "important",
              indicators: [],
            },
          ],
        },
      },
    },
  );
  expect(profileResp.ok()).toBeTruthy();

  async function attachCandidate(label: string): Promise<string> {
    const candidate = await post<{ id: string }>("/recruitment/candidates", {
      first_name: label,
      last_name: "Candidate",
      email: `canvas-${label.toLowerCase()}-${stamp}@test.com`,
    });
    const cv = await post<{ id: string }>("/recruitment/candidate-vacancies", {
      candidate_id: candidate.id,
      vacancy_id: vacancy.id,
    });
    return cv.id;
  }

  const scoredCvId = await attachCandidate("Scored");
  const unscoredCvId = await attachCandidate("Unscored");

  // Manager half: a round, the caller as its evaluator, then two scores.
  // A draft sheet owned by a real user already counts towards the matrix,
  // so neither the sheet nor the round has to be submitted/completed.
  const round = await post<{ id: string }>(
    `/v1/candidate-vacancies/${scoredCvId}/assessment-rounds`,
    { type: "interview" },
  );
  await post(`/v1/assessment-rounds/${round.id}/evaluators`, {
    user_id: reg.userId,
  });

  const sheetsResp = await page.request.get(
    `${API_BASE}/v1/assessment-rounds/${round.id}/assessments`,
    auth,
  );
  expect(sheetsResp.ok()).toBeTruthy();
  const sheets = (await sheetsResp.json()) as {
    id: string;
    evaluator_user_id: string | null;
  }[];
  const sheet = sheets.find((s) => s.evaluator_user_id === reg.userId);
  expect(sheet, "self sheet is created together with the evaluator").toBeTruthy();

  for (const competenceId of [COMPETENCE_ALPHA, COMPETENCE_BETA]) {
    const scoreResp = await page.request.patch(
      `${API_BASE}/v1/assessments/${sheet!.id}/competence-scores/${competenceId}`,
      { ...auth, data: { score_value: 4, score_source: "manual" } },
    );
    expect(scoreResp.ok()).toBeTruthy();
  }

  await setAuthTokens(page, reg.accessToken, reg.refreshToken);

  return {
    accessToken: reg.accessToken,
    refreshToken: reg.refreshToken,
    vacancyId: vacancy.id,
    scoredCvId,
    unscoredCvId,
  };
}

test.describe("Recruitment — fullscreen assessment canvas (HRP-510)", () => {
  test("opens from the vacancy assessments tab and renders scored cells", async ({
    page,
  }) => {
    const fx = await seedCanvas(page);

    await page.goto(`/recruitment/requisitions/${fx.vacancyId}`);
    await page.getByTestId("recruitment-vacancy-tab-assessments").click();

    const openBtn = page.getByTestId("assessment-canvas-open-fullscreen-btn");
    await expect(openBtn).toBeVisible({ timeout: 15000 });
    await openBtn.click();

    await page.waitForURL(
      `**/recruitment/requisitions/${fx.vacancyId}/assessments/canvas`,
    );
    await expect(page.getByTestId("recruitment-canvas-fullscreen")).toBeVisible();
    await expect(page.getByTestId("canvas-matrix")).toBeVisible({
      timeout: 15000,
    });

    // Scored candidate: a manager number, and the AI half explicitly empty
    // because no analysis has run for this pair.
    const scoredCell = page.getByTestId(
      `canvas-cell-${fx.scoredCvId}-${COMPETENCE_ALPHA}`,
    );
    await expect(scoredCell).toContainText(/M:\s*\d/);
    await expect(scoredCell).toContainText("AI:");

    // Unscored candidate: both halves empty, same grid.
    await expect(
      page.getByTestId(`canvas-cell-${fx.unscoredCvId}-${COMPETENCE_ALPHA}`),
    ).toContainText("M:—");

    await expect(page.getByTestId("canvas-totals")).toBeVisible();
    await expect(
      page.getByTestId(`canvas-total-${fx.scoredCvId}`),
    ).toBeVisible();

    // The shell has no app chrome — that is the whole point of the route.
    await expect(page.getByTestId("sidebar-nav")).toHaveCount(0);

    await page.getByTestId("canvas-back-link").click();
    await page.waitForURL(`**/recruitment/requisitions/${fx.vacancyId}`);
  });

  test("scale switch, filters and the candidate panel reshape the grid", async ({
    page,
  }) => {
    const fx = await seedCanvas(page);

    await page.goto(
      `/recruitment/requisitions/${fx.vacancyId}/assessments/canvas`,
    );
    await expect(page.getByTestId("canvas-matrix")).toBeVisible({
      timeout: 15000,
    });

    const scoredCell = page.getByTestId(
      `canvas-cell-${fx.scoredCvId}-${COMPETENCE_ALPHA}`,
    );
    const pointsText = await scoredCell.innerText();

    // Points → Percent rescales the same score against the tenant maximum.
    await page.getByTestId("canvas-scale-select").selectOption("percent");
    await expect(scoredCell).toContainText("%");
    expect(await scoredCell.innerText()).not.toBe(pointsText);
    await page.getByTestId("canvas-scale-select").selectOption("points");

    // View: Manager only drops the AI line from every cell.
    await page.getByTestId("canvas-view-select").selectOption("manager");
    await expect(scoredCell).not.toContainText("AI:");
    await page.getByTestId("canvas-view-select").selectOption("manager_ai");

    // "Hide unscored" removes the candidate nobody has assessed.
    const unscoredCell = page.getByTestId(
      `canvas-cell-${fx.unscoredCvId}-${COMPETENCE_ALPHA}`,
    );
    await expect(unscoredCell).toBeVisible();
    await page.getByTestId("canvas-filter-unscored").click();
    await expect(unscoredCell).toHaveCount(0);
    await expect(scoredCell).toBeVisible();
    await page.getByTestId("canvas-filter-unscored").click();
    await expect(unscoredCell).toBeVisible();

    // The candidate panel hides a column without touching the filters.
    await page.getByTestId(`canvas-candidate-toggle-${fx.scoredCvId}`).click();
    await expect(scoredCell).toHaveCount(0);
    await page.getByTestId(`canvas-candidate-toggle-${fx.scoredCvId}`).click();
    await expect(scoredCell).toBeVisible();
  });

  test("divergence deep link opens with the filter already applied", async ({
    page,
  }) => {
    const fx = await seedCanvas(page);

    await page.goto(
      `/recruitment/requisitions/${fx.vacancyId}/assessments/canvas?filter=divergences`,
    );

    await expect(
      page.getByTestId("recruitment-canvas-fullscreen"),
    ).toBeVisible();
    await expect(page.getByTestId("canvas-filter-divergences")).toBeChecked();

    // Manager-only scores cannot diverge from an AI score that does not
    // exist, so the filtered grid is empty rather than merely unsorted.
    await expect(page.getByTestId("canvas-matrix-empty")).toBeVisible({
      timeout: 15000,
    });

    await page.getByTestId("canvas-filter-divergences").click();
    await expect(page.getByTestId("canvas-matrix")).toBeVisible();
  });
});
