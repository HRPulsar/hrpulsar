import { test, expect } from "./fixtures";
import { registerUser, setAuthTokens } from "./helpers";

const API_BASE = process.env.E2E_API_BASE ?? "http://localhost:8100/api";
/** A breakdown is two live LLM calls; opt in locally with E2E_LLM=1
 * against a backend that has a key and a worker. */
const LIVE_LLM = process.env.E2E_LLM === "1";

/**
 * HRP-762 — the AI decomposition surface without a live model (the
 * precedent of ai-competence-generation.spec.ts): the run is started for
 * real and either sits in the queue (no worker) or fails without an LLM key
 * (worker, no key) - both branches of the banner are exercised, the
 * container is freed either way. The reclassify dialog is opened and closed.
 */
test.describe("Coverage — AI decomposition UI", () => {
  let accessToken: string;
  let refreshToken: string;
  let containerId: string;
  let bareContainerId: string;
  let stepContainerId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const admin = await registerUser(page);
    accessToken = admin.accessToken;
    refreshToken = admin.refreshToken;
    const headers = { Authorization: `Bearer ${accessToken}` };
    const described = await page.request.post(`${API_BASE}/work/containers`, {
      headers,
      data: {
        type: "process",
        title: "Month-end close",
        description:
          "Every month Finance closes the books: readiness check, postings, reconciliation, sign-off.",
      },
    });
    containerId = (await described.json()).id;
    const bare = await page.request.post(`${API_BASE}/work/containers`, {
      headers,
      data: { type: "initiative", title: "Undescribed project" },
    });
    bareContainerId = (await bare.json()).id;
    // Its own container: a step on the generated one would turn Generate
    // into the confirm-replace dialog for the test above.
    const withStep = await page.request.post(`${API_BASE}/work/containers`, {
      headers,
      data: {
        type: "process",
        title: "Bank postings",
        description: "The accountant posts the bank transactions every morning.",
      },
    });
    stepContainerId = (await withStep.json()).id;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test("no description, no Generate button", async ({ page }) => {
    await page.goto(`/coverage/${bareContainerId}`);
    await expect(page.getByTestId("coverage-detail")).toBeVisible({ timeout: 10000 });
    await page.getByTestId("coverage-tab-steps").click();
    await expect(page.getByTestId("coverage-steps-empty")).toBeVisible();
    await expect(page.getByTestId("coverage-btn-generate")).toHaveCount(0);
  });

  test("Generate shows the banner; discard or dismiss frees the container", async ({
    page,
  }) => {
    await page.goto(`/coverage/${containerId}`);
    await expect(page.getByTestId("coverage-btn-generate")).toBeVisible({ timeout: 10000 });
    await page.getByTestId("coverage-btn-generate").click();

    const banner = page.getByTestId("coverage-banner-generating");
    await expect(banner).toBeVisible({ timeout: 10000 });
    // The POST answers with the run queued, model or no model: that much is
    // deterministic, and the banner renders exactly what it answered.
    await expect(banner).toHaveAttribute("data-status", "pending");
    // Either the run is waiting for a worker / running (Discard), or it
    // failed for want of a model (Dismiss) - and it may flip from one to
    // the other under us, so one retrying locator covers both buttons.
    const finish = page
      .getByTestId("coverage-btn-dismiss-generation")
      .or(page.getByTestId("coverage-btn-discard-generation"));
    await finish.first().click({ timeout: 15000 });
    await expect(banner).toBeHidden({ timeout: 10000 });
    await expect(page.getByTestId("coverage-btn-generate")).toBeVisible();
  });

  test("live: the first breakdown applies itself and lands on the coverage", async ({
    page,
  }) => {
    test.skip(!LIVE_LLM, "needs a live model and a worker: run with E2E_LLM=1");
    const headers = { Authorization: `Bearer ${accessToken}` };
    const fresh = await (
      await page.request.post(`${API_BASE}/work/containers`, {
        headers,
        data: {
          type: "process",
          title: `Goods receipt ${Date.now()}`,
          description:
            "Deliveries arrive at the dock: the paperwork is checked, the pallets counted against the order, damage recorded, and the receipt registered with batches.",
        },
      })
    ).json();
    await page.goto(`/coverage/${fresh.id}`);
    await page.getByTestId("coverage-btn-generate").click();
    // §5.5: nothing to replace, so there is no Apply button to press - the
    // run applies itself and the steps are simply there.
    await expect(page.getByTestId("coverage-match-list")).toBeVisible({ timeout: 180000 });
    await expect(page.getByTestId("coverage-banner-generating")).toBeHidden({
      timeout: 30000,
    });
    await page.getByTestId("coverage-tab-steps").click();
    await expect(page.locator('li[data-testid^="coverage-step-row-"]').first()).toBeVisible();

    // §5.13: a regeneration does gate, and shows what it would overwrite.
    await page.getByTestId("coverage-btn-generate").click();
    await page.getByTestId("confirm-dialog-btn-confirm").click();
    await expect(page.getByTestId("coverage-btn-apply-generation")).toBeVisible({
      timeout: 180000,
    });
    await page.getByTestId("coverage-draft-preview").click();
    await expect(page.getByTestId("coverage-draft-current")).toBeVisible();
    await expect(page.getByTestId("coverage-draft-proposed")).toBeVisible();
    await page.getByTestId("coverage-btn-discard-generation").click();
  });

  test("reclassify dialog opens for a step and closes without a comment", async ({
    page,
  }) => {
    await page.goto(`/coverage/${stepContainerId}`);
    await expect(page.getByTestId("coverage-detail")).toBeVisible({ timeout: 10000 });
    await page.getByTestId("coverage-tab-steps").click();
    await page.getByTestId("coverage-step-input-new").fill("Post the bank transactions");
    await page.getByTestId("coverage-step-btn-add").click();
    const row = page.locator('li[data-testid^="coverage-step-row-"]').first();
    await expect(row).toBeVisible({ timeout: 10000 });
    await row.locator('[data-testid$="-btn-reclassify"]').click();
    await expect(page.getByTestId("coverage-modal-reclassify")).toBeVisible();
    await expect(page.getByTestId("coverage-btn-reclassify-submit")).toBeDisabled();
    await page.getByTestId("coverage-reclassify-input").fill("A scripted call with the bank");
    await expect(page.getByTestId("coverage-btn-reclassify-submit")).toBeEnabled();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("coverage-modal-reclassify")).toBeHidden();
  });
});
