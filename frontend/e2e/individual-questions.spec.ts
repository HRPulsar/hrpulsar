/**
 * HRP-205 — Individual interview questions on the candidate card.
 *
 * Acceptance: the Interview questions section renders on the candidate
 * page between AI Insights and Assessments, gates generation on a parsed
 * resume, and its controls are reachable.
 *
 * AI generation itself needs a live LLM, so this spec covers the
 * deterministic surface: section presence, the empty state, and the
 * disabled Generate button when no parsed resume exists. Generation,
 * regeneration, dynamic_next and auto-cover are unit-tested with a
 * mocked LLM (backend/tests/unit/test_hrp205_question_sets.py).
 *
 * Requires E2E_MODE=true on the backend.
 */
import { test, expect } from "@playwright/test";
import { registerUser, setAuthTokens } from "./helpers";

const API_BASE = "http://localhost:8100/api";

test.describe("Individual interview questions (HRP-205)", () => {
  test("section renders with empty state; generate gated on parsed resume", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const authHeader = { Authorization: `Bearer ${admin.accessToken}` };

    const vacancyResp = await page.request.post(
      `${API_BASE}/recruitment/vacancies`,
      {
        headers: authHeader,
        data: { title: `Questions Vacancy ${Date.now()}` },
      },
    );
    expect(vacancyResp.ok()).toBeTruthy();
    const vacancy = await vacancyResp.json();

    const candResp = await page.request.post(
      `${API_BASE}/recruitment/candidates`,
      {
        headers: authHeader,
        data: {
          first_name: "HRP",
          last_name: `Two-O-Five ${Date.now()}`,
          email: `qcand-${Date.now()}@test.com`,
        },
      },
    );
    expect(candResp.ok()).toBeTruthy();
    const candidate = await candResp.json();

    const cvResp = await page.request.post(
      `${API_BASE}/recruitment/candidate-vacancies`,
      {
        headers: authHeader,
        data: { candidate_id: candidate.id, vacancy_id: vacancy.id },
      },
    );
    expect(cvResp.ok()).toBeTruthy();

    await setAuthTokens(page, admin.accessToken, admin.refreshToken);
    await page.goto(`/recruitment/candidates/${candidate.id}`);

    const section = page.getByTestId(
      "recruitment-interview-questions-section",
    );
    await expect(section).toBeVisible({ timeout: 15000 });

    // No sets yet → empty state with the Generate CTA.
    await expect(
      section.getByTestId("recruitment-interview-questions-empty"),
    ).toBeVisible({ timeout: 15000 });

    // Candidate has no parsed resume → the button is disabled and the
    // empty state explains why (REDO checklist: disabled needs a reason).
    const generateBtn = section.getByTestId(
      "recruitment-interview-questions-generate-btn",
    );
    await expect(generateBtn).toBeDisabled();
    await expect(
      section.getByText("Upload and parse a resume", { exact: false }),
    ).toBeVisible();
  });
});
