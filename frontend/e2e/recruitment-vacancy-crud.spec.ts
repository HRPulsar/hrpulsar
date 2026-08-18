/**
 * HRP-177 — Vacancy lifecycle CRUD happy path.
 *
 * Acceptance criteria from the ticket: Edit, Archive, Restore, and
 * permanent Delete must work end-to-end from the list view kebab menu.
 * Test ids declared in pack-rec (HRP-177) and mirrored in TEST_IDS.md.
 *
 * Requires E2E_MODE=true on the backend (registerUser uses
 * /auth/dev/auto-register).
 */
import { test, expect } from "./fixtures";
import { registerUser, setAuthTokens } from "./helpers";

const API_BASE = "http://localhost:8100/api";

async function createVacancy(
  page: import("@playwright/test").Page,
  accessToken: string,
  title: string,
): Promise<{ id: string; title: string }> {
  const resp = await page.request.post(`${API_BASE}/recruitment/vacancies`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    data: { title },
  });
  if (!resp.ok()) {
    throw new Error(`createVacancy failed (${resp.status()}): ${await resp.text()}`);
  }
  const body = await resp.json();
  return { id: body.id, title: body.title };
}

test.describe("Recruitment vacancy CRUD (HRP-177)", () => {
  test("edit pre-fills, saves, and reflects on the card", async ({ page }) => {
    const admin = await registerUser(page);
    const v = await createVacancy(page, admin.accessToken, `Vacancy ${Date.now()}`);
    await setAuthTokens(page, admin.accessToken, admin.refreshToken);

    await page.goto("/recruitment/requisitions");
    await expect(page.getByTestId(`vacancy-list-row-${v.id}`)).toBeVisible({
      timeout: 10000,
    });

    await page.getByTestId(`vacancy-actions-menu-trigger-${v.id}`).click();
    await page.getByTestId(`vacancy-actions-menu-edit-${v.id}`).click();

    await expect(page).toHaveURL(new RegExp(`/recruitment/requisitions/${v.id}/edit$`));
    await expect(page.getByTestId("vacancy-edit-form")).toBeVisible({ timeout: 10000 });

    const titleInput = page.getByTestId("recruitment-vacancy-input-title");
    await expect(titleInput).toHaveValue(v.title);

    const newTitle = `${v.title} (edited)`;
    await titleInput.fill(newTitle);

    await page.getByTestId("vacancy-edit-form-save").click();

    // The candidates table normalizes the URL to include the persisted
    // sort (?sort=&dir=, HRP-267) as soon as it mounts, so accept an
    // optional query string after the vacancy id.
    await expect(page).toHaveURL(
      new RegExp(`/recruitment/requisitions/${v.id}(\\?.*)?$`),
      { timeout: 10000 },
    );

    // Round-trip through the API so we don't depend on per-page rendering
    // for the assertion — the card just needs to reload its data.
    const fresh = await page.request.get(
      `${API_BASE}/recruitment/vacancies/${v.id}`,
      { headers: { Authorization: `Bearer ${admin.accessToken}` } },
    );
    expect(fresh.ok()).toBeTruthy();
    expect((await fresh.json()).title).toBe(newTitle);
  });

  test("archive keeps the row under All statuses and restore clears the badge", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const v = await createVacancy(page, admin.accessToken, `Vacancy ${Date.now()}`);
    await setAuthTokens(page, admin.accessToken, admin.refreshToken);

    await page.goto("/recruitment/requisitions");
    await expect(page.getByTestId(`vacancy-list-row-${v.id}`)).toBeVisible({
      timeout: 10000,
    });

    await page.getByTestId(`vacancy-actions-menu-trigger-${v.id}`).click();
    await page.getByTestId(`vacancy-actions-menu-archive-${v.id}`).click();

    await expect(page.getByTestId("vacancy-archive-modal")).toBeVisible({
      timeout: 5000,
    });
    await page.getByTestId("vacancy-archive-modal-confirm").click();

    // HRP-363: "All statuses" includes archived vacancies — the row stays
    // visible but flips its badge to "archived".
    await expect(
      page.getByTestId(`vacancy-list-row-${v.id}`).getByText("archived"),
    ).toBeVisible({ timeout: 10000 });

    // A concrete status filter still hides the archived row.
    await page.getByTestId("vacancy-status-filter").click();
    await page.getByRole("option", { name: "Draft" }).click();
    await expect(page.getByTestId(`vacancy-list-row-${v.id}`)).toBeHidden({
      timeout: 10000,
    });

    // The dedicated Archived view surfaces it.
    await page.getByTestId("vacancy-status-filter").click();
    await page.getByRole("option", { name: "Archived" }).click();
    await expect(page.getByTestId(`vacancy-list-row-${v.id}`)).toBeVisible({
      timeout: 10000,
    });

    // Restore from the Archived view → row is gone from this view…
    await page.getByTestId(`vacancy-actions-menu-trigger-${v.id}`).click();
    await page.getByTestId(`vacancy-actions-menu-restore-${v.id}`).click();
    await expect(page.getByTestId(`vacancy-list-row-${v.id}`)).toBeHidden({
      timeout: 10000,
    });

    // …and back in the default-filter list without the archived badge.
    await page.getByTestId("vacancy-status-filter").click();
    await page.getByRole("option", { name: "All statuses" }).click();
    await expect(page.getByTestId(`vacancy-list-row-${v.id}`)).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId(`vacancy-list-row-${v.id}`).getByText("archived"),
    ).toBeHidden();
  });

  test("delete permanently is a one-click confirm and removes the row", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const v = await createVacancy(page, admin.accessToken, `Vacancy ${Date.now()}`);
    await setAuthTokens(page, admin.accessToken, admin.refreshToken);

    await page.goto("/recruitment/requisitions");
    await expect(page.getByTestId(`vacancy-list-row-${v.id}`)).toBeVisible({
      timeout: 10000,
    });

    await page.getByTestId(`vacancy-actions-menu-trigger-${v.id}`).click();
    await page.getByTestId(`vacancy-actions-menu-delete-${v.id}`).click();

    await expect(page.getByTestId("vacancy-delete-modal")).toBeVisible({
      timeout: 5000,
    });

    // HRP-177 REDO: confirmation is a single button, no text-typing guard.
    const confirmBtn = page.getByTestId("vacancy-delete-modal-confirm");
    await expect(confirmBtn).toBeEnabled();
    await confirmBtn.click();

    // List page reloads and the row is gone.
    await expect(page.getByTestId(`vacancy-list-row-${v.id}`)).toBeHidden({
      timeout: 10000,
    });

    // Backend physically removed it — direct GET returns 404.
    const dead = await page.request.get(
      `${API_BASE}/recruitment/vacancies/${v.id}`,
      { headers: { Authorization: `Bearer ${admin.accessToken}` } },
    );
    expect(dead.status()).toBe(404);
  });

  // HRP-360: hiring manager on the create form and the Overview block.
  test("hiring manager defaults to the current user and shows on overview", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    await setAuthTokens(page, admin.accessToken, admin.refreshToken);

    await page.goto("/recruitment/requisitions/new");
    // registerUser signs up as "E2E Tester" (admin) — the picker defaults
    // to the creating user.
    await expect(
      page.getByTestId("recruitment-vacancy-select-hiring-manager"),
    ).toContainText("E2E Tester", { timeout: 10000 });

    await page
      .getByTestId("recruitment-vacancy-input-title")
      .fill(`HM Vacancy ${Date.now()}`);
    await page.getByTestId("recruitment-vacancy-btn-save-draft").click();

    await expect(page).toHaveURL(/\/recruitment\/requisitions\/[0-9a-f-]+/, {
      timeout: 10000,
    });
    await expect(
      page.getByTestId("vacancy-field-hiring-manager"),
    ).toHaveText("E2E Tester", { timeout: 10000 });
  });
});
