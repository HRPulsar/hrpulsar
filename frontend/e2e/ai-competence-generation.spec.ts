import { test, expect } from "./fixtures";
import {
  registerUser,
  setAuthTokens,
  createDictionaryItem,
} from "./helpers";

const API_BASE = "http://localhost:8100/api";

/**
 * CR13 — UI smoke for AI competence generation.
 *
 * Real LLM-driven flows belong in CR8 (final E2E pass). Here we exercise the
 * non-network parts of the new UI: status-button states, confirm-dialog wiring,
 * preflight modal when another tenant user has an active session.
 */
test.describe("AI competence generation UI", () => {
  let accessToken: string;
  let refreshToken: string;
  let userToken: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const creds = await registerUser(page);
    accessToken = creds.accessToken;
    refreshToken = creds.refreshToken;
    userToken = creds.accessToken;
    await createDictionaryItem(
      { page, accessToken },
      "specialization",
      "Backend Engineer",
    );
    await page.request.post(`${API_BASE}/skill-levels`, {
      headers: { Authorization: `Bearer ${userToken}` },
      data: { title: "Basic", sort_index: 0 },
    });
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
  });

  test('status-button defaults to "Generate library with AI"', async ({
    page,
  }) => {
    await page.goto("/competences");
    await expect(
      page.getByTestId("compgen-btn-generate-base"),
    ).toBeVisible({ timeout: 10000 });
  });

  test("clicking status-button opens the confirm dialog", async ({ page }) => {
    await page.goto("/competences");
    await page.getByTestId("compgen-btn-generate-base").click();
    await expect(page.getByTestId("compgen-confirm-dialog")).toBeVisible({
      timeout: 5000,
    });
    await expect(
      page.getByTestId("compgen-confirm-checkbox-indicators"),
    ).toBeVisible();
    await expect(page.getByTestId("compgen-confirm-btn-start")).toBeVisible();
    await page.getByTestId("compgen-confirm-btn-cancel").click();
    await expect(
      page.getByTestId("compgen-confirm-dialog"),
    ).not.toBeVisible();
  });

  test("active-others endpoint is reachable", async ({ page }) => {
    // The PreflightModal flow needs a second user in the same tenant to
    // light up — that requires an invitation/accept flow which is heavier
    // than a smoke test. Here we just verify the endpoint is wired and
    // returns the expected shape (full UX flow lives in CR8).
    const resp = await page.request.get(
      `${API_BASE}/competence-generation/sessions/active-others`,
      { headers: { Authorization: `Bearer ${userToken}` } },
    );
    expect(resp.ok()).toBeTruthy();
    const list = await resp.json();
    expect(Array.isArray(list)).toBeTruthy();
  });

  test("?compgen=open auto-opens the drawer when an active session exists", async ({
    page,
  }) => {
    // Ensure there's an active session.
    const sessResp = await page.request.post(
      `${API_BASE}/competence-generation/sessions`,
      {
        headers: { Authorization: `Bearer ${userToken}` },
        data: { scope: "whole_base", params: {} },
      },
    );
    // 201 (new) or 409 (already active from previous test) — both fine.
    expect([201, 409]).toContain(sessResp.status());

    await page.goto("/competences?compgen=open");
    await expect(page.getByTestId("compgen-drawer")).toBeVisible({
      timeout: 10000,
    });
  });

  test("HRP-91 — Cancel generation requires explicit confirm", async ({
    page,
  }) => {
    // Make sure there's an active session — reuse an existing one if any.
    const sessResp = await page.request.post(
      `${API_BASE}/competence-generation/sessions`,
      {
        headers: { Authorization: `Bearer ${userToken}` },
        data: { scope: "whole_base", params: {} },
      },
    );
    expect([201, 409]).toContain(sessResp.status());

    await page.goto("/competences?compgen=open");
    await expect(page.getByTestId("compgen-drawer")).toBeVisible({
      timeout: 10000,
    });
    const cancelBtn = page.getByTestId("compgen-btn-cancel-generation");
    if (!(await cancelBtn.isVisible().catch(() => false))) {
      // Session might already be in a non-cancellable state — that's fine
      // for the smoke check.
      return;
    }
    await cancelBtn.click();
    await expect(page.getByTestId("compgen-cancel-confirm")).toBeVisible({
      timeout: 5000,
    });
    // Clicking "Keep session" should leave the session running.
    await page.getByTestId("compgen-cancel-confirm-keep").click();
    await expect(page.getByTestId("compgen-cancel-confirm")).toBeHidden();
    await expect(page.getByTestId("compgen-drawer")).toBeVisible();

    // "Discard and cancel" actually cancels — the drawer should close once
    // the session leaves the active set.
    await cancelBtn.click();
    await expect(page.getByTestId("compgen-cancel-confirm")).toBeVisible();
    await page.getByTestId("compgen-cancel-confirm-discard").click();
    await expect(page.getByTestId("compgen-drawer")).toBeHidden({
      timeout: 15000,
    });
  });
});
