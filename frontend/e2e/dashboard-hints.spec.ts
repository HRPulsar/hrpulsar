import { test, expect, type Page } from "./fixtures";

import {
  API_BASE,
  createDictionaryItem,
  createPosition,
  provisionTenantMember,
  setAuthTokens,
  setupFullTenant,
} from "./helpers";

/**
 * HRP-659 — the question marks next to the dashboard headings and stages.
 *
 * The labels stay as the customer worded them, so what a number actually
 * counts lives behind a hint. A hint that renders but never opens is the
 * same bug as no hint at all, so every case below asserts the text
 * appears — once by click (the only path that works on touch) and once by
 * hover (the pointer path).
 *
 * Both dashboards are covered: the company loop an admin/manager sees and
 * the personal loop the frontend falls back to when `/analytics/dev-loop`
 * answers 403.
 */

/** Every hint the company dashboard owns. */
const ADMIN_HINTS = [
  "dashboard-hint-title",
  "dashboard-hint-queue",
  "dashboard-hint-cycle",
  "dashboard-loop-stage-hint-assessed",
  "dashboard-loop-stage-hint-gaps",
  "dashboard-loop-stage-hint-developing",
  "dashboard-loop-stage-hint-closed",
];

/** Every hint the personal dashboard owns. */
const MY_HINTS = [
  "dashboard-hint-title",
  "dashboard-my-hint-queue",
  "dashboard-my-hint-strengths",
  "dashboard-my-hint-growth",
  "dashboard-my-stage-hint-assessed",
  "dashboard-my-stage-hint-gaps",
  "dashboard-my-stage-hint-developing",
  "dashboard-my-stage-hint-closed",
];

/**
 * The explanation the trigger promises, taken off the DOM rather than out
 * of the message catalogue — the spec must not pin translations.
 *
 * `Hint` builds the aria-label as `${title}. ${text}` when it was given a
 * title and as `${text}` when it was not; the popup renders the title and
 * the text as separate nodes. Dropping everything up to the first `". "`
 * therefore yields a string the popup contains in both shapes.
 */
async function hintBodyText(page: Page, testId: string): Promise<string> {
  const label = await page.getByTestId(testId).getAttribute("aria-label");
  expect(label, `${testId} must carry its explanation in aria-label`).toBeTruthy();
  const [, ...rest] = (label as string).split(". ");
  return rest.length > 0 ? rest.join(". ") : (label as string);
}

/** Open one hint the way the argument says and assert the text shows up. */
async function expectHintOpens(
  page: Page,
  testId: string,
  how: "click" | "hover",
): Promise<void> {
  const body = await hintBodyText(page, testId);
  const trigger = page.getByTestId(testId);
  await trigger.scrollIntoViewIfNeeded();
  if (how === "click") await trigger.click();
  else await trigger.hover();

  // Base UI renders the popup into a portal without an ARIA role, so the
  // component's own `data-slot` is the structural handle here — the text
  // itself still comes off the trigger, never out of a message catalogue.
  const tooltip = page
    .locator('[data-slot="tooltip-content"]')
    .filter({ hasText: body });
  await expect(tooltip).toBeVisible({ timeout: 5000 });

  // Leave the hint closed so the next case starts from a clean state:
  // a click-opened tooltip is sticky until the toggle is pressed again.
  if (how === "click") await trigger.click();
  await page.mouse.move(0, 0);
  await expect(tooltip).toHaveCount(0, { timeout: 5000 });
}

test.describe("HRP-659 — company dashboard hints", () => {
  test("every heading and stage hint renders and opens", async ({ page }) => {
    const setup = await setupFullTenant(page);
    await setAuthTokens(page, setup.accessToken, setup.refreshToken);
    await page.goto("/dashboard");

    // The loop hero is what carries the stage hints — wait for it before
    // asserting on any of them.
    await expect(page.getByTestId("dashboard-loop-stage-assessed")).toBeVisible({
      timeout: 15000,
    });

    for (const testId of ADMIN_HINTS) {
      await expect(page.getByTestId(testId), testId).toBeVisible();
    }

    await expectHintOpens(page, "dashboard-hint-title", "click");
    await expectHintOpens(page, "dashboard-loop-stage-hint-gaps", "hover");
    await expectHintOpens(page, "dashboard-hint-cycle", "click");
  });
});

test.describe("HRP-659 — personal dashboard hints", () => {
  test("every personal heading and stage hint renders and opens", async ({
    page,
  }) => {
    const setup = await setupFullTenant(page);
    const opts = { page, accessToken: setup.accessToken };
    const headers = { Authorization: `Bearer ${setup.accessToken}` };
    const stamp = Date.now().toString(36);

    // The Growth card only renders when the person's position names both a
    // specialization and a grade AND that specialization's ladder has a
    // grade above the current one — otherwise `my-loop.growth` is null and
    // `dashboard-my-hint-growth` would be missing for a reason that has
    // nothing to do with HRP-659.
    const spec = await createDictionaryItem(
      opts,
      "specialization",
      `Hints-spec-${stamp}`,
    );
    const junior = await createDictionaryItem(opts, "grade", `Hints-g1-${stamp}`);
    const senior = await createDictionaryItem(opts, "grade", `Hints-g2-${stamp}`);
    for (const [grade, sortIndex] of [
      [junior, 0],
      [senior, 1],
    ] as const) {
      const chain = await page.request.post(`${API_BASE}/grade-system/chains`, {
        headers,
        data: {
          grade_id: grade.id,
          specialization_id: spec.id,
          sort_index: sortIndex,
          competence_links: [],
        },
      });
      expect(chain.ok(), `chain create failed: ${await chain.text()}`).toBeTruthy();
    }

    const position = await createPosition(opts, `Hints-pos-${stamp}`, {
      specialization_id: spec.id,
      grade_id: junior.id,
      division_id: setup.divisionId,
    });

    const member = await provisionTenantMember(opts, {
      roleCode: "employee",
      positionId: position.id,
      firstName: "Hints",
      lastName: "Member",
    });
    expect(member.employeeId, "member must own an employee row").toBeTruthy();

    await setAuthTokens(page, member.accessToken, member.refreshToken);
    await page.goto("/dashboard");

    // The personal hero replaces the company one for this role.
    await expect(page.getByTestId("dashboard-my-stage-assessed")).toBeVisible({
      timeout: 20000,
    });
    await expect(page.getByTestId("dashboard-loop-stage-assessed")).toHaveCount(0);

    for (const testId of MY_HINTS) {
      await expect(page.getByTestId(testId), testId).toBeVisible();
    }

    await expectHintOpens(page, "dashboard-my-hint-strengths", "click");
    await expectHintOpens(page, "dashboard-my-stage-hint-closed", "hover");
    await expectHintOpens(page, "dashboard-my-hint-growth", "click");
  });
});
