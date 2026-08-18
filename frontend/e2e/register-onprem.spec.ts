import { test, expect, Page } from "./fixtures";

import { uniqueEmail } from "./helpers";

/**
 * HRP-390: self-hosted (onprem) entry surface.
 *
 * Requires backend AND frontend AND the Playwright process running with
 * DEPLOYMENT_MODE=onprem (the community CI default) and no email provider
 * configured on the backend (RESEND_API_KEY= SMTP_HOST=), so
 * POST /api/auth/register auto-verifies the account and the UI logs the
 * user straight in. The gate below is opt-in on purpose: with
 * DEPLOYMENT_MODE unset (e.g. a local run against a saas-mode stack) the
 * frontend renders the moderated funnel and these tests would false-fail —
 * covered by signup-moderation.spec.ts in saas mode instead.
 */
test.skip(
  process.env.DEPLOYMENT_MODE !== "onprem",
  "requires the whole stack (backend, frontend, runner) in onprem mode",
);

async function registerViaUI(page: Page, email: string, password: string) {
  await page.goto("/register");
  await page.getByTestId("register-input-firstname").fill("Self");
  await page.getByTestId("register-input-lastname").fill("Hosted");
  await page
    .getByTestId("register-input-company")
    .fill(`SelfHosted Corp ${Date.now()}`);
  await page.getByTestId("register-input-email").fill(email);
  await page.getByTestId("register-input-password").fill(password);
  await page.getByTestId("register-btn-submit").click();
}

test.describe("Self-hosted entry", () => {
  test("root redirects to /login when logged out", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/login/, { timeout: 10000 });
    await expect(page.getByTestId("login-form")).toBeVisible({
      timeout: 10000,
    });
  });

  test("register page renders the self-serve form", async ({ page }) => {
    await page.goto("/register");
    await expect(page.getByTestId("register-form")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("register-input-firstname")).toBeVisible();
    await expect(page.getByTestId("register-input-lastname")).toBeVisible();
    await expect(page.getByTestId("register-input-company")).toBeVisible();
    await expect(page.getByTestId("register-input-email")).toBeVisible();
    await expect(page.getByTestId("register-input-password")).toBeVisible();
    // The moderated funnel's role selector must not leak into onprem.
    await expect(page.getByTestId("register-select-role")).toHaveCount(0);
  });

  test("self-serve registration lands in the app without email verification", async ({
    page,
  }) => {
    await registerViaUI(page, uniqueEmail(), "selfhost123");

    // Auto-verify + auto-login: no verify-email detour, straight to the
    // app — a fresh tenant admin gets the first-login onboarding wizard.
    await expect(page).toHaveURL(/\/(onboarding|dashboard)/, {
      timeout: 15000,
    });
  });

  test("registered account can sign back in", async ({ page }) => {
    const email = uniqueEmail();
    const password = "selfhost123";
    await registerViaUI(page, email, password);
    await expect(page).toHaveURL(/\/(onboarding|dashboard)/, {
      timeout: 15000,
    });

    // Fresh session: clear tokens, then sign in through the login form.
    await page.evaluate(() => {
      localStorage.clear();
      document.cookie =
        "has_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
    });
    await page.goto("/login");
    await page.getByTestId("login-input-email").fill(email);
    await page.getByTestId("login-input-password").fill(password);
    await page.getByTestId("login-btn-submit").click();
    await expect(page).toHaveURL(/\/(onboarding|dashboard)/, {
      timeout: 10000,
    });
  });
});
