/**
 * HRP-273 / HRP-204e — UI smoke for the bulk resume-only analyze
 * affordance on the vacancy candidates table.
 *
 * The bulk bar shows up when at least one row has
 * ``ai_verdict === "pending"`` and ``ai_readiness === "resume_only"`` —
 * i.e. a parsed resume is on file and no AI analysis has produced a
 * verdict yet. The spec uses ``_test/seed-verdict`` (E2E_MODE-gated) to
 * shape that state so the test does not need a live Celery + LLM
 * pipeline.
 *
 * Coverage targets:
 *   1. No eligible row → no bulk bar.
 *   2. Seeded eligible rows → bulk bar appears with the correct count
 *      and 20 cr × N cost label.
 *   3. Clicking the bar opens the confirm modal; confirm fires the bulk
 *      endpoint and the modal closes.
 *
 * The "queued / failed / skipped" per-row response handling is unit-
 * tested on the backend (test_recruitment_resume_only_analysis.py); the
 * E2E here verifies the recruiter-facing wiring only.
 */
import { expect, test } from "@playwright/test";
import { registerUser, setAuthTokens, uniqueEmail } from "../helpers";

const API_BASE = "http://localhost:8100/api";

interface BulkSetup {
  accessToken: string;
  vacancyId: string;
  candidateVacancyIds: string[];
}

async function seedVerdict(
  request: import("@playwright/test").APIRequestContext,
  accessToken: string,
  cvId: string,
  body: Record<string, unknown>,
): Promise<void> {
  const resp = await request.post(
    `${API_BASE}/recruitment/_test/seed-verdict`,
    {
      headers: { Authorization: `Bearer ${accessToken}` },
      data: { candidate_vacancy_id: cvId, ...body },
    },
  );
  if (!resp.ok()) {
    throw new Error(
      `seedVerdict failed (${resp.status()}): ${await resp.text()}`,
    );
  }
}

async function setupVacancyWithNCandidates(
  page: import("@playwright/test").Page,
  count: number,
): Promise<BulkSetup> {
  const admin = await registerUser(page);
  await setAuthTokens(page, admin.accessToken, admin.refreshToken);

  const vacancyResp = await page.request.post(
    `${API_BASE}/recruitment/vacancies`,
    {
      headers: { Authorization: `Bearer ${admin.accessToken}` },
      data: { title: `HRP-273 bulk ${Date.now()}` },
    },
  );
  if (!vacancyResp.ok()) {
    throw new Error(
      `createVacancy failed (${vacancyResp.status()}): ${await vacancyResp.text()}`,
    );
  }
  const vacancy = (await vacancyResp.json()) as { id: string };

  const cvIds: string[] = [];
  for (let i = 0; i < count; i += 1) {
    const resp = await page.request.post(
      `${API_BASE}/recruitment/vacancies/${vacancy.id}/candidates`,
      {
        headers: { Authorization: `Bearer ${admin.accessToken}` },
        data: {
          full_name: `Bulk Candidate ${i + 1}`,
          email: uniqueEmail(),
        },
      },
    );
    if (!resp.ok()) {
      throw new Error(
        `add candidate ${i} failed (${resp.status()}): ${await resp.text()}`,
      );
    }
    const body = (await resp.json()) as { candidate_vacancy_id: string };
    cvIds.push(body.candidate_vacancy_id);
  }

  return {
    accessToken: admin.accessToken,
    vacancyId: vacancy.id,
    candidateVacancyIds: cvIds,
  };
}

test.describe("HRP-273 — Bulk resume-only analyze UI", () => {
  test("hides the bulk bar when no row is eligible", async ({ page }) => {
    const setup = await setupVacancyWithNCandidates(page, 1);
    // Freshly-added candidates have ``ai_readiness="none"`` and verdict
    // ``"pending"`` — both conditions for the bar must hold so no bar
    // should appear yet.

    await page.goto(`/recruitment/requisitions/${setup.vacancyId}`);
    const table = page.getByTestId("vacancy-candidates-table");
    await expect(table).toBeVisible({ timeout: 15000 });

    await expect(
      page.getByTestId("vacancy-candidates-bulk-analyze-btn"),
    ).toHaveCount(0);
  });

  test("shows the bulk bar with N × 20 cr cost when eligible rows exist", async ({
    page,
  }) => {
    const setup = await setupVacancyWithNCandidates(page, 2);
    for (const cvId of setup.candidateVacancyIds) {
      await seedVerdict(page.request, setup.accessToken, cvId, {
        ai_verdict: "pending",
        ai_readiness: "resume_only",
      });
    }

    await page.goto(`/recruitment/requisitions/${setup.vacancyId}`);
    const bulkButton = page.getByTestId("vacancy-candidates-bulk-analyze-btn");
    await expect(bulkButton).toBeVisible({ timeout: 15000 });
    // 2 × 20 cr — the bar shows total cost so the recruiter knows the
    // damage before opening the confirm modal.
    await expect(bulkButton).toContainText("40 cr");
  });

  test("clicking the bar opens the confirm modal and closes it on confirm", async ({
    page,
  }) => {
    const setup = await setupVacancyWithNCandidates(page, 2);
    for (const cvId of setup.candidateVacancyIds) {
      await seedVerdict(page.request, setup.accessToken, cvId, {
        ai_verdict: "pending",
        ai_readiness: "resume_only",
      });
    }

    await page.goto(`/recruitment/requisitions/${setup.vacancyId}`);
    const bulkButton = page.getByTestId("vacancy-candidates-bulk-analyze-btn");
    await expect(bulkButton).toBeVisible({ timeout: 15000 });
    await bulkButton.click();

    const modal = page.getByTestId("vacancy-candidates-bulk-analyze-modal");
    await expect(modal).toBeVisible({ timeout: 5000 });

    // Confirm fires the bulk endpoint — capture the request so the test
    // does not depend on the toast timing window.
    const [bulkResp] = await Promise.all([
      page.waitForResponse(
        (r) =>
          r.url().includes(`/recruitment/vacancies/${setup.vacancyId}/ai-analyses/bulk`) &&
          r.request().method() === "POST",
      ),
      page
        .getByTestId("vacancy-candidates-bulk-analyze-modal-confirm")
        .click(),
    ]);
    expect([200, 201, 202]).toContain(bulkResp.status());

    await expect(modal).toBeHidden({ timeout: 10000 });
  });
});
