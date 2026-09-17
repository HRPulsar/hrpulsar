import { test, expect } from "./fixtures";
import { API_BASE, provisionTenantMember, registerUser, setAuthTokens } from "./helpers";

/**
 * HRP-810 - a restricted process is invisible to a colleague: no Coverage
 * entry in the menu, and its link answers as if it did not exist. Once the
 * admin opens it to the whole company, the colleague sees the section and
 * reads the process without any edit or access button.
 */
test.describe("Coverage - process access", () => {
  test("restricted, then company-wide and read-only", async ({ page, browser }) => {
    const admin = await registerUser(page);
    const headers = { Authorization: `Bearer ${admin.accessToken}` };
    const stamp = Date.now();
    const title = `Severance ${stamp}`;

    const created = await page.request.post(`${API_BASE}/work/containers`, {
      headers,
      data: { type: "process", title },
    });
    expect(created.ok()).toBeTruthy();
    const container = await created.json();
    expect(container.visibility).toBe("restricted");

    const colleagueTokens = await provisionTenantMember(
      { page, accessToken: admin.accessToken },
      { roleCode: "employee", firstName: "Col", lastName: "League" },
    );

    // The context is the colleague's browser: closed in `finally`, or a
    // failing assertion leaks it for the rest of the worker.
    const colleagueContext = await browser.newContext();
    try {
      const colleague = await colleagueContext.newPage();
      await setAuthTokens(colleague, colleagueTokens.accessToken, colleagueTokens.refreshToken);
      await colleague.goto("/dashboard");
      // The talent market entry needs the user's roles: once it is there,
      // /auth/me has landed and a missing Coverage entry means something.
      await expect(colleague.getByTestId("sidebar-link-talent-market")).toBeVisible({
        timeout: 10000,
      });
      await expect(colleague.getByTestId("sidebar-link-coverage")).toHaveCount(0);
      const hidden = await colleague.request.get(`${API_BASE}/work/containers/${container.id}`, {
        headers: { Authorization: `Bearer ${colleagueTokens.accessToken}` },
      });
      expect(hidden.status()).toBe(404);

      // The admin opens it to the company from the access dialog.
      await setAuthTokens(page, admin.accessToken, admin.refreshToken);
      await page.goto(`/coverage/${container.id}`);
      await page.getByTestId("coverage-btn-access").click();
      await expect(page.getByTestId("coverage-access-dialog")).toBeVisible();
      await page.getByTestId("coverage-access-visibility-company").click();
      await page.getByTestId("coverage-access-btn-save").click();
      await expect(page.getByTestId("coverage-access-history").locator("li")).toHaveCount(1);

      await colleague.goto("/dashboard");
      await expect(colleague.getByTestId("sidebar-link-coverage")).toBeVisible({ timeout: 10000 });
      await colleague.goto(`/coverage/${container.id}`);
      await expect(colleague.getByTestId("coverage-detail-title")).toHaveText(title, {
        timeout: 10000,
      });
      await expect(colleague.getByTestId("coverage-btn-edit")).toHaveCount(0);
      await expect(colleague.getByTestId("coverage-btn-access")).toHaveCount(0);
    } finally {
      await colleagueContext.close();
    }
  });
});
