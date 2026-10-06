/**
 * HRP-989 — the candidate GDPR page is reachable from the interface:
 * from the recruitment settings and from the candidate card.
 *
 * Requires E2E_MODE=true on the backend (auto-register).
 */
import { expect, test } from "@playwright/test";
import { API_BASE, registerUser, setAuthTokens, uniqueEmail } from "../helpers";

test.describe("GDPR page links (HRP-989)", () => {
  test("opens from the settings and from the candidate card", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const lastName = `Gdpr${Date.now()}`;
    const candidateResp = await page.request.post(
      `${API_BASE}/recruitment/candidates`,
      {
        headers: { Authorization: `Bearer ${admin.accessToken}` },
        data: { first_name: "Greta", last_name: lastName, email: uniqueEmail() },
      },
    );
    expect(candidateResp.ok()).toBeTruthy();
    const candidate = await candidateResp.json();
    await setAuthTokens(page, admin.accessToken, admin.refreshToken);

    // From the settings: the tile, then the candidate search.
    await page.goto("/recruitment/settings");
    await page
      .getByTestId("rec-settings-card-gdpr")
      .getByRole("link")
      .click();
    await expect(page.getByTestId("recruitment-gdpr-page")).toBeVisible({
      timeout: 15000,
    });
    await page.getByTestId("recruitment-gdpr-search-input").fill(lastName);
    await page.getByTestId("recruitment-gdpr-search-btn").click();
    await page.getByTestId(`recruitment-gdpr-candidate-${candidate.id}`).click();
    await expect(page.getByTestId("candidate-gdpr-page")).toBeVisible({
      timeout: 15000,
    });

    // From the candidate card.
    await page.goto(`/recruitment/candidates/${candidate.id}`);
    await page.getByTestId("candidate-card-gdpr-link").click();
    await expect(page).toHaveURL(
      new RegExp(`/recruitment/candidates/${candidate.id}/gdpr$`),
    );
    await expect(page.getByTestId("candidate-gdpr-page")).toBeVisible({
      timeout: 15000,
    });
  });
});
