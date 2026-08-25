import { test, expect } from "./fixtures";
import {
  API_BASE,
  createDivision,
  provisionTenantMember,
  registerUser,
  setAuthTokens,
} from "./helpers";

/**
 * HRP-620 / HRP-621 — the role is visible in the employee list and on the
 * card, and an admin changes it from the card. Before this, the only role
 * mutation in the product was "strip manager", and a role was only ever
 * rendered in the holder's own sidebar footer.
 */
test.describe("HRP-621 employee role management", () => {
  test("API: recruiter is invitable and the list filters by role", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const opts = { page, accessToken: admin.accessToken };
    const division = await createDivision(opts, `Roles ${Date.now()}`);
    const member = await provisionTenantMember(opts, {
      roleCode: "recruiter",
      divisionId: division.id,
      firstName: "Rita",
      lastName: "Recruiter",
    });

    const list = await (
      await page.request.get(`${API_BASE}/employees?role=recruiter&limit=100`, {
        headers: { Authorization: `Bearer ${admin.accessToken}` },
      })
    ).json();

    const row = list.items.find((e: { id: string }) => e.id === member.employeeId);
    expect(row, "role filter dropped the recruiter").toBeTruthy();
    expect(row.roles).toContain("recruiter");
  });

  test("UI: the list shows a role column and an admin changes it on the card", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const opts = { page, accessToken: admin.accessToken };
    const division = await createDivision(opts, `Roles ${Date.now()}`);
    const member = await provisionTenantMember(opts, {
      roleCode: "employee",
      divisionId: division.id,
      firstName: "Ellie",
      lastName: "Employee",
    });
    await setAuthTokens(page, admin.accessToken, admin.refreshToken);

    await page.goto("/employees");
    await expect(
      page.getByTestId(`employees-row-${member.employeeId}-role`),
    ).toBeVisible({ timeout: 15000 });

    await page.goto(`/employees/${member.employeeId}`);
    const select = page.getByTestId("employee-detail-select-role");
    await expect(select).toBeVisible({ timeout: 15000 });
    await select.click();
    await page.getByRole("option", { name: "Manager", exact: true }).click();

    await expect
      .poll(
        async () => {
          const emp = await (
            await page.request.get(
              `${API_BASE}/employees/${member.employeeId}`,
              { headers: { Authorization: `Bearer ${admin.accessToken}` } },
            )
          ).json();
          return emp.roles as string[];
        },
        { timeout: 15000 },
      )
      .toContain("manager");
  });

  test("UI: a non-admin sees the role as a read-only badge", async ({ page }) => {
    const admin = await registerUser(page);
    const opts = { page, accessToken: admin.accessToken };
    const division = await createDivision(opts, `Roles ${Date.now()}`);
    const member = await provisionTenantMember(opts, {
      roleCode: "employee",
      divisionId: division.id,
      firstName: "Ellie",
      lastName: "Employee",
    });

    await setAuthTokens(page, member.accessToken, member.refreshToken);
    await page.goto(`/employees/${member.employeeId}`);
    await expect(page.getByTestId("employee-detail-role-badge")).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByTestId("employee-detail-select-role")).toHaveCount(0);
  });
});
