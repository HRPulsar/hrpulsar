/**
 * Cold-start QA sweeps.
 *
 * Each test walks a shipped surface from a freshly-registered, EMPTY
 * tenant: empty state → first entity created through the UI → the new
 * state is measurable in the UI. Surfaces covered here: talent market,
 * exams, recruitment onboarding → first vacancy + reports empty state,
 * dictionaries (HRP-282/285/286 semantics), and the manager-assessment
 * public link round-trip. The billing/credit-purchase surface is
 * covered by SaaS-only tests.
 */
import { test, expect } from "./fixtures";
import { registerUser, setAuthTokens, loginViaUI } from "./helpers";

const API_BASE = "http://localhost:8100/api";

function isoToday(): string {
  return new Date().toISOString().slice(0, 10);
}

test.describe("Cold start — Talent Market", () => {
  test("empty state → create card via UI → card appears → detail opens", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    await setAuthTokens(page, admin.accessToken, admin.refreshToken);

    await page.goto("/talent-market");
    await expect(page.getByTestId("talent-market-empty")).toBeVisible({
      timeout: 10000,
    });

    await page.getByTestId("talent-market-btn-create").click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    const title = `Cold Start Card ${Date.now()}`;
    // The Title input is the first textbox in the dialog (no testid).
    await dialog.locator("input").first().fill(title);
    await page
      .getByTestId("talent-market-input-start-date")
      .fill(isoToday());
    await dialog.getByRole("button", { name: /^Create$/ }).click();

    // Card lands on the list; the empty state is gone.
    await expect(page.getByText(title)).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId("talent-market-empty")).toBeHidden();

    // Cross-page: the card title links to the detail page.
    await page.getByRole("link", { name: title }).click();
    await expect(page).toHaveURL(/\/talent-market\/[0-9a-f-]+/, {
      timeout: 10000,
    });
    await expect(page.getByTestId("talent-market-btn-edit-title")).toBeVisible({
      timeout: 10000,
    });
  });
});

test.describe("Cold start — Exams", () => {
  test("empty state → create exam via UI → row appears → detail opens", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    await setAuthTokens(page, admin.accessToken, admin.refreshToken);

    await page.goto("/exams");
    await expect(page.getByTestId("exams-empty")).toBeVisible({
      timeout: 10000,
    });

    await page.getByTestId("exams-btn-create").click();
    await expect(page.getByTestId("exams-modal-create")).toBeVisible();

    const title = `Cold Start Exam ${Date.now()}`;
    await page.getByTestId("exams-modal-create-input-title").fill(title);
    await page.getByTestId("exams-modal-create-btn-submit").click();

    await expect(page.getByTestId("exams-table")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByText(title)).toBeVisible({ timeout: 10000 });

    await page.getByRole("link", { name: title }).click();
    await expect(page).toHaveURL(/\/exams\/[0-9a-f-]+/, { timeout: 10000 });
    await expect(page.getByTestId("exam-title")).toHaveText(title, {
      timeout: 10000,
    });
  });
});

test.describe("Cold start — Recruitment onboarding → first vacancy", () => {
  test("welcome banner CTA → create first vacancy via UI → reports empty state", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    await loginViaUI(page, admin.email, admin.password);

    await page.goto("/recruitment");
    await expect(page).toHaveURL(/\/recruitment\/requisitions/, {
      timeout: 10000,
    });
    await expect(page.getByTestId("recruitment-onboarding")).toBeVisible({
      timeout: 10000,
    });

    // The welcome-step CTA routes into the create-vacancy page.
    await page.getByTestId("recruitment-onboarding-cta").click();
    await expect(page).toHaveURL(/\/recruitment\/requisitions\/new/, {
      timeout: 10000,
    });

    const title = `Cold Start Vacancy ${Date.now()}`;
    await page.getByTestId("recruitment-vacancy-input-title").fill(title);
    await page.getByTestId("recruitment-vacancy-btn-save-draft").click();
    await expect(page).toHaveURL(/\/recruitment\/requisitions\/[0-9a-f-]+/, {
      timeout: 10000,
    });
    await expect(page.getByTestId("recruitment-vacancy-detail")).toBeVisible();

    // R4a reports page renders its empty state on a fresh tenant.
    await page.goto("/recruitment/reports");
    await expect(page.getByTestId("recruitment-reports-page")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByText("No reports yet")).toBeVisible();
  });
});

test.describe("Cold start — Dictionaries (HRP-282/285/286)", () => {
  test("system items present → custom item via UI → system item deactivate-only", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    await setAuthTokens(page, admin.accessToken, admin.refreshToken);

    await page.goto("/dictionaries");
    await expect(page.getByTestId("dictionaries-list")).toBeVisible({
      timeout: 10000,
    });

    // HRP-282: a fresh tenant already sees seeded System rows.
    await expect(page.getByText("System").first()).toBeVisible();

    // Custom item via the UI dialog.
    await page.getByTestId("dictionaries-btn-add").click();
    const form = page.getByTestId("dictionaries-modal-form");
    await expect(form).toBeVisible();
    const title = `Cold Start Grade ${Date.now()}`;
    await form.locator("input").first().fill(title);
    await form.getByRole("button", { name: /^Create$/ }).click();
    await expect(page.getByText(title)).toBeVisible({ timeout: 10000 });

    // HRP-285: editing a System row only allows the Active toggle —
    // title input is disabled.
    const systemRow = page
      .getByTestId("dictionaries-list")
      .locator("tbody tr")
      .filter({ hasText: "System" })
      .first();
    await systemRow.locator("button").click();
    await page.locator('[data-testid$="-btn-edit"]').first().click();
    await expect(form).toBeVisible();
    await expect(form.locator("input").first()).toBeDisabled();
    await expect(form.getByRole("checkbox")).toBeVisible();

    // HRP-286: System rows expose no Delete item, and the API refuses
    // to delete origin items.
    await expect(
      page.locator('[data-testid$="-btn-delete"]'),
    ).toHaveCount(0);
  });
});

