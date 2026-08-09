/**
 * HRP-273 / HRP-204e — UI smoke for the resume-only AI analysis flow on
 * the candidate card.
 *
 * Real Celery + LLM live in a separate environment; the spec drives the
 * UI states via the existing ``_test/seed-verdict`` helper (E2E_MODE-
 * gated, see backend/app/modules/recruitment/router.py) and asserts the
 * candidate card honours the contract the recruiter actually depends on:
 *
 *   1. Fresh manually-added candidate → empty state + a disabled
 *      Analyze split-button (HRP-488 case 1: nothing to analyse yet).
 *   2. After a seeded ``resume_only`` verdict the AI Insights section
 *      renders the verdict word AND the ``[resume only]`` sub-badge.
 *   3. A full-mode seeded verdict swaps the sub-badge to ``[full]``.
 *
 * The deep "click → poll → finish" loop needs the Celery worker + LLM key
 * and lives in CR8 / staging. Marking those gaps explicitly here keeps
 * CI green without faking results the recruiter would not see in prod.
 */
import { expect, test } from "@playwright/test";
import { registerUser, setAuthTokens, uniqueEmail } from "../helpers";

const API_BASE = "http://localhost:8100/api";

interface AuthedSetup {
  accessToken: string;
  vacancyId: string;
  candidateId: string;
  candidateVacancyId: string;
}

