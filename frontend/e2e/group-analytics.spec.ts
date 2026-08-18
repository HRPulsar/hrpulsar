/**
 * HRP-546 — e2e coverage for the Analytics block on a mass assessment
 * (HRP-528).
 *
 * The block only exists once a child assessment is Done, and everything it
 * draws is derived from those children. The fixture therefore walks one
 * child all the way through the lifecycle over the API — sent →
 * in_progress → answers → done — scoring two competences deliberately far
 * apart so the matrix has something to sort and filter.
 */
import { expect, test, type Page } from "./fixtures";

import {
  API_BASE,
  createCompetence,
  createCompetenceGroup,
  createIndicator,
  pickFirstSkillLevel,
  setAuthTokens,
  setupFullTenant,
} from "./helpers";

interface AnalyticsFixture {
  groupId: string;
  employeeId: string;
  /** Competence answered with the best option on the scale. */
  strongCompetenceId: string;
  /** Competence answered with the weakest option on the scale. */
  weakCompetenceId: string;
}

async function seedDoneMassAssessment(page: Page): Promise<AnalyticsFixture> {
  const setup = await setupFullTenant(page);
  const opts = { page, accessToken: setup.accessToken };
  const auth = { headers: { Authorization: `Bearer ${setup.accessToken}` } };
  const stamp = Date.now().toString(36);

  async function get<T>(path: string): Promise<T> {
    const resp = await page.request.get(`${API_BASE}${path}`, auth);
    if (!resp.ok()) {
      throw new Error(`GET ${path} failed (${resp.status()}): ${await resp.text()}`);
    }
    return resp.json() as Promise<T>;
  }
  async function send(
    method: "post" | "put",
    path: string,
    data: unknown,
  ): Promise<unknown> {
    const resp = await page.request[method](`${API_BASE}${path}`, {
      ...auth,
      data: data as Record<string, unknown>,
    });
    if (!resp.ok()) {
      throw new Error(
        `${method.toUpperCase()} ${path} failed (${resp.status()}): ${await resp.text()}`,
      );
    }
    return resp.json();
  }

  const skillLevel = await pickFirstSkillLevel(opts);
  const compGroup = await createCompetenceGroup(opts, `AnalyticsGrp-${stamp}`);
  const strong = await createCompetence(opts, compGroup.id, `Alpha-${stamp}`);
  const weak = await createCompetence(opts, compGroup.id, `Beta-${stamp}`);
  await createIndicator(opts, strong.id, `AlphaInd-${stamp}`, skillLevel.id);
  await createIndicator(opts, weak.id, `BetaInd-${stamp}`, skillLevel.id);

  const scales = await get<{ id: string; is_default: boolean }[]>(
    "/answer-scales",
  );
  const defaultScale = scales.find((s) => s.is_default);
  expect(defaultScale, "tenant seed provides a default answer scale").toBeTruthy();

  // Mass assessment over the single seeded employee.
  const group = (await send("post", "/assessment-groups", {
    title: `Analytics mass ${stamp}`,
    employee_ids: [setup.employeeId],
    type_code: "self",
  })) as { id: string; assessments: { id: string }[] };

  await send("put", `/assessment-groups/${group.id}/criteria`, {
    criteria_type: "competences",
    competences: [
      { competence_id: strong.id, skill_level_id: skillLevel.id },
      { competence_id: weak.id, skill_level_id: skillLevel.id },
    ],
  });
  await send("put", `/assessment-groups/${group.id}/scale`, {
    scale_id: defaultScale!.id,
  });

  const strongIndicator = (
    await get<{ indicators: { id: string }[] }>(`/competences/${strong.id}`)
  ).indicators[0].id;
  const weakIndicator = (
    await get<{ indicators: { id: string }[] }>(`/competences/${weak.id}`)
  ).indicators[0].id;

  for (const child of group.assessments) {
    // Sending snapshots the scale, so the options are read afterwards.
    await send("post", `/assessments/${child.id}/status`, {
      status_code: "sent",
    });
    const detail = await get<{
      scale_id: string;
      participants: { id: string; role: string }[];
    }>(`/assessments/${child.id}`);
    const participant = detail.participants.find((p) => p.role === "self");
    expect(participant, "a self assessment auto-creates its participant").toBeTruthy();

    const snapshot = await get<{
      options: { id: string; weight: number; is_neutral: boolean }[];
    }>(`/answer-scales/${detail.scale_id}`);
    const scoring = snapshot.options
      .filter((o) => !o.is_neutral)
      .sort((a, b) => a.weight - b.weight);
    // Two distinct options are the fixture's precondition: the matrix sort
    // test needs the two competences to land on different averages.
    expect(
      scoring.length,
      "the seeded scale must offer at least two scoring options",
    ).toBeGreaterThan(1);
    const worst = scoring[0];
    const best = scoring[scoring.length - 1];
    expect(best.weight).toBeGreaterThan(worst.weight);

    // `in_progress` is never a manual target (HRP-192): the first answer
    // drives it. Answering every indicator also completes the participant,
    // which is what unlocks the on_review → done checkpoint below.
    for (const [indicatorId, option] of [
      [strongIndicator, best],
      [weakIndicator, worst],
    ] as const) {
      await send("post", `/assessments/${child.id}/answers`, {
        participant_id: participant!.id,
        indicator_id: indicatorId,
        answer_option_id: option.id,
        score: option.weight,
      });
    }

    const current = await get<{ status_code: string }>(
      `/assessments/${child.id}`,
    );
    if (current.status_code !== "done") {
      if (current.status_code !== "on_review") {
        await send("post", `/assessments/${child.id}/status`, {
          status_code: "on_review",
        });
      }
      await send("post", `/assessments/${child.id}/status`, {
        status_code: "done",
      });
    }
  }

  await setAuthTokens(page, setup.accessToken, setup.refreshToken);

  return {
    groupId: group.id,
    employeeId: setup.employeeId,
    strongCompetenceId: strong.id,
    weakCompetenceId: weak.id,
  };
}

