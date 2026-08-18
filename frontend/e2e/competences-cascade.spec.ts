import { test, expect } from "./fixtures";
import {
  createCompetenceGroup,
  pickFirstSkillLevel,
  publishCompetence,
  registerUser,
  setAuthTokens,
} from "./helpers";

// HRP-139 — cascade activation, hidden-state inheritance, and Delete/menu
// rules around used groups. Backend cascade was shipped in HRP-118 (units
// already cover the service layer); this suite locks the UI surface.

const API_BASE = "http://localhost:8100/api";

async function createGroupViaApi(
  page: import("@playwright/test").Page,
  accessToken: string,
  title: string,
  extra: Record<string, unknown> = {},
) {
  const resp = await page.request.post(`${API_BASE}/competence-groups`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    data: { title, ...extra },
  });
  if (!resp.ok()) {
    throw new Error(
      `createGroupViaApi failed (${resp.status()}): ${await resp.text()}`,
    );
  }
  return resp.json();
}

async function fetchCompetenceById(
  page: import("@playwright/test").Page,
  accessToken: string,
  competenceId: string,
) {
  const resp = await page.request.get(
    `${API_BASE}/competences/${competenceId}`,
    { headers: { Authorization: `Bearer ${accessToken}` } },
  );
  if (!resp.ok()) {
    throw new Error(
      `fetchCompetence failed (${resp.status()}): ${await resp.text()}`,
    );
  }
  return resp.json();
}

