import { test, expect } from "./fixtures";

/**
 * HRP-612 (wave 2): demo persona switcher.
 *
 * Starts a demo sandbox through the API (the marketing-side /demo entry
 * lives in the marketing repo), lands on the admin dashboard, switches
 * to the employee persona via the banner and expects the personal
 * dashboard, then switches back.
 *
 * Requires DEPLOYMENT_MODE=saas on backend + frontend + Playwright and
 * DEMO_ENABLED=true on the backend; skips gracefully when the demo
 * pool is unavailable (mirrors the marketing demo-cta spec).
 */

import { API_BASE, SAAS_E2E } from "./helpers";

test.skip(!SAAS_E2E, "demo sandbox endpoints only exist in saas mode");

test.describe("Demo persona switcher", () => {
  test("admin → employee → admin", async ({ page }) => {
    const start = await page.request.post(`${API_BASE}/demo/start`, {
      data: {},
    });
    // Graceful skip ONLY when the sandbox is disabled/full (503) — any
    // other failure (429 rate limit, 500) must fail loudly instead of
    // hiding a broken switch-view behind a green skip.
    test.skip(start.status() === 503, "demo sandbox disabled on this stack");
    expect(start.ok(), `demo/start failed: ${start.status()}`).toBeTruthy();
    const { access_token } = await start.json();

    // Mirror lib/demo.ts::persistDemoSession — seed storage from a loaded
    // page so the cookies ride along on the /dashboard request (the same
    // dance as helpers.setAuthTokens).
    await page.goto("/login");
    await page.evaluate((token: string) => {
      localStorage.setItem("access_token", token);
      localStorage.removeItem("refresh_token");
      document.cookie = "has_token=1; path=/; SameSite=Lax";
      document.cookie = "demo_session=1; path=/; SameSite=Lax";
    }, access_token);

    await page.goto("/dashboard");
    await expect(page.getByTestId("demo-banner")).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByTestId("dashboard-loop-stage-assessed")).toBeVisible({
      timeout: 15000,
    });

    // Switch to the employee persona → personal dashboard.
    await page.getByTestId("demo-banner-view-employee").click();
    await expect(page.getByTestId("dashboard-my-stage-assessed")).toBeVisible({
      timeout: 20000,
    });
    await expect(page.getByTestId("dashboard-my-strengths")).toBeVisible();
    await expect(page.getByTestId("dashboard-loop-stage-assessed")).toHaveCount(
      0,
    );

    // And back to the admin view.
    await page.getByTestId("demo-banner-view-admin").click();
    await expect(page.getByTestId("dashboard-loop-stage-assessed")).toBeVisible({
      timeout: 20000,
    });
  });
});
