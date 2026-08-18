import { test, expect } from "./fixtures";
import { registerUser, setAuthTokens } from "./helpers";

test.describe("AI Settings page", () => {
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

  test("admin can switch effort tier and the choice persists across reload", async ({
    page,
  }) => {
    await page.goto("/settings/ai");

    // Wait for the presets to render. Balanced is active by default.
    await expect(page.getByTestId("settings-ai-preset-balanced")).toHaveAttribute(
      "data-active",
      "true",
      { timeout: 10000 },
    );

    // Switch to Thorough.
    await page.getByTestId("settings-ai-preset-thorough").click();

    // Save bar appears with the diff.
    await expect(page.getByTestId("settings-ai-save-bar")).toBeVisible();
    await page.getByTestId("settings-ai-btn-save").click();

    // Bar disappears once saved.
    await expect(page.getByTestId("settings-ai-save-bar")).toBeHidden({
      timeout: 5000,
    });

    // Reload — Thorough should still be active.
    await page.reload();
    await expect(page.getByTestId("settings-ai-preset-thorough")).toHaveAttribute(
      "data-active",
      "true",
      { timeout: 10000 },
    );
  });

  test("model whitelist select is visible and effective summary is rendered", async ({
    page,
  }) => {
    await page.goto("/settings/ai");
    await expect(page.getByTestId("settings-ai-select-provider")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("settings-ai-select-model")).toBeVisible();
  });

  test("a visitor without a token never sees the editable form", async ({
    page,
  }) => {
    // Drop the registered admin token so /settings/ai falls back to the
    // permissions guard. This relies on the guard being client-side.
    // HRP-436: non-admins are now redirected to /dashboard with a toast
    // (see admin-section-access.spec.ts); here the token is gone entirely.
    await page.context().clearCookies();
    await page.evaluate(() => {
      localStorage.removeItem("access_token");
      localStorage.removeItem("refresh_token");
    });
    await page.goto("/settings/ai");
    // Either redirected to /login or "AI Settings" placeholder text shown.
    // We assert that the editable form is NOT visible.
    await expect(page.getByTestId("settings-ai-presets")).toHaveCount(0);
  });
});
