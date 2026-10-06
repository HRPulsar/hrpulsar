/**
 * HRP-979 — the candidate withdraws consent on the public link, and the
 * candidate card shows it with the AI actions held back.
 *
 * Requires E2E_MODE=true on the backend (auto-register and the consent
 * seed seam).
 */
import { expect, test } from "@playwright/test";
import {
  API_BASE,
  registerUser,
  setAuthTokens,
  signCandidateConsent,
  uniqueEmail,
} from "../helpers";

test.describe("Candidate consent withdrawal (HRP-979)", () => {
  test("withdrawn on the public page, shown on the candidate card", async ({
    page,
    browser,
  }) => {
    const admin = await registerUser(page);
    const headers = { Authorization: `Bearer ${admin.accessToken}` };
    const vacancy = await (
      await page.request.post(`${API_BASE}/recruitment/vacancies`, {
        headers,
        data: { title: `Consent ${Date.now()}` },
      })
    ).json();
    const candidate = await (
      await page.request.post(`${API_BASE}/recruitment/candidates`, {
        headers,
        data: {
          first_name: "Wanda",
          last_name: `Withdraw ${Date.now()}`,
          email: uniqueEmail(),
        },
      })
    ).json();
    const cv = await page.request.post(
      `${API_BASE}/recruitment/candidate-vacancies`,
      { headers, data: { candidate_id: candidate.id, vacancy_id: vacancy.id } },
    );
    expect(cv.ok()).toBeTruthy();
    const token = await signCandidateConsent(
      page,
      admin.accessToken,
      candidate.id,
    );

    const anonContext = await browser.newContext();
    const anonPage = await anonContext.newPage();
    await anonPage.goto(`/recruitment/consent/${token}`);
    await expect(anonPage.getByTestId("consent-page-signed")).toBeVisible({
      timeout: 15000,
    });
    await anonPage.getByTestId("consent-page-btn-withdraw").click();
    await anonPage.getByTestId("consent-page-withdraw-confirm-btn").click();
    await expect(anonPage.getByTestId("consent-page-revoked")).toBeVisible();
    // The link stays withdrawn on a reload.
    await anonPage.reload();
    await expect(anonPage.getByTestId("consent-page-revoked")).toBeVisible({
      timeout: 15000,
    });
    await anonContext.close();

    await setAuthTokens(page, admin.accessToken, admin.refreshToken);
    await page.goto(`/recruitment/candidates/${candidate.id}`);
    await expect(
      page.getByTestId("recruitment-candidate-interviews-consent-banner"),
    ).toContainText("withdrew consent", { timeout: 15000 });
    await expect(
      page.getByTestId("recruitment-interview-questions-consent-hint"),
    ).toBeVisible();
  });
});
