import { test, expect } from "@playwright/test";
import {
  createDictionaryItem,
  registerUser,
  setAuthTokens,
} from "./helpers";

test.describe("Specializations page", () => {
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

  test("specializations tab is visible from Company", async ({ page }) => {
    await page.goto("/company/positions");
    await expect(page.getByTestId("company-tab-specializations")).toBeVisible({
      timeout: 10000,
    });
  });

  test("list page renders", async ({ page }) => {
    await page.goto("/company/specializations");
    await expect(page.getByTestId("specializations-search")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("specializations-table")).toBeVisible({
      timeout: 10000,
    });
  });

  test("search input is filterable", async ({ page }) => {
    await page.goto("/company/specializations");
    await page.getByTestId("specializations-search").fill("zzz-no-match-zzz");
    await page.waitForTimeout(150);
    await expect(
      page.getByText("No specializations match your search."),
    ).toBeVisible({ timeout: 10000 });
  });

  test("HRP-103: admin can delete an unused specialization from list", async ({
    page,
  }) => {
    const title = `Doomed-${Date.now()}`;
    const spec = await createDictionaryItem(
      { page, accessToken },
      "specialization",
      title,
    );

    await page.goto("/company/specializations");
    const row = page.getByTestId(`specializations-row-${spec.id}`);
    await expect(row).toBeVisible({ timeout: 10000 });

    await row
      .getByTestId(`specializations-row-${spec.id}-menu`)
      .click();
    await page
      .getByTestId(`specializations-row-${spec.id}-btn-delete`)
      .click();
    await page.getByTestId("confirm-dialog-btn-confirm").click();

    await expect(row).toBeHidden({ timeout: 10000 });
  });

  test("HRP-103: admin can delete an unused specialization from detail page", async ({
    page,
  }) => {
    const title = `DoomedDetail-${Date.now()}`;
    const spec = await createDictionaryItem(
      { page, accessToken },
      "specialization",
      title,
    );

    await page.goto(`/company/specializations/${spec.id}`);
    await page.getByTestId("specialization-detail-delete-btn").click();
    await page.getByTestId("confirm-dialog-btn-confirm").click();

    await expect(page).toHaveURL(/\/company\/specializations\/?$/, {
      timeout: 10000,
    });
    await expect(
      page.getByTestId(`specializations-row-${spec.id}`),
    ).toBeHidden({ timeout: 10000 });
  });

  test("HRP-103 redo: delete confirm enumerates positions + chains that block delete", async ({
    page,
  }) => {
    // Pre-create a specialization with a live position and grade chain so
    // the delete confirm has something concrete to enumerate.
    const stamp = Date.now().toString(36);
    const spec = await createDictionaryItem(
      { page, accessToken },
      "specialization",
      `BlockedSpec-${stamp}`,
    );
    const grade = await createDictionaryItem(
      { page, accessToken },
      "grade",
      `BlockedGrade-${stamp}`,
    );
    const API = "http://localhost:8100/api";
    const auth = { Authorization: `Bearer ${accessToken}` };
    const posResp = await page.request.post(`${API}/positions`, {
      headers: auth,
      data: { title: `BlockedPos-${stamp}`, specialization_id: spec.id },
    });
    if (!posResp.ok()) throw new Error(`position seed failed: ${await posResp.text()}`);
    const pos = await posResp.json();
    const chainResp = await page.request.post(`${API}/grade-system/chains`, {
      headers: auth,
      data: {
        grade_id: grade.id,
        specialization_id: spec.id,
        competence_links: [],
      },
    });
    if (!chainResp.ok()) throw new Error(`chain seed failed: ${await chainResp.text()}`);
    const chain = await chainResp.json();

    await page.goto(`/company/specializations/${spec.id}`);
    await page.getByTestId("specialization-detail-delete-btn").click();

    // References block surfaces both kinds with the human-readable titles
    // the operator needs to act on.
    await expect(page.getByTestId("usage-references")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId(`usage-references-position-${pos.id}`),
    ).toBeVisible();
    await expect(
      page.getByTestId(`usage-references-chain-${chain.id}`),
    ).toBeVisible();
    // Confirm button is locked while references are still attached.
    await expect(
      page.getByTestId("confirm-dialog-btn-confirm"),
    ).toBeDisabled();
  });
});
