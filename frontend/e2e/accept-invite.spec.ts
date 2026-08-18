import { test, expect } from "./fixtures";
import {
  API_BASE,
  createInvitation,
  registerUser,
  revealInvitationToken,
  uniqueEmail,
} from "./helpers";

/**
 * HRP-435: the accept page pre-fills First/Last name by splitting the single
 * `Name` the inviter typed. Both fields stay editable.
 */
test.describe("Accept invitation — prefill from the invitation", () => {
  let adminAccess: string;
  let inviteToken: string;
  let inviteEmail: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const admin = await registerUser(page);
    adminAccess = admin.accessToken;

    inviteEmail = uniqueEmail();
    const inv = await createInvitation(
      { page, accessToken: adminAccess },
      inviteEmail,
      "employee",
      { name: "Anna Maria Schmidt" },
    );

    inviteToken = await revealInvitationToken(
      { page, accessToken: adminAccess },
      inv.id,
    );

    await page.close();
  });

  test("first name and last name are pre-filled from the invitation name", async ({
    page,
  }) => {
    await page.goto(`/accept-invite?token=${inviteToken}`);

    await expect(page.getByTestId("accept-invite-input-firstname")).toHaveValue(
      "Anna",
      { timeout: 10000 },
    );
    // Everything after the first space stays together as the last name.
    await expect(page.getByTestId("accept-invite-input-lastname")).toHaveValue(
      "Maria Schmidt",
    );
    // The invited address is shown, never dumped into a name field.
    await expect(page.getByTestId("accept-invite-input-email")).toHaveValue(
      inviteEmail,
    );
  });

  test("pre-filled names remain editable", async ({ page }) => {
    await page.goto(`/accept-invite?token=${inviteToken}`);

    const firstName = page.getByTestId("accept-invite-input-firstname");
    await expect(firstName).toHaveValue("Anna", { timeout: 10000 });

    await firstName.fill("Annika");
    await expect(firstName).toHaveValue("Annika");
  });

  test("an unknown token surfaces an error and locks the form", async ({
    page,
  }) => {
    await page.goto("/accept-invite?token=definitely-not-a-real-token");

    await expect(page.getByTestId("accept-invite-error")).toBeVisible({
      timeout: 10000,
    });
    // Nothing to submit — don't let the visitor fill it in for a second error.
    await expect(page.getByTestId("accept-invite-btn-submit")).toBeDisabled();
  });

  // The user-visible outcome of the ticket: accepting with the pre-filled
  // values creates an account carrying that split name.
  test("the pre-filled name lands on the created account", async ({ page }) => {
    const email = uniqueEmail();
    const admin = await registerUser(page);
    const inv = await createInvitation(
      { page, accessToken: admin.accessToken },
      email,
      "employee",
      { name: "Bjorn Erik Larsen" },
    );
    const token = await revealInvitationToken(
      { page, accessToken: admin.accessToken },
      inv.id,
    );

    await page.goto(`/accept-invite?token=${token}`);
    await expect(page.getByTestId("accept-invite-input-firstname")).toHaveValue(
      "Bjorn",
      { timeout: 10000 },
    );
    await expect(page.getByTestId("accept-invite-input-lastname")).toHaveValue(
      "Erik Larsen",
    );

    await page.getByTestId("accept-invite-input-password").fill("newpass12345");
    await page.getByTestId("accept-invite-btn-submit").click();

    // A fresh tenant has not completed onboarding, so the new member lands
    // there rather than on the dashboard — either way the account exists.
    await expect(page).toHaveURL(/\/(dashboard|onboarding)$/, {
      timeout: 15000,
    });

    const me = await page.request.get(`${API_BASE}/auth/me`, {
      headers: {
        Authorization: `Bearer ${await page.evaluate(() =>
          localStorage.getItem("access_token"),
        )}`,
      },
    });
    expect(me.ok()).toBeTruthy();
    const body = await me.json();
    expect(body.first_name).toBe("Bjorn");
    expect(body.last_name).toBe("Erik Larsen");
  });
});