test.describe("HRP-139 — cascade activation + Delete visibility", () => {
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

  test("activate Sub also lights up its inactive ancestor and descendant", async ({
    page,
  }) => {
    const stamp = Date.now();
    const root = await createGroupViaApi(
      page,
      accessToken,
      `Root ${stamp}`,
      { is_active: false },
    );
    const sub = await createGroupViaApi(page, accessToken, `Sub ${stamp}`, {
      is_active: false,
      parent_id: root.id,
    });
    const leaf = await createGroupViaApi(page, accessToken, `Leaf ${stamp}`, {
      is_active: false,
      parent_id: sub.id,
    });

    await page.goto("/competences");
    // All three start hidden — their badges are present.
    for (const id of [root.id, sub.id, leaf.id]) {
      await expect(
        page.getByTestId(`competences-group-${id}-hidden-badge`),
      ).toBeVisible({ timeout: 10000 });
    }

    // Toggle visibility on Sub — the cascade walks up to Root and down to Leaf.
    await page.getByTestId(`competences-group-${sub.id}-actions`).click();
    await page
      .getByTestId(`competences-group-${sub.id}-btn-deactivate`)
      .click();

    for (const id of [root.id, sub.id, leaf.id]) {
      await expect(
        page.getByTestId(`competences-group-${id}-hidden-badge`),
      ).toHaveCount(0, { timeout: 10000 });
    }
  });

  test("competence added under an inactive group inherits is_active=false (single + bulk)", async ({
    page,
  }) => {
    const stamp = Date.now();
    const group = await createGroupViaApi(
      page,
      accessToken,
      `Hidden ${stamp}`,
      { is_active: false },
    );

    await page.goto("/competences");
    // Single-flow: add via the per-group "Add competence" menu item.
    await page.getByTestId(`competences-group-${group.id}-actions`).click();
    await page
      .getByTestId(`competences-group-${group.id}-btn-add-competence`)
      .click();
    await page
      .getByTestId("competences-modal-competence-input-title")
      .fill(`Solo ${stamp}`);
    await page.getByTestId("competences-modal-competence-btn-next").click();
    await page.getByTestId("competences-modal-competence-btn-submit").click();
    await expect(
      page.getByTestId("competences-modal-competence"),
    ).toBeHidden({ timeout: 10000 });

    // Bulk-flow: same group, two rows in one go.
    await page
      .getByTestId(`competences-group-${group.id}-btn-bulk-add`)
      .click({ force: true });
    await page
      .getByTestId("competences-modal-bulk-row-0-title")
      .fill(`BulkOne ${stamp}`);
    await page.getByTestId("competences-modal-bulk-btn-add-row").click();
    await page
      .getByTestId("competences-modal-bulk-row-1-title")
      .fill(`BulkTwo ${stamp}`);
    await page.getByTestId("competences-modal-bulk-btn-submit").click();
    await expect(page.getByTestId("competences-modal-bulk")).toBeHidden({
      timeout: 10000,
    });

    // Verify backend persisted is_active=false for every fresh row via the
    // tree endpoint (the only public list path is /competence-tree).
    const treeResp = await page.request.get(`${API_BASE}/competence-tree`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    expect(treeResp.ok()).toBeTruthy();
    type CompetenceNode = { id: string; title: string };
    type GroupNode = { id: string; competences: CompetenceNode[] };
    const tree: GroupNode[] = await treeResp.json();
    const targetGroup = tree.find((g) => g.id === group.id);
    expect(targetGroup, "freshly-created group must show up in the tree").toBeTruthy();
    const wantedTitles = [
      `Solo ${stamp}`,
      `BulkOne ${stamp}`,
      `BulkTwo ${stamp}`,
    ];
    const matches = (targetGroup?.competences ?? []).filter((c) =>
      wantedTitles.includes(c.title),
    );
    expect(matches).toHaveLength(3);
    for (const row of matches) {
      const detail = await fetchCompetenceById(page, accessToken, row.id);
      expect(detail.is_active, `${detail.title} should inherit hidden`).toBe(
        false,
      );
    }
  });

  test("snackbar copy on deactivate matches the spec", async ({ page }) => {
    const stamp = Date.now();
    const group = await createCompetenceGroup(
      { page, accessToken },
      `Snack ${stamp}`,
    );

    await page.goto("/competences");
    await page.getByTestId(`competences-group-${group.id}-actions`).click();
    await page
      .getByTestId(`competences-group-${group.id}-btn-deactivate`)
      .click();

    await expect(
      page.getByText(
        "Competence group and its contents are hidden from users",
      ),
    ).toBeVisible({ timeout: 10000 });
  });

  test("Delete is hidden when the group is referenced, edit dialog shows the used-by-client badge", async ({
    page,
  }) => {
    const stamp = Date.now();
    const opts = { page, accessToken };
    const group = await createCompetenceGroup(opts, `Used ${stamp}`);
    const lvl = await pickFirstSkillLevel(opts);

    // Create + publish a competence, then wire it into a grade chain so
    // usage_check returns true and the rollup marks the group as used.
    const compResp = await page.request.post(`${API_BASE}/competences`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      data: { title: `UsedComp ${stamp}`, group_id: group.id },
    });
    expect(compResp.ok()).toBeTruthy();
    const comp = await compResp.json();
    const indResp = await page.request.post(
      `${API_BASE}/competences/${comp.id}/indicators`,
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: { title: `Ind ${stamp}`, skill_level_id: lvl.id, weight: 1 },
      },
    );
    expect(indResp.ok()).toBeTruthy();
    await publishCompetence(opts, comp.id);
    const spec = await page.request
      .post(`${API_BASE}/dictionaries/specialization`, {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: { title: `UsedSpec ${stamp}` },
      })
      .then((r) => r.json());
    const grade = await page.request
      .post(`${API_BASE}/dictionaries/grade`, {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: { title: `UsedGrade ${stamp}` },
      })
      .then((r) => r.json());
    const chainResp = await page.request.post(
      `${API_BASE}/grade-system/chains`,
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: {
          grade_id: grade.id,
          specialization_id: spec.id,
          competence_links: [
            { competence_id: comp.id, skill_level_id: lvl.id },
          ],
        },
      },
    );
    expect(chainResp.ok()).toBeTruthy();

    await page.goto("/competences");
    await page.getByTestId(`competences-group-${group.id}-actions`).click();
    // Edit/Add still available, Delete is gone.
    await expect(
      page.getByTestId(`competences-group-${group.id}-btn-edit`),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId(`competences-group-${group.id}-btn-delete`),
    ).toHaveCount(0);

    // HRP-137: opening the Edit dialog on a used group shows the read-only
    // affordance instead of the activate-by-default checkbox.
    await page
      .getByTestId(`competences-group-${group.id}-btn-edit`)
      .click();
    await expect(page.getByTestId("competences-modal-group")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId("competences-modal-group-used-by-client"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("competences-modal-group-checkbox-active"),
    ).toHaveCount(0);
  });

  test("HRP-137 — fresh (not-used) group still shows the checkbox in Edit", async ({
    page,
  }) => {
    const stamp = Date.now();
    const group = await createCompetenceGroup(
      { page, accessToken },
      `Fresh ${stamp}`,
    );

    await page.goto("/competences");
    await page.getByTestId(`competences-group-${group.id}-actions`).click();
    await page.getByTestId(`competences-group-${group.id}-btn-edit`).click();
    await expect(page.getByTestId("competences-modal-group")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId("competences-modal-group-checkbox-active"),
    ).toBeVisible();
    await expect(
      page.getByTestId("competences-modal-group-used-by-client"),
    ).toHaveCount(0);
  });
});
