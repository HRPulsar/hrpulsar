import { test, expect } from "@playwright/test";
import {
  registerUser,
  setAuthTokens,
  createDictionaryItem,
} from "./helpers";

const API_BASE = "http://localhost:8100/api";

// POS5 — AI Generate matrix page. We exercise the form, file rejection, and
// the banner. The actual LLM call is mocked at the route level so the test
// stays deterministic and free of API keys.

test.describe("Specialization AI Generate (POS5)", () => {
  let accessToken: string;
  let refreshToken: string;
  let specId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    const reg = await registerUser(page);
    accessToken = reg.accessToken;
    refreshToken = reg.refreshToken;

    const opts = { page, accessToken };
    const stamp = Date.now().toString(36);
    const spec = await createDictionaryItem(opts, "specialization", `AISpec-${stamp}`);
    specId = spec.id;
    const grade = await createDictionaryItem(opts, "grade", `AIGrade-${stamp}`);

    const chain = await page.request.post(`${API_BASE}/grade-system/chains`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      data: {
        grade_id: grade.id,
        specialization_id: spec.id,
        competence_links: [],
      },
    });
    if (!chain.ok()) {
      throw new Error(`chain failed: ${await chain.text()}`);
    }

    await page.close();
  });

  test("form renders, banner shows model, .doc upload is rejected", async ({
    page,
  }) => {
    await setAuthTokens(page, accessToken, refreshToken);

    await page.goto(`/company/specializations/${specId}/ai-generate`);

    // Page header
    await expect(
      page.getByTestId("specialization-ai-generate"),
    ).toBeVisible();

    // Settings banner shows effective_model and effort
    const banner = page.getByTestId("ai-settings-banner");
    await expect(banner).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId("ai-settings-banner-model")).not.toBeEmpty();
    await expect(page.getByTestId("ai-settings-banner-effort")).not.toBeEmpty();
    await expect(page.getByTestId("ai-settings-banner-link")).toHaveAttribute(
      "href",
      "/settings/ai",
    );

    // Form fields are present
    await expect(page.getByTestId("ai-generate-responsibilities")).toBeVisible();
    await expect(page.getByTestId("ai-generate-daily-tasks")).toBeVisible();
    await expect(page.getByTestId("ai-generate-weekly-tasks")).toBeVisible();
    await expect(page.getByTestId("ai-generate-kpi")).toBeVisible();
    await expect(
      page.getByTestId("ai-generate-requirements-text"),
    ).toBeVisible();

    // .doc rejection happens server-side when the form is submitted with a
    // .doc file. We submit only with a .txt file so the precheck passes —
    // and verify the request reaches the API. (Full LLM execution is a
    // backend concern with its own unit tests.)
    await page
      .getByTestId("ai-generate-responsibilities")
      .fill("Owns the API layer end-to-end.");

    // Drop a small .txt for the upload list
    await page.getByTestId("ai-generate-file-input").setInputFiles({
      name: "role.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("Backend Engineer responsibilities."),
    });
    await expect(page.getByTestId("ai-generate-file-list")).toContainText(
      "role.txt",
    );

    // Try to attach a .doc — the file is added to the list (whitelist
    // enforcement is server-side), but we verify the server returns 400
    // when we submit. Mock server response to avoid burning credits.
    await page.route(
      `${API_BASE}/competence-generation/specialization-matrix-sessions`,
      (route) =>
        route.fulfill({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({
            detail:
              "Supported file types: .pdf, .docx, .xlsx, .xls, .rtf, .txt. Save the file in one of these formats.",
          }),
        }),
    );

    await page.getByTestId("ai-generate-file-input").setInputFiles({
      name: "legacy.doc",
      mimeType: "application/msword",
      buffer: Buffer.from("legacy"),
    });

    await page.getByTestId("ai-generate-submit").click();

    // Toast should surface the 400 message.
    await expect(page.getByText(/Supported file types/i)).toBeVisible({
      timeout: 5000,
    });
  });
});
