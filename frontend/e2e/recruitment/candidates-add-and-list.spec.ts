/**
 * HRP-181 REDO Stage 5 — end-to-end coverage of the canonical
 * candidate-add flow on a vacancy:
 *
 *   open vacancy → manual add (redirect to candidate card)
 *   → bulk-upload two resumes → seed parser completion via E2E hook
 *   → import them → verify the table reloads
 *   → change a stage inline → seed AI verdict → open verdict popover
 *   → open Manage stages drawer → rename a stage → save
 *
 * The spec deliberately sidesteps Celery + LLM: the bulk-upload modal
 * polls ``GET .../resumes/parsing-status`` which never flips on its own
 * in the test stack, so the spec calls ``POST /_test/seed-parsed-files``
 * (E2E_MODE-gated) to mark the uploaded files ``completed`` with
 * deterministic stub data. Same shortcut applies to ``seed-verdict``.
 */
import { type APIRequestContext, type Page, expect, test } from "@playwright/test";
import { registerUser, setAuthTokens, uniqueEmail } from "../helpers";

const API_BASE = "http://localhost:8100/api";
// Minimal valid-enough PDF: the bulk-upload sniff only checks the
// leading ``%PDF-`` magic. The Celery parser never runs because the
// seed endpoint flips parse_status before the test polls.
const MINIMAL_PDF = Buffer.from("%PDF-1.4\n%EOF\n");

interface AuthOpts {
  page: Page;
  accessToken: string;
}

async function createVacancy(
  opts: AuthOpts,
  title: string,
): Promise<{ id: string; title: string }> {
  const resp = await opts.page.request.post(`${API_BASE}/recruitment/vacancies`, {
    headers: { Authorization: `Bearer ${opts.accessToken}` },
    data: { title },
  });
  if (!resp.ok()) {
    throw new Error(
      `createVacancy failed (${resp.status()}): ${await resp.text()}`,
    );
  }
  const body = await resp.json();
  return { id: body.id, title: body.title };
}

interface ParsedFileSeed {
  file_id: string;
  parsed_data: {
    first_name: string;
    last_name: string;
    contacts: { email: string };
    experience: Array<Record<string, unknown>>;
  };
}

async function seedParsedFiles(
  request: APIRequestContext,
  accessToken: string,
  files: ParsedFileSeed[],
): Promise<void> {
  const resp = await request.post(
    `${API_BASE}/recruitment/_test/seed-parsed-files`,
    {
      headers: { Authorization: `Bearer ${accessToken}` },
      data: { files },
    },
  );
  if (!resp.ok()) {
    throw new Error(
      `seedParsedFiles failed (${resp.status()}): ${await resp.text()}`,
    );
  }
}

async function seedVerdict(
  request: APIRequestContext,
  accessToken: string,
  cvId: string,
  body: Record<string, unknown>,
): Promise<void> {
  const resp = await request.post(
    `${API_BASE}/recruitment/_test/seed-verdict`,
    {
      headers: { Authorization: `Bearer ${accessToken}` },
      data: { candidate_vacancy_id: cvId, ...body },
    },
  );
  if (!resp.ok()) {
    throw new Error(
      `seedVerdict failed (${resp.status()}): ${await resp.text()}`,
    );
  }
}

