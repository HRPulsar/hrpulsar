import { test, expect } from "./fixtures";
import { registerUser, setAuthTokens, uniqueEmail } from "./helpers";

const API_BASE = "http://localhost:8100/api";

/**
 * EMP3 — division manager assignment auto-upgrades a user's role; clearing
 * the assignment surfaces the role-downgrade-dialog and demotes back to
 * employee on confirm.
 */

interface AliceContext {
  email: string;
  employeeId: string;
  userId: string;
  accessToken: string;
}

async function provisionAliceAsEmployee(
  page: import("@playwright/test").Page,
  adminAccessToken: string,
): Promise<AliceContext> {
  // Need a division so `accept_invitation` actually materialises the
  // Employee record (the service only creates one if division_id or
  // position_id is set on the invitation).
  const seedDiv = await (
    await page.request.post(`${API_BASE}/divisions`, {
      headers: { Authorization: `Bearer ${adminAccessToken}` },
      data: { name: `Seed ${Date.now()}-${Math.random().toString(36).slice(2)}` },
    })
  ).json();

  const aliceEmail = uniqueEmail();
  const invite = await (
    await page.request.post(`${API_BASE}/invitations`, {
      headers: { Authorization: `Bearer ${adminAccessToken}` },
      data: {
        email: aliceEmail,
        name: "Alice Manager",
        role_code: "employee",
        division_id: seedDiv.id,
      },
    })
  ).json();

  const tokenResp = await page.request.get(
    `${API_BASE}/auth/dev/invitations/${invite.id}/token`,
    { headers: { Authorization: `Bearer ${adminAccessToken}` } },
  );
  if (!tokenResp.ok()) {
    throw new Error(
      `dev invitation-token endpoint not available (${tokenResp.status()}); ` +
        `is E2E_MODE=true on the backend?`,
    );
  }
  const { token } = await tokenResp.json();

  const acceptResp = await page.request.post(`${API_BASE}/auth/accept-invite`, {
    data: {
      token,
      password: "alicepass123",
      first_name: "Alice",
      last_name: "Manager",
    },
  });
  expect(acceptResp.ok()).toBeTruthy();
  const aliceCreds = await acceptResp.json();

  const empList = await (
    await page.request.get(`${API_BASE}/employees?limit=100`, {
      headers: { Authorization: `Bearer ${adminAccessToken}` },
    })
  ).json();
  const alice = empList.items.find(
    (e: { user_email: string }) => e.user_email === aliceEmail,
  );
  expect(alice, "Alice Employee row not found").toBeTruthy();

  return {
    email: aliceEmail,
    employeeId: alice.id,
    userId: alice.user_id,
    accessToken: aliceCreds.access_token,
  };
}

test.describe("EMP3 division role sync", () => {
  test("API: assign upgrades; clearing returns pending; downgrade strips manager", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const alice = await provisionAliceAsEmployee(page, admin.accessToken);

    // 1. Create a division with Alice as manager → role upgrade.
    const div = await (
      await page.request.post(`${API_BASE}/divisions`, {
        headers: { Authorization: `Bearer ${admin.accessToken}` },
        data: {
          name: `R&D ${Date.now()}`,
          manager_id: alice.employeeId,
        },
      })
    ).json();

    let aliceMe = await (
      await page.request.get(`${API_BASE}/auth/me`, {
        headers: { Authorization: `Bearer ${alice.accessToken}` },
      })
    ).json();
    expect(aliceMe.roles).toContain("manager");

    // 2. Clear manager via API → response carries pending_role_downgrade.
    const updated = await (
      await page.request.put(`${API_BASE}/divisions/${div.id}`, {
        headers: { Authorization: `Bearer ${admin.accessToken}` },
        data: { manager_id: null },
      })
    ).json();
    expect(updated.pending_role_downgrade.length).toBe(1);
    expect(updated.pending_role_downgrade[0].employee_id).toBe(alice.employeeId);

    // 3. Hit the downgrade endpoint and verify role removed.
    const downgrade = await page.request.post(
      `${API_BASE}/employees/${alice.employeeId}/downgrade-role`,
      { headers: { Authorization: `Bearer ${admin.accessToken}` } },
    );
    expect(downgrade.ok()).toBeTruthy();

    aliceMe = await (
      await page.request.get(`${API_BASE}/auth/me`, {
        headers: { Authorization: `Bearer ${alice.accessToken}` },
      })
    ).json();
    expect(aliceMe.roles).not.toContain("manager");
  });

  test("UI: clearing manager via the company dialog auto-downgrades silently (HRP-196)", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const alice = await provisionAliceAsEmployee(page, admin.accessToken);

    const div = await (
      await page.request.post(`${API_BASE}/divisions`, {
        headers: { Authorization: `Bearer ${admin.accessToken}` },
        data: { name: `Sales ${Date.now()}`, manager_id: alice.employeeId },
      })
    ).json();

    await setAuthTokens(page, admin.accessToken, admin.refreshToken);
    await page.goto("/company");
    const row = page.getByTestId(`company-division-${div.id}`);
    await row.waitFor({ timeout: 15000 });

    // Open the kebab menu and click Edit.
    await row.getByRole("button").first().click();
    await page.getByText("Edit", { exact: true }).first().click();

    // Switch the manager Select to None.
    await page.getByTestId("company-modal-division-select-manager").click();
    await page.getByRole("option", { name: "None" }).click();
    await page.getByTestId("company-modal-division-btn-submit").click();

    // HRP-196: backend now auto-downgrades when the user loses their last
    // managed division; no confirm dialog appears, the FE only shows a
    // toast and the role is already stripped by the time the PUT returns.
    await expect(page.getByTestId("role-downgrade-dialog")).toBeHidden({
      timeout: 2000,
    });

    // Verify Alice's role was actually stripped — the auto-downgrade is
    // synchronous server-side, but we poll so /auth/me observes the
    // updated user_roles row even under CI load.
    await expect
      .poll(
        async () => {
          const me = await (
            await page.request.get(`${API_BASE}/auth/me`, {
              headers: { Authorization: `Bearer ${alice.accessToken}` },
            })
          ).json();
          return me.roles as string[];
        },
        { timeout: 10000 },
      )
      .not.toContain("manager");
  });
});