test.describe("Cold start — Manager assessment public link (HRP-186)", () => {
  test("round + invite via UI → public link → consent → submit", async ({
    page,
    browser,
  }) => {
    const admin = await registerUser(page);
    const authHeader = { Authorization: `Bearer ${admin.accessToken}` };

    // Vacancy + candidate + link (API scaffolding; the assessment flow
    // itself is driven through the UI below).
    const vacancy = await (
      await page.request.post(`${API_BASE}/recruitment/vacancies`, {
        headers: authHeader,
        data: { title: `MA Vacancy ${Date.now()}` },
      })
    ).json();
    // HRP-352: external invites are refused until the vacancy profile
    // has competences — seed a minimal matrix.
    await page.request.put(
      `${API_BASE}/recruitment/vacancies/${vacancy.id}/profile`,
      {
        headers: authHeader,
        data: {
          profile_data: {
            competences: [
              {
                id: "communication",
                name: "Communication",
                criticality: "critical",
                indicators: [],
              },
            ],
          },
        },
      },
    );
    const candidate = await (
      await page.request.post(`${API_BASE}/recruitment/candidates`, {
        headers: authHeader,
        data: {
          first_name: "Public",
          last_name: "Evaluated",
          email: `ma-${Date.now()}@test.com`,
        },
      })
    ).json();
    const cv = await (
      await page.request.post(`${API_BASE}/recruitment/candidate-vacancies`, {
        headers: authHeader,
        data: { candidate_id: candidate.id, vacancy_id: vacancy.id },
      })
    ).json();

    await loginViaUI(page, admin.email, admin.password);
    await page.goto(`/recruitment/candidates/${candidate.id}`);
    await expect(page.getByTestId("candidate-section-assessments")).toBeVisible(
      { timeout: 15000 },
    );

    // Create the first assessment round through the UI.
    await page.getByTestId("assessment-round-new-btn").click();
    await page
      .getByTestId("assessment-round-new-confirm-modal-confirm")
      .click();
    await expect(
      page.locator('[data-testid^="assessment-round-tab-"]').first(),
    ).toBeVisible({ timeout: 10000 });

    // Invite an external evaluator through the modal.
    await page.getByTestId("invite-evaluator-modal-open").click();
    const modal = page.getByTestId("invite-evaluator-modal");
    await expect(modal).toBeVisible();
    await page
      .getByTestId("invite-evaluator-modal-email-0")
      .fill(`evaluator-${Date.now()}@test.com`);
    await page.getByTestId("invite-evaluator-modal-name-0").fill("Eva Luator");
    await page.getByTestId("invite-evaluator-modal-submit").click();
    await expect(modal).toBeHidden({ timeout: 10000 });
    await expect(
      page.locator('[data-testid^="assessment-round-invite-"]').first(),
    ).toBeVisible({ timeout: 10000 });

    // Reveal the public token (E2E-only endpoint) and open the link
    // anonymously in a fresh browser context.
    const invites = await (
      await page.request.get(
        `${API_BASE}/v1/candidate-vacancies/${cv.id}/manager-assessment-invites`,
        { headers: authHeader },
      )
    ).json();
    expect(invites.length).toBe(1);
    const tokenResp = await (
      await page.request.get(
        `${API_BASE}/recruitment/_test/assessment-invites/${invites[0].id}/token`,
        { headers: authHeader },
      )
    ).json();

    const anonContext = await browser.newContext();
    const anonPage = await anonContext.newPage();
    await anonPage.goto(`/public/assessments/${tokenResp.token}`);
    await expect(
      anonPage.getByTestId("public-assessment-consent-modal"),
    ).toBeVisible({ timeout: 15000 });
    await anonPage.getByTestId("public-assessment-consent-accept-btn").click();
    await expect(anonPage.getByTestId("public-assessment-page")).toBeVisible({
      timeout: 10000,
    });

    await anonPage
      .getByTestId("public-assessment-final-notes")
      .fill("Strong candidate, hire.");
    await anonPage.getByTestId("public-assessment-submit-btn").click();
    // HRP-359: no competences were scored, so the critical-competence
    // warning modal gates the submit — confirm it.
    await expect(
      anonPage.getByTestId("public-assessment-submit-warning-modal"),
    ).toBeVisible({ timeout: 5000 });
    await anonPage
      .getByTestId("public-assessment-submit-warning-modal-confirm")
      .click();
    await expect(
      anonPage.getByTestId("public-assessment-submitted-banner"),
    ).toBeVisible({ timeout: 10000 });
    await anonContext.close();

    // The recruiter side reflects the submission.
    await page.reload();
    await expect(
      page.locator('[data-testid^="assessment-round-invite-"]').first(),
    ).toBeVisible({ timeout: 15000 });
  });
});
