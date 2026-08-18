import { test, expect } from "./fixtures";

/**
 * HRP-264 (M6): end-to-end smoke for the moderated signup flow.
 *
 * Covers the visitor-facing path only — submit /register, click the
 * verify link, land on the waiting screen. The Slack moderation +
 * magic-login portion runs server-side from a Bolt listener that
 * cannot be exercised from Playwright in CI; those legs are covered
 * by backend tests (`test_signup_approve_reject.py`).
 *
 * Requires the backend to run with E2E_MODE=true; the verify-token is
 * read from the JSON response of POST /api/signup-request which we
 * intercept via the dev exposure on the SignupRequest row.
 */

const API_BASE = "http://localhost:8100/api";

import { SAAS_E2E } from "./helpers";

// HRP-390: /register renders the moderated funnel only in saas mode;
// onprem serves the self-serve form (see register-onprem.spec.ts).
test.skip(!SAAS_E2E, "moderated signup funnel only renders in saas mode");

test.describe("Signup moderation", () => {
  test("submits /register and shows waiting screen on verify", async ({ page }) => {
    const email = `e2e-signup-${Date.now()}@test.com`;

    await page.goto("/register");
    await page.getByTestId("register-input-firstname").fill("E2E");
    await page.getByTestId("register-input-email").fill(email);
    await page
      .getByTestId("register-select-role")
      .selectOption("founder");
    await page.getByTestId("register-input-company").fill("Acme E2E");

    const responsePromise = page.waitForResponse((res) =>
      res.url().endsWith("/api/signup-request") &&
      res.request().method() === "POST",
    );
    await page.getByTestId("register-btn-submit").click();
    const response = await responsePromise;
    expect(response.status()).toBe(201);

    // Lands on the "check your email" waiting screen.
    await expect(page).toHaveURL(/\/verify-email\?email=/);
    await expect(page.getByTestId("verify-email-target")).toHaveText(email);
  });

  test("verifies the email and shows the moderation-waiting copy", async ({
    page,
    request,
  }) => {
    const email = `e2e-verify-${Date.now()}@test.com`;

    // Create the signup via the public API.
    const createRes = await request.post(`${API_BASE}/signup-request`, {
      data: {
        email,
        first_name: "Verify",
        last_name: "Flow",
        company_name: "Verify Co",
        role: "founder",
      },
    });
    expect(createRes.status()).toBe(201);

    // The backend exposes a dev helper under E2E_MODE for retrieving the
    // verify token without an inbox. Skip the test if it's not wired in
    // this environment.
    const tokenRes = await request.get(
      `${API_BASE}/auth/dev/signup-verify-token?email=${encodeURIComponent(email)}`,
    );
    test.skip(
      tokenRes.status() === 404,
      "Backend dev signup-verify-token endpoint not available — wire it up to enable this leg.",
    );
    const { token } = (await tokenRes.json()) as { token: string };

    await page.goto(`/verify-email?token=${token}&flow=signup`);
    await expect(page.getByTestId("verify-signup-waiting")).toBeVisible();
  });
});