test.describe("Mass assessment — Analytics block (HRP-528)", () => {
  test("renders the analytics card, gauge, matrix and summary tree", async ({
    page,
  }) => {
    const fx = await seedDoneMassAssessment(page);

    await page.goto(`/assessment-groups/${fx.groupId}`);

    const card = page.getByTestId("group-analytics-card");
    await expect(card).toBeVisible({ timeout: 20000 });
    await expect(page.getByTestId("group-analytics-detailed")).toBeVisible();

    // Competence criteria (not "current positions") → gauge + matrix, and
    // the employees table stays out of the picture.
    await expect(page.getByTestId("group-analytics-average-gauge")).toBeVisible();
    await expect(page.getByTestId("group-analytics-employees-table")).toHaveCount(0);

    const matrix = page.getByTestId("group-analytics-competence-matrix");
    await expect(matrix).toBeVisible();
    await expect(
      page.getByTestId(`group-analytics-competence-matrix-column-${fx.employeeId}`),
    ).toBeVisible();
    for (const competenceId of [fx.strongCompetenceId, fx.weakCompetenceId]) {
      await expect(
        page.getByTestId(`group-analytics-competence-matrix-row-${competenceId}`),
      ).toBeVisible();
      await expect(
        page.getByTestId(
          `group-analytics-competence-matrix-cell-${competenceId}-${fx.employeeId}`,
        ),
      ).toBeVisible();
    }

    // At-risk / top-performer plates belong to the non-"all grades" layout.
    await expect(page.getByTestId("group-analytics-at-risk")).toBeVisible();
    await expect(page.getByTestId("group-analytics-top-performers")).toBeVisible();

    await expect(page.getByTestId("group-analytics-summary")).toBeVisible();
    await expect(page.getByTestId("group-analytics-tree")).toBeVisible();
    await expect(
      page.getByTestId(`group-analytics-tree-row-${fx.strongCompetenceId}`),
    ).toBeVisible();
  });

  test("matrix sort flips the row order and the competence filter narrows it", async ({
    page,
  }) => {
    const fx = await seedDoneMassAssessment(page);

    await page.goto(`/assessment-groups/${fx.groupId}`);
    await expect(page.getByTestId("group-analytics-card")).toBeVisible({
      timeout: 20000,
    });

    const rows = page.locator(
      '[data-testid^="group-analytics-competence-matrix-row-"]:not([data-testid$="-average"])',
    );
    const firstBefore = await rows.first().getAttribute("data-testid");

    await page.getByTestId("group-analytics-competence-matrix-sort").click();
    await expect
      .poll(async () => rows.first().getAttribute("data-testid"))
      .not.toBe(firstBefore);

    // The competence filter is a search popover — picking one competence
    // leaves exactly its row in the matrix.
    await page.getByTestId("group-analytics-filter-competences").click();
    await page
      .getByTestId(
        `group-analytics-filter-competences-option-${fx.strongCompetenceId}`,
      )
      .click();
    await page.keyboard.press("Escape");

    await expect(
      page.getByTestId(
        `group-analytics-competence-matrix-row-${fx.strongCompetenceId}`,
      ),
    ).toBeVisible();
    await expect(
      page.getByTestId(
        `group-analytics-competence-matrix-row-${fx.weakCompetenceId}`,
      ),
    ).toHaveCount(0);
  });
});
