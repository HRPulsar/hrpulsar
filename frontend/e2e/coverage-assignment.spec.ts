import { test, expect } from "./fixtures";
import { API_BASE, createEmployee, registerUser, setAuthTokens } from "./helpers";

/**
 * HRP-809 — a step names the person who does it and the person who checks
 * and signs it.
 *
 * A judgement step (P6) on a fresh tenant is a gap. Assigning someone with
 * no matching skills closes it: the To do list empties, the Coverage row
 * shows the person with "No matching skills", and the formal step asks
 * who checks until an accountable person is named. Taking the executor off
 * brings the gap back.
 */
test.describe("Coverage — step assignment", () => {
  test("assign executor and accountable, then unassign", async ({ page }) => {
    const admin = await registerUser(page);
    await setAuthTokens(page, admin.accessToken, admin.refreshToken);
    const headers = { Authorization: `Bearer ${admin.accessToken}` };
    const employee = await createEmployee(
      { page, accessToken: admin.accessToken },
      admin.userId,
      "Credit controller",
    );

    const container = await (
      await page.request.post(`${API_BASE}/work/containers`, {
        headers,
        data: { type: "process", title: `Credit release ${Date.now()}` },
      })
    ).json();
    const step = await (
      await page.request.post(`${API_BASE}/work/containers/${container.id}/steps`, {
        headers,
        data: {
          title: "Decide on the credit hold",
          primitive_codes: ["P6"],
          responsibility: "formal",
        },
      })
    ).json();

    await page.goto(`/coverage/${container.id}`);
    await expect(page.getByTestId("coverage-match-list")).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId(`coverage-verdict-${step.id}`)).toHaveAttribute("data-verdict", "gap");

    // The executor, from the To do list.
    await page.getByTestId("coverage-tab-gaps").click();
    await page.getByTestId(`coverage-gap-row-${step.id}-btn-assign`).click();
    await expect(page.getByTestId("coverage-modal-assign")).toBeVisible();
    await page.getByTestId(`coverage-modal-assign-option-${employee.id}`).click();
    await expect(page.getByTestId("coverage-modal-assign")).toBeHidden();
    await expect(page.getByTestId("coverage-gaps-empty")).toBeVisible({ timeout: 10000 });

    await page.getByTestId("coverage-tab-coverage").click();
    await expect(page.getByTestId(`coverage-verdict-${step.id}`)).toHaveAttribute(
      "data-verdict",
      "human",
      { timeout: 10000 },
    );
    await expect(page.getByTestId(`coverage-executor-${step.id}`)).toBeVisible();
    await expect(page.getByTestId(`coverage-executor-unmatched-${step.id}`)).toBeVisible();
    await expect(page.getByTestId(`coverage-btn-hire-${step.id}`)).toHaveCount(0);

    // The accountable: asked for on a formal step until someone is named.
    const whoChecks = page.getByTestId(`coverage-btn-assign-accountable-${step.id}`);
    await expect(whoChecks).toHaveAttribute("data-needs", "true");
    await whoChecks.click();
    await page.getByTestId(`coverage-modal-assign-option-${employee.id}`).click();
    await expect(page.getByTestId(`coverage-accountable-${step.id}`)).toBeVisible({ timeout: 10000 });
    await expect(whoChecks).not.toHaveAttribute("data-needs");

    // Taking the executor off brings the gap back.
    await page.getByTestId(`coverage-btn-assign-executor-${step.id}`).click();
    await page.getByTestId("coverage-modal-assign-btn-clear").click();
    await expect(page.getByTestId(`coverage-verdict-${step.id}`)).toHaveAttribute(
      "data-verdict",
      "gap",
      { timeout: 10000 },
    );
    await expect(page.getByTestId(`coverage-executor-${step.id}`)).toHaveCount(0);
    await page.getByTestId("coverage-tab-gaps").click();
    await expect(page.getByTestId(`coverage-gap-row-${step.id}`)).toBeVisible({ timeout: 10000 });
  });
});
