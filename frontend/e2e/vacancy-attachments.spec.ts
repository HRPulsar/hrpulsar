/**
 * HRP-846 — vacancy attachments widget on the vacancy page.
 *
 * The widget (context files for AI profile generation) fell off the page in
 * the HRP-180 single-page redesign while its API stayed alive. This covers
 * the surface end to end: the block is on the page, a file uploads into the
 * list, and delete (after the browser confirm) removes it.
 *
 * Storage may be unconfigured on CI — the backend then keeps the metadata row
 * only, which is all the list needs.
 *
 * Requires E2E_MODE=true on the backend (registerUser uses
 * /api/auth/dev/auto-register).
 */
import { test, expect } from "./fixtures";
import { registerUser, setAuthTokens } from "./helpers";

const API_BASE = "http://localhost:8100/api";

test.describe("Vacancy attachments (HRP-846)", () => {
  test("upload and delete an attachment on the vacancy page", async ({ page }) => {
    const admin = await registerUser(page);
    const resp = await page.request.post(`${API_BASE}/recruitment/vacancies`, {
      headers: { Authorization: `Bearer ${admin.accessToken}` },
      data: { title: `Attachments Vacancy ${Date.now()}` },
    });
    if (!resp.ok()) {
      throw new Error(`createVacancy failed (${resp.status()}): ${await resp.text()}`);
    }
    const vacancy = await resp.json();

    await setAuthTokens(page, admin.accessToken, admin.refreshToken);
    await page.goto(`/recruitment/requisitions/${vacancy.id}`);

    const widget = page.getByTestId("vacancy-attachments");
    await expect(widget).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId("vacancy-attachments-upload-btn")).toBeVisible();

    await page.getByTestId("vacancy-attachments-input").setInputFiles({
      name: "context.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("Hiring context for the profile prompt.\n"),
    });

    const row = widget.locator('[data-testid^="vacancy-attachment-row-"]');
    await expect(row).toHaveCount(1, { timeout: 10000 });
    await expect(row).toContainText("context.txt");

    page.once("dialog", (dialog) => dialog.accept());
    await widget.locator('[data-testid^="vacancy-attachment-delete-"]').click();
    await expect(row).toHaveCount(0, { timeout: 10000 });
  });
});
