import { test, expect } from "./fixtures";
import { createInvitation, registerUser, setAuthTokens } from "./helpers";

test.describe("Invitations — INV2 (inline edit + email change)", () => {
  let adminAccess: string;
  let adminRefresh: string;
  let invitationId: string;
  let invitationEmail: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();

    const adminCreds = await registerUser(page);
    adminAccess = adminCreds.accessToken;
    adminRefresh = adminCreds.refreshToken;

    invitationEmail = `inv2-target-${Date.now()}@example.com`;
    const inv = await createInvitation(
      { page, accessToken: adminAccess },
      invitationEmail,
      "employee",
      { name: "INV2 Target" },
    );
    invitationId = inv.id;

    await page.close();
  });

  // HRP-436 moved the manager case (Invitations is admin-only now) to
  // admin-section-access.spec.ts, which owns the whole Admin-group matrix.

  test("admin: all three fields editable + edit-email button available", async ({
    page,
  }) => {
    await setAuthTokens(page, adminAccess, adminRefresh);
    await page.goto("/settings/invitations");
    await expect(page.getByTestId("invitations-table")).toBeVisible({
      timeout: 10000,
    });

    await expect(
      page.getByTestId(`invitations-row-${invitationId}-edit-role`),
    ).toBeVisible();
    await expect(
      page.getByTestId(`invitations-row-${invitationId}-edit-division`),
    ).toBeVisible();
    await expect(
      page.getByTestId(`invitations-row-${invitationId}-edit-position`),
    ).toBeVisible();
    await expect(
      page.getByTestId(`invitations-row-${invitationId}-btn-edit-email`),
    ).toBeVisible();
  });

  test("admin: change invitation email through the modal", async ({ page }) => {
    await setAuthTokens(page, adminAccess, adminRefresh);
    await page.goto("/settings/invitations");
    await expect(page.getByTestId("invitations-table")).toBeVisible({
      timeout: 10000,
    });

    const newEmail = `inv2-rotated-${Date.now()}@example.com`;
    const patchPromise = page.waitForResponse(
      (resp) =>
        resp.url().includes(`/invitations/${invitationId}/email`) &&
        resp.request().method() === "PATCH",
    );

    await page
      .getByTestId(`invitations-row-${invitationId}-btn-edit-email`)
      .click();
    await expect(page.getByTestId("invitations-modal-edit-email")).toBeVisible();
    await page.getByTestId("invitations-modal-edit-email-input").fill(newEmail);
    await page.getByTestId("invitations-modal-edit-email-btn-submit").click();

    const resp = await patchPromise;
    expect(resp.status()).toBe(200);

    // Modal closes after success
    await expect(page.getByTestId("invitations-modal-edit-email")).toHaveCount(
      0,
    );

    // Row email cell reflects the new address
    const row = page.getByTestId(`invitations-row-${invitationId}`);
    await expect(row).toContainText(newEmail);

    // Reset back so the suite stays idempotent for repeated local runs
    invitationEmail = newEmail;
  });
});

test.describe("Invitations — INV3 (optimistic update + rollback)", () => {
  let adminAccess: string;
  let adminRefresh: string;
  let invitationId: string;
  let originalRole: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const adminCreds = await registerUser(page);
    adminAccess = adminCreds.accessToken;
    adminRefresh = adminCreds.refreshToken;

    const inv = await createInvitation(
      { page, accessToken: adminAccess },
      `inv3-target-${Date.now()}@example.com`,
      "employee",
      { name: "INV3 Target" },
    );
    invitationId = inv.id;
    originalRole = inv.role_code;

    await page.close();
  });

  test("PATCH 500 → toast + row reverts to original role", async ({ page }) => {
    await setAuthTokens(page, adminAccess, adminRefresh);

    // Force PATCH /api/invitations/{id} to fail; let other calls (incl. /email) pass through.
    await page.route(
      (url) => {
        const path = new URL(url).pathname;
        return /\/api\/invitations\/[^/]+$/.test(path);
      },
      async (route) => {
        if (route.request().method() === "PATCH") {
          await route.fulfill({
            status: 500,
            contentType: "application/json",
            body: JSON.stringify({ detail: "Boom" }),
          });
          return;
        }
        await route.continue();
      },
    );

    await page.goto("/settings/invitations");
    await expect(page.getByTestId("invitations-table")).toBeVisible({
      timeout: 10000,
    });

    const roleTrigger = page.getByTestId(
      `invitations-row-${invitationId}-edit-role`,
    );
    await expect(roleTrigger).toBeVisible();
    await expect(roleTrigger).toContainText(originalRole, {
      ignoreCase: true,
    });

    // Pick any role different from current; "manager" is always present in seed data.
    const targetRole = originalRole === "manager" ? "admin" : "manager";

    await roleTrigger.click();
    await page.getByRole("option", { name: new RegExp(targetRole, "i") }).click();

    // Toast surfaces the error (sonner renders into [data-sonner-toaster]).
    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: /boom|failed/i }),
    ).toBeVisible({ timeout: 5000 });

    // After load() rollback, the trigger shows the original role again.
    await expect(roleTrigger).toContainText(originalRole, {
      ignoreCase: true,
      timeout: 5000,
    });
  });
});
