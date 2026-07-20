import { test, expect } from "@playwright/test";
import {
  registerUser,
  setAuthTokens,
  createDictionaryItem,
} from "./helpers";

test.describe("Specialization AI history tab (HRP-71 phase 2)", () => {
  let accessToken: string;
  let refreshToken: string;
  let specId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const reg = await registerUser(page);
    accessToken = reg.accessToken;
    refreshToken = reg.refreshToken;

    const stamp = Date.now().toString(36);
    const spec = await createDictionaryItem(
      { page, accessToken },
      "specialization",
      `AIHist-${stamp}`,
    );
    specId = spec.id;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("AI history tab renders empty state for a fresh specialization", async ({
    page,
  }) => {
    await page.goto(`/company/specializations/${specId}?tab=ai-history`);
    await expect(page.getByTestId("specialization-detail")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId("specialization-tab-ai-history"),
    ).toHaveAttribute("aria-selected", "true");
    await expect(
      page.getByTestId("specialization-ai-history-empty"),
    ).toBeVisible({ timeout: 10000 });
  });

  test("clicking AI history tab updates the URL deep-link", async ({
    page,
  }) => {
    await page.goto(`/company/specializations/${specId}`);
    await expect(page.getByTestId("specialization-detail")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("specialization-tab-ai-history").click();
    await expect(page).toHaveURL(/[?&]tab=ai-history/);
    await expect(
      page.getByTestId("specialization-ai-history-empty"),
    ).toBeVisible({ timeout: 10000 });
  });
});
