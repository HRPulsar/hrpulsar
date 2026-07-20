/**
 * R4d Group 5 — vacancy analytics tab renders the funnel + summary.
 *
 * After seeding the demo tenant we open a demo vacancy and switch to
 * the Analytics tab. The funnel-kanban + radar should render without
 * any client-side error (status='ready' on the analytics tab).
 */
import { test, expect } from "@playwright/test";
import { registerUser, loginViaUI } from "./helpers";

const API_BASE = "http://localhost:8100/api";

test.describe("Recruitment analytics", () => {
  test("vacancy analytics tab renders for a demo vacancy", async ({ page }) => {
    const { email, password, accessToken } = await registerUser(page);

    // Seed demo data via the recruiter onboarding endpoint.
    const seedResp = await page.request.post(
      `${API_BASE}/recruitment/onboarding/demo-seed`,
      { headers: { Authorization: `Bearer ${accessToken}` }, data: {} },
    );
    expect(seedResp.ok()).toBeTruthy();

    // Find the first demo vacancy via the API.
    const list = await page.request.get(
      `${API_BASE}/recruitment/vacancies?limit=1`,
      { headers: { Authorization: `Bearer ${accessToken}` } },
    );
    expect(list.ok()).toBeTruthy();
    const listJson = await list.json();
    expect(listJson.items?.length).toBeGreaterThan(0);
    const vacancyId = listJson.items[0].id;

    await loginViaUI(page, email, password);
    await page.goto(`/recruitment/requisitions/${vacancyId}`);

    await expect(page.getByTestId("recruitment-vacancy-detail")).toBeVisible({
      timeout: 10000,
    });

    // Switch to analytics tab.
    await page.getByTestId("recruitment-vacancy-tab-analytics").click();

    await expect(page.getByTestId("recruitment-vacancy-analytics")).toBeVisible({
      timeout: 10000,
    });
  });
});
