/**
 * HRP-546 — e2e coverage for the Generate report dialog (HRP-521).
 *
 * The dialog's job is to turn four controls — candidate scope, sheets,
 * audience and the guards around them — into one POST body. So that body is
 * what the spec asserts: the request is intercepted on its way out and
 * checked field by field, including the deliberate omission of
 * `candidate_vacancy_ids` on "All active" (the worker resolves that set
 * itself; sending the picker's page would silently cap the report).
 *
 * The spec stops at the submitting step. Producing a finished .xlsx needs a
 * Celery worker and object storage, neither of which the e2e stack runs —
 * and the download half of the dialog is not what HRP-521 changed.
 */
import { expect, test, type Page } from "@playwright/test";

import { API_BASE, registerUser, setAuthTokens } from "../helpers";

const SECTION_CODES = [
  "summary_ranking",
  "competency_matrix",
  "detailed_analysis",
  "incomplete_data",
] as const;

interface ReportFixture {
  vacancyId: string;
  candidateVacancyIds: string[];
}

async function seedVacancyWithCandidates(page: Page): Promise<ReportFixture> {
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
    title: `Report E2E ${stamp}`,
  });

  const candidateVacancyIds: string[] = [];
  for (const label of ["Ada", "Grace"]) {
    const candidate = await post<{ id: string }>("/recruitment/candidates", {
      first_name: label,
      last_name: "Reportee",
      email: `report-${label.toLowerCase()}-${stamp}@test.com`,
    });
    const cv = await post<{ id: string }>("/recruitment/candidate-vacancies", {
      candidate_id: candidate.id,
      vacancy_id: vacancy.id,
    });
    candidateVacancyIds.push(cv.id);
  }

  await setAuthTokens(page, reg.accessToken, reg.refreshToken);
  return { vacancyId: vacancy.id, candidateVacancyIds };
}

async function openWizard(page: Page, vacancyId: string): Promise<void> {
  await page.goto(`/recruitment/requisitions/${vacancyId}`);
  await page.getByTestId("recruitment-vacancy-tab-reports").click();
  const newBtn = page.getByTestId("recruitment-reports-btn-new");
  await expect(newBtn).toBeVisible({ timeout: 15000 });
  await newBtn.click();
  await expect(page.getByTestId("recruitment-report-wizard")).toBeVisible();
}

test.describe("Recruitment — Generate report dialog (HRP-521)", () => {
  test("opens with every sheet preselected and the recruiter audience", async ({
    page,
  }) => {
    const fx = await seedVacancyWithCandidates(page);
    await openWizard(page, fx.vacancyId);

    await expect(
      page.getByTestId("recruitment-report-vacancy-title"),
    ).toBeVisible();

    for (const code of SECTION_CODES) {
      await expect(
        page.getByTestId(`recruitment-report-section-${code}`),
      ).toBeChecked();
    }

    await expect(
      page.getByTestId("recruitment-report-audience-recruiter"),
    ).toBeChecked();
    await expect(page.getByTestId("recruitment-report-scope-all")).toBeChecked();

    // Nobody has reached the last active stage of the default funnel, so
    // the finalists bucket is empty and its radio must say so rather than
    // submitting an empty candidate list.
    await expect(
      page.getByTestId("recruitment-report-scope-finalists"),
    ).toBeDisabled();

    // Custom scope reveals the picker, and submitting nothing is blocked.
    await page.getByTestId("recruitment-report-scope-custom").click();
    await expect(page.getByTestId("recruitment-report-custom-list")).toBeVisible();
    await expect(
      page.getByTestId("recruitment-report-btn-submit"),
    ).toBeDisabled();

    await page
      .getByTestId(`recruitment-report-custom-candidate-${fx.candidateVacancyIds[0]}`)
      .click();
    await expect(
      page.getByTestId("recruitment-report-btn-submit"),
    ).toBeEnabled();
  });

  test("dropping every sheet blocks generation with an error toast", async ({
    page,
  }) => {
    const fx = await seedVacancyWithCandidates(page);
    await openWizard(page, fx.vacancyId);

    for (const code of SECTION_CODES) {
      await page.getByTestId(`recruitment-report-section-${code}`).uncheck();
    }

    await page.getByTestId("recruitment-report-btn-submit").click();

    // The wizard's own guard, not merely "some toast appeared" — the page
    // raises others (credit warnings) that would satisfy a bare locator.
    await expect(
      page.locator("[data-sonner-toast]").filter({
        hasText: "Select at least one sheet",
      }),
    ).toBeVisible();
    // Still on the configure step — the request was never sent.
    await expect(
      page.getByTestId("recruitment-report-sections"),
    ).toBeVisible();
    await expect(
      page.getByTestId("recruitment-report-btn-submit"),
    ).toBeVisible();
  });

  test("custom scope, one sheet and the hiring-manager audience reach the API", async ({
    page,
  }) => {
    const fx = await seedVacancyWithCandidates(page);
    await openWizard(page, fx.vacancyId);

    // Keep exactly one sheet.
    for (const code of SECTION_CODES) {
      if (code === "competency_matrix") continue;
      await page.getByTestId(`recruitment-report-section-${code}`).uncheck();
    }
    await expect(
      page.getByTestId("recruitment-report-section-competency_matrix"),
    ).toBeChecked();

    await page.getByTestId("recruitment-report-scope-custom").click();
    await page
      .getByTestId(`recruitment-report-custom-candidate-${fx.candidateVacancyIds[1]}`)
      .click();
    await page.getByTestId("recruitment-report-audience-hiring-manager").click();

    const [request] = await Promise.all([
      page.waitForRequest(
        (req) =>
          req.method() === "POST" &&
          req.url().includes(`/recruitment/vacancies/${fx.vacancyId}/reports`),
      ),
      page.getByTestId("recruitment-report-btn-submit").click(),
    ]);

    const body = request.postDataJSON() as {
      sections: string[];
      audience: string;
      candidate_vacancy_ids?: string[];
    };
    expect(body.sections).toEqual(["competency_matrix"]);
    expect(body.audience).toBe("hiring_manager");
    expect(body.candidate_vacancy_ids).toEqual([fx.candidateVacancyIds[1]]);

    // Positive assertion: the dialog is actually on the submitting step.
    // A bare "submit button is gone" would also pass if the request 4xx'd
    // and the dialog re-rendered something else entirely.
    await expect(
      page.getByTestId("recruitment-report-submitting"),
    ).toBeVisible();
  });

  test("all-active scope omits the candidate whitelist", async ({ page }) => {
    const fx = await seedVacancyWithCandidates(page);
    await openWizard(page, fx.vacancyId);

    const [request] = await Promise.all([
      page.waitForRequest(
        (req) =>
          req.method() === "POST" &&
          req.url().includes(`/recruitment/vacancies/${fx.vacancyId}/reports`),
      ),
      page.getByTestId("recruitment-report-btn-submit").click(),
    ]);

    const body = request.postDataJSON() as {
      sections: string[];
      audience: string;
      candidate_vacancy_ids?: string[];
    };
    expect(body.sections).toEqual([...SECTION_CODES]);
    expect(body.audience).toBe("recruiter");
    expect(body.candidate_vacancy_ids).toBeUndefined();
  });
});
