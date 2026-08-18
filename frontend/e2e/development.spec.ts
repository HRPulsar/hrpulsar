import { test, expect } from "./fixtures";
import {
  registerUser,
  setAuthTokens,
  setupFullTenant,
  createPDP,
  seedPDPItemWithMaterial,
} from "./helpers";

test.describe("Development page", () => {
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

  test("development page renders", async ({ page }) => {
    await page.goto("/development");
    await expect(page.getByTestId("development-heading")).toBeVisible({
      timeout: 10000,
    });
  });

  test("empty state", async ({ page }) => {
    await page.goto("/development");
    await expect(page.getByTestId("development-empty")).toBeVisible({
      timeout: 10000,
    });
  });

  test("create button visible", async ({ page }) => {
    await page.goto("/development");
    await expect(page.getByTestId("development-btn-create")).toBeVisible({
      timeout: 10000,
    });
  });
});

test.describe("Development with data", () => {
  let accessToken: string;
  let refreshToken: string;
  let pdpId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const setup = await setupFullTenant(page);
    accessToken = setup.accessToken;
    refreshToken = setup.refreshToken;
    const pdp = await createPDP(
      { page, accessToken },
      setup.employeeId,
    );
    pdpId = pdp.id;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("plan card visible", async ({ page }) => {
    await page.goto("/development");
    await expect(
      page.getByTestId(`development-row-${pdpId}`),
    ).toBeVisible({ timeout: 10000 });
  });

  test("plan status badge", async ({ page }) => {
    await page.goto("/development");
    await expect(
      page.getByTestId(`development-row-${pdpId}-status`),
    ).toBeVisible({ timeout: 10000 });
  });

  test("navigate to detail", async ({ page }) => {
    await page.goto("/development");
    await page.getByTestId(`development-row-${pdpId}`).click();
    await expect(page).toHaveURL(new RegExp(`/development/${pdpId}`), {
      timeout: 10000,
    });
  });

  test("detail page renders", async ({ page }) => {
    await page.goto(`/development/${pdpId}`);
    await expect(page.getByTestId("development-detail-title")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByTestId("development-detail-status")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByTestId("development-detail-progress"),
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByTestId("development-detail-goals-list"),
    ).toBeVisible({ timeout: 10000 });
  });
});

test.describe("Development status lifecycle", () => {
  test("draft → sent → in_progress → review → done", async ({ browser }) => {
    // HRP-16: review goes straight to done; on_approval/approved are gone.
    // HRP-197: manual sent → in_progress is removed — the plan auto-promotes
    // when the owner ticks the first item. We mark the seed item passed via
    // API to simulate that path.
    const ctx = await browser.newPage();
    const setup = await setupFullTenant(ctx);
    await setAuthTokens(ctx, setup.accessToken, setup.refreshToken);

    const pdp = await createPDP(
      { page: ctx, accessToken: setup.accessToken },
      setup.employeeId,
      "Lifecycle Plan",
    );
    // HRP-12: the Send action stays disabled until the plan has at least
    // one item with one material. Seed the minimum so the lifecycle walk
    // can proceed past Draft.
    const item = await seedPDPItemWithMaterial(
      { page: ctx, accessToken: setup.accessToken },
      pdp.id,
    );

    await ctx.goto(`/development/${pdp.id}`);

    const status = ctx.getByTestId("development-detail-status");
    await expect(status).toHaveText("Draft", { timeout: 10000 });

    // Draft → Sent (manual button)
    const sentBtn = ctx.getByTestId("development-detail-btn-status-sent");
    await expect(sentBtn).toBeVisible({ timeout: 10000 });
    await sentBtn.click();
    await expect(status).toHaveText("Sent", { timeout: 10000 });

    // Sent → In progress (HRP-197: auto-promotes when owner marks first item passed)
    const passResp = await ctx.request.post(
      `http://localhost:8100/api/pdp/${pdp.id}/items/${item.id}/pass`,
      {
        headers: { Authorization: `Bearer ${setup.accessToken}` },
        data: { is_passed: true },
      },
    );
    if (!passResp.ok()) {
      throw new Error(
        `mark_item_passed failed (${passResp.status()}): ${await passResp.text()}`,
      );
    }
    await ctx.reload();
    await expect(status).toHaveText("In progress", { timeout: 10000 });

    // In progress → On review (manual button, requires every item passed)
    const reviewBtn = ctx.getByTestId("development-detail-btn-status-review");
    await expect(reviewBtn).toBeVisible({ timeout: 10000 });
    await reviewBtn.click();
    await expect(status).toHaveText("On review", { timeout: 10000 });

    // On review → Done (manual button)
    const doneBtn = ctx.getByTestId("development-detail-btn-status-done");
    await expect(doneBtn).toBeVisible({ timeout: 10000 });
    await doneBtn.click();
    await expect(status).toHaveText("Done", { timeout: 10000 });

    await expect(
      ctx.getByTestId("development-detail-status-actions"),
    ).toHaveCount(0);

    await ctx.close();
  });
});
