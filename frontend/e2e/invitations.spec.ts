import { test, expect } from "@playwright/test";
import { registerUser, setAuthTokens, createInvitation } from "./helpers";

test.describe("Invitations — INV1 (Name + Division column + reordered columns)", () => {
  let accessToken: string;
  let refreshToken: string;
  let invitationId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const creds = await registerUser(page);
    accessToken = creds.accessToken;
    refreshToken = creds.refreshToken;

    const inv = await createInvitation(
      { page, accessToken },
      "inv1-target@example.com",
      "employee",
      { name: "INV1 Target" },
    );
    invitationId = inv.id;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("modal requires name, email, division and position before submit", async ({
    page,
  }) => {
    // HRP-195: Send invitation must collect Name + Email + Division +
    // Position. The Position picker stays empty in this test, so the
    // submit must remain disabled even after every other field is set.
    await page.goto("/settings/invitations");
    await expect(page.getByTestId("invitations-btn-invite")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("invitations-btn-invite").click();

    const nameInput = page.getByTestId("invitations-modal-invite-input-name");
    await expect(nameInput).toBeVisible({ timeout: 10000 });

    const submit = page.getByTestId("invitations-modal-invite-btn-submit");
    await page
      .getByTestId("invitations-modal-invite-input-email")
      .fill("disabled-without-name@example.com");
    await expect(submit).toBeDisabled();

    // Filling the name alone is no longer enough — division + position
    // are still missing.
    await nameInput.fill("Anna Doe");
    await expect(submit).toBeDisabled();
  });

  test("table exposes Name and Division cells with the new column order", async ({
    page,
  }) => {
    await page.goto("/settings/invitations");
    await expect(page.getByTestId("invitations-table")).toBeVisible({
      timeout: 10000,
    });

    const nameCell = page.getByTestId(`invitations-row-${invitationId}-name`);
    const divisionCell = page.getByTestId(
      `invitations-row-${invitationId}-division`,
    );
    await expect(nameCell).toHaveText("INV1 Target", { timeout: 10000 });
    await expect(divisionCell).toBeVisible({ timeout: 10000 });

    // Header order: Name → Email → Role → Division → Position → Status → Invited by → Date → Actions
    const headers = await page
      .getByTestId("invitations-table")
      .locator("thead th")
      .allTextContents();
    expect(headers).toEqual([
      "Name",
      "Email",
      "Role",
      "Division",
      "Position",
      "Status",
      "Invited by",
      "Date",
      "Actions",
    ]);
  });
});