async function setupVacancyWithCandidate(
  page: import("@playwright/test").Page,
): Promise<AuthedSetup> {
  const admin = await registerUser(page);
  await setAuthTokens(page, admin.accessToken, admin.refreshToken);

  const vacancyResp = await page.request.post(
    `${API_BASE}/recruitment/vacancies`,
    {
      headers: { Authorization: `Bearer ${admin.accessToken}` },
      data: { title: `HRP-273 ${Date.now()}` },
    },
  );
  if (!vacancyResp.ok()) {
    throw new Error(
      `createVacancy failed (${vacancyResp.status()}): ${await vacancyResp.text()}`,
    );
  }
  const vacancy = (await vacancyResp.json()) as { id: string };

  // Manual add — backend returns the canonical candidate dict with the
  // implicit ``candidate_vacancy_id`` attached.
  const candidateResp = await page.request.post(
    `${API_BASE}/recruitment/vacancies/${vacancy.id}/candidates`,
    {
      headers: { Authorization: `Bearer ${admin.accessToken}` },
      data: {
        full_name: "Resume Only Alpha",
        email: uniqueEmail(),
      },
    },
  );
  if (!candidateResp.ok()) {
    throw new Error(
      `add candidate failed (${candidateResp.status()}): ${await candidateResp.text()}`,
    );
  }
  const candidate = (await candidateResp.json()) as {
    id: string;
    candidate_vacancy_id: string;
  };

  return {
    accessToken: admin.accessToken,
    vacancyId: vacancy.id,
    candidateId: candidate.id,
    candidateVacancyId: candidate.candidate_vacancy_id,
  };
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

test.describe("HRP-273 — Resume-only AI analysis UI", () => {
  test("empty state surfaces the Analyze split-button", async ({ page }) => {
    const setup = await setupVacancyWithCandidate(page);
    await page.goto(
      `/recruitment/candidates/${setup.candidateId}?vacancyId=${setup.vacancyId}`,
    );

    const aiInsights = page.getByTestId(
      "candidate-section-ai-insights-empty-state",
    );
    await expect(aiInsights).toBeVisible({ timeout: 15000 });

    // HRP-488: the empty state owns the action now — the section footer
    // that used to carry it is gone, and both modes live in the menu
    // behind a single "Analyze" trigger.
    const analyzeTrigger = aiInsights.getByTestId(
      "candidate-section-ai-insights-analyze-menu-trigger",
    );
    await expect(analyzeTrigger).toBeVisible();
    await expect(analyzeTrigger).toContainText(/Analyze/i);

    // HRP-488 case 1: this candidate was added by hand, so there is no
    // resume to analyse — the control is visible (the option stays
    // discoverable) but disabled, and the hint says what to do.
    await expect(analyzeTrigger).toBeDisabled();
    await expect(aiInsights).toContainText(/resume/i);
  });

  test("the manual refresh control is gone from the section header", async ({
    page,
  }) => {
    // HRP-489: it never did anything a user could observe — the section
    // refetches after every trigger and polls while a run is in flight.
    const setup = await setupVacancyWithCandidate(page);
    await page.goto(
      `/recruitment/candidates/${setup.candidateId}?vacancyId=${setup.vacancyId}`,
    );

    const section = page.getByTestId("candidate-section-ai-insights");
    await expect(section).toBeVisible({ timeout: 15000 });
    await expect(section.getByRole("button", { name: /refresh/i })).toHaveCount(
      0,
    );
  });

  test("seeded resume-only verdict renders verdict word + [resume only] sub-badge", async ({
    page,
  }) => {
    const setup = await setupVacancyWithCandidate(page);

    await seedVerdict(page.request, setup.accessToken, setup.candidateVacancyId, {
      ai_verdict: "needs_check",
      ai_readiness: "resume_only",
      ai_analysis_mode: "resume_only",
      ai_score: 0.64, // canonical raw 0..1 scale (HRP-274)
      ai_verdict_summary:
        "Resume matches Junior expectations but lacks a recent project.",
      ai_key_strength: "Strong fundamentals",
      ai_key_risk: "Limited senior signal",
    });

    await page.goto(`/recruitment/requisitions/${setup.vacancyId}`);

    // The candidates table caches the verdict + AI readiness; ensure the
    // verdict cell rendered the seeded word (case-insensitive — the
    // badge component title-cases the underscore string).
    const verdictBadge = page.getByTestId(
      `vacancy-candidates-row-${setup.candidateVacancyId}-ai-verdict-badge`,
    );
    await expect(verdictBadge).toBeVisible({ timeout: 15000 });
    await expect(verdictBadge).toContainText(/needs check/i);

    // The mode sub-badge renders only when ``ai_analysis_mode`` is set —
    // assert the actual ``[resume only]`` chip, not just the verdict word.
    const modeBadge = page.getByTestId(
      `vacancy-candidates-row-${setup.candidateVacancyId}-ai-analysis-mode-badge-resume_only`,
    );
    await expect(modeBadge).toBeVisible();
    await expect(modeBadge).toHaveText(/resume only/i);
    await expect(
      page.getByTestId(
        `vacancy-candidates-row-${setup.candidateVacancyId}-ai-analysis-mode-badge-full`,
      ),
    ).toHaveCount(0);
  });

  test("seeded full verdict swaps the sub-badge to [full]", async ({
    page,
  }) => {
    const setup = await setupVacancyWithCandidate(page);

    await seedVerdict(page.request, setup.accessToken, setup.candidateVacancyId, {
      ai_verdict: "recommended",
      ai_readiness: "resume_and_transcript",
      ai_analysis_mode: "full",
      ai_score: 0.92, // canonical raw 0..1 scale (HRP-274)
      ai_verdict_summary: "Strong match.",
    });

    await page.goto(`/recruitment/requisitions/${setup.vacancyId}`);
    const verdictBadge = page.getByTestId(
      `vacancy-candidates-row-${setup.candidateVacancyId}-ai-verdict-badge`,
    );
    await expect(verdictBadge).toBeVisible({ timeout: 15000 });
    await expect(verdictBadge).toContainText(/recommended/i);

    // The ``[full]`` sub-badge replaces ``[resume only]`` for full-mode runs.
    const modeBadge = page.getByTestId(
      `vacancy-candidates-row-${setup.candidateVacancyId}-ai-analysis-mode-badge-full`,
    );
    await expect(modeBadge).toBeVisible();
    await expect(modeBadge).toHaveText(/full/i);
    await expect(
      page.getByTestId(
        `vacancy-candidates-row-${setup.candidateVacancyId}-ai-analysis-mode-badge-resume_only`,
      ),
    ).toHaveCount(0);
  });
});
