import { test, expect } from "./fixtures";
import { registerUser, setAuthTokens } from "./helpers";

test.describe("Dictionaries page", () => {
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

  test("dictionaries page renders", async ({ page }) => {
    await page.goto("/dictionaries");
    await expect(page.getByTestId("dictionaries-list")).toBeVisible({
      timeout: 10000,
    });
  });

  test("add button visible", async ({ page }) => {
    await page.goto("/dictionaries");
    await expect(page.getByTestId("dictionaries-btn-add")).toBeVisible({
      timeout: 10000,
    });
  });

  test("empty state for specific type", async ({ page }) => {
    // Navigate to a type that may have no items; at minimum the page renders
    await page.goto("/dictionaries");
    await expect(page.getByTestId("dictionaries-btn-add")).toBeVisible({
      timeout: 10000,
    });
    // The "goals" tab is less likely to have seeded data
    const goalsTab = page.locator("button", { hasText: "Goals" });
    await goalsTab.click();
    // Either empty state or list should be visible
    const empty = page.getByTestId("dictionaries-empty");
    const list = page.getByTestId("dictionaries-list");
    await expect(empty.or(list)).toBeVisible({ timeout: 10000 });
  });

  test("has dictionary items", async ({ page }) => {
    await page.goto("/dictionaries");
    // Default tab is "grade" which has origin-seeded items
    await expect(page.getByTestId("dictionaries-list")).toBeVisible({
      timeout: 10000,
    });
    const rows = page.getByTestId("dictionaries-list").locator("tbody tr");
    await expect(rows.first()).toBeVisible({ timeout: 10000 });
    expect(await rows.count()).toBeGreaterThanOrEqual(1);
  });

  test("item actions available", async ({ page }) => {
    await page.goto("/dictionaries");
    await expect(page.getByTestId("dictionaries-list")).toBeVisible({
      timeout: 10000,
    });
    // Click the actions dropdown on the first row
    const firstActionBtn = page
      .getByTestId("dictionaries-list")
      .locator("tbody tr")
      .first()
      .locator("button");
    await firstActionBtn.click();
    // Edit is always available; Delete is hidden for Source=System rows
    // (HRP-286) — we only assert Edit here.
    const editBtn = page.locator('[data-testid$="-btn-edit"]').first();
    await expect(editBtn).toBeVisible({ timeout: 10000 });
  });

  test("add button opens create form", async ({ page }) => {
    await page.goto("/dictionaries");
    await expect(page.getByTestId("dictionaries-btn-add")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("dictionaries-btn-add").click();
    await expect(page.getByTestId("dictionaries-modal-form")).toBeVisible({
      timeout: 10000,
    });
  });
});
