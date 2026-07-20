import { test, expect } from "@playwright/test";
import {
  registerUser,
  setAuthTokens,
  createPosition,
  setupFullTenant,
} from "./helpers";

test.describe("Positions page", () => {
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

  test("positions page loads with empty state", async ({ page }) => {
    await page.goto("/company/positions");
    await expect(page.getByTestId("positions-table")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByText("No positions yet"),
    ).toBeVisible({ timeout: 10000 });
  });

  test("tab navigation visible", async ({ page }) => {
    await page.goto("/company/positions");
    await expect(page.getByRole("link", { name: "Overview" })).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByRole("link", { name: "Positions" })).toBeVisible({
      timeout: 10000,
    });
  });

  test("create position button visible", async ({ page }) => {
    await page.goto("/company/positions");
    await expect(page.getByTestId("positions-btn-create")).toBeVisible({
      timeout: 10000,
    });
  });

  test("AI generate button visible", async ({ page }) => {
    await page.goto("/company/positions");
    await expect(page.getByTestId("positions-btn-ai-generate")).toBeVisible({
      timeout: 10000,
    });
  });

  test("open create position dialog", async ({ page }) => {
    await page.goto("/company/positions");
    await page.getByTestId("positions-btn-create").click();
    await expect(page.getByTestId("position-edit-dialog")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId("position-edit-input-title"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("position-edit-select-specialization"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("position-edit-select-grade"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("position-edit-select-division"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("position-edit-input-headcount"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("position-edit-btn-save"),
    ).toBeVisible({ timeout: 10000 });
  });

  test("close create dialog with cancel", async ({ page }) => {
    await page.goto("/company/positions");
    await page.getByTestId("positions-btn-create").click();
    await expect(page.getByTestId("position-edit-dialog")).toBeVisible({
      timeout: 10000,
    });
    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(
      page.getByTestId("position-edit-dialog"),
    ).not.toBeVisible({ timeout: 10000 });
  });

  test("search input visible", async ({ page }) => {
    await page.goto("/company/positions");
    await expect(page.getByTestId("positions-search")).toBeVisible({
      timeout: 10000,
    });
  });
});

test.describe("Positions CRUD", () => {
  let accessToken: string;
  let refreshToken: string;
  let positionId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const creds = await registerUser(page);
    accessToken = creds.accessToken;
    refreshToken = creds.refreshToken;
    const pos = await createPosition(
      { page, accessToken },
      "Backend Developer",
    );
    positionId = pos.id;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("position table shows created position", async ({ page }) => {
    await page.goto("/company/positions");
    await expect(page.getByTestId("positions-table")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId(`positions-row-${positionId}`),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId(`positions-row-${positionId}`),
    ).toContainText("Backend Developer");
  });

  // HRP-399: the 409 duplicate-title conflict must surface inside the dialog
  // instead of leaving it silently open.
  test("duplicate title shows a conflict error in the dialog", async ({
    page,
  }) => {
    await page.goto("/company/positions");
    await page.getByTestId("positions-btn-create").click();
    await expect(page.getByTestId("position-edit-dialog")).toBeVisible({
      timeout: 10000,
    });
    await page
      .getByTestId("position-edit-input-title")
      .fill("Backend Developer");
    await page.getByTestId("position-edit-btn-save").click();

    await expect(page.getByTestId("position-edit-error")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("position-edit-error")).toContainText(
      "already exists",
    );
    // Dialog stays open and the save button leaves its loading state.
    await expect(page.getByTestId("position-edit-dialog")).toBeVisible();
    await expect(page.getByTestId("position-edit-btn-save")).toBeEnabled();
  });

  test("create position via dialog", async ({ page }) => {
    await page.goto("/company/positions");
    await page.getByTestId("positions-btn-create").click();
    await page
      .getByTestId("position-edit-input-title")
      .fill("QA Engineer");
    await page.getByTestId("position-edit-btn-save").click();
    await expect(
      page.getByTestId("position-edit-dialog"),
    ).not.toBeVisible({ timeout: 10000 });
    await expect(page.getByText("QA Engineer")).toBeVisible({
      timeout: 10000,
    });
  });

  test("search filters positions", async ({ page }) => {
    await page.goto("/company/positions");
    await expect(page.getByTestId("positions-table")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("positions-search").fill("Backend");
    await page.waitForTimeout(500);
    await expect(page.getByText("Backend Developer")).toBeVisible({
      timeout: 10000,
    });
  });

  test("tab navigation to overview works", async ({ page }) => {
    await page.goto("/company/positions");
    await page.getByRole("link", { name: "Overview" }).click();
    await expect(page.getByTestId("company-card-info")).toBeVisible({
      timeout: 10000,
    });
  });

  test("edit position via actions menu", async ({ page }) => {
    await page.goto("/company/positions");
    await expect(
      page.getByTestId(`positions-row-${positionId}`),
    ).toBeVisible({ timeout: 10000 });
    // Open dropdown — POS6 added a headcount drilldown button to the row,
    // so target the actions trigger by its testid instead of `getByRole`.
    await page.getByTestId(`positions-row-${positionId}-actions`).click();
    await page.getByRole("menuitem", { name: "Edit" }).click();
    await expect(page.getByTestId("position-edit-dialog")).toBeVisible({
      timeout: 10000,
    });
    // Change title
    const titleInput = page.getByTestId("position-edit-input-title");
    await titleInput.clear();
    await titleInput.fill("Lead Backend Developer");
    await page.getByTestId("position-edit-btn-save").click();
    await expect(
      page.getByTestId("position-edit-dialog"),
    ).not.toBeVisible({ timeout: 10000 });
    await expect(page.getByText("Lead Backend Developer")).toBeVisible({
      timeout: 10000,
    });
  });

  test("delete position without employees", async ({ page }) => {
    // Create a temporary position to delete
    const tempPos = await createPosition(
      { page, accessToken },
      "Temp To Delete",
    );
    await page.goto("/company/positions");
    await expect(
      page.getByTestId(`positions-row-${tempPos.id}`),
    ).toBeVisible({ timeout: 10000 });
    // Open dropdown — see edit-test note about POS6 headcount button.
    await page.getByTestId(`positions-row-${tempPos.id}-actions`).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();
    // Confirm dialog
    await expect(page.getByTestId("confirm-dialog")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("confirm-dialog-btn-confirm").click();
    await expect(
      page.getByTestId(`positions-row-${tempPos.id}`),
    ).not.toBeVisible({ timeout: 10000 });
  });
});

test.describe("Position in Employee flow", () => {
  let accessToken: string;
  let refreshToken: string;
  let employeeId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const setup = await setupFullTenant(page);
    accessToken = setup.accessToken;
    refreshToken = setup.refreshToken;
    employeeId = setup.employeeId;
    await createPosition({ page, accessToken }, "Full Stack Developer");
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("position combobox visible in employee create dialog", async ({
    page,
  }) => {
    await page.goto("/employees");
    await page.getByTestId("employees-btn-create").click();
    await expect(
      page.getByTestId("employees-modal-create-input-position"),
    ).toBeVisible({ timeout: 10000 });
  });

  test("position combobox visible in employee edit dialog", async ({
    page,
  }) => {
    await page.goto("/employees");
    await page.getByTestId(`employees-row-${employeeId}-actions`).click();
    await page.getByTestId(`employees-row-${employeeId}-btn-edit`).click();
    await expect(
      page.getByTestId("employees-modal-edit-input-position"),
    ).toBeVisible({ timeout: 10000 });
  });

  test("position combobox opens and shows positions", async ({ page }) => {
    await page.goto("/employees");
    await page.getByTestId("employees-btn-create").click();
    await expect(page.getByTestId("employees-modal-create")).toBeVisible({
      timeout: 10000,
    });
    // Click combobox trigger
    await page.getByTestId("employees-modal-create-input-position").click();
    // Search for position
    await page.getByPlaceholder("Search positions...").fill("Full Stack");
    await page.waitForTimeout(500);
    await expect(page.getByText("Full Stack Developer")).toBeVisible({
      timeout: 10000,
    });
  });
});

test.describe("Positions POS0 quick wins", () => {
  let accessToken: string;
  let refreshToken: string;
  let positionId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const creds = await registerUser(page);
    accessToken = creds.accessToken;
    refreshToken = creds.refreshToken;
    const pos = await createPosition({ page, accessToken }, "POS0 Drilldown");
    positionId = pos.id;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("Division column header is rendered", async ({ page }) => {
    await page.goto("/company/positions");
    await expect(page.getByTestId("positions-table")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId("positions-table").getByRole("columnheader", {
        name: "Division",
      }),
    ).toBeVisible({ timeout: 10000 });
  });

  test("headcount cell opens drill-down with empty state", async ({ page }) => {
    await page.goto("/company/positions");
    await expect(
      page.getByTestId(`positions-row-${positionId}`),
    ).toBeVisible({ timeout: 10000 });
    await page.getByTestId(`positions-row-${positionId}-headcount`).click();
    await expect(page.getByTestId("positions-drilldown")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId("positions-drilldown-empty"),
    ).toBeVisible({ timeout: 10000 });
  });
});

test.describe("Positions POS6 lifecycle + occupancy + alerts", () => {
  let accessToken: string;
  let refreshToken: string;
  let positionId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const setup = await setupFullTenant(page);
    accessToken = setup.accessToken;
    refreshToken = setup.refreshToken;

    const opts = { page, accessToken };

    // Position with capped headcount; the existing employee gets reassigned
    // to it so the drill-down has a row to render.
    const pos = await createPosition(opts, "POS6 Filled", {
      headcount: 2,
      division_id: setup.divisionId,
    });
    positionId = pos.id;

    const assignResp = await page.request.put(
      `http://localhost:8100/api/employees/${setup.employeeId}`,
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        data: { position_id: positionId },
      },
    );
    if (!assignResp.ok()) {
      throw new Error(`assign failed (${assignResp.status()})`);
    }

    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("Status column shows the lifecycle badge", async ({ page }) => {
    await page.goto("/company/positions");
    await expect(
      page.getByTestId(`positions-row-${positionId}-status`),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId(`positions-row-${positionId}-status`),
    ).toHaveAttribute("data-status", "active");
  });

  test("Filled / Plan column shows occupancy ratio", async ({ page }) => {
    await page.goto("/company/positions");
    await expect(
      page.getByTestId(`positions-row-${positionId}-headcount`),
    ).toContainText("1/2", { timeout: 10000 });
  });

  test("Drill-down lists assigned employees via shared row component", async ({
    page,
  }) => {
    await page.goto("/company/positions");
    await page.getByTestId(`positions-row-${positionId}-headcount`).click();
    await expect(page.getByTestId("positions-drilldown")).toBeVisible({
      timeout: 10000,
    });
    // Exactly one data row inside the drilldown — uses the unified
    // <EmployeeListRow> component (testIdPrefix=positions-drilldown-row).
    // HRP-175 adds a sticky header row (`-header`) so we scope to rows
    // that carry a real employee id via data-employee-id.
    await expect(
      page.locator("li[data-employee-id]"),
    ).toHaveCount(1, { timeout: 10000 });
    // HRP-175: verify the sticky column header row is present.
    await expect(
      page.getByTestId("positions-drilldown-row-header"),
    ).toBeVisible();
    // HRP-175: Specialization column has its own cell now.
    await expect(
      page.getByTestId("positions-drilldown-row-column-specialization"),
    ).toBeVisible();
  });

  test("Status menu transitions the position to closed and disables Edit", async ({
    page,
  }) => {
    await page.goto("/company/positions");
    await page
      .getByTestId(`positions-row-${positionId}-actions`)
      .click();
    await page
      .getByTestId(`positions-row-${positionId}-btn-status-closed`)
      .click();
    await expect(
      page.getByTestId(`positions-row-${positionId}-status`),
    ).toHaveAttribute("data-status", "closed", { timeout: 10000 });

    // Re-open the actions menu — Edit must be disabled while closed.
    await page
      .getByTestId(`positions-row-${positionId}-actions`)
      .click();
    await expect(
      page.getByTestId(`positions-row-${positionId}-btn-edit`),
    ).toHaveAttribute("data-disabled", /.*/, { timeout: 10000 });

    // Reopen for downstream tests (this describe block is order-sensitive).
    await page
      .getByTestId(`positions-row-${positionId}-btn-status-active`)
      .click();
    await expect(
      page.getByTestId(`positions-row-${positionId}-status`),
    ).toHaveAttribute("data-status", "active", { timeout: 10000 });
  });
});