test.describe("Recruitment HRP-181 canonical candidate flow", () => {
  test("manual add, bulk upload + import, stage change, verdict popover, stages drawer", async ({
    page,
  }) => {
    const admin = await registerUser(page);
    const opts: AuthOpts = { page, accessToken: admin.accessToken };
    const vacancy = await createVacancy(opts, `HRP-181 ${Date.now()}`);

    await setAuthTokens(page, admin.accessToken, admin.refreshToken);
    await page.goto(`/recruitment/requisitions/${vacancy.id}`);

    const candidatesSection = page.getByTestId("vacancy-section-candidates");
    await expect(candidatesSection).toBeVisible({ timeout: 15000 });
    await expect(
      candidatesSection.getByTestId("vacancy-candidates-table-empty"),
    ).toBeVisible({ timeout: 10000 });

    // ── Manual add — redirects to the candidate card on success ──────
    await candidatesSection
      .getByTestId("vacancy-section-candidates-add-btn")
      .click();

    const dialog = page.getByTestId("vacancy-candidates-add-modal");
    await expect(dialog).toBeVisible();
    await dialog.getByTestId("vacancy-candidates-add-modal-tab-manual").click();

    const manualEmail = uniqueEmail();
    await dialog
      .getByTestId("vacancy-candidates-add-manual-field-full_name")
      .fill("Manual Alpha");
    await dialog
      .getByTestId("vacancy-candidates-add-manual-field-email")
      .fill(manualEmail);
    await dialog.getByTestId("vacancy-candidates-add-submit-btn").click();

    await page.waitForURL(/\/recruitment\/candidates\/[0-9a-f-]+$/, {
      timeout: 15000,
    });

    // ── Bulk upload two minimal PDFs ───────────────────────────────────
    await page.goto(`/recruitment/requisitions/${vacancy.id}`);
    await expect(candidatesSection).toBeVisible({ timeout: 15000 });
    await candidatesSection
      .getByTestId("vacancy-section-candidates-add-btn")
      .click();
    await expect(dialog).toBeVisible();
    // Default tab is upload, no need to switch.
    await dialog.locator('input[type="file"]').setInputFiles([
      { name: "resume-bulk-1.pdf", mimeType: "application/pdf", buffer: MINIMAL_PDF },
      { name: "resume-bulk-2.pdf", mimeType: "application/pdf", buffer: MINIMAL_PDF },
    ]);

    // Capture the bulk-upload ack so we know the file_ids to seed.
    const [uploadResp] = await Promise.all([
      page.waitForResponse(
        (r) =>
          r.url().includes("/resumes/bulk-upload") &&
          r.request().method() === "POST" &&
          r.status() === 201,
      ),
      dialog.getByTestId("vacancy-candidates-add-submit-btn").click(),
    ]);
    const ack = (await uploadResp.json()) as Array<{ file_id: string }>;
    expect(ack).toHaveLength(2);

    // Seed parsed data so the polling step transitions to summary.
    const stamp = Date.now();
    await seedParsedFiles(page.request, admin.accessToken, [
      {
        file_id: ack[0].file_id,
        parsed_data: {
          first_name: "Bulk",
          last_name: "Alpha",
          contacts: { email: `bulk-alpha-${stamp}@e2e.test` },
          experience: [{ position: "Senior Engineer" }],
        },
      },
      {
        file_id: ack[1].file_id,
        parsed_data: {
          first_name: "Bulk",
          last_name: "Beta",
          contacts: { email: `bulk-beta-${stamp}@e2e.test` },
          experience: [{ position: "Engineering Manager" }],
        },
      },
    ]);

    // The poll runs every 2.5 s and re-triggers finalize when pending +
    // processing both hit zero. Wait for the summary step (Import button).
    const importButton = dialog.getByTestId("vacancy-candidates-add-submit-btn");
    await expect(importButton).toContainText(/Import 2 candidates/i, {
      timeout: 20000,
    });
    await importButton.click();

    await expect(dialog).toBeHidden({ timeout: 15000 });

    // ── Table now lists three rows (1 manual + 2 imported) ─────────────
    const table = candidatesSection.getByTestId("vacancy-candidates-table");
    await expect(table).toBeVisible({ timeout: 15000 });
    const rowLocator = candidatesSection.locator(
      '[data-testid^="vacancy-candidates-row-"]',
    );
    await expect.poll(async () => rowLocator.count(), {
      timeout: 15000,
    }).toBeGreaterThanOrEqual(3);

    // Fetch enriched list so we know the cv_id of a row to drive next steps.
    const enrichedResp = await page.request.get(
      `${API_BASE}/recruitment/vacancies/${vacancy.id}/candidates/enriched`,
      { headers: { Authorization: `Bearer ${admin.accessToken}` } },
    );
    expect(enrichedResp.ok()).toBeTruthy();
    const rows = (await enrichedResp.json()) as Array<{
      id: string;
      candidate_name: string;
      stage_id: string;
    }>;
    expect(rows.length).toBeGreaterThanOrEqual(3);
    const target = rows[0];

    // ── Stage change (active → another active stage, no confirm) ──────
    const funnelResp = await page.request.get(
      `${API_BASE}/recruitment/vacancies/${vacancy.id}/funnel-stages`,
      { headers: { Authorization: `Bearer ${admin.accessToken}` } },
    );
    const funnel = (await funnelResp.json()) as Array<{
      id: string;
      name: string;
      stage_type: string;
    }>;
    const safeStage = funnel.find(
      (s) => s.stage_type === "active" && s.id !== target.stage_id,
    );
    expect(safeStage).toBeDefined();

    const stageSelect = page.getByTestId(
      `vacancy-candidates-row-${target.id}-stage-select`,
    );
    await stageSelect.click();
    await page.getByRole("option", { name: safeStage!.name }).click();
    // Verify via the enriched API rather than a toast — the toast lifetime
    // is too short to assert reliably.
    await expect
      .poll(
        async () => {
          const r = await page.request.get(
            `${API_BASE}/recruitment/vacancies/${vacancy.id}/candidates/enriched`,
            { headers: { Authorization: `Bearer ${admin.accessToken}` } },
          );
          const list = (await r.json()) as Array<{
            id: string;
            stage: { name: string } | null;
          }>;
          return list.find((x) => x.id === target.id)?.stage?.name ?? null;
        },
        { timeout: 10000 },
      )
      .toBe(safeStage!.name);

    // ── AI verdict popover ─────────────────────────────────────────────
    await seedVerdict(page.request, admin.accessToken, target.id, {
      ai_verdict: "recommended",
      ai_readiness: "resume_only",
      ai_score: 0.84, // canonical raw 0..1 scale (HRP-274)
      ai_verdict_summary: "Strong backend match — clear delivery record.",
      ai_key_strength: "Years of Python + FastAPI ownership",
      ai_key_risk: "Limited recent team-lead exposure",
      ai_risk_mitigation: "Pair with an existing tech lead for the first cycle",
    });

    await page.reload();
    await expect(table).toBeVisible({ timeout: 15000 });
    const verdictBadge = page.getByTestId(
      `vacancy-candidates-row-${target.id}-ai-verdict-badge`,
    );
    await expect(verdictBadge).toContainText(/Recommended/i, {
      timeout: 10000,
    });
    await page
      .getByTestId(`vacancy-candidates-row-${target.id}-ai-verdict-info-btn`)
      .click();
    const popover = page.getByTestId(
      `vacancy-candidates-row-${target.id}-ai-verdict-popover`,
    );
    await expect(popover).toBeVisible({ timeout: 5000 });
    await expect(popover).toContainText("Strong backend match");
    await expect(popover).toContainText("FastAPI ownership");
    // Close popover (click outside).
    await page.keyboard.press("Escape");

    // ── Manage stages drawer: rename first stage, save ────────────────
    await candidatesSection.getByTestId("vacancy-stage-manage-btn").click();
    const drawer = page.getByTestId("vacancy-stage-manage-drawer");
    await expect(drawer).toBeVisible({ timeout: 5000 });

    const firstStageName = drawer
      .locator(
        '[data-testid^="vacancy-stage-manage-item-"][data-testid$="-name"]',
      )
      .first();
    await firstStageName.fill("Screen (renamed)");
    await drawer.getByTestId("vacancy-stage-manage-save-btn").click();

    // Sheet closes on successful save.
    await expect(drawer).toBeHidden({ timeout: 10000 });

    // Effective stages reflect the rename.
    const refreshed = await page.request.get(
      `${API_BASE}/recruitment/vacancies/${vacancy.id}/funnel-stages`,
      { headers: { Authorization: `Bearer ${admin.accessToken}` } },
    );
    const refreshedStages = (await refreshed.json()) as Array<{ name: string }>;
    expect(refreshedStages.map((s) => s.name)).toContain("Screen (renamed)");
  });
});
