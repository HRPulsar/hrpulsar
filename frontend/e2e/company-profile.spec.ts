import type { Page } from "@playwright/test";

import { test, expect } from "./fixtures";
import {
  provisionTenantMember,
  registerUser,
  setAuthTokens,
  setupFullTenant,
} from "./helpers";

test.describe("Company profile page", () => {
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

  test("Profile tab visible in Company section", async ({ page }) => {
    await page.goto("/company");
    await expect(page.getByTestId("company-tab-profile")).toBeVisible({
      timeout: 10000,
    });
  });

  test("Profile tab navigates to /company/profile", async ({ page }) => {
    await page.goto("/company");
    await page.getByTestId("company-tab-profile").click();
    await expect(page).toHaveURL(/\/company\/profile$/, { timeout: 10000 });
    await expect(page.getByTestId("company-profile-card-fields")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("company-profile-card-logo")).toBeVisible({
      timeout: 10000,
    });
  });

  test("admin can edit description, industry, size, website", async ({
    page,
  }) => {
    await page.goto("/company/profile");
    await expect(page.getByTestId("company-profile-input-description")).toBeVisible({
      timeout: 10000,
    });

    const desc = `E2E description ${Date.now()}`;
    const industry = `E2E Industry ${Date.now()}`;
    const website = "https://e2e-company.test";

    await page.getByTestId("company-profile-input-description").fill(desc);
    await page.getByTestId("company-profile-input-industry").fill(industry);
    await page.getByTestId("company-profile-input-website").fill(website);

    await page.getByTestId("company-profile-input-size").click();
    await page.getByRole("option", { name: /51-200 employees/ }).click();

    await page.getByTestId("company-profile-btn-save").click();
    await expect(page.getByText("Company profile saved")).toBeVisible({
      timeout: 10000,
    });

    await page.reload();
    await expect(
      page.getByTestId("company-profile-input-description"),
    ).toHaveValue(desc, { timeout: 10000 });
    await expect(
      page.getByTestId("company-profile-input-industry"),
    ).toHaveValue(industry, { timeout: 10000 });
    await expect(
      page.getByTestId("company-profile-input-website"),
    ).toHaveValue(website, { timeout: 10000 });
    await expect(page.getByTestId("company-profile-input-size")).toContainText(
      "51-200",
      { timeout: 10000 },
    );
  });
});

test.describe("Company profile read-only for non-admin", () => {
  let memberAccessToken: string;
  let memberRefreshToken: string;
  let employeeAccessToken: string;
  let employeeRefreshToken: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const adminCreds = await registerUser(page);
    // HRP-622: a plain employee no longer opens the profile at all, so the
    // read-only view is checked on another role below the admin.
    const member = await provisionTenantMember(
      { page, accessToken: adminCreds.accessToken },
      { roleCode: "hr" },
    );
    memberAccessToken = member.accessToken;
    memberRefreshToken = member.refreshToken;
    const employee = await provisionTenantMember(
      { page, accessToken: adminCreds.accessToken },
      { roleCode: "employee" },
    );
    employeeAccessToken = employee.accessToken;
    employeeRefreshToken = employee.refreshToken;
    await page.close();
  });

  test("employee keeps the overview tab only, direct links bounce (HRP-622)", async ({
    page,
  }) => {
    await setAuthTokens(page, employeeAccessToken, employeeRefreshToken);
    await page.goto("/company");
    await expect(page.getByTestId("company-tab-overview")).toBeVisible({
      timeout: 10000,
    });
    for (const tab of ["profile", "positions", "specializations"]) {
      await expect(page.getByTestId(`company-tab-${tab}`)).toHaveCount(0);
    }
    for (const path of [
      "/company/profile",
      "/company/positions",
      "/company/specializations",
    ]) {
      await page.goto(path);
      await expect(page, path).toHaveURL(/\/dashboard$/, { timeout: 10000 });
      await expect(
        page
          .locator("[data-sonner-toast]")
          .filter({ hasText: /don't have permission/i })
          .first(),
      ).toBeVisible();
    }
  });

  test("non-admin sees fields disabled and no save button", async ({ page }) => {
    await setAuthTokens(page, memberAccessToken, memberRefreshToken);
    await page.goto("/company/profile");

    await expect(page.getByTestId("company-profile-card-fields")).toBeVisible({
      timeout: 10000,
    });

    await expect(
      page.getByTestId("company-profile-input-description"),
    ).toBeDisabled();
    await expect(
      page.getByTestId("company-profile-input-industry"),
    ).toBeDisabled();
    await expect(
      page.getByTestId("company-profile-input-website"),
    ).toBeDisabled();
    await expect(page.getByTestId("company-profile-input-size")).toBeDisabled();
    await expect(page.getByTestId("company-profile-input-region")).toBeDisabled();

    await expect(page.getByTestId("company-profile-btn-save")).toHaveCount(0);
    await expect(
      page.getByTestId("company-profile-btn-upload-logo"),
    ).toBeDisabled();

    await expect(
      page.getByText("Only admins can edit the company profile."),
    ).toBeVisible({ timeout: 10000 });
  });
});

test.describe("Company region drives the education levels (HRP-1066)", () => {
  let accessToken: string;
  let refreshToken: string;
  let employeeId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const setup = await setupFullTenant(page);
    accessToken = setup.accessToken;
    refreshToken = setup.refreshToken;
    employeeId = setup.employeeId;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  async function pickRegion(page: Page, name: string) {
    await page.goto("/company/profile");
    const region = page.getByTestId("company-profile-input-region");
    await expect(region).toBeEnabled({ timeout: 10000 });
    await region.click();
    await page.getByRole("option", { name, exact: true }).click();
    await page.getByTestId("company-profile-btn-save").click();
    await expect(page.getByText("Company profile saved")).toBeVisible({
      timeout: 10000,
    });
    await page.reload();
    await expect(page.getByTestId("company-profile-input-region")).toContainText(
      name,
      { timeout: 10000 },
    );
  }

  async function degreeOptions(page: Page) {
    await page.goto(`/employees/${employeeId}`);
    await page.getByTestId("employee-tab-education").click();
    await page.getByTestId("employee-education-btn-add").click();
    await page.getByTestId("employee-edu-degree").click();
    const options = page.getByRole("option");
    await expect(options.first()).toBeVisible({ timeout: 10000 });
    return options.allTextContents();
  }

  test("RU offers the Russian levels, no region the default set", async ({
    page,
  }) => {
    await page.goto("/company/profile");
    await expect(page.getByTestId("company-profile-input-region")).toContainText(
      "Not specified",
      { timeout: 10000 },
    );
    expect(await degreeOptions(page)).toContain("PhD");

    await pickRegion(page, "Russia");
    const ru = await degreeOptions(page);
    expect(ru).toContain("Specialist degree");
    expect(ru).toContain("Candidate of Sciences");
    expect(ru).not.toContain("PhD");

    await pickRegion(page, "Not specified");
    const plain = await degreeOptions(page);
    expect(plain).toContain("PhD");
    expect(plain).not.toContain("Specialist degree");
  });
});
