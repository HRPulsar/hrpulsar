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

// HRP-99: each `upsert_matrix_bulk` call mutated grade_competence_links via
// db.add / db.delete on a session opened with expire_on_commit=False, so
// pair.competence_links kept its pre-save snapshot in Python. The follow-up
// get_matrix_bulk(...) read that stale collection — the API returned an
// empty matrix even though the row was committed, and the editor on the
// detail page rendered "No competences". F5 reloaded a fresh session and
// the matrix reappeared.
test.describe("HRP-99: matrix save round-trip on detail page", () => {
  let accessToken: string;
  let refreshToken: string;
  let specId: string;
  let gradeId: string;
  let levelId: string;
  let competence1Title: string;
  let competence1Id: string;
  let competence2Id: string;
  let levelTitle: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const reg = await registerUser(page);
    accessToken = reg.accessToken;
    refreshToken = reg.refreshToken;
    const opts = { page, accessToken };
    const stamp = Date.now().toString(36);

    const spec = await createDictionaryItem(opts, "specialization", `MtxBug-${stamp}`);
    specId = spec.id;
    const junior = await createDictionaryItem(opts, "grade", `Jr-${stamp}`);
    gradeId = junior.id;

    const group = await createCompetenceGroup(opts, `MtxBugGroup-${stamp}`);
    const comp1 = await createCompetence(opts, group.id, `MtxBugComp-${stamp}-1`);
    competence1Title = comp1.title;
    competence1Id = comp1.id;
    const comp2 = await createCompetence(opts, group.id, `MtxBugComp-${stamp}-2`);
    competence2Id = comp2.id;

    const level = await pickFirstSkillLevel(opts);
    levelTitle = level.title;
    levelId = level.id;
    await createIndicator(opts, comp1.id, "Knows the basics", level.id);
    await createIndicator(opts, comp2.id, "Knows the basics", level.id);

    const chain = await page.request.post(`${API_BASE}/grade-system/chains`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      data: {
        grade_id: junior.id,
        specialization_id: spec.id,
        competence_links: [],
      },
    });
    if (!chain.ok()) throw new Error(`chain failed: ${await chain.text()}`);
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("scenario 1: add competence + pick level + save → row stays visible without F5", async ({
    page,
  }) => {
    await page.goto(`/company/specializations/${specId}`);
    await expect(page.getByTestId("specialization-detail")).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId("matrix-editor")).toBeVisible({ timeout: 10000 });

    await page.getByTestId("matrix-add-competence-btn").click();
    await expect(page.getByTestId("matrix-add-competences-dialog")).toBeVisible();
    await page.getByTestId("matrix-add-competences-search").fill(competence1Title);
    await page
      .locator('[data-testid^="matrix-add-comp-"]:not([data-testid$="-open"])')
      .first()
      .click();
    await page.getByTestId("matrix-add-competences-save").click();
    await expect(page.getByTestId("matrix-add-competences-dialog")).toBeHidden();

    await expect(page.getByTestId(`matrix-row-${competence1Id}`)).toBeVisible();

    const cell = page.locator('[data-testid^="matrix-cell-select-"]').first();
    await cell.selectOption({ label: levelTitle });

    await page.getByTestId("matrix-unsaved-bar-btn-save").click();
    await expect(page.getByTestId("matrix-unsaved-bar")).toBeHidden({ timeout: 5000 });

    // The bug surfaced here: row disappeared because the API returned a
    // stale matrix from session cache. The frontend then trusted that
    // empty snapshot and rendered "No competences in this matrix yet".
    await expect(page.getByTestId(`matrix-row-${competence1Id}`)).toBeVisible();
    await expect(
      page.locator('[data-testid^="matrix-cell-select-"]').first(),
    ).toHaveValue(/.+/);
  });

  test("scenario 5: remove competence + save → row disappears without F5", async ({ page }) => {
    // Pre-seed: matrix already contains comp2 with a level.
    const seed = await page.request.put(
      `${API_BASE}/specializations/${specId}/matrix-bulk`,
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: {
          grades: [
            {
              grade_id: gradeId,
              links: [{ competence_id: competence2Id, skill_level_id: levelId }],
            },
          ],
        },
      },
    );
    if (!seed.ok()) throw new Error(`seed failed: ${await seed.text()}`);

    await page.goto(`/company/specializations/${specId}`);
    await expect(page.getByTestId("specialization-detail")).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId(`matrix-row-${competence2Id}`)).toBeVisible({ timeout: 10000 });

    await page.getByTestId(`matrix-row-${competence2Id}-btn-remove`).click();
    await page.getByTestId("matrix-row-remove-confirm-confirm").click();
    await expect(page.getByTestId(`matrix-row-${competence2Id}`)).toBeHidden();

    await page.getByTestId("matrix-unsaved-bar-btn-save").click();
    await expect(page.getByTestId("matrix-unsaved-bar")).toBeHidden({ timeout: 5000 });

    // Without the fix, the API returned the still-cached row and the
    // editor's useEffect[bulk] re-hydrated state with it — the deleted
    // row reappeared until F5.
    await expect(page.getByTestId(`matrix-row-${competence2Id}`)).toBeHidden();
    await expect(page.getByTestId("matrix-empty")).toBeVisible();
  });
});
