import { test, expect } from "./fixtures";
import { registerUser, setAuthTokens } from "./helpers";

const API_BASE = process.env.E2E_API_BASE ?? "http://localhost:8100/api";

/**
 * HRP-762 — a gap handed to Recruitment (REFACTOR_PLAN §6, §7.6).
 *
 * A step that needs a judgement (P6) fits no agent pack and, on a fresh
 * tenant, no person: a gap. The To do tab opens a hire need for it, the row
 * links to the draft vacancy, and the vacancy is listed in Recruitment.
 *
 * W6 (§5.10): the same tab has a second section for the work an agent type
 * could take that nobody has automated - and that section is not offered
 * for hiring, on the screen or on the server.
 */
test.describe("Coverage — gap to hire need", () => {
  test("gap step → hire need → draft vacancy in Recruitment", async ({ page }) => {
    const admin = await registerUser(page);
    await setAuthTokens(page, admin.accessToken, admin.refreshToken);
    const headers = { Authorization: `Bearer ${admin.accessToken}` };

    const container = await (
      await page.request.post(`${API_BASE}/work/containers`, {
        headers,
        data: {
          type: "process",
          title: `Credit release ${Date.now()}`,
          description: "The credit manager decides whether to release an order on credit hold.",
        },
      })
    ).json();
    const step = await (
      await page.request.post(`${API_BASE}/work/containers/${container.id}/steps`, {
        headers,
        data: { title: "Decide on the credit hold", primitive_codes: ["P6"] },
      })
    ).json();
    // Covered by an agent type, automated by nobody: the second section.
    const extraction = await (
      await page.request.post(`${API_BASE}/work/containers/${container.id}/steps`, {
        headers,
        data: { title: "Record the hold in the ledger", primitive_codes: ["P1"] },
      })
    ).json();

    await page.goto(`/coverage/${container.id}`);
    await expect(page.getByTestId("coverage-detail")).toBeVisible({ timeout: 10000 });

    // W6 (§5.9): the same handoff is offered on the Coverage row itself,
    // with the three routes the question actually has. Opened and closed
    // here - the flow below is what creates the vacancy.
    await expect(page.getByTestId("coverage-match-list")).toBeVisible({ timeout: 10000 });
    await page.getByTestId(`coverage-btn-hire-${step.id}`).click();
    await expect(page.getByTestId("coverage-modal-hire")).toBeVisible();
    await expect(page.getByTestId("coverage-hire-route-internal_first")).toBeVisible();
    await expect(page.getByTestId("coverage-hire-route-external")).toBeVisible();
    await expect(page.getByTestId("coverage-hire-route-agency")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("coverage-modal-hire")).toBeHidden();

    await page.getByTestId("coverage-tab-gaps").click();
    const row = page.getByTestId(`coverage-gap-row-${step.id}`);
    await expect(row).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId(`coverage-gap-row-${step.id}-capability-P6`)).toBeVisible();
    await expect(page.getByTestId("coverage-gap-btn-hire-need")).toBeDisabled();

    // The automatable step is on the other list: a skill to write, not a
    // person to hire - so it has no checkbox and no hire route at all.
    const todo = page.getByTestId(`coverage-todo-row-${extraction.id}`);
    await expect(todo).toBeVisible();
    await expect(page.getByTestId(`coverage-todo-row-${extraction.id}-btn-skill`)).toBeVisible();
    await expect(page.getByTestId(`coverage-gap-row-${extraction.id}`)).toHaveCount(0);

    await page.getByTestId(`coverage-gap-row-${step.id}-checkbox`).click();
    await expect(page.getByTestId("coverage-gap-btn-hire-need")).toBeEnabled();
    await page.getByTestId("coverage-gap-btn-hire-need").click();

    const link = page.getByTestId(`coverage-gap-row-${step.id}-link-vacancy`);
    await expect(link).toBeVisible({ timeout: 15000 });
    const href = await link.getAttribute("href");
    expect(href).toMatch(/\/recruitment\/requisitions\/[0-9a-f-]+$/);
    const vacancyId = href!.split("/").pop()!;

    // The draft vacancy exists in Recruitment, titled after the breakdown.
    await page.goto("/recruitment/requisitions");
    await expect(page.getByTestId(`vacancy-list-row-${vacancyId}`)).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId(`vacancy-list-row-${vacancyId}`)).toContainText(
      container.title,
    );
  });
});
