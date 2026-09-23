import { test, expect } from "./fixtures";
import {
  API_BASE,
  createDivision,
  createEmployee,
  provisionTenantMember,
  registerUser,
  setAuthTokens,
} from "./helpers";

/**
 * HRP-864 — what a Coverage row lets the reader follow.
 *
 * A step title in a summary bucket scrolls to the step's row; the agent type
 * says what an agent of that type does; the executor's name opens the
 * employee card. A colleague with the plain employee role, who sees the
 * process because a step names them as accountable, follows the same link
 * and gets the card the employee module gives them - not an error.
 */
test.describe("Coverage — row links", () => {
  test("step jump, agent type popover, employee links", async ({ page, browser }) => {
    const admin = await registerUser(page);
    await setAuthTokens(page, admin.accessToken, admin.refreshToken);
    const headers = { Authorization: `Bearer ${admin.accessToken}` };
    const controller = await createEmployee(
      { page, accessToken: admin.accessToken },
      admin.userId,
      "Credit controller",
    );
    // An invitation makes the employee row only when it carries a division.
    const division = await createDivision({ page, accessToken: admin.accessToken }, `Finance ${Date.now()}`);
    const colleague = await provisionTenantMember(
      { page, accessToken: admin.accessToken },
      { roleCode: "employee", divisionId: division.id, firstName: "Col", lastName: "League" },
    );
    expect(colleague.employeeId).toBeTruthy();

    const container = await (
      await page.request.post(`${API_BASE}/work/containers`, {
        headers,
        data: { type: "process", title: `Invoice run ${Date.now()}` },
      })
    ).json();
    const step = async (data: Record<string, unknown>) =>
      (
        await page.request.post(`${API_BASE}/work/containers/${container.id}/steps`, { headers, data })
      ).json();
    const extract = await step({ title: "Extract the invoice data", primitive_codes: ["P1"] });
    for (let i = 0; i < 8; i += 1) {
      await step({ title: `Filler step ${i}`, primitive_codes: ["P6"] });
    }
    const signed = await step({ title: "Release the payment", primitive_codes: ["P6"] });
    const assigned = await page.request.patch(`${API_BASE}/work/steps/${signed.id}`, {
      headers,
      data: { executor_employee_id: controller.id, accountable_employee_id: colleague.employeeId },
    });
    expect(assigned.ok()).toBeTruthy();

    await page.goto(`/coverage/${container.id}`);
    await expect(page.getByTestId("coverage-match-list")).toBeVisible({ timeout: 10000 });

    // (c) The agent type says what it does.
    await page.getByTestId(`coverage-pack-chip-${extract.id}`).click();
    await expect(page.getByTestId(`coverage-pack-chip-${extract.id}-popover`)).toContainText(
      "structured fields",
    );
    await page.keyboard.press("Escape");

    // (b) The last row is below the fold; its title in the bucket brings it up.
    const lastRow = page.getByTestId(`coverage-match-row-${signed.id}`);
    await expect(lastRow).not.toBeInViewport();
    await page.getByTestId(`coverage-summary-blocked-step-${signed.id}`).click();
    await expect(lastRow).toBeInViewport();
    await expect(lastRow).toBeFocused();

    // (a) The executor's name opens the card.
    await page.getByTestId(`coverage-link-executor-${signed.id}`).click();
    await expect(page).toHaveURL(new RegExp(`/employees/${controller.id}$`));
    await expect(page.getByTestId("employee-name")).toBeVisible({ timeout: 10000 });

    // The same link for a colleague who may not read the HR record.
    const context = await browser.newContext();
    try {
      const reader = await context.newPage();
      await setAuthTokens(reader, colleague.accessToken, colleague.refreshToken);
      await reader.goto(`/coverage/${container.id}`);
      await expect(reader.getByTestId("coverage-match-list")).toBeVisible({ timeout: 10000 });
      await expect(reader.getByTestId(`coverage-link-accountable-${signed.id}`)).toHaveAttribute(
        "href",
        `/employees/${colleague.employeeId}`,
      );
      await reader.getByTestId(`coverage-link-executor-${signed.id}`).click();
      await expect(reader).toHaveURL(new RegExp(`/employees/${controller.id}$`));
      // The directory card (HRP-623): who the person is, nothing to edit.
      await expect(reader.getByTestId("employee-name")).toBeVisible({ timeout: 10000 });
      await expect(reader.getByTestId("employee-btn-edit")).toHaveCount(0);
    } finally {
      await context.close();
    }
  });
});
