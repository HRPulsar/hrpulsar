/**
 * HRP-687 — "Add from dictionary" on a vacancy is a real picker.
 *
 * Cold-start path on a tenant with no demo seed: create one competence,
 * link it to the vacancy through the dictionary picker, and watch the
 * HRP-667 bridge ("Post to talent market") unlock and produce a card —
 * all without a page reload. Before this ticket the button was a stub
 * toast and the bridge was unreachable through the UI.
 *
 * Requires E2E_MODE=true on the backend (registerUser uses
 * /auth/dev/auto-register).
 */
import { test, expect } from "./fixtures";
import {
  API_BASE,
  createCompetence,
  createCompetenceGroup,
  registerUser,
  setAuthTokens,
} from "./helpers";

test.describe("Vacancy library competences (HRP-687)", () => {
  test("add from dictionary unlocks the talent-market bridge", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const opts = { page, accessToken: admin.accessToken };
    const stamp = Date.now();
    const group = await createCompetenceGroup(opts, `HRP687 group ${stamp}`);
    const competence = await createCompetence(
      opts,
      group.id,
      `HRP687 competence ${stamp}`,
    );

    const created = await page.request.post(`${API_BASE}/recruitment/vacancies`, {
      headers: { Authorization: `Bearer ${admin.accessToken}` },
      data: { title: `HRP687 vacancy ${stamp}` },
    });
    expect(created.ok()).toBeTruthy();
    const vacancy = await created.json();

    await setAuthTokens(page, admin.accessToken, admin.refreshToken);
    await page.goto(`/recruitment/requisitions/${vacancy.id}`);

    // The bridge starts locked: the matcher scores against library-linked
    // competences and the fresh vacancy has none.
    const postBtn = page.getByTestId("vacancy-internal-candidates-post-btn");
    await expect(postBtn).toBeVisible({ timeout: 15000 });
    await expect(postBtn).toBeDisabled();

    await page.getByTestId("vacancy-competences-add-from-dict-btn").click();
    await expect(
      page.getByTestId("vacancy-competences-library-dialog"),
    ).toBeVisible();
    await page
      .getByTestId(`vacancy-competences-library-picker-group-toggle-${group.id}`)
      .click();
    await page
      .getByTestId(`vacancy-competences-library-picker-${competence.id}`)
      .click();
    await page.getByTestId("vacancy-competences-library-save-btn").click();

    // Reactivity, both halves: the section lists the linked competence and
    // the sibling internal-candidates block re-reads its precondition.
    await expect(
      page.getByTestId(`vacancy-library-competence-${competence.id}`),
    ).toBeVisible({ timeout: 10000 });
    await expect(postBtn).toBeEnabled({ timeout: 10000 });

    await postBtn.click();
    await expect(page.getByTestId("vacancy-internal-candidates")).toBeVisible({
      timeout: 15000,
    });
    // Nobody is employed on this tenant, so the shortlist is legitimately
    // empty — the card itself is what proves the bridge fired.
    await expect(
      page.getByTestId("vacancy-internal-candidates-card-link"),
    ).toBeVisible();
  });
});
