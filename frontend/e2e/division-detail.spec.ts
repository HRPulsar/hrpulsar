import { test, expect } from "@playwright/test";
import { setupFullTenant, setAuthTokens } from "./helpers";

test.describe("Division detail page (HRP-216 regression)", () => {
  let accessToken: string;
  let refreshToken: string;
  let divisionId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const setup = await setupFullTenant(page);
    accessToken = setup.accessToken;
    refreshToken = setup.refreshToken;
    divisionId = setup.divisionId;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("opens without crashing — Edit button is visible", async ({ page }) => {
    // HRP-216: a Position[] vs PositionList type mismatch crashed
    // AddEmployeeDialog mounting (allPositions.map was called on an
    // object, not an array). The page never rendered past the error
    // boundary. Asserting the Edit button reaches the DOM guards the
    // whole post-load tree against the same regression.
    await page.goto(`/company/divisions/${divisionId}`);
    await expect(page.getByTestId("division-detail-btn-edit")).toBeVisible({
      timeout: 10000,
    });
  });
});
