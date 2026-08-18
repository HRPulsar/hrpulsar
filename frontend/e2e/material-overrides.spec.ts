import { expect, test } from "./fixtures";
import {
  createCompetence,
  createCompetenceGroup,
  createDictionaryItem,
  createMaterial,
  pickFirstSkillLevel,
  registerUser,
  setAuthTokens,
} from "./helpers";

test.describe("Material specialization overrides (POS7)", () => {
  let accessToken: string;
  let refreshToken: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const creds = await registerUser(page);
    accessToken = creds.accessToken;
    refreshToken = creds.refreshToken;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("hide a base material in context of a specialization", async ({ page }) => {
    const stamp = Date.now();
    const opts = { page, accessToken };

    const group = await createCompetenceGroup(opts, `OverrideGrp ${stamp}`);
    const comp = await createCompetence(opts, group.id, `SQL ${stamp}`);
    const skill = await pickFirstSkillLevel(opts);
    const m1 = await createMaterial(opts, comp.id, "SQL Basics Book", skill.id);
    const m2 = await createMaterial(opts, comp.id, "SQL Advanced Course", skill.id);

    const backend = await createDictionaryItem(
      opts,
      "specialization",
      `Backend ${stamp}`,
    );

    await page.goto(`/competences/${comp.id}`);
    await expect(page.getByTestId("materials-overrides-panel")).toBeVisible({
      timeout: 10000,
    });

    // Switch context to the new specialization (Radix Select).
    await page.getByTestId("materials-context-select").click();
    await page.getByRole("option", { name: backend.title }).click();

    // Both materials are visible by default.
    await expect(
      page.getByTestId(`material-override-row-${m1.id}`),
    ).toBeVisible();
    await expect(
      page.getByTestId(`material-override-row-${m2.id}`),
    ).toBeVisible();

    // Hide one in context.
    await page.getByTestId(`material-override-btn-hide-${m1.id}`).click();
    await expect(
      page.getByTestId("material-override-hidden-list"),
    ).toBeVisible();
    await expect(
      page.getByTestId(`material-override-hidden-row-${m1.id}`),
    ).toBeVisible();

    // Restore default.
    await page
      .getByTestId(`material-override-btn-restore-${m1.id}`)
      .first()
      .click();
    await expect(
      page.getByTestId(`material-override-row-${m1.id}`),
    ).toBeVisible();
  });
});
