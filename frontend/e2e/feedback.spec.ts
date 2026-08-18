/**
 * HRP-586 — "?" feedback widget in the app header.
 *
 * The submission is fanned out to the team chat by the enterprise
 * handler; with no Slack configured (CI) the endpoint still answers 204,
 * so this spec covers the full user path on both deployment modes.
 */
import { test, expect } from "./fixtures";
import { registerUser, setAuthTokens } from "./helpers";

test.describe("Feedback widget", () => {
  let accessToken: string;
  let refreshToken: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const creds = await registerUser(page);
    accessToken = creds.accessToken;
    refreshToken = creds.refreshToken;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("sends a rating and a comment", async ({ page }) => {
    await page.goto("/dashboard");
    await page.getByTestId("header-btn-feedback").click();
    await expect(page.getByTestId("feedback-dialog")).toBeVisible({
      timeout: 10000,
    });

    // Nothing filled in yet — the submit button mirrors the backend guard.
    await expect(page.getByTestId("feedback-submit")).toBeDisabled();

    await page.getByTestId("feedback-rating-up").click();
    await page.getByTestId("feedback-input-message").fill("Reports are useful");
    await page.getByTestId("feedback-submit").click();

    await expect(page.getByTestId("feedback-dialog")).toBeHidden({
      timeout: 10000,
    });
  });
});
