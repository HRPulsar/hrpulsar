import { test, expect } from "./fixtures";
import {
  registerUser,
  setAuthTokens,
  createDictionaryItem,
  createCompetenceGroup,
  createCompetence,
  createIndicator,
  pickFirstSkillLevel,
} from "./helpers";

const API_BASE = "http://localhost:8100/api";

test.describe("Specialization matrix UX (POS4)", () => {
  let accessToken: string;
  let refreshToken: string;
  let specId: string;
  let competenceTitle: string;
  let tooltipCompetenceId: string;
  let tooltipCompetenceTitle: string;
  let levelTitle: string;
  let juniorTitle: string;
  let seniorTitle: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const reg = await registerUser(page);
    accessToken = reg.accessToken;
    refreshToken = reg.refreshToken;

    const opts = { page, accessToken };
    const stamp = Date.now().toString(36);

    const spec = await createDictionaryItem(opts, "specialization", `Mtx-${stamp}`);
    specId = spec.id;
    const junior = await createDictionaryItem(opts, "grade", `Junior-${stamp}`);
    const senior = await createDictionaryItem(opts, "grade", `Senior-${stamp}`);
    juniorTitle = junior.title;
    seniorTitle = senior.title;

    // Bump senior sort_index so it sits above junior in the matrix.
    const seniorPatch = await page.request.put(
      `${API_BASE}/dictionaries/items/${senior.id}`,
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: { sort_index: 50 },
      },
    );
    if (!seniorPatch.ok()) {
      throw new Error(
        `failed to bump grade sort_index (${seniorPatch.status()}): ${await seniorPatch.text()}`,
      );
    }

    const group = await createCompetenceGroup(opts, `MtxGroup-${stamp}`);
    const comp = await createCompetence(opts, group.id, `MtxComp-${stamp}`);
    competenceTitle = comp.title;

    // Tooltip test needs its own competence — the cascade test attaches and
    // saves `comp` to the matrix, after which the add-competence dropdown
    // filters it out (matrix-editor.tsx `availableForAdd`). Without a fresh
    // entity the tooltip test would race the cascade test for the only
    // option in the picker.
    const tooltipComp = await createCompetence(
      opts,
      group.id,
      `MtxCompTooltip-${stamp}`,
    );
    tooltipCompetenceId = tooltipComp.id;
    tooltipCompetenceTitle = tooltipComp.title;

    const level = await pickFirstSkillLevel(opts);
    levelTitle = level.title;
    await createIndicator(opts, comp.id, "Knows the basics", level.id);
    await createIndicator(opts, tooltipComp.id, "Knows the basics", level.id);

    const chain1 = await page.request.post(`${API_BASE}/grade-system/chains`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      data: {
        grade_id: junior.id,
        specialization_id: spec.id,
        competence_links: [],
      },
    });
    if (!chain1.ok()) {
      throw new Error(`junior chain failed: ${await chain1.text()}`);
    }
    const chain2 = await page.request.post(`${API_BASE}/grade-system/chains`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      data: {
        grade_id: senior.id,
        specialization_id: spec.id,
        competence_links: [],
      },
    });
    if (!chain2.ok()) {
      throw new Error(`senior chain failed: ${await chain2.text()}`);
    }

    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("matrix page renders headers and cells", async ({ page }) => {
    await page.goto(`/company/specializations/${specId}/matrix`);
    await expect(page.getByTestId("matrix-page")).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId("matrix-empty")).toBeVisible();
    // HRP-100: legacy dropdown was replaced by the Add-competences modal,
    // so the surface we expect at rest is the trigger button.
    await expect(page.getByTestId("matrix-add-competence-btn")).toBeVisible();
  });

  test("cascade promotes lower-grade level up to higher grades on save", async ({
    page,
  }) => {
    await page.goto(`/company/specializations/${specId}/matrix`);
    await expect(page.getByTestId("matrix-page")).toBeVisible({ timeout: 10000 });

    // HRP-100: open the new modal, search for the seeded competence,
    // tick its checkbox and confirm.
    await page.getByTestId("matrix-add-competence-btn").click();
    await expect(page.getByTestId("matrix-add-competences-dialog")).toBeVisible();
    await page.getByTestId("matrix-add-competences-search").fill(competenceTitle);
    await page
      .locator('[data-testid^="matrix-add-comp-"]:not([data-testid$="-open"])')
      .first()
      .click();
    await page.getByTestId("matrix-add-competences-save").click();
    await expect(page.getByTestId("matrix-add-competences-dialog")).toBeHidden();

    await expect(page.getByTestId("matrix-table")).toBeVisible();

    // Find the cell for the junior grade (lowest sort_index → first column)
    // and pick the seeded skill level.
    const juniorHeader = page.getByText(juniorTitle).first();
    await expect(juniorHeader).toBeVisible();

    const cells = page.locator('[data-testid^="matrix-cell-select-"]');
    await expect(cells).toHaveCount(2);

    // First cell = junior (lowest sort_index). Set the level.
    await cells.nth(0).selectOption({ label: levelTitle });

    // The second cell (senior) cascades up to the same level via client-side
    // logic and should reflect the new value before save.
    await expect(cells.nth(1)).toHaveValue(/.+/);

    await page.getByTestId("matrix-unsaved-bar").waitFor();
    await page.getByTestId("matrix-unsaved-bar-btn-save").click();
    await expect(page.getByTestId("matrix-unsaved-bar")).toBeHidden({ timeout: 5000 });

    // Reload to confirm persistence on both grades.
    await page.reload();
    await expect(page.getByTestId("matrix-table")).toBeVisible();
    const reloadedCells = page.locator('[data-testid^="matrix-cell-select-"]');
    await expect(reloadedCells.nth(0)).toHaveValue(/.+/);
    await expect(reloadedCells.nth(1)).toHaveValue(/.+/);
    // Both reloaded cells should match the same level (cascade was applied
    // and persisted).
    const v0 = await reloadedCells.nth(0).inputValue();
    const v1 = await reloadedCells.nth(1).inputValue();
    expect(v0).toBe(v1);
    expect(v0).not.toBe("");
    void seniorTitle; // referenced via header above; quiet unused-var lint
  });

  test("indicators tooltip opens and closes", async ({ page }) => {
    await page.goto(`/company/specializations/${specId}/matrix`);
    await expect(page.getByTestId("matrix-page")).toBeVisible({ timeout: 10000 });

    // Use the dedicated tooltip competence so this test doesn't race the
    // cascade test for the only available option (the modal filters out
    // already-attached competences).
    await page.getByTestId("matrix-add-competence-btn").click();
    await expect(page.getByTestId("matrix-add-competences-dialog")).toBeVisible();
    await page.getByTestId("matrix-add-competences-search").fill(tooltipCompetenceTitle);
    await page
      .locator('[data-testid^="matrix-add-comp-"]:not([data-testid$="-open"])')
      .first()
      .click();
    await page.getByTestId("matrix-add-competences-save").click();
    await expect(page.getByTestId("matrix-add-competences-dialog")).toBeHidden();

    // Locate the tooltip competence's row by id — the matrix may already
    // contain the cascade test's competence, so cells.nth(0) is no longer
    // a stable target.
    const tooltipCells = page.locator(
      `[data-testid^="matrix-cell-select-${tooltipCompetenceId}-"]`,
    );
    await expect(tooltipCells.first()).toBeVisible();
    await tooltipCells.first().selectOption({ label: levelTitle });

    const infoBtn = page
      .locator(`[data-testid^="matrix-cell-btn-info-${tooltipCompetenceId}-"]`)
      .first();
    await infoBtn.click();
    await expect(page.getByTestId("matrix-indicators-tooltip")).toBeVisible();
    await page.getByTestId("matrix-indicators-tooltip-close").click();
    await expect(page.getByTestId("matrix-indicators-tooltip")).toBeHidden();
  });
});
