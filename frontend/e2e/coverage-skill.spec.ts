import { test, expect } from "./fixtures";
import { registerUser, setAuthTokens } from "./helpers";

const API_BASE = process.env.E2E_API_BASE ?? "http://localhost:8100/api";
/** The generation is one live LLM call (30 credits); opt in locally with
 * E2E_LLM=1 against a backend that has a key. CI runs the negative case and
 * the button states only. */
const LIVE_LLM = process.env.E2E_LLM === "1";

/**
 * HRP-762 — SKILL.md of a step (REFACTOR_PLAN §4.4, §7.6): the button is
 * there for a step an agent can perform and absent for a step blocked by
 * judgement; with a live model the file is generated, previewed and
 * downloaded as SKILL.md.
 *
 * W6 (§5.12): the generation runs in a Celery task, so the dialog shows a
 * progress strip and polls the row rather than holding the request open.
 */
test.describe("Coverage — agent skill", () => {
  let accessToken: string;
  let refreshToken: string;
  let containerId: string;
  let agentStepId: string;
  let blockedStepId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const admin = await registerUser(page);
    accessToken = admin.accessToken;
    refreshToken = admin.refreshToken;
    const headers = { Authorization: `Bearer ${accessToken}` };
    containerId = (
      await (
        await page.request.post(`${API_BASE}/work/containers`, {
          headers,
          data: {
            type: "process",
            title: "Invoice intake",
            description:
              "Supplier invoices arrive by email; the fields are extracted into the ledger and a manager approves the exceptions.",
          },
        })
      ).json()
    ).id;
    agentStepId = (
      await (
        await page.request.post(`${API_BASE}/work/containers/${containerId}/steps`, {
          headers,
          data: { title: "Extract the invoice fields", primitive_codes: ["P1"] },
        })
      ).json()
    ).id;
    blockedStepId = (
      await (
        await page.request.post(`${API_BASE}/work/containers/${containerId}/steps`, {
          headers,
          data: { title: "Approve the exceptions", primitive_codes: ["P6"] },
        })
      ).json()
    ).id;
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await setAuthTokens(page, accessToken, refreshToken);
    await page.goto(`/coverage/${containerId}`);
    await expect(page.getByTestId("coverage-detail")).toBeVisible({ timeout: 10000 });
    await page.getByTestId("coverage-tab-coverage").click();
    await expect(page.getByTestId("coverage-match-list")).toBeVisible({ timeout: 10000 });
  });

  test("Get the skill only where an agent can perform the step", async ({ page }) => {
    await expect(page.getByTestId(`coverage-verdict-${agentStepId}`)).toHaveAttribute(
      "data-verdict",
      "agent",
    );
    await expect(page.getByTestId(`coverage-btn-get-skill-${agentStepId}`)).toBeVisible();
    await expect(page.getByTestId(`coverage-skill-status-${agentStepId}`)).toHaveAttribute(
      "data-status",
      "none",
    );
    // Blocked by judgement: no button, the catalog says no agent performs it.
    await expect(page.getByTestId(`coverage-mode-${blockedStepId}`)).toBeVisible();
    await expect(page.getByTestId(`coverage-btn-get-skill-${blockedStepId}`)).toHaveCount(0);
  });

  test("live: generate, preview and download SKILL.md", async ({ page }) => {
    test.skip(!LIVE_LLM, "needs a live model: run with E2E_LLM=1");
    await page.getByTestId(`coverage-btn-get-skill-${agentStepId}`).click();
    const modal = page.getByTestId("coverage-modal-skill");
    await expect(modal).toBeVisible({ timeout: 10000 });
    // Queued, not awaited: the strip and its clock are what the reader sees
    // until the worker writes the file.
    await expect(page.getByTestId("coverage-skill-progress")).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByTestId("coverage-skill-preview")).toContainText("---", {
      timeout: 120000,
    });
    await expect(page.getByTestId("coverage-skill-preview")).toContainText(/name:/);
    const downloadPromise = page.waitForEvent("download");
    await page.getByTestId("coverage-btn-skill-download").click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("SKILL.md");
  });
});
