import { test, expect } from "@playwright/test";
import {
  registerUser,
  setAuthTokens,
  createInvitation,
  skipUnlessMultiLocaleStand,
} from "./helpers";

test.describe("Profile settings", () => {
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

  test("profile page renders", async ({ page }) => {
    await page.goto("/settings/profile");
    await expect(
      page.getByTestId("settings-profile-input-firstname"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("settings-profile-input-lastname"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("settings-profile-info-email"),
    ).toBeVisible({ timeout: 10000 });
  });

  test("interface-language select visible on multi-locale deployments", async ({
    page,
  }) => {
    // F7 (HRP-481): CI runs multi-locale (AVAILABLE_LOCALES=de,en); on a
    // single-locale stack the select is hidden, so the check is gated —
    // on what the stand actually serves (HRP-511 e), not on env alone.
    await page.goto("/settings/profile");
    await skipUnlessMultiLocaleStand(page);
    await expect(
      page.getByTestId("settings-profile-select-language"),
    ).toBeVisible({ timeout: 10000 });
  });

  test("language switcher flips the interface to German and back", async ({
    page,
  }) => {
    await page.goto("/settings/profile");
    await skipUnlessMultiLocaleStand(page);
    const trigger = page.getByTestId("header-btn-language");
    await expect(trigger).toBeVisible({ timeout: 10000 });
    // The trigger's aria-label is t(common.changeLanguage) — it re-renders
    // in the selected locale after router.refresh(), which makes it a
    // stable signal that the de catalog actually took over.
    await trigger.click();
    await page.getByTestId("header-menu-language-de").click();
    await expect(trigger).toHaveAttribute("aria-label", "Sprache ändern", {
      timeout: 10000,
    });
    await trigger.click();
    await page.getByTestId("header-menu-language-en").click();
    await expect(trigger).toHaveAttribute("aria-label", "Change language", {
      timeout: 10000,
    });
  });

  test("profile inputs have values", async ({ page }) => {
    await page.goto("/settings/profile");
    await expect(
      page.getByTestId("settings-profile-input-firstname"),
    ).toBeVisible({ timeout: 10000 });
    // Registration sets first_name="E2E", last_name="Tester"
    await expect(
      page.getByTestId("settings-profile-input-firstname"),
    ).not.toHaveValue("", { timeout: 10000 });
    await expect(
      page.getByTestId("settings-profile-input-lastname"),
    ).not.toHaveValue("", { timeout: 10000 });
  });

  test("save button visible", async ({ page }) => {
    await page.goto("/settings/profile");
    await expect(page.getByTestId("settings-profile-btn-save")).toBeVisible({
      timeout: 10000,
    });
  });

  test("avatar section visible", async ({ page }) => {
    await page.goto("/settings/profile");
    await expect(page.getByTestId("settings-profile-avatar")).toBeVisible({
      timeout: 10000,
    });
  });

  test("upload avatar button visible", async ({ page }) => {
    await page.goto("/settings/profile");
    await expect(
      page.getByTestId("settings-profile-btn-upload-avatar"),
    ).toBeVisible({ timeout: 10000 });
  });

  test("password change form visible", async ({ page }) => {
    await page.goto("/settings/profile");
    await expect(
      page.getByTestId("settings-password-input-current"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("settings-password-input-new"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("settings-password-input-confirm"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("settings-password-btn-submit"),
    ).toBeVisible({ timeout: 10000 });
  });

  test("email is read-only", async ({ page }) => {
    await page.goto("/settings/profile");
    await expect(
      page.getByTestId("settings-profile-info-email"),
    ).toBeVisible({ timeout: 10000 });
    const emailText = await page
      .getByTestId("settings-profile-info-email")
      .textContent();
    expect(emailText).toContain("@");
  });
});

test.describe("Invitations", () => {
  let accessToken: string;
  let refreshToken: string;
  let invitationId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const creds = await registerUser(page);
    accessToken = creds.accessToken;
    refreshToken = creds.refreshToken;
    // Create an invitation via API
    const inv = await createInvitation(
      { page, accessToken },
      "invited-user@example.com",
      "employee",
    );
    invitationId = inv.id;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("invitations page renders", async ({ page }) => {
    await page.goto("/settings/invitations");
    await expect(page.getByTestId("invitations-table")).toBeVisible({
      timeout: 10000,
    });
  });

  test("invite button visible", async ({ page }) => {
    await page.goto("/settings/invitations");
    await expect(page.getByTestId("invitations-btn-invite")).toBeVisible({
      timeout: 10000,
    });
  });

  test("invitation row visible", async ({ page }) => {
    await page.goto("/settings/invitations");
    await expect(
      page.getByTestId(`invitations-row-${invitationId}`),
    ).toBeVisible({ timeout: 10000 });
  });

  test("invitation status badge", async ({ page }) => {
    await page.goto("/settings/invitations");
    await expect(
      page.getByTestId(`invitations-row-${invitationId}-status`),
    ).toBeVisible({ timeout: 10000 });
  });

  test("revoke button visible", async ({ page }) => {
    await page.goto("/settings/invitations");
    await expect(
      page.getByTestId(`invitations-row-${invitationId}-btn-revoke`),
    ).toBeVisible({ timeout: 10000 });
  });

  test("invite dialog opens", async ({ page }) => {
    await page.goto("/settings/invitations");
    await expect(page.getByTestId("invitations-btn-invite")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("invitations-btn-invite").click();
    await expect(
      page.getByTestId("invitations-modal-invite"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("invitations-modal-invite-input-email"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("invitations-modal-invite-select-role"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("invitations-modal-invite-btn-submit"),
    ).toBeVisible({ timeout: 10000 });
  });
});
