import { test, expect } from "./fixtures";
import { API_BASE, provisionTenantMember, registerUser, setAuthTokens } from "./helpers";

/**
 * HRP-854 (review 2.0) - the access dialog holds two people pickers, the
 * accountable owner and the employee rules, each with its own search box.
 * Typing in one used to filter the other as well. vitest cannot open the
 * base-ui Select that switches the rule picker to "employee", so the
 * separate-search contract lives here.
 */
test.describe("Coverage - access dialog picker search", () => {
  test("the owner search and the rule search filter their own lists only", async ({ page }) => {
    const admin = await registerUser(page);
    const headers = { Authorization: `Bearer ${admin.accessToken}` };

    const created = await page.request.post(`${API_BASE}/work/containers`, {
      headers,
      data: { type: "process", description: "E2E fixture", title: `Picker search ${Date.now()}` },
    });
    expect(created.ok()).toBeTruthy();
    const container = await created.json();

    // A division makes the invitation create an employee row - only
    // employees appear in the dialog's people pickers.
    const divResp = await page.request.post(`${API_BASE}/divisions`, {
      headers,
      data: { name: `Picker div ${Date.now()}` },
    });
    expect(divResp.ok()).toBeTruthy();
    const division = await divResp.json();

    await provisionTenantMember(
      { page, accessToken: admin.accessToken },
      { roleCode: "employee", divisionId: division.id, firstName: "Astrid", lastName: "Ownerson" },
    );
    await provisionTenantMember(
      { page, accessToken: admin.accessToken },
      { roleCode: "employee", divisionId: division.id, firstName: "Boris", lastName: "Rulecki" },
    );

    await setAuthTokens(page, admin.accessToken, admin.refreshToken);
    await page.goto(`/coverage/${container.id}`);
    await page.getByTestId("coverage-btn-access").click();
    await expect(page.getByTestId("coverage-access-dialog")).toBeVisible();

    // Open both pickers: the owner list and the employee-rule list.
    await page.getByTestId("coverage-access-btn-owner").click();
    const ownerList = page.getByTestId("coverage-access-owner-list");
    await expect(ownerList.getByText("Astrid Ownerson")).toBeVisible({ timeout: 10000 });

    // base-ui Select: click the trigger, then the option.
    await page.getByTestId("coverage-access-add-kind").click();
    await page.getByTestId("coverage-access-add-kind-employee").click();
    const ruleList = page.getByTestId("coverage-access-add-employee");
    await expect(ruleList.getByText("Boris Rulecki")).toBeVisible({ timeout: 10000 });

    // Typing in the rule search narrows the rule list and leaves the owner
    // list alone.
    await page.getByTestId("coverage-access-add-employee-search").fill("Rulecki");
    await expect(ruleList.getByText("Boris Rulecki")).toBeVisible();
    await expect(ruleList.getByText("Astrid Ownerson")).toHaveCount(0);
    await expect(ownerList.getByText("Astrid Ownerson")).toBeVisible();
    await expect(ownerList.getByText("Boris Rulecki")).toBeVisible();

    // And the other way round: the owner search never touches the rule list.
    await page.getByTestId("coverage-access-owner-search").fill("Ownerson");
    await expect(ownerList.getByText("Astrid Ownerson")).toBeVisible();
    await expect(ownerList.getByText("Boris Rulecki")).toHaveCount(0);
    await expect(ruleList.getByText("Boris Rulecki")).toBeVisible();
    await expect(ruleList.getByText("Astrid Ownerson")).toHaveCount(0);
  });
});
