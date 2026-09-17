import { test, expect } from "./fixtures";
import { registerUser, setAuthTokens } from "./helpers";

/**
 * HRP-762 — Coverage, the manual path (REFACTOR_PLAN §7.6).
 *
 * Fresh tenant: empty state → describe a process → add a step by hand → set
 * its capabilities → the Coverage tab names an agent type for it → Accept
 * all closes the breakdown. No LLM anywhere on this path.
 *
 * W6 (§5.4): the page opens on Coverage, not on Steps - the answer first,
 * the list of steps second.
 */
test.describe("Coverage — manual breakdown", () => {
  test("empty state → new process → step → capabilities → verdict → accept all", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    await setAuthTokens(page, admin.accessToken, admin.refreshToken);

    await page.goto("/coverage");
    await expect(page.getByTestId("coverage-empty")).toBeVisible({ timeout: 10000 });
    await page.getByTestId("coverage-btn-create-process").click();
    await expect(page).toHaveURL(/\/coverage\/new/, { timeout: 10000 });

    const title = `Contract review ${Date.now()}`;
    await page.getByTestId("coverage-input-title").fill(title);
    await page
      .getByTestId("coverage-textarea-description")
      .fill("Legal reviews every counterparty contract before signature.");
    await page.getByTestId("coverage-btn-submit").click();
    await expect(page).toHaveURL(/\/coverage\/[0-9a-f-]+$/, { timeout: 10000 });
    await expect(page.getByTestId("coverage-detail-title")).toContainText(title);
    // Coverage is the tab that opens, and it says there is nothing to cover.
    await expect(page.getByTestId("coverage-coverage-empty")).toBeVisible();

    // A step by hand, then its capabilities through the picker.
    await page.getByTestId("coverage-tab-steps").click();
    await expect(page.getByTestId("coverage-steps-empty")).toBeVisible();
    await page.getByTestId("coverage-step-input-new").fill("Check the draft against the playbook");
    await page.getByTestId("coverage-step-btn-add").click();
    const row = page.locator('li[data-testid^="coverage-step-row-"]').first();
    await expect(row).toBeVisible({ timeout: 10000 });
    await expect(row.locator('[data-testid$="-state"]')).toBeVisible();
    await row.locator('[data-testid$="-btn-capabilities"]').click();
    await expect(page.getByTestId("coverage-modal-capabilities")).toBeVisible();
    await page.getByTestId("coverage-capability-option-P1").click();
    await page.getByTestId("coverage-capability-option-P2").click();
    await page.getByTestId("coverage-btn-capabilities-save").click();
    await expect(page.getByTestId("coverage-modal-capabilities")).toBeHidden();
    await expect(row.locator('[data-testid$="-capability-P1"]')).toBeVisible();
    await expect(row.locator('[data-testid$="-capability-P2"]')).toBeVisible();

    // Coverage tab: P1 + P2 fit the compliance_check pack → an agent covers
    // the step; the verdict is preliminary until the breakdown is accepted.
    await page.getByTestId("coverage-tab-coverage").click();
    const verdict = page.locator('[data-testid^="coverage-verdict-"]').first();
    await expect(verdict).toHaveAttribute("data-verdict", "agent", { timeout: 10000 });
    await expect(page.locator('[data-testid^="coverage-tentative-"]').first()).toBeVisible();
    await expect(page.locator('[data-testid^="coverage-agent-"]').first()).toBeVisible();

    // W6 (§5.3, §5.4): the headline plaque counts the quality of the step -
    // P1 is strong, P2 better than a person, and a step is only as good as
    // its weakest capability. One step is shorter than four, so the plaque
    // shows the count rather than a percentage.
    await expect(page.getByTestId("coverage-headline")).toBeVisible();
    await expect(page.getByTestId("coverage-quality-strong")).toHaveAttribute(
      "data-count",
      "1",
    );
    await expect(page.getByTestId("coverage-quality-no")).toHaveAttribute("data-count", "0");

    // W6 (§5.1): hours instead of the ordinal scales, and the ROI plaque
    // adds them up as soon as one step carries an estimate.
    await expect(page.getByTestId("coverage-roi-total")).toHaveCount(0);
    await page.getByTestId("coverage-btn-weights").click();
    const hoursEditor = page.getByTestId("coverage-weights-wizard");
    await expect(hoursEditor).toBeVisible();
    await hoursEditor.locator('[data-testid$="-input-hours"]').fill("2");
    await hoursEditor.locator('[data-testid$="-input-runs"]').fill("50");
    await page.getByTestId("coverage-btn-weights-save").click();
    await expect(hoursEditor).toBeHidden();
    await expect(page.getByTestId("coverage-roi-total")).toHaveAttribute(
      "data-hours",
      "100",
      { timeout: 10000 },
    );
    await expect(page.getByTestId("coverage-roi-moves")).toHaveAttribute("data-hours", "100");
    // No rate set: hours only, with a link to where the rate lives (§5.2).
    await expect(page.getByTestId("coverage-roi-rate")).toBeVisible();

    // Accept all: the container is active, nothing is preliminary any more.
    await page.getByTestId("coverage-tab-steps").click();
    await page.getByTestId("coverage-btn-accept-all").click();
    // The badge text is translated; the status is not.
    await expect(page.getByTestId("coverage-detail-status")).toHaveAttribute(
      "data-status",
      "active",
      { timeout: 10000 },
    );
    await expect(page.getByTestId("coverage-btn-accept-all")).toBeHidden();
    await page.getByTestId("coverage-tab-coverage").click();
    await expect(verdict).toHaveAttribute("data-verdict", "agent", { timeout: 10000 });
    await expect(page.locator('[data-testid^="coverage-tentative-"]')).toHaveCount(0);

    // The list page shows the breakdown; the empty state is gone.
    await page.goto("/coverage");
    await expect(page.getByTestId("coverage-table")).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(title)).toBeVisible();
    await expect(page.getByTestId("coverage-empty")).toBeHidden();
  });
});
