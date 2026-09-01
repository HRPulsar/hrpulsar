import { test, expect } from "./fixtures";

import {
  createDivision,
  createEmployee,
  createPosition,
  registerUser,
  seedBelowBarResult,
  setAuthTokens,
  setupCriteriaFixture,
} from "./helpers";

/**
 * HRP-660 — the employee card has to describe the person the same way the
 * list that linked to it does, and it has to be the place an action about
 * that person starts.
 *
 * The fixture is the smallest thing that produces a real gap: a position
 * whose grade-specialization requires one competence, and a done
 * assessment that scored that competence under the passing bar. That one
 * fact drives the `gaps_without_plan` badge on the card header, the gap
 * badge on the competence row, and the "no plan yet" state both Create
 * development plan entry points resolve.
 *
 * The closing assertion is the loop, not the artefact: once the plan
 * exists, `gaps_without_plan` gives way to `competence_gap` — a gap
 * somebody is working on is no longer an alarm, and the card must not keep
 * claiming otherwise.
 */
test.describe("HRP-660 — employee card issues and actions", () => {
  test("issues row, gap badge, and a plan created from the gap", async ({
    page,
  }) => {
    const reg = await registerUser(page);
    const opts = { page, accessToken: reg.accessToken };
    const stamp = Date.now().toString(36);

    const division = await createDivision(opts, "Engineering");
    // specialization + grade + published-shape competence + the chain that
    // ties them together; the Competences tab reads exactly this.
    const criteria = await setupCriteriaFixture(opts);
    const position = await createPosition(opts, `Card-pos-${stamp}`, {
      specialization_id: criteria.specializationId,
      grade_id: criteria.gradeId,
      division_id: division.id,
    });
    const employee = await createEmployee(
      opts,
      reg.userId,
      "E2E Tester",
      "2025-01-15",
      division.id,
      position.id,
    );
    await seedBelowBarResult(opts, employee.id, {
      competenceId: criteria.competenceId,
      skillLevelId: criteria.skillLevelId,
    });

    await setAuthTokens(page, reg.accessToken, reg.refreshToken);
    await page.goto(`/employees/${employee.id}`);
    await expect(page.getByTestId("employee-name")).toBeVisible({
      timeout: 15000,
    });

    // 1. The ISSUES row names the problem the list would name. Only the
    //    narrower code shows: `gaps_without_plan` implies `competence_gap`,
    //    and issues_by_employee() drops the broader one so the card does
    //    not say the same thing twice.
    const issues = page.getByTestId("employee-issues");
    await expect(issues).toBeVisible({ timeout: 15000 });
    await expect(
      issues.getByTestId("employee-issue-gaps_without_plan"),
    ).toBeVisible();
    await expect(
      issues.getByTestId("employee-issue-competence_gap"),
    ).toHaveCount(0);

    // 2. The Actions menu offers everything that starts about this person.
    await page.getByTestId("employee-btn-actions").click();
    await expect(
      page.getByTestId("employee-action-development-plan"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("employee-action-create-assessment"),
    ).toBeVisible();
    await expect(page.getByTestId("employee-action-add-event")).toBeVisible();
    await page.keyboard.press("Escape");

    // 3. The competence that caused the badge is marked as a gap in the
    //    tree, and the plan can be started right there.
    await page.getByTestId("employee-tab-competences").click();
    await expect(
      page.getByTestId("employee-competences-current-tree"),
    ).toBeVisible({ timeout: 15000 });
    await expect(
      page.getByTestId(`employee-competence-gap-${criteria.competenceId}`),
    ).toBeVisible({ timeout: 15000 });

    await page.getByTestId("employee-competences-btn-development-plan").click();
    // The dialog page consumes the deep link and its filter mirror strips
    // the query straight away, so asserting `?employee_id=` races the
    // strip. The URL only reliably says we moved to /development — the
    // prefill assertions below are the real check that the link landed.
    await expect(page).toHaveURL(/\/development(\?|$)/, { timeout: 15000 });

    // The deep link opens the dialog already pointed at this employee and
    // titles the plan after them — an empty title would mean the link was
    // read but the prefill never landed.
    const title = page.getByTestId("development-create-title");
    await expect(title).toBeVisible({ timeout: 15000 });
    await expect(title).not.toHaveValue("");
    await expect(page.getByTestId("development-create-employee")).toBeVisible();

    // The dialog footer is Cancel then Create; neither carries a testid,
    // so the submit is addressed structurally rather than by its label.
    // ponytail: swap to `development-create-btn-submit` once it exists.
    await page.locator('[data-slot="dialog-footer"] button').last().click();

    // Opened from the card, the create lands on the new plan.
    await expect(page).toHaveURL(/\/development\/[0-9a-f-]{36}$/, {
      timeout: 15000,
    });
    const planId = page.url().split("/").pop() as string;

    // 4. The plan is visible where plans live.
    await page.goto("/development");
    await expect(page.getByTestId(`development-row-${planId}`)).toBeVisible({
      timeout: 15000,
    });

    // 5. Back on the card: the gap is now being worked on, so the alarm
    //    badge gives way to the informational one — the same swap the
    //    employee list performs on the row that links here.
    await page.goto(`/employees/${employee.id}`);
    await expect(page.getByTestId("employee-issues")).toBeVisible({
      timeout: 15000,
    });
    await expect(
      page.getByTestId("employee-issue-competence_gap"),
    ).toBeVisible();
    await expect(
      page.getByTestId("employee-issue-gaps_without_plan"),
    ).toHaveCount(0);
  });
});
