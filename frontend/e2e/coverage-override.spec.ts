import { test, expect, type Page } from "./fixtures";
import { API_BASE, registerUser, setAuthTokens } from "./helpers";

/**
 * HRP-863 — the company overrules the computed mode and agent type of a
 * step, right on its Coverage row.
 *
 * Five estimated steps: 400 h move to an agent, 200 h go to review, 300 h
 * stay with people. Moving a judgement step (200 h) to "automatable" by hand
 * moves its hours and the shares with it, marks the row "Set manually" and
 * makes it a step a skill can be written for; "Return to computed" undoes
 * all of it. A step no single agent type covers becomes an agent's once the
 * company names the type.
 */
const share = async (page: Page, bucket: string) =>
  Number(await page.getByTestId(`coverage-summary-${bucket}`).getAttribute("data-share"));

test.describe("Coverage — manual mode and agent type", () => {
  test("override, return to computed, name an agent type", async ({ page }) => {
    const admin = await registerUser(page);
    await setAuthTokens(page, admin.accessToken, admin.refreshToken);
    const headers = { Authorization: `Bearer ${admin.accessToken}` };

    const container = await (
      await page.request.post(`${API_BASE}/work/containers`, {
        headers,
        data: { type: "process", title: `Month-end close ${Date.now()}` },
      })
    ).json();
    const step = async (title: string, codes: string[], hours: number, runs: number) =>
      (
        await page.request.post(`${API_BASE}/work/containers/${container.id}/steps`, {
          headers,
          data: { title, primitive_codes: codes, hours_per_run: hours, runs_per_year: runs },
        })
      ).json();
    await step("Extract the invoice data", ["P1"], 8, 50);
    await step("Draft the summary", ["P1", "P5"], 2, 50);
    const judged = await step("Decide on the exceptions", ["P6"], 4, 50);
    await step("Approve the payment", ["P6"], 2, 50);
    const uncovered = await step("Build and word the report", ["P5", "P9"], 1, 100);

    await page.goto(`/coverage/${container.id}`);
    await expect(page.getByTestId("coverage-match-list")).toBeVisible({ timeout: 10000 });
    await expect.poll(() => share(page, "automatable")).toBeCloseTo(44.4, 1);
    await expect(page.getByTestId(`coverage-btn-get-skill-${judged.id}`)).toHaveCount(0);

    // The mode, from its badge.
    await page.getByTestId(`coverage-btn-change-mode-${judged.id}`).click();
    await page.getByTestId(`coverage-btn-change-mode-${judged.id}-option-automatable`).click();
    await expect(page.getByTestId("coverage-summary-automatable")).toContainText("Decide on the exceptions", {
      timeout: 10000,
    });
    await expect.poll(() => share(page, "automatable")).toBeCloseTo(66.7, 1);
    await expect.poll(() => share(page, "blocked")).toBeCloseTo(11.1, 1);
    await expect(page.getByTestId(`coverage-btn-get-skill-${judged.id}`)).toBeVisible();
    // The row does not argue with the company while no agent is named.
    await expect(page.getByTestId(`coverage-verdict-${judged.id}`)).toHaveCount(0);
    await expect(page.getByTestId(`coverage-quality-${judged.id}`)).toHaveCount(0);

    // Back to what the catalog says.
    await page.getByTestId(`coverage-btn-change-mode-${judged.id}`).click();
    await page.getByTestId(`coverage-btn-change-mode-${judged.id}-reset`).click();
    await expect.poll(() => share(page, "automatable")).toBeCloseTo(44.4, 1);
    await expect(page.getByTestId("coverage-summary-blocked")).toContainText("Decide on the exceptions");
    await expect(page.getByTestId(`coverage-quality-${judged.id}`)).toBeVisible();

    // The agent type, where no single one covered the step.
    await expect(page.getByTestId(`coverage-verdict-${uncovered.id}`)).toHaveAttribute("data-verdict", "gap");
    await page.getByTestId(`coverage-btn-change-pack-${uncovered.id}`).click();
    await page.getByTestId(`coverage-btn-change-pack-${uncovered.id}-option-drafting`).click();
    await expect(page.getByTestId(`coverage-verdict-${uncovered.id}`)).toHaveAttribute(
      "data-verdict",
      "agent",
      { timeout: 10000 },
    );
    // Set by hand: its menu offers the computed value back.
    await page.getByTestId(`coverage-btn-change-pack-${uncovered.id}`).click();
    await expect(page.getByTestId(`coverage-btn-change-pack-${uncovered.id}-reset`)).toBeVisible();
    await page.keyboard.press("Escape");

    // To do re-reads on open: the step left "nobody covers this".
    await page.getByTestId("coverage-tab-gaps").click();
    await expect(page.getByTestId(`coverage-todo-row-${uncovered.id}`)).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId(`coverage-gap-row-${uncovered.id}`)).toHaveCount(0);
  });
});
