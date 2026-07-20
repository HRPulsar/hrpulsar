import { test, expect, Page } from "@playwright/test";

import { completeOnboarding, registerUser, setAuthTokens } from "./helpers";

/**
 * HRP-397: community/self-hosted builds must not call /api/billing/* at all —
 * the backend has no billing routes there, and every request shows up as a
 * 404 in the browser console of a fresh install.
 *
 * Requires the whole stack (backend, frontend, runner) in onprem mode; the
 * saas stack mounts billing routes and legitimately calls them.
 */
test.skip(
  process.env.DEPLOYMENT_MODE !== "onprem",
  "onprem-only: saas deployments legitimately call /api/billing/*",
);

function trackBillingRequests(page: Page): string[] {
  const seen: string[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/api/billing/")) seen.push(req.url());
  });
  return seen;
}

test.describe("No billing requests on-prem", () => {
  test("core pages fire zero /api/billing/* requests", async ({ page }) => {
    // Every dashboard navigation triggers a sidebar-wide RSC prefetch
    // (~16 ?_rsc= requests), so "networkidle" takes several seconds per
    // page and the 5-page sweep does not fit the default 30s budget.
    test.setTimeout(120_000);
    const billingRequests = trackBillingRequests(page);

    const reg = await registerUser(page);
    await completeOnboarding({ page, accessToken: reg.accessToken });
    await setAuthTokens(page, reg.accessToken, reg.refreshToken);

    // Pages that previously fired ungated billing lookups: positions
    // (cost-confirmation hook) and AI settings (/billing/costs), plus the
    // core surfaces from the smoke run (dashboard, company, competences).
    for (const path of [
      "/dashboard",
      "/company",
      "/company/positions",
      "/competences",
      "/settings/ai",
    ]) {
      await page.goto(path);
      // Give the page time to mount and fire its data requests. networkidle
      // can stay busy through the prefetch storm on slow runners — the
      // assertion below is the real check, so a noisy network is not a
      // failure by itself.
      await page
        .waitForLoadState("networkidle", { timeout: 15_000 })
        .catch(() => {});
    }

    expect(billingRequests).toEqual([]);
  });
});
