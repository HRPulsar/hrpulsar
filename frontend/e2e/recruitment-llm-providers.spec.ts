import { test, expect } from "./fixtures";
import { completeOnboarding, registerUser, setAuthTokens } from "./helpers";

// HRP-986: a self-hosted OpenAI-compatible model is connected from the
// recruitment LLM providers page - its server address is saved with the row
// (no API key needed) and reads back after a reload. A public https host
// keeps the address valid under the saas SSRF guard as well.
const BASE_URL = "https://example.com/v1";

test.describe("Recruitment LLM providers", () => {
  test("a self-hosted model's server address survives a reload", async ({
    page,
  }) => {
    const { accessToken, refreshToken } = await registerUser(page);
    await completeOnboarding({ page, accessToken });
    await setAuthTokens(page, accessToken, refreshToken);

    await page.goto("/recruitment/settings/llm-providers");
    await expect(
      page.getByTestId("recruitment-llm-providers-page"),
    ).toBeVisible({ timeout: 10000 });

    // The address field belongs to OpenAI-compatible providers only.
    await expect(page.getByTestId("llm-input-base-url")).toHaveCount(0);
    await page.getByTestId("llm-input-provider").selectOption("openai");
    await page.getByTestId("llm-input-model").fill("llama3.1");
    await page.getByTestId("llm-input-base-url").fill(BASE_URL);
    await page.getByTestId("llm-btn-create").click();

    const savedUrl = page.locator('[data-testid^="llm-row-base-url-"]');
    await expect(savedUrl).toHaveText(BASE_URL, { timeout: 10000 });
    await expect(page.locator('[data-testid^="llm-btn-test-"]')).toBeVisible();

    await page.reload();
    await expect(savedUrl).toHaveText(BASE_URL, { timeout: 10000 });
  });
});
