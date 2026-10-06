import { test, expect } from "./fixtures";
import { CHECK_ORIGIN, PUBLIC_CHECK_E2E, browseFrom, uniqueIp } from "./public-check-helpers";

/** A breakdown is two live model calls: opt in with E2E_LLM=1 against a
 * backend and a Celery worker that have a model key (as
 * coverage-decomposition.spec.ts). CI runs public-check.spec.ts instead. */
const LIVE_LLM = process.env.E2E_LLM === "1";

/**
 * HRP-932 — the public check end to end with the real model: the form, the
 * progress bar, the result with three lists and a reason per step.
 */
test.skip(!PUBLIC_CHECK_E2E, "the public check is off: PUBLIC_CHECK_ENABLED / PUBLIC_CHECK_HOST");
test.skip(!LIVE_LLM, "needs a live model and a worker: run with E2E_LLM=1");

test("a process typed on the check host comes back broken down", async ({ page }) => {
  test.setTimeout(600_000);
  await browseFrom(page, uniqueIp());
  await page.goto(`${CHECK_ORIGIN}/`);
  await page.getByTestId("check-example-goods-receipt").click();
  // The team size is part of the text the model reads: a fresh one per run
  // keeps the breakdown cache (HRP-921) from answering instead of the model.
  await page
    .getByTestId("check-input-team-size")
    .fill(String(Math.floor(Math.random() * 9000) + 1000));
  await page.getByTestId("check-input-hourly-rate").fill("40");
  await page.getByTestId("check-btn-submit").click();

  await page.waitForURL(`${CHECK_ORIGIN}/r/**`);
  await expect(page.getByTestId("check-progress-bar")).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId("check-result")).toBeVisible({ timeout: 540_000 });
  await expect(page.getByTestId("check-result-preliminary")).toBeVisible();
  await expect(
    page.getByTestId("check-result-headline").or(page.getByTestId("check-result-no-shares")),
  ).toBeVisible();
  const reasons = page.locator('[data-testid^="check-step-"][data-testid$="-reason"]');
  expect(await reasons.count()).toBeGreaterThan(0);
  for (const reason of await reasons.all()) await expect(reason).not.toBeEmpty();
  await expect(page.getByTestId("check-social")).toBeVisible();
  await expect(page.getByTestId("check-save")).toBeVisible();
});
